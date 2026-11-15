import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader

from backend.db import stamp
from backend.errors import ApiError
from backend.models import Login, SessionView, User

COOKIE = "solar_session"
session_cookie = APIKeyCookie(name=COOKIE, auto_error=False)
ingest_header = APIKeyHeader(name="X-Ingest-Key", auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    )
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    algorithm, salt, digest = stored.split("$")
    if algorithm != "scrypt":
        return False
    actual = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1
    )
    return hmac.compare_digest(actual.hex(), digest)


DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_private_host(host: str | None) -> bool:
    """True for RFC 1918 / loopback IPv4 literals (used only in local demo LAN mode)."""
    import ipaddress

    try:
        address = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return address.is_private and not address.is_unspecified


def check_origin(request: Request):
    settings = request.app.state.settings
    origin = request.headers.get("origin")
    same_origin = str(request.base_url).rstrip("/")
    if origin and origin not in (*settings.allowed_origins, same_origin):
        raise ApiError(403, "origin_not_allowed", "This browser origin is not allowed")
    lan_ok = settings.demo_lan and is_private_host(request.url.hostname)
    if (
        not settings.cookie_secure
        and not lan_ok
        and request.url.hostname
        not in (
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        )
    ):
        raise ApiError(
            403, "https_required", "Non-loopback sessions require secure HTTPS cookies"
        )


def login(request: Request, credentials: Login) -> tuple[str, SessionView]:
    check_origin(request)
    database = request.app.state.database
    peer = request.client.host if request.client else "unknown"
    now = time.time()
    # Commit the attempt before password validation so failed logins remain counted.
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM login_attempts WHERE attempted_at < ?", (now - 900,)
        )
        attempts = connection.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE client_key=?", (peer,)
        ).fetchone()[0]
        if attempts >= 20:
            raise ApiError(
                429, "login_rate_limited", "Too many login attempts; try again later"
            )
        connection.execute("INSERT INTO login_attempts VALUES (?,?)", (peer, now))
        row = connection.execute(
            "SELECT * FROM users WHERE username=?", (credentials.username,)
        ).fetchone()
    valid = verify_password(
        credentials.password, row["password_hash"] if row else DUMMY_HASH
    )
    if not row or not valid:
        raise ApiError(401, "invalid_credentials", "Invalid username or password")
    return start_session(request, row, "login")


LOOPBACK_PEERS = ("127.0.0.1", "::1", "localhost", "testclient")


def require_demo_login(request: Request):
    """One-click demo sign-in exists only when explicitly enabled, and only for loopback clients."""
    peer = request.client.host if request.client else ""
    settings = request.app.state.settings
    allowed = peer in LOOPBACK_PEERS or (settings.demo_lan and is_private_host(peer))
    if not settings.demo_login or not allowed:
        raise ApiError(404, "not_found", "Resource not found")
    check_origin(request)


def demo_login(request: Request, username: str) -> tuple[str, SessionView]:
    require_demo_login(request)
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    return start_session(request, row, "demo_login")


def demo_accounts(request: Request) -> list[dict]:
    require_demo_login(request)
    with request.app.state.database.connect() as connection:
        users = connection.execute(
            "SELECT user_id, username, role, account_type FROM users ORDER BY role, username"
        ).fetchall()
        result = []
        for user in users:
            sites = [
                row[0]
                for row in connection.execute(
                    "SELECT s.alias FROM user_sites us JOIN sites s ON s.site_id=us.site_id "
                    "WHERE us.user_id=? ORDER BY s.alias LIMIT 5",
                    (user["user_id"],),
                )
            ]
            areas = [
                row[0]
                for row in connection.execute(
                    "SELECT a.alias FROM user_areas ua JOIN areas a ON a.area_id=ua.area_id "
                    "WHERE ua.user_id=? ORDER BY a.alias",
                    (user["user_id"],),
                )
            ]
            try:
                crews = [
                    row[0]
                    for row in connection.execute(
                        "SELECT c.name FROM crew_members m JOIN crews c ON c.crew_id=m.crew_id "
                        "WHERE m.user_id=? ORDER BY c.name",
                        (user["user_id"],),
                    )
                ]
            except Exception:
                crews = []
            result.append(
                {
                    "username": user["username"],
                    "role": user["role"],
                    "account_type": user["account_type"],
                    "sites": sites,
                    "areas": areas,
                    "crews": crews,
                }
            )
    return result


def start_session(request: Request, row, action: str) -> tuple[str, SessionView]:
    database = request.app.state.database
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(
        hours=request.app.state.settings.session_hours
    )
    with database.connect() as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (stamp(),))
        previous = request.cookies.get(COOKIE)
        if previous:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?", (token_hash(previous),)
            )
        connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?)",
            (token_hash(token), row["user_id"], csrf, stamp(expires)),
        )
        database.audit(
            connection,
            row["user_id"],
            action,
            row["user_id"],
            request.state.request_id,
        )
    return token, SessionView(
        user=User(
            **{key: row[key] for key in ("user_id", "username", "role", "account_type")}
        ),
        csrf_token=csrf,
        expires_at=expires,
    )


def authenticated(
    request: Request,
    token: Annotated[str | None, Security(session_cookie)],
) -> SessionView:
    check_origin(request)
    if not token or len(token) > 256:
        raise ApiError(
            401, "authentication_required", "Sign in to access this resource"
        )
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT u.user_id,u.username,u.role,u.account_type,s.csrf_token,s.expires_at "
            "FROM sessions s JOIN users u ON u.user_id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>?",
            (token_hash(token), stamp()),
        ).fetchone()
    if not row:
        raise ApiError(401, "authentication_required", "Session is missing or expired")
    return SessionView(
        user=User(
            **{key: row[key] for key in ("user_id", "username", "role", "account_type")}
        ),
        csrf_token=row["csrf_token"],
        expires_at=row["expires_at"],
    )


def require_csrf(request: Request, session: SessionView):
    candidate = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(candidate, session.csrf_token):
        raise ApiError(403, "csrf_required", "A valid X-CSRF-Token header is required")


def pipeline_access(
    request: Request,
    key: Annotated[str | None, Security(ingest_header)],
):
    configured = request.app.state.settings.ingest_key
    if not configured:
        raise ApiError(
            503, "ingestion_disabled", "HTTP ingestion has not been configured"
        )
    if not key or not hmac.compare_digest(key, configured):
        raise ApiError(401, "invalid_ingest_key", "A valid pipeline key is required")


def accessible_sites(connection, user: User):
    return connection.execute(
        "SELECT s.* FROM sites s WHERE "
        "EXISTS (SELECT 1 FROM user_sites us WHERE us.site_id=s.site_id AND us.user_id=?) "
        "OR (? != 'customer' AND EXISTS "
        "(SELECT 1 FROM user_areas ua WHERE ua.area_id=s.area_id AND ua.user_id=?)) "
        "ORDER BY s.site_id",
        (user.user_id, user.role, user.user_id),
    ).fetchall()


def authorized_site(connection, user: User, site_id: str):
    for row in accessible_sites(connection, user):
        if row["site_id"] == site_id:
            return row
    raise ApiError(404, "not_found", "Resource not found")


def authorized_areas(connection, user: User):
    if user.role == "customer":
        raise ApiError(403, "operations_required", "An operations role is required")
    return connection.execute(
        "SELECT a.* FROM areas a JOIN user_areas ua ON ua.area_id=a.area_id "
        "WHERE ua.user_id=? ORDER BY a.area_id",
        (user.user_id,),
    ).fetchall()
