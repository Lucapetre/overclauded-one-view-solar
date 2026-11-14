import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import Body, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.config import Settings
from backend.db import Database, site_from_row
from backend.energy import history, snapshot
from backend.errors import ApiError
from backend.ingestion import ingest
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
        if request.method in ("POST", "PUT", "PATCH"):
            chunks = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_request_bytes:
                    return error_response(
                        request, 413, "request_too_large", "Request body is too large"
                    )
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
    return app


app = create_app()
