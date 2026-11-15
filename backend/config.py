import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from backend.clock import AnalyticalClock


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Settings:
    frontend_dist: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "SOLAR_FRONTEND_DIST",
                str(Path(__file__).resolve().parents[1] / "frontend" / "dist"),
            )
        )
    )
    database_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("SOLAR_DATABASE", ".local/solar.sqlite3")
        )
    )
    ingest_key: str = field(default_factory=lambda: os.getenv("SOLAR_INGEST_KEY", ""))
    cookie_secure: bool = field(
        default_factory=lambda: (
            os.getenv("SOLAR_COOKIE_SECURE", "false").lower() == "true"
        )
    )
    allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            origin.strip().rstrip("/")
            for origin in os.getenv(
                "SOLAR_ALLOWED_ORIGINS",
                "http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174",
            ).split(",")
            if origin.strip()
        )
    )
    # Support videos; kept outside the served frontend build.
    media_dir: Path = field(
        default_factory=lambda: Path(os.getenv("SOLAR_MEDIA_DIR", ".local/media"))
    )
    session_hours: int = 8
    max_request_bytes: int = 262144
    max_media_bytes: int = 30 * 1024 * 1024
    # Power Block Offers. The in-app worker settles offers in a background thread.
    offer_worker: bool = field(
        default_factory=lambda: (
            os.getenv("SOLAR_OFFER_WORKER", "true").lower() == "true"
        )
    )
    offer_worker_interval_seconds: int = 30
    # Local demo only: one-click sign-in to existing accounts from /demo/ (loopback only).
    # Local demo only: also allow phones/laptops on the same private (LAN) network.
    demo_lan: bool = field(
        default_factory=lambda: os.getenv("SOLAR_DEMO_LAN", "false").lower() == "true"
    )
    demo_login: bool = field(
        default_factory=lambda: os.getenv("SOLAR_DEMO_LOGIN", "false").lower() == "true"
    )
    offer_settlement_grace_minutes: int = 60
    offer_max_active_per_client: int = 3
    # Injectable analytical UTC clock for planning, offers acceptance and settlement.
    # By default it is wall time, or the forward-only scenario clock stored in the database
    # (`python -m backend scenario ...`). Sessions and audit receipt always use wall time.
    clock: Callable[[], datetime] | None = None

    def __post_init__(self):
        if self.clock is None:
            object.__setattr__(self, "clock", AnalyticalClock(self.database_path))
