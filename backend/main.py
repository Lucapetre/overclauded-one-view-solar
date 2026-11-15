import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from backend import dispatch
from backend.clock import clock_state, wall_now
from backend.component_models import EquipmentEvidence, EquipmentSummary
from backend.components import equipment_evidence, equipment_summary
from backend.config import Settings
from backend.customer import (
    REQUEST_TYPES,
    add_reply,
    complete_lesson,
    create_request,
    get_contract,
    lesson_catalog,
    list_requests,
    save_contract,
)
from backend.customer_models import (
    Contract,
    ContractView,
    LessonAnswers,
    LessonCatalog,
    LessonResult,
    RequestType,
    SupportReplyCreate,
    SupportRequest,
    SupportRequestCreate,
)
from backend.db import Database, site_from_row
from backend.energy import history, snapshot
from backend.energy_views import EnergyOverview, EnergyPeriods, overview, periods
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.media import is_upload, media_file, store_media
from backend.models import (
    Area,
    AreaSummary,
    EnergyHistory,
    EnergySnapshot,
    ErrorEnvelope,
    IngestResult,
    Login,
    SessionView,
    Site,
    TelemetryRecord,
    utc,
)
from backend.offers import (
    accept_offer,
    cancel_offer,
    client_offers,
    create_offer,
    list_manager_offers,
    list_notifications,
    manager_clients,
    manager_offer_detail,
    mark_all_read,
    mark_read,
    my_offers,
    offer_audit,
    preview_draft,
    preview_offer,
    publish_offer,
    savings_summary,
    update_offer,
)
from backend.offers_models import (
    AcceptOffer,
    AuditEntry,
    ClientOffer,
    ManagerClient,
    ManagerOffer,
    ManagerOfferDetail,
    NotificationList,
    OfferDraft,
    OfferPreview,
    OfferStatus,
    SavingsSummary,
    UserOffer,
)
from backend.offers_worker import start_background_worker
from backend.ops import (
    assign_incident,
    auto_dispatch,
    capacity,
    get_incident,
    list_incidents,
    ops_map,
    resolve_incident,
    revenue,
    schedule_meeting,
    send_team,
    teams,
)
from backend.ops_models import (
    AssignRequest,
    AutoDispatchResult,
    CapacityView,
    Incident,
    IncidentDetail,
    MeetingRequest,
    OpsMap,
    RevenueView,
    TeamsView,
)
from backend.planner import (
    accept_task,
    cancel_task,
    create_task,
    list_tasks,
    plan,
    review_task,
    task_progress,
    update_task,
)
from backend.planner_models import (
    AcceptTask,
    ClockView,
    PlanDecision,
    ReviewTask,
    Task,
    TaskCreate,
    TaskProgress,
    TaskUpdate,
)
from backend.planning_models import (
    AgendaView,
    ApplyRequest,
    CloseRequest,
    CrewPlanView,
    EpisodeDetail,
    OverrideRequest,
    ProgressRequest,
    ProposeRequest,
    QueueView,
    StatusProjection,
    UnmappedSites,
)
from backend.provider_models import (
    ProviderFrames,
    ProviderLatest,
    ProviderObservations,
    ProviderSite,
)
from backend.providers import provider_history, provider_latest, provider_sites
from backend.security import (
    COOKIE,
    accessible_sites,
    authenticated,
    authorized_areas,
    authorized_site,
    demo_accounts,
    demo_login,
    login,
    pipeline_access,
    require_csrf,
    token_hash,
)

Session = Annotated[SessionView, Depends(authenticated)]
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    if settings.media_dir.resolve().is_relative_to(settings.frontend_dist.resolve()):
        raise ValueError("SOLAR_MEDIA_DIR must not be inside the served frontend build")
    database = Database(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.migrate()
        stop = (
            start_background_worker(database, settings)
            if settings.offer_worker
            else None
        )
        yield
        if stop:
            stop()

    app = FastAPI(
        title="One View Solar telemetry API",
        version="1.0.0",
        lifespan=lifespan,
        responses={
            status: {"model": ErrorEnvelope}
            for status in (401, 403, 404, 409, 413, 422, 429, 500, 503)
        },
    )
    app.state.settings = settings
    app.state.database = database
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )

    def error_response(request: Request, status: int, code: str, message: str):
        return JSONResponse(
            status_code=status,
            content={
                "code": code,
                "message": message,
                "request_id": request.state.request_id,
            },
            headers={
                "X-Request-ID": request.state.request_id,
                "Cache-Control": "no-store",
            },
        )

    @app.middleware("http")
    async def request_metadata(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        # Bound the actual body, including chunked requests without Content-Length.
        # Only the support video upload route accepts the larger media limit.
        if request.method in ("POST", "PUT", "PATCH"):
            media = is_upload(request.method, request.url.path)
            limit = settings.max_media_bytes if media else settings.max_request_bytes
            code = "media_too_large" if media else "request_too_large"
            message = (
                "The video is larger than 30 MB"
                if media
                else "Request body is too large"
            )
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > limit:
                return error_response(request, 413, code, message)
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit:
                    return error_response(request, 413, code, message)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Request failed; request_id=%s", request.state.request_id)
            return error_response(
                request, 500, "internal_error", "An internal error occurred"
            )
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            request, 422, "invalid_request", "Request does not match the API contract"
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return error_response(
            request,
            exc.status_code,
            "not_found" if exc.status_code == 404 else "http_error",
            str(exc.detail),
        )

    @app.get("/health", tags=["runtime"])
    def health() -> dict[str, str]:
        with database.connect() as connection:
            connection.execute("SELECT 1 FROM schema_migrations").fetchone()
        return {"status": "ok"}

    @app.post("/api/v1/auth/login", response_model=SessionView, tags=["auth"])
    def sign_in(request: Request, credentials: Login, response: Response):
        token, session = login(request, credentials)
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return session

    @app.get("/api/v1/auth/demo-accounts", include_in_schema=False)
    def list_demo_accounts(request: Request):
        return demo_accounts(request)

    @app.post("/api/v1/auth/demo-login", include_in_schema=False)
    def sign_in_demo(
        request: Request, payload: Annotated[dict, Body()], response: Response
    ):
        username = payload.get("username") if isinstance(payload, dict) else None
        if not isinstance(username, str) or not 1 <= len(username) <= 96:
            raise ApiError(422, "invalid_request", "Choose a demo account")
        token, session = demo_login(request, username)
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=settings.session_hours * 3600,
            path="/",
        )
        return session

    @app.post("/api/v1/auth/logout", status_code=204, tags=["auth"])
    def sign_out(request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (token_hash(request.cookies[COOKIE]),),
            )
            database.audit(
                connection,
                session.user.user_id,
                "logout",
                session.user.user_id,
                request.state.request_id,
            )
        response = Response(status_code=204)
        response.delete_cookie(
            COOKIE,
            path="/",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    @app.get("/api/v1/me", response_model=SessionView, tags=["auth"])
    def me(session: Session):
        return session

    @app.get("/api/v1/sites", response_model=list[Site], tags=["sites"])
    def sites(session: Session):
        with database.connect() as connection:
            return [
                site_from_row(row) for row in accessible_sites(connection, session.user)
            ]

    @app.get(
        "/api/v1/provider/sites",
        response_model=list[ProviderSite],
        tags=["provider data"],
    )
    def imported_sites(session: Session):
        with database.connect() as connection:
            return provider_sites(connection, session.user)

    @app.get(
        "/api/v1/sites/{site_id}/provider/latest",
        response_model=ProviderLatest,
        tags=["provider data"],
    )
    def imported_latest(site_id: str, session: Session):
        with database.connect() as connection:
            return provider_latest(connection, session.user, site_id)

    def imported_history(
        site_id,
        session,
        start,
        end,
        metric,
        endpoint,
        device,
        channel,
        limit,
        offset,
        observations,
    ):
        try:
            start, end = utc(start), utc(end)
        except ValueError as exc:
            raise ApiError(422, "invalid_time_range", str(exc)) from exc
        with database.connect() as connection:
            return provider_history(
                connection,
                session.user,
                site_id,
                start,
                end,
                metric,
                endpoint,
                device,
                channel,
                limit,
                offset,
                observations=observations,
            )

    @app.get(
        "/api/v1/sites/{site_id}/provider/observations",
        response_model=ProviderObservations,
        tags=["provider data"],
    )
    def imported_observations(
        site_id: str,
        session: Session,
        start: Annotated[datetime, Query(alias="from")],
        end: Annotated[datetime, Query(alias="to")],
        metric: Annotated[str | None, Query(max_length=128)] = None,
        endpoint: Annotated[str | None, Query(max_length=128)] = None,
        device: Annotated[str | None, Query(max_length=128)] = None,
        channel: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    ):
        return imported_history(
            site_id,
            session,
            start,
            end,
            metric,
            endpoint,
            device,
            channel,
            limit,
            offset,
            True,
        )

    @app.get(
        "/api/v1/sites/{site_id}/provider/frames",
        response_model=ProviderFrames,
        tags=["provider data"],
    )
    def imported_frames(
        site_id: str,
        session: Session,
        start: Annotated[datetime, Query(alias="from")],
        end: Annotated[datetime, Query(alias="to")],
        metric: Annotated[str | None, Query(max_length=128)] = None,
        endpoint: Annotated[str | None, Query(max_length=128)] = None,
        device: Annotated[str | None, Query(max_length=128)] = None,
        channel: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0, le=1000000)] = 0,
    ):
        return imported_history(
            site_id,
            session,
            start,
            end,
            metric,
            endpoint,
            device,
            channel,
            limit,
            offset,
            False,
        )

    @app.get("/api/v1/sites/{site_id}", response_model=Site, tags=["sites"])
    def site(site_id: str, session: Session):
        with database.connect() as connection:
            return site_from_row(authorized_site(connection, session.user, site_id))

    @app.get(
        "/api/v1/sites/{site_id}/energy/latest",
        response_model=EnergySnapshot,
        tags=["energy"],
    )
    def latest(site_id: str, session: Session):
        with database.connect() as connection:
            return snapshot(
                connection,
                site_from_row(authorized_site(connection, session.user, site_id)),
            )

    @app.get(
        "/api/v1/sites/{site_id}/energy/overview",
        response_model=EnergyOverview,
        tags=["energy"],
    )
    def energy_overview(site_id: str, session: Session):
        with database.connect() as connection:
            return overview(connection, session.user, site_id)

    @app.get(
        "/api/v1/sites/{site_id}/energy/periods",
        response_model=EnergyPeriods,
        tags=["energy"],
    )
    def energy_periods(
        site_id: str,
        session: Session,
        period: Literal["today", "week", "month", "year"] = "today",
    ):
        with database.connect() as connection:
            return periods(connection, session.user, site_id, period)

    @app.get(
        "/api/v1/sites/{site_id}/energy", response_model=EnergyHistory, tags=["energy"]
    )
    def energy_history(
        site_id: str,
        session: Session,
        start: Annotated[datetime, Query(alias="from")],
        end: Annotated[datetime, Query(alias="to")],
        resolution: Literal["raw", "15m", "1h", "1d"] = "raw",
    ):
        try:
            start, end = utc(start), utc(end)
        except ValueError as exc:
            raise ApiError(422, "invalid_time_range", str(exc)) from exc
        with database.connect() as connection:
            row = authorized_site(connection, session.user, site_id)
            return history(connection, row, start, end, resolution)

    @app.get("/api/v1/areas", response_model=list[Area], tags=["operations"])
    def areas(session: Session):
        with database.connect() as connection:
            return [
                Area(**dict(row)) for row in authorized_areas(connection, session.user)
            ]

    @app.get(
        "/api/v1/areas/{area_id}/summary",
        response_model=AreaSummary,
        tags=["operations"],
    )
    def area_summary(area_id: str, session: Session):
        with database.connect() as connection:
            permitted = {
                row["area_id"]: row
                for row in authorized_areas(connection, session.user)
            }
            if area_id not in permitted:
                raise ApiError(404, "not_found", "Resource not found")
            snapshots = [
                snapshot(connection, site_from_row(row))
                for row in accessible_sites(connection, session.user)
                if row["area_id"] == area_id
            ]
            statuses = [item.freshness.status for item in snapshots]
            return AreaSummary(
                area=Area(**dict(permitted[area_id])),
                monitored_sites=len(snapshots),
                recent_sites=statuses.count("fresh"),
                stale_sites=statuses.count("stale"),
                unavailable_sites=statuses.count("unavailable"),
                unassessed_sites=statuses.count("future")
                + statuses.count("unknown_clock"),
                sites=snapshots,
            )

    @app.get(
        "/api/v1/sites/{site_id}/contract",
        response_model=ContractView,
        tags=["customer"],
        response_model_exclude_unset=True,
    )
    def contract(site_id: str, session: Session):
        with database.connect() as connection:
            return get_contract(connection, session.user, site_id)

    @app.post(
        "/api/v1/sites/{site_id}/contract",
        response_model=ContractView,
        tags=["customer"],
        response_model_exclude_unset=True,
    )
    def update_contract(
        site_id: str, payload: Contract, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return save_contract(
                database,
                connection,
                session.user,
                site_id,
                payload,
                request.state.request_id,
            )

    @app.get(
        "/api/v1/support/request-types",
        response_model=list[RequestType],
        tags=["customer"],
    )
    def request_types(session: Session):
        return REQUEST_TYPES

    @app.get(
        "/api/v1/support/requests",
        response_model=list[SupportRequest],
        tags=["customer"],
    )
    def support_requests(session: Session):
        with database.connect() as connection:
            return list_requests(connection, session.user)

    @app.post(
        "/api/v1/support/requests",
        response_model=SupportRequest,
        status_code=201,
        tags=["customer"],
    )
    def open_request(payload: SupportRequestCreate, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return create_request(
                database, connection, session.user, payload, request.state.request_id
            )

    @app.post(
        "/api/v1/support/requests/{request_id}/replies",
        response_model=SupportRequest,
        status_code=201,
        tags=["customer"],
    )
    def reply(
        request_id: str,
        payload: SupportReplyCreate,
        request: Request,
        session: Session,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return add_reply(
                database,
                connection,
                session.user,
                request_id,
                payload.text,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/support/requests/{request_id}/media",
        response_model=SupportRequest,
        status_code=201,
        tags=["customer"],
        responses={415: {"model": ErrorEnvelope}},
        openapi_extra={
            "requestBody": {
                "required": True,
                "description": "Raw MP4 or WebM bytes (not multipart), at most 30 MB",
                "content": {
                    "video/mp4": {"schema": {"type": "string", "format": "binary"}},
                    "video/webm": {"schema": {"type": "string", "format": "binary"}},
                },
            }
        },
    )
    async def upload_media(
        request_id: str,
        request: Request,
        session: Session,
        filename: Annotated[str, Query(min_length=1, max_length=255)] = "support-video",
    ):
        require_csrf(request, session)
        body = await request.body()

        def save():
            with database.connect() as connection:
                return store_media(
                    database,
                    connection,
                    session.user,
                    request_id,
                    filename,
                    request.headers.get("content-type", ""),
                    body,
                    settings.media_dir,
                    settings.max_media_bytes,
                    request.state.request_id,
                )

        return await run_in_threadpool(save)

    @app.get(
        "/api/v1/support/media/{media_id}",
        response_class=FileResponse,
        tags=["customer"],
        responses={
            200: {
                "description": "The stored video, served inline",
                "content": {"video/mp4": {}, "video/webm": {}},
            }
        },
    )
    def support_media(media_id: str, session: Session):
        with database.connect() as connection:
            path, content_type, filename = media_file(
                connection, session.user, media_id, settings.media_dir
            )
        return FileResponse(
            path,
            media_type=content_type,
            filename=filename,
            content_disposition_type="inline",
        )

    @app.get("/api/v1/ops/map", response_model=OpsMap, tags=["operations"])
    def operations_map(session: Session):
        with database.connect() as connection:
            return ops_map(connection, session.user)

    @app.get(
        "/api/v1/ops/incidents", response_model=list[Incident], tags=["operations"]
    )
    def incidents(session: Session, status: Literal["open", "all"] = "open"):
        with database.connect() as connection:
            return list_incidents(connection, session.user, status)

    @app.get(
        "/api/v1/ops/incidents/{incident_id}",
        response_model=IncidentDetail,
        tags=["operations"],
    )
    def incident(incident_id: str, session: Session):
        with database.connect() as connection:
            return get_incident(connection, session.user, incident_id)

    @app.post(
        "/api/v1/ops/incidents/{incident_id}/assign",
        response_model=IncidentDetail,
        tags=["operations"],
    )
    def assign(
        incident_id: str, payload: AssignRequest, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return assign_incident(
                database,
                connection,
                session.user,
                incident_id,
                payload.crew_id,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/incidents/{incident_id}/send-team",
        response_model=IncidentDetail,
        tags=["operations"],
    )
    def dispatch_team(incident_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return send_team(
                database,
                connection,
                session.user,
                incident_id,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/incidents/{incident_id}/meeting",
        response_model=IncidentDetail,
        tags=["operations"],
    )
    def meeting(
        incident_id: str, payload: MeetingRequest, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return schedule_meeting(
                database,
                connection,
                session.user,
                incident_id,
                payload.start,
                payload.end,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/incidents/{incident_id}/resolve",
        response_model=IncidentDetail,
        tags=["operations"],
    )
    def resolve(incident_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return resolve_incident(
                database,
                connection,
                session.user,
                incident_id,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/dispatch/auto",
        response_model=AutoDispatchResult,
        tags=["operations"],
    )
    def dispatch_by_severity(request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return auto_dispatch(
                database, connection, session.user, request.state.request_id
            )

    @app.get("/api/v1/ops/teams", response_model=TeamsView, tags=["operations"])
    def operations_teams(session: Session):
        with database.connect() as connection:
            return teams(connection, session.user)

    @app.get("/api/v1/ops/revenue", response_model=RevenueView, tags=["operations"])
    def operations_revenue(session: Session):
        with database.connect() as connection:
            return revenue(connection, session.user)

    @app.get("/api/v1/ops/capacity", response_model=CapacityView, tags=["operations"])
    def operations_capacity(session: Session):
        with database.connect() as connection:
            return capacity(connection, session.user)

    @app.get("/api/v1/lessons", response_model=LessonCatalog, tags=["customer"])
    def lessons(session: Session):
        with database.connect() as connection:
            return lesson_catalog(connection, session.user)

    @app.post(
        "/api/v1/lessons/{lesson_id}/complete",
        response_model=LessonResult,
        tags=["customer"],
    )
    def finish_lesson(
        lesson_id: str, payload: LessonAnswers, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return complete_lesson(
                database,
                connection,
                session.user,
                lesson_id,
                payload.answers,
                request.state.request_id,
            )

    @app.get(
        "/api/v1/manager/offers",
        response_model=list[ManagerOffer],
        tags=["power offers"],
    )
    def manager_offers(session: Session, status: OfferStatus | None = None):
        with database.connect() as connection:
            return list_manager_offers(
                connection, session.user, status, settings.clock()
            )

    @app.post(
        "/api/v1/manager/offers",
        response_model=ManagerOfferDetail,
        status_code=201,
        tags=["power offers"],
    )
    def new_offer(payload: OfferDraft, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return create_offer(
                database,
                connection,
                session.user,
                payload,
                request.state.request_id,
                settings.clock(),
            )

    @app.post(
        "/api/v1/manager/offers/preview",
        response_model=OfferPreview,
        tags=["power offers"],
    )
    def preview_new_offer(payload: OfferDraft, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return preview_draft(connection, session.user, payload, settings.clock())

    @app.get(
        "/api/v1/manager/clients",
        response_model=list[ManagerClient],
        tags=["power offers"],
    )
    def offer_clients(
        session: Session,
        area_id: Annotated[str | None, Query(max_length=96)] = None,
    ):
        with database.connect() as connection:
            return manager_clients(connection, session.user, area_id)

    @app.get(
        "/api/v1/manager/offers/{offer_id}",
        response_model=ManagerOfferDetail,
        tags=["power offers"],
    )
    def manager_offer(offer_id: str, session: Session):
        with database.connect() as connection:
            return manager_offer_detail(
                connection, session.user, offer_id, settings.clock()
            )

    @app.post(
        "/api/v1/manager/offers/{offer_id}",
        response_model=ManagerOfferDetail,
        tags=["power offers"],
    )
    def edit_offer(
        offer_id: str, payload: OfferDraft, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return update_offer(
                database,
                connection,
                session.user,
                offer_id,
                payload,
                request.state.request_id,
                settings.clock(),
            )

    @app.get(
        "/api/v1/manager/offers/{offer_id}/preview",
        response_model=OfferPreview,
        tags=["power offers"],
    )
    def preview_saved_offer(offer_id: str, session: Session):
        with database.connect() as connection:
            return preview_offer(connection, session.user, offer_id, settings.clock())

    @app.post(
        "/api/v1/manager/offers/{offer_id}/publish",
        response_model=ManagerOfferDetail,
        tags=["power offers"],
    )
    def publish_saved_offer(offer_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return publish_offer(
                database,
                connection,
                session.user,
                offer_id,
                request.state.request_id,
                settings.clock(),
            )

    @app.post(
        "/api/v1/manager/offers/{offer_id}/cancel",
        response_model=ManagerOfferDetail,
        tags=["power offers"],
    )
    def cancel_saved_offer(offer_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return cancel_offer(
                database,
                connection,
                session.user,
                offer_id,
                request.state.request_id,
                settings.clock(),
            )

    @app.get(
        "/api/v1/manager/offers/{offer_id}/audit",
        response_model=list[AuditEntry],
        tags=["power offers"],
    )
    def offer_audit_log(offer_id: str, session: Session):
        with database.connect() as connection:
            return offer_audit(connection, session.user, offer_id)

    @app.get("/api/v1/offers", response_model=list[ClientOffer], tags=["power offers"])
    def available_offers(session: Session):
        with database.connect() as connection:
            return client_offers(connection, session.user, settings.clock())

    @app.get(
        "/api/v1/offers/mine", response_model=list[UserOffer], tags=["power offers"]
    )
    def accepted_offers(
        session: Session, status: Literal["active", "history", "all"] = "all"
    ):
        with database.connect() as connection:
            return my_offers(connection, session.user, status)

    @app.get(
        "/api/v1/offers/savings", response_model=SavingsSummary, tags=["power offers"]
    )
    def offer_savings(session: Session):
        with database.connect() as connection:
            return savings_summary(connection, session.user, settings.clock())

    @app.post(
        "/api/v1/offers/{offer_id}/accept",
        response_model=UserOffer,
        status_code=201,
        tags=["power offers"],
        responses={200: {"model": UserOffer, "description": "Idempotent repeat"}},
    )
    def accept(
        offer_id: str,
        request: Request,
        response: Response,
        session: Session,
        payload: Annotated[AcceptOffer | None, Body()] = None,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", min_length=1, max_length=128),
        ] = None,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            view, created = accept_offer(
                database,
                connection,
                session.user,
                offer_id,
                payload.site_id if payload else None,
                idempotency_key,
                request.state.request_id,
                settings.clock(),
                settings.offer_max_active_per_client,
            )
        if not created:
            response.status_code = 200
        return view

    @app.get(
        "/api/v1/notifications",
        response_model=NotificationList,
        tags=["notifications"],
    )
    def notifications(session: Session, unread: bool = False):
        with database.connect() as connection:
            return list_notifications(connection, session.user, unread)

    @app.post(
        "/api/v1/notifications/read-all",
        response_model=NotificationList,
        tags=["notifications"],
    )
    def read_all_notifications(request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return mark_all_read(connection, session.user, settings.clock())

    @app.post(
        "/api/v1/notifications/{notification_id}/read",
        response_model=NotificationList,
        tags=["notifications"],
    )
    def read_notification(notification_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return mark_read(
                connection, session.user, notification_id, settings.clock()
            )

    @app.post(
        "/internal/v1/telemetry",
        response_model=IngestResult,
        dependencies=[Depends(pipeline_access)],
        tags=["pipeline"],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/TelemetryRecord"},
                    }
                },
            }
        },
    )
    def ingest_record(request: Request, payload: Annotated[Any, Body()]):
        return ingest(database, payload, request.state.request_id)

    # ------------------------------------------------------------ analytical clock, planner

    @app.get("/api/v1/clock", response_model=ClockView, tags=["runtime"])
    def analytical_clock(session: Session):
        """Read-only analytical clock (live = wall time, or the local scenario clock)."""
        with database.connect() as connection:
            state = clock_state(connection)
            return ClockView(
                mode=state.mode,
                analytical_now=state.now,
                wall_now=wall_now(),
                scenario_id=state.scenario_id,
                run_id=state.run_id,
                scenario_started_at=state.started_at,
                synthetic=state.mode == "scenario",
            )

    @app.get(
        "/api/v1/sites/{site_id}/tasks", response_model=list[Task], tags=["planner"]
    )
    def planner_tasks(site_id: str, session: Session):
        with database.connect() as connection:
            return list_tasks(connection, session.user, site_id)

    @app.post(
        "/api/v1/sites/{site_id}/tasks",
        response_model=Task,
        status_code=201,
        tags=["planner"],
    )
    def new_planner_task(
        site_id: str, payload: TaskCreate, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return create_task(
                database,
                connection,
                session.user,
                site_id,
                payload,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/sites/{site_id}/tasks/{task_id}",
        response_model=Task,
        tags=["planner"],
    )
    def edit_planner_task(
        site_id: str,
        task_id: str,
        payload: TaskUpdate,
        request: Request,
        session: Session,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return update_task(
                database,
                connection,
                session.user,
                site_id,
                task_id,
                payload,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/sites/{site_id}/tasks/{task_id}/cancel",
        response_model=Task,
        tags=["planner"],
    )
    def cancel_planner_task(
        site_id: str, task_id: str, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return cancel_task(
                database,
                connection,
                session.user,
                site_id,
                task_id,
                request.state.request_id,
            )

    @app.get(
        "/api/v1/sites/{site_id}/plan", response_model=PlanDecision, tags=["planner"]
    )
    def planner_decision(
        site_id: str,
        session: Session,
        task: Annotated[str, Query(min_length=1, max_length=64)],
    ):
        with database.connect() as connection:
            return plan(connection, session.user, site_id, task)

    @app.post(
        "/api/v1/sites/{site_id}/tasks/{task_id}/accept",
        response_model=Task,
        status_code=201,
        tags=["planner"],
        responses={200: {"model": Task, "description": "Idempotent repeat"}},
    )
    def accept_planner_task(
        site_id: str,
        task_id: str,
        payload: AcceptTask,
        request: Request,
        response: Response,
        session: Session,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", min_length=1, max_length=128),
        ] = None,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            view, created = accept_task(
                database,
                connection,
                session.user,
                site_id,
                task_id,
                payload,
                idempotency_key,
                request.state.request_id,
            )
        if not created:
            response.status_code = 200
        return view

    @app.post(
        "/api/v1/sites/{site_id}/tasks/{task_id}/review",
        response_model=Task,
        tags=["planner"],
    )
    def review_planner_task(
        site_id: str,
        task_id: str,
        payload: ReviewTask,
        request: Request,
        session: Session,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return review_task(
                database,
                connection,
                session.user,
                site_id,
                task_id,
                payload,
                request.state.request_id,
            )

    @app.get(
        "/api/v1/sites/{site_id}/tasks/{task_id}/progress",
        response_model=TaskProgress,
        tags=["planner"],
    )
    def planner_progress(site_id: str, task_id: str, session: Session):
        with database.connect() as connection:
            return task_progress(connection, session.user, site_id, task_id)

    @app.get(
        "/api/v1/sites/{site_id}/equipment/summary",
        response_model=EquipmentSummary,
        tags=["equipment"],
    )
    def site_equipment(site_id: str, session: Session):
        with database.connect() as connection:
            return equipment_summary(connection, session.user, site_id)

    @app.get(
        "/api/v1/sites/{site_id}/equipment/evidence",
        response_model=EquipmentEvidence,
        tags=["equipment"],
    )
    def site_equipment_evidence(
        site_id: str,
        session: Session,
        start: Annotated[datetime, Query(alias="from")],
        end: Annotated[datetime, Query(alias="to")],
        family: Literal["meter", "battery", "weather"] | None = None,
        metric: Annotated[str | None, Query(max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
        offset: Annotated[int, Query(ge=0, le=100000)] = 0,
    ):
        try:
            start, end = utc(start), utc(end)
        except ValueError as exc:
            raise ApiError(422, "invalid_time_range", str(exc)) from exc
        with database.connect() as connection:
            return equipment_evidence(
                connection,
                session.user,
                site_id,
                family,
                start,
                end,
                metric,
                limit,
                offset,
            )

    # ------------------------------------------------ correlated episodes, ranking, crew plans

    @app.get("/api/v1/ops/queue", response_model=QueueView, tags=["operations"])
    def operations_queue(session: Session, status: Literal["open", "all"] = "open"):
        with database.connect() as connection:
            return dispatch.ranked_queue(connection, session.user, status)

    @app.get(
        "/api/v1/ops/episodes/{incident_id}",
        response_model=EpisodeDetail,
        tags=["operations"],
    )
    def operations_episode(incident_id: str, session: Session):
        with database.connect() as connection:
            return dispatch.episode_detail(connection, session.user, incident_id)

    @app.post(
        "/api/v1/ops/episodes/{incident_id}/acknowledge",
        response_model=EpisodeDetail,
        tags=["operations"],
    )
    def acknowledge_episode(incident_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.acknowledge(
                database,
                connection,
                session.user,
                incident_id,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/episodes/{incident_id}/close",
        response_model=EpisodeDetail,
        tags=["operations"],
    )
    def close_episode(
        incident_id: str, payload: CloseRequest, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.close_episode(
                database,
                connection,
                session.user,
                incident_id,
                payload.reason_code,
                payload.note,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/episodes/{incident_id}/priority-override",
        response_model=EpisodeDetail,
        tags=["operations"],
    )
    def override_priority(
        incident_id: str, payload: OverrideRequest, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.set_override(
                database,
                connection,
                session.user,
                incident_id,
                payload.band,
                payload.reason,
                payload.expires_at,
                request.state.request_id,
            )

    @app.post(
        "/api/v1/ops/episodes/{incident_id}/priority-override/revoke",
        response_model=EpisodeDetail,
        tags=["operations"],
    )
    def revoke_priority_override(incident_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.revoke_override(
                database,
                connection,
                session.user,
                incident_id,
                request.state.request_id,
            )

    @app.get("/api/v1/ops/status", response_model=StatusProjection, tags=["operations"])
    def operations_status(session: Session):
        with database.connect() as connection:
            return dispatch.projection(connection, session.user)

    @app.get("/api/v1/ops/unmapped", response_model=UnmappedSites, tags=["operations"])
    def operations_unmapped(session: Session):
        with database.connect() as connection:
            view = dispatch.projection(connection, session.user)
        return {
            "revision": view["revision"],
            "status_as_of": view["status_as_of"],
            "count": len(view["unmapped"]),
            "sites": view["unmapped"],
        }

    @app.post(
        "/api/v1/ops/plans",
        response_model=CrewPlanView,
        status_code=201,
        tags=["operations"],
    )
    def propose_crew_plan(
        request: Request,
        session: Session,
        payload: Annotated[ProposeRequest | None, Body()] = None,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.propose_plan(
                database,
                connection,
                session.user,
                request.state.request_id,
                (payload or ProposeRequest()).horizon_hours,
            )

    @app.get(
        "/api/v1/ops/plans/latest", response_model=CrewPlanView, tags=["operations"]
    )
    def latest_crew_plan(session: Session):
        with database.connect() as connection:
            return dispatch.latest_plan(connection, session.user)

    @app.get(
        "/api/v1/ops/plans/{plan_id}", response_model=CrewPlanView, tags=["operations"]
    )
    def crew_plan(plan_id: str, session: Session):
        with database.connect() as connection:
            return dispatch.plan_view(connection, session.user, plan_id)

    @app.post(
        "/api/v1/ops/plans/{plan_id}/review",
        response_model=CrewPlanView,
        tags=["operations"],
    )
    def review_crew_plan(plan_id: str, request: Request, session: Session):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.review_plan(
                database, connection, session.user, plan_id, request.state.request_id
            )

    @app.post(
        "/api/v1/ops/plans/{plan_id}/apply",
        response_model=CrewPlanView,
        tags=["operations"],
    )
    def apply_crew_plan(
        plan_id: str,
        payload: ApplyRequest,
        request: Request,
        session: Session,
        idempotency_key: Annotated[
            str | None,
            Header(alias="Idempotency-Key", min_length=1, max_length=128),
        ] = None,
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.apply_plan(
                database,
                connection,
                session.user,
                plan_id,
                payload.expected_input_digest,
                idempotency_key,
                request.state.request_id,
            )

    @app.get("/api/v1/ops/agenda", response_model=AgendaView, tags=["operations"])
    def operations_agenda(session: Session):
        with database.connect() as connection:
            return dispatch.agenda(connection, session.user)

    @app.post(
        "/api/v1/ops/assignments/{assignment_id}/progress",
        response_model=AgendaView,
        tags=["operations"],
    )
    def assignment_progress(
        assignment_id: str, payload: ProgressRequest, request: Request, session: Session
    ):
        require_csrf(request, session)
        with database.connect() as connection:
            return dispatch.update_progress(
                database,
                connection,
                session.user,
                assignment_id,
                payload.state,
                payload.expected_revision,
                payload.outcome,
                payload.note,
                request.state.request_id,
            )

    def openapi():
        if app.openapi_schema is None:
            schema = get_openapi(
                title=app.title, version=app.version, routes=app.routes
            )
            record_schema = TelemetryRecord.model_json_schema(
                ref_template="#/components/schemas/{model}"
            )
            definitions = record_schema.pop("$defs", {})
            schema["components"]["schemas"].update(definitions)
            schema["components"]["schemas"]["TelemetryRecord"] = record_schema
            app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = openapi

    # Serve built browser apps from the same origin as the session API.
    # Keep the fallback limited to frontend paths; unknown API routes remain JSON 404s.
    if (settings.frontend_dist / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=settings.frontend_dist / "assets"),
            name="frontend-assets",
        )

    @app.get("/", include_in_schema=False)
    @app.get("/consumer", include_in_schema=False)
    @app.get("/consumer/{path:path}", include_in_schema=False)
    @app.get("/ops", include_in_schema=False)
    @app.get("/ops/{path:path}", include_in_schema=False)
    @app.get("/demo", include_in_schema=False)
    @app.get("/demo/{path:path}", include_in_schema=False)
    def frontend(path: str = ""):
        index = settings.frontend_dist / "index.html"
        if not index.is_file():
            raise ApiError(
                503,
                "frontend_not_built",
                "Build the frontend with npm ci and npm run build in frontend/, or use the Vite development server",
            )
        return FileResponse(index, media_type="text/html")

    return app


app = create_app()
