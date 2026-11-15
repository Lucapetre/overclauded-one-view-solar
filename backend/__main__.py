import argparse
import getpass
import json
import os
from datetime import datetime
from pathlib import Path

from backend.clock import (
    advance_scenario,
    clock_state,
    parse_duration,
    scenario_status,
    start_scenario,
)
from backend.components import import_component_snapshot
from backend.config import Settings
from backend.db import Database, stamp
from backend.dispatch import run_correlation
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import SiteRegistration, utc
from backend.offers_worker import (
    reconcile,
    run_worker,
    settle_due,
    simulate_offer_meter,
)
from backend.providers import import_provider_snapshot
from backend.provisioning import (
    add_crew_member,
    create_crew,
    create_user,
    grant_access,
    register_site,
    set_account_type,
    set_password,
)
from backend.seed import (
    seed_component_scenario,
    seed_demo,
    seed_scenario_operations,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local phase 2 database tools")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Apply pending migrations")
    commands.add_parser(
        "seed-demo",
        help="Seed 60 simulated sites in Bucharest Sectors 1-6 and Ilfov, with scoped demo accounts",
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
    account.add_argument(
        "--account-type",
        choices=["home", "business"],
        default="home",
        help="Customer accounts only: household or business presentation",
    )
    kind = commands.add_parser(
        "set-account-type", help="Switch a customer account between home and business"
    )
    kind.add_argument("username")
    kind.add_argument("account_type", choices=["home", "business"])
    password = commands.add_parser(
        "set-password",
        help="Change an existing account's password and revoke its sessions",
    )
    password.add_argument("username")
    for kind in ("site", "area"):
        grant = commands.add_parser(
            f"grant-{kind}", help=f"Grant explicit {kind} access to a user"
        )
        grant.add_argument("username")
        grant.add_argument("subject")
    crew = commands.add_parser(
        "create-crew", help="Create a field crew for one area and incident families"
    )
    crew.add_argument("name")
    crew.add_argument("--area", required=True)
    crew.add_argument(
        "--skills",
        required=True,
        help="Comma-separated incident families, e.g. Production,Telemetry,Local issue",
    )
    crew.add_argument("--shift", default="08:00-18:00")
    member = commands.add_parser(
        "add-crew-member", help="Add a technician account to a crew"
    )
    member.add_argument("crew")
    member.add_argument("username")
    worker = commands.add_parser(
        "offers-worker",
        help="Run the Power Block Offers settlement worker (progress, reminders, settlement)",
    )
    worker.add_argument(
        "--once", action="store_true", help="Run a single pass and exit"
    )
    worker.add_argument(
        "--interval", type=float, default=30.0, help="Seconds between passes"
    )
    settle = commands.add_parser(
        "settle-offers",
        help="Run one offers worker pass, optionally at an explicit time",
    )
    settle.add_argument("--now", help="Timezone-aware ISO 8601 time; defaults to now")
    simulate = commands.add_parser(
        "simulate-offer-meter",
        help="SYNTHETIC demo meter data for the elapsed part of an accepted offer's window",
    )
    simulate.add_argument("user_offer_id")
    simulate.add_argument("--fraction", type=float, default=0.8)
    simulate.add_argument("--coverage", type=float, default=1.0)
    savings = commands.add_parser(
        "reconcile-savings",
        help="Recompute savings counters from the settlement ledger and fix mismatches",
    )
    savings.add_argument("--username", help="Only this client account")
    savings.add_argument(
        "--check", action="store_true", help="Report only; exit 1 on mismatches"
    )
    scenario = commands.add_parser(
        "scenario",
        help="Local forward-only analytical scenario clock (restart = new local database)",
    )
    steps = scenario.add_subparsers(dest="scenario_command", required=True)
    begin = steps.add_parser("start", help="Start a scenario run at an aware timestamp")
    begin.add_argument("name")
    begin.add_argument("--at", required=True, help="Timezone-aware ISO 8601 start time")
    advance = steps.add_parser("advance", help="Move the scenario clock forward")
    target = advance.add_mutually_exclusive_group(required=True)
    target.add_argument("--to", help="Timezone-aware ISO 8601 time (not earlier)")
    target.add_argument("--by", help="Duration such as 15m, 2h or 1d")
    advance.add_argument(
        "--correlate",
        action="store_true",
        help="Then run the incident correlation rules at the new analytical time",
    )
    advance.add_argument(
        "--settle",
        action="store_true",
        help="Then run one offers worker pass at the new analytical time",
    )
    steps.add_parser("status", help="Show the analytical clock")
    provision = commands.add_parser(
        "provision-component-scenario",
        help="Place the nine provider sites (fictional coordinates) and create scenario accounts and grants",
    )
    provision.add_argument("--sites", type=Path, default=Path("demo_data/sites.json"))
    provision.add_argument(
        "--assets", type=Path, default=Path("demo_components/assets.json")
    )
    components = commands.add_parser(
        "import-components",
        help="Import a component (meter/battery/irradiance) snapshot; never grants access",
    )
    components.add_argument(
        "--database", type=Path, default=Path("build/components/component.sqlite")
    )
    operations = commands.add_parser(
        "provision-scenario-operations",
        help="Create the scenario crews, technicians, shifts, windows and travel matrix "
        "(synthetic planning inputs); run after provision-component-scenario",
    )
    operations.add_argument(
        "--inputs", type=Path, default=Path("demo_components/operations_inputs.json")
    )
    operations.add_argument("--sites", type=Path, default=Path("demo_data/sites.json"))
    operations.add_argument(
        "--assets", type=Path, default=Path("demo_components/assets.json")
    )
    commands.add_parser(
        "correlate",
        help="Run the incident correlation rules at the current analytical time",
    )
    enrich = commands.add_parser(
        "enrich-demo",
        help="Idempotent SYNTHETIC enrichment of a scenario database: city demo, grants, "
        "contracts, offers, incidents, crews and agenda (refuses unless a scenario is active)",
    )
    enrich.add_argument(
        "--allow-live",
        action="store_true",
        help="Run even though no scenario clock is active",
    )
    arguments = parser.parse_args(argv)
    settings = Settings()
    database = Database(settings.database_path)
    try:
        database.migrate()
        execute(arguments, database, settings)
    except ApiError as exc:
        parser.exit(
            2,
            f"Error [{exc.code}]: {exc.message}\nDatabase: {database.path.resolve()}\n",
        )
    except EOFError:
        parser.exit(
            2,
            "No password was entered. Use an interactive terminal or set SOLAR_ACCOUNT_PASSWORD.\n",
        )
    except KeyboardInterrupt:
        parser.exit(130, "\nCommand cancelled.\n")


def _aware(text: str) -> datetime:
    try:
        return utc(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError as exc:
        raise ApiError(422, "invalid_time", str(exc)) from exc


def store_credentials(settings: Settings, credentials: dict) -> Path:
    """Merge new demo credentials into the private local file (never printed)."""
    destination = settings.database_path.parent / "demo-credentials.json"
    if credentials:
        previous = json.loads(destination.read_text()) if destination.exists() else {}
        previous.update(credentials)
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        if hasattr(os, "fchmod"):  # Not available on Windows.
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(previous, stream, indent=2)
    return destination


def execute(arguments, database: Database, settings: Settings):
    if arguments.command == "import-provider":
        print(
            json.dumps(
                import_provider_snapshot(
                    database, arguments.database, arguments.sites, arguments.frames
                ),
                indent=2,
            )
        )
    elif arguments.command == "import-components":
        print(
            json.dumps(
                import_component_snapshot(database, arguments.database), indent=2
            )
        )
    elif arguments.command == "register-site":
        registration = SiteRegistration.model_validate_json(arguments.path.read_text())
        register_site(database, registration)
        print(f"Registered site {registration.site.site_id}")
    elif arguments.command in ("create-user", "set-password"):
        with database.connect() as connection:
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username=?", (arguments.username,)
            ).fetchone()
        if arguments.command == "create-user" and existing:
            raise ApiError(
                409,
                "account_exists",
                "Username already exists. Sign in with the existing password or use set-password to change it",
            )
        if arguments.command == "set-password" and not existing:
            raise ApiError(
                404,
                "not_found",
                "User not found. Create the account with create-user first",
            )
        password = os.getenv("SOLAR_ACCOUNT_PASSWORD") or getpass.getpass(
            "New password (12–256 characters): "
        )
        if arguments.command == "create-user":
            create_user(
                database,
                arguments.username,
                password,
                arguments.role,
                arguments.account_type,
            )
            print(f"Created account {arguments.username} with no site or area grants")
        else:
            set_password(database, arguments.username, password)
            print(
                f"Updated password for {arguments.username}; existing sessions revoked"
            )
    elif arguments.command == "set-account-type":
        set_account_type(database, arguments.username, arguments.account_type)
        print(f"{arguments.username} is now a {arguments.account_type} account")
    elif arguments.command.startswith("grant-"):
        grant_access(
            database,
            arguments.username,
            arguments.subject,
            arguments.command.removeprefix("grant-"),
        )
        print("Access grant recorded")
    elif arguments.command == "create-crew":
        crew_id = create_crew(
            database,
            arguments.name,
            arguments.area,
            arguments.skills.split(","),
            arguments.shift,
        )
        print(f"Created crew {arguments.name} ({crew_id}) in area {arguments.area}")
    elif arguments.command == "add-crew-member":
        add_crew_member(database, arguments.crew, arguments.username)
        print(f"{arguments.username} is a member of {arguments.crew}")
    elif arguments.command == "seed-demo":
        credentials = seed_demo(database, os.getenv("SOLAR_DEMO_PASSWORD"))
        destination = store_credentials(settings, credentials)
        print(
            f"Synthetic demo ready. New account credentials are stored privately at {destination}"
        )
    elif arguments.command == "provision-component-scenario":
        credentials = seed_component_scenario(
            database,
            os.getenv("SOLAR_DEMO_PASSWORD"),
            arguments.sites,
            arguments.assets,
        )
        destination = store_credentials(settings, credentials)
        print(
            "Component scenario provisioned (fictional placements, explicit grants). "
            f"New account credentials are stored privately at {destination}"
        )
    elif arguments.command == "provision-scenario-operations":
        credentials = seed_scenario_operations(
            database,
            os.getenv("SOLAR_DEMO_PASSWORD"),
            arguments.inputs,
            arguments.sites,
            arguments.assets,
        )
        destination = store_credentials(settings, credentials)
        print(
            "Scenario operations provisioned (synthetic crews, shifts and travel matrix). "
            f"New account credentials are stored privately at {destination}"
        )
    elif arguments.command == "enrich-demo":
        from backend.enrich import enrich_demo

        print(
            json.dumps(
                enrich_demo(database, settings, allow_live=arguments.allow_live),
                indent=2,
                default=str,
            )
        )
    elif arguments.command == "correlate":
        print(json.dumps(run_correlation(database), indent=2, default=str))
    elif arguments.command == "scenario":
        if arguments.scenario_command == "start":
            result = start_scenario(database, arguments.name, _aware(arguments.at))
        elif arguments.scenario_command == "advance":
            result = advance_scenario(
                database,
                to=_aware(arguments.to) if arguments.to else None,
                by=parse_duration(arguments.by) if arguments.by else None,
            )
            if arguments.correlate:
                result["correlation"] = run_correlation(database)
            if arguments.settle:
                result["offers_worker"] = settle_due(database, None, settings)
        else:
            result = scenario_status(database)
        print(json.dumps(result, indent=2))
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
    elif arguments.command == "offers-worker":
        print(
            "Offers worker running; press Ctrl+C to stop"
            if not arguments.once
            else "Offers worker: one pass"
        )
        summary = run_worker(
            database, settings, once=arguments.once, interval=arguments.interval
        )
        if summary is not None:
            print(json.dumps(summary))
    elif arguments.command == "settle-offers":
        now = (
            utc(datetime.fromisoformat(arguments.now.replace("Z", "+00:00")))
            if arguments.now
            else None
        )
        print(json.dumps(settle_due(database, now, settings)))
    elif arguments.command == "simulate-offer-meter":
        print(
            json.dumps(
                simulate_offer_meter(
                    database,
                    arguments.user_offer_id,
                    arguments.fraction,
                    arguments.coverage,
                ),
                indent=2,
            )
        )
    elif arguments.command == "reconcile-savings":
        user_id = None
        if arguments.username:
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT user_id FROM users WHERE username=?", (arguments.username,)
                ).fetchone()
            if not row:
                raise ApiError(404, "not_found", "User not found")
            user_id = row["user_id"]
        mismatches = reconcile(database, user_id, fix=not arguments.check)
        print(json.dumps({"mismatches": mismatches, "fixed": not arguments.check}))
        if mismatches and arguments.check:
            raise SystemExit(1)
    elif arguments.command == "replay-clock":
        timestamp = utc(
            datetime.fromisoformat(arguments.timestamp.replace("Z", "+00:00"))
        )
        with database.connect() as connection:
            scenario_running = clock_state(connection).mode == "scenario"
        if scenario_running:
            # In a scenario run the replay clock is the forward-only analytical clock.
            result = advance_scenario(database, to=timestamp)
            print(f"Scenario clock {result['status']}: {result['analytical_now']}")
            return
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
