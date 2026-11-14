import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

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
        yield

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
        allow_headers=["Content-Type", "X-CSRF-Token"],
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
    )
    def contract(site_id: str, session: Session):
        with database.connect() as connection:
            return get_contract(connection, session.user, site_id)

    @app.post(
        "/api/v1/sites/{site_id}/contract",
        response_model=ContractView,
        tags=["customer"],
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
