"""Customer support videos: one short clip per request, stored outside the web root.

The body is the raw video (no multipart). Type, size and magic bytes are checked on
the server; duration is only checked in the browser. There is no virus scanning or
transcoding.
"""

import re
import secrets
import unicodedata
import uuid
from pathlib import Path

from backend.customer import _requests, _visible_request, require_customer
from backend.customer_models import SupportRequest
from backend.db import stamp
from backend.errors import ApiError
from backend.models import User
from backend.ops import log_incident

EXTENSIONS = {"video/mp4": ".mp4", "video/webm": ".webm"}
UPLOAD_PATH = re.compile(r"^/api/v1/support/requests/[^/]+/media$")
WEBM_MAGIC = b"\x1a\x45\xdf\xa3"


def is_upload(method: str, path: str) -> bool:
    return method == "POST" and bool(UPLOAD_PATH.match(path))


def safe_filename(name: str, content_type: str) -> str:
    """A display-only basename; the stored file name is always server-generated."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._ ()-]+", "_", base).strip(" ._")
    extension = EXTENSIONS[content_type]
    if not base:
        base = "support-video" + extension
    if len(base) > 120:
        stem, dot, suffix = base.rpartition(".")
        if dot and len(suffix) <= 5:
            base = stem[: 119 - len(suffix)] + "." + suffix
        else:
            base = base[:120]
    return base


def matches_magic(content_type: str, body: bytes) -> bool:
    if content_type == "video/mp4":
        return len(body) >= 12 and body[4:8] == b"ftyp"
    return body[:4] == WEBM_MAGIC


def store_media(
    database,
    connection,
    user: User,
    identifier: str,
    filename: str,
    content_type: str,
    body: bytes,
    media_dir: Path,
    max_bytes: int,
    request_id: str,
) -> SupportRequest:
    require_customer(user)
    row = _visible_request(connection, user, identifier)
    if row["priority"] == "immediate_danger":
        raise ApiError(
            422,
            "media_not_allowed",
            "Do not film a dangerous situation. Keep away and wait for the team",
        )
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type not in EXTENSIONS:
        raise ApiError(
            415, "unsupported_media_type", "Upload an MP4 or WebM video file"
        )
    if len(body) > max_bytes:
        raise ApiError(413, "media_too_large", "The video is larger than 30 MB")
    if not body or not matches_magic(content_type, body):
        raise ApiError(
            422, "invalid_media", "The file content is not a valid MP4 or WebM video"
        )
    connection.execute("BEGIN IMMEDIATE")
    if connection.execute(
        "SELECT 1 FROM support_media WHERE request_id=?", (identifier,)
    ).fetchone():
        raise ApiError(409, "media_exists", "This request already has a video")
    media_dir.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16) + EXTENSIONS[content_type]
    path = media_dir / stored
    path.write_bytes(body)
    try:
        media_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO support_media(media_id,request_id,filename,content_type,"
            "size_bytes,stored_name,uploaded_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                media_id,
                identifier,
                safe_filename(filename, content_type),
                content_type,
                len(body),
                stored,
                user.user_id,
                stamp(),
            ),
        )
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE support_request_id=?",
            (identifier,),
        ).fetchone()
        if incident:
            log_incident(
                connection,
                incident["incident_id"],
                user.username,
                "customer_video",
                f"Customer {user.username} attached a video ({len(body)} bytes)",
            )
        database.audit(
            connection, user.user_id, "support.media.uploaded", media_id, request_id
        )
        result = _requests(connection, user, "r.request_id=?", (identifier,))[0]
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return result


def media_file(connection, user: User, media_id: str, media_dir: Path):
    row = connection.execute(
        "SELECT * FROM support_media WHERE media_id=?", (media_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    # Same visibility as the request itself: the owner, or staff with the site in scope.
    _visible_request(connection, user, row["request_id"])
    path = media_dir / row["stored_name"]
    if not path.is_file():
        raise ApiError(404, "not_found", "Resource not found")
    return path, row["content_type"], row["filename"]
