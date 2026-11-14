import argparse
import getpass
import json
import os
from datetime import datetime
from pathlib import Path

from backend.config import Settings
from backend.db import Database, stamp
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import SiteRegistration, utc
from backend.providers import import_provider_snapshot
from backend.provisioning import create_user, grant_access, register_site
from backend.seed import seed_demo


def main():
    parser = argparse.ArgumentParser(description="Local phase 2 database tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply pending migrations")
    commands.add_parser(
        "seed-demo", help="Seed 24 simulated sites and scoped demo accounts"
    )
    importer = commands.add_parser(
        "import", help="Import a JSON record or JSON array from phase 1"
    )
    importer.add_argument("path", type=Path)
    replay = commands.add_parser(
        "replay-clock",
        help="Set analytical replay time; wall-clock session time is unchanged",
    )
    replay.add_argument("timestamp")
    provider = commands.add_parser(
        "import-provider",
        help="Import a phase 1 scraper snapshot and frames without losing canonical semantics",
    )
    provider.add_argument("--database", type=Path, required=True)
    provider.add_argument("--sites", type=Path, default=Path("demo_data/sites.json"))
    provider.add_argument(
        "--frames", type=Path, default=Path("build/site_frames_15min.csv")
    )
    register = commands.add_parser(
        "register-site", help="Register a phase 1 site's capabilities and energy stream"
    )
    register.add_argument("path", type=Path)
    account = commands.add_parser(
        "create-user", help="Create an account with no initial data access"
    )
    account.add_argument("username")
    account.add_argument(
        "--role",
        choices=["customer", "dispatcher", "technician", "supervisor"],
        required=True,
    )
    for kind in ("site", "area"):
        grant = commands.add_parser(
            f"grant-{kind}", help=f"Grant explicit {kind} access to a user"
        )
        grant.add_argument("username")
        grant.add_argument("subject")
    arguments = parser.parse_args()
    settings = Settings()
    database = Database(settings.database_path)
    database.migrate()
    if arguments.command == "import-provider":
        print(
            json.dumps(
                import_provider_snapshot(
                    database, arguments.database, arguments.sites, arguments.frames
                ),
                indent=2,
            )
        )
    elif arguments.command == "register-site":
        registration = SiteRegistration.model_validate_json(arguments.path.read_text())
        register_site(database, registration)
        print(f"Registered site {registration.site.site_id}")
    elif arguments.command == "create-user":
        password = os.getenv("SOLAR_ACCOUNT_PASSWORD") or getpass.getpass(
            "New account password: "
        )
        create_user(database, arguments.username, password, arguments.role)
        print(f"Created account {arguments.username} with no site or area grants")
    elif arguments.command.startswith("grant-"):
        grant_access(
            database,
            arguments.username,
            arguments.subject,
            arguments.command.removeprefix("grant-"),
        )
        print("Access grant recorded")
    elif arguments.command == "seed-demo":
        credentials = seed_demo(database, os.getenv("SOLAR_DEMO_PASSWORD"))
        destination = settings.database_path.parent / "demo-credentials.json"
        if credentials:
            previous = (
                json.loads(destination.read_text()) if destination.exists() else {}
            )
            previous.update(credentials)
            descriptor = os.open(
                destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(previous, stream, indent=2)
        print(
            f"Synthetic demo ready. New account credentials are stored privately at {destination}"
        )
    elif arguments.command == "import":
        payload = json.loads(arguments.path.read_text())
        rejected = 0
        for record in payload if isinstance(payload, list) else [payload]:
            try:
                print(ingest(database, record).model_dump_json())
            except ApiError as exc:
                rejected += 1
                print(json.dumps({"code": exc.code, "message": exc.message}))
        if rejected:
            raise SystemExit(1)
    elif arguments.command == "replay-clock":
        timestamp = utc(
            datetime.fromisoformat(arguments.timestamp.replace("Z", "+00:00"))
        )
        with database.connect() as connection:
            connection.execute(
                "INSERT INTO settings VALUES ('replay_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (stamp(timestamp),),
            )
        print(f"Replay clock set to {stamp(timestamp)}")
    else:
        print("Database migrations complete")


if __name__ == "__main__":
    main()
