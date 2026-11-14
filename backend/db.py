import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from backend.models import Site


def stamp(value: datetime | None = None) -> str:
    return (
        (value or datetime.now(UTC)).astimezone(UTC).isoformat(timespec="microseconds")
    )


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
            )
            for path in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
                if not connection.execute(
                    "SELECT 1 FROM schema_migrations WHERE version=?", (path.name,)
                ).fetchone():
                    # executescript owns this transaction: migration and version commit together.
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + path.read_text()
                        + "\nINSERT INTO schema_migrations VALUES ('"
                        + path.name.replace("'", "''")
                        + "');\nCOMMIT;"
                    )

    def audit(self, connection, actor: str, action: str, subject: str, request_id: str):
        connection.execute(
            "INSERT INTO audit(actor,action,subject,received_at,request_id) VALUES (?,?,?,?,?)",
            (actor, action, subject, stamp(), request_id),
        )


def site_from_row(row: sqlite3.Row) -> Site:
    return Site(
        **{
            key: row[key]
            for key in (
                "site_id",
                "alias",
                "area_id",
                "topology_mode",
                "reporting_interval_seconds",
                "stale_after_seconds",
            )
        },
        capabilities=json.loads(row["capabilities"]),
        measurement_requirements=json.loads(row["measurement_requirements"]),
    )
