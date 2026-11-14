import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
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
    session_hours: int = 8
    max_request_bytes: int = 262144
