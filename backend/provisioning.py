import json
import re
import uuid

from backend.db import Database, site_from_row
from backend.errors import ApiError
from backend.models import SiteRegistration, User
from backend.ops_models import FAMILIES
from backend.security import hash_password

SHIFT_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def create_crew(
    database: Database,
    name: str,
    area_id: str,
    skills: list[str],
    shift: str = "08:00-18:00",
) -> str:
    """Local administration only: a crew works in one area and covers incident families."""
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise ApiError(422, "invalid_crew", "Crew name must be 1–80 characters")
    skills = list(dict.fromkeys(skill.strip() for skill in skills if skill.strip()))
    unknown = [skill for skill in skills if skill not in FAMILIES]
    if not skills or unknown:
        raise ApiError(
            422,
            "invalid_skills",
            "Skills must be a comma-separated list of: " + ", ".join(FAMILIES),
        )
    if not SHIFT_PATTERN.match(shift):
        raise ApiError(422, "invalid_shift", "Shift must look like 08:00-18:00")
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if not connection.execute(
            "SELECT 1 FROM areas WHERE area_id=?", (area_id,)
        ).fetchone():
            raise ApiError(404, "not_found", "Area not found")
        if connection.execute("SELECT 1 FROM crews WHERE name=?", (name,)).fetchone():
            raise ApiError(409, "crew_exists", "A crew with this name already exists")
        crew_id = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "crew"
        if connection.execute(
            "SELECT 1 FROM crews WHERE crew_id=?", (crew_id,)
        ).fetchone():
            crew_id = f"{crew_id}-{uuid.uuid4().hex[:8]}"
        connection.execute(
            "INSERT INTO crews(crew_id,name,area_id,skills,shift) VALUES (?,?,?,?,?)",
            (crew_id, name, area_id, json.dumps(skills), shift),
        )
        database.audit(
            connection, "local-admin", "crew.created", crew_id, "local-provisioning"
        )
    return crew_id


def add_crew_member(database: Database, crew_name: str, username: str):
    with database.connect() as connection:
        crew = connection.execute(
            "SELECT crew_id FROM crews WHERE name=?", (crew_name,)
        ).fetchone()
        if not crew:
            raise ApiError(
                404, "not_found", "Crew not found. Create it with create-crew first"
            )
        user = connection.execute(
            "SELECT user_id,role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not user:
            raise ApiError(
                404,
                "not_found",
                "User not found. Create the account with create-user first",
            )
        if user["role"] != "technician":
            raise ApiError(
                422, "invalid_account", "Only technician accounts can join a crew"
            )
        connection.execute(
            "INSERT OR IGNORE INTO crew_members(crew_id,user_id) VALUES (?,?)",
            (crew["crew_id"], user["user_id"]),
        )
        database.audit(
            connection,
            "local-admin",
            "crew.member.added",
            crew["crew_id"] + ":" + user["user_id"],
            "local-provisioning",
        )


def register_site(database: Database, registration: SiteRegistration):
    """Local administration only. Changes to an existing stream need an explicit migration."""
    site = registration.site
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT * FROM sites WHERE site_id=?", (site.site_id,)
        ).fetchone()
        if existing:
            stream = connection.execute(
                "SELECT device_id,source_id FROM energy_streams WHERE site_id=?",
                (site.site_id,),
            ).fetchone()
            current = site_from_row(existing)
            placement = connection.execute(
                "SELECT area_id FROM site_placements WHERE site_id=?", (site.site_id,)
            ).fetchone()
            # An explicit local placement (provision-component-scenario) sets the area of
            # an imported site; a re-import without an area still matches its contract.
            if (
                placement
                and site.area_id is None
                and current.area_id == placement["area_id"]
            ):
                current = current.model_copy(update={"area_id": None})
            if (
                current == site
                and stream
                and tuple(stream) == (registration.device_id, registration.source_id)
            ):
                return
            raise ApiError(
                409,
                "site_conflict",
                "Existing site configuration differs; use a reviewed database migration",
            )
        if registration.area:
            previous = connection.execute(
                "SELECT * FROM areas WHERE area_id=?", (registration.area.area_id,)
            ).fetchone()
            if previous and dict(previous) != registration.area.model_dump():
                raise ApiError(
                    409, "area_conflict", "Existing area configuration differs"
                )
            connection.execute(
                "INSERT OR IGNORE INTO areas VALUES (?,?,?)",
                (
                    registration.area.area_id,
                    registration.area.alias,
                    registration.area.topology_mode,
                ),
            )
        elif (
            site.area_id
            and not connection.execute(
                "SELECT 1 FROM areas WHERE area_id=?", (site.area_id,)
            ).fetchone()
        ):
            raise ApiError(
                422,
                "unknown_area",
                "Include the area configuration when registering its first site",
            )
        connection.execute(
            "INSERT INTO sites VALUES (?,?,?,?,?,?,?,?)",
            (
                site.site_id,
                site.alias,
                site.area_id,
                site.topology_mode,
                site.reporting_interval_seconds,
                site.stale_after_seconds,
                json.dumps(site.capabilities),
                json.dumps(site.measurement_requirements),
            ),
        )
        connection.execute(
            "INSERT INTO devices VALUES (?,?,?)",
            (registration.device_id, site.site_id, registration.source_id),
        )
        connection.execute(
            "INSERT INTO energy_streams VALUES (?,?,?)",
            (site.site_id, registration.device_id, registration.source_id),
        )
        database.audit(
            connection,
            "local-admin",
            "site.registered",
            site.site_id,
            "local-provisioning",
        )


def create_user(
    database: Database,
    username: str,
    password: str,
    role: str,
    account_type: str = "home",
):
    if not 1 <= len(username) <= 96:
        raise ApiError(
            422,
            "invalid_account",
            "Username must be 1–96 characters",
        )
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM users WHERE username=?", (username,)
        ).fetchone():
            raise ApiError(
                409,
                "account_exists",
                "Username already exists. Sign in with the existing password or use set-password to change it",
            )
        validate_password(password)
        if account_type not in ("home", "business") or (
            account_type == "business" and role != "customer"
        ):
            raise ApiError(
                422,
                "invalid_account",
                "Account type is home or business, and business applies to customers only",
            )
        user = User(
            user_id=uuid.uuid4().hex,
            username=username,
            role=role,
            account_type=account_type,
        )
        connection.execute(
            "INSERT INTO users(user_id,username,password_hash,role,account_type) VALUES (?,?,?,?,?)",
            (
                user.user_id,
                user.username,
                hash_password(password),
                user.role,
                user.account_type,
            ),
        )
        database.audit(
            connection,
            "local-admin",
            "user.created",
            user.user_id,
            "local-provisioning",
        )


def validate_password(password: str):
    if not 12 <= len(password) <= 256:
        raise ApiError(422, "invalid_password", "Password must be 12–256 characters")


def set_password(database: Database, username: str, password: str):
    """Local administrator password change; existing sessions are revoked."""
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT user_id FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise ApiError(
                404,
                "not_found",
                "User not found. Create the account with create-user first",
            )
        validate_password(password)
        connection.execute(
            "UPDATE users SET password_hash=? WHERE user_id=?",
            (hash_password(password), row["user_id"]),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        database.audit(
            connection,
            "local-admin",
            "user.password.changed",
            row["user_id"],
            "local-provisioning",
        )


def set_account_type(database: Database, username: str, account_type: str):
    """Local administrator change between a home and a business customer account."""
    with database.connect() as connection:
        row = connection.execute(
            "SELECT user_id,role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not row:
            raise ApiError(
                404,
                "not_found",
                "User not found. Create the account with create-user first",
            )
        if row["role"] != "customer":
            raise ApiError(
                422, "invalid_account", "Only customer accounts have an account type"
            )
        connection.execute(
            "UPDATE users SET account_type=? WHERE user_id=?",
            (account_type, row["user_id"]),
        )
        database.audit(
            connection,
            "local-admin",
            f"user.account_type.{account_type}",
            row["user_id"],
            "local-provisioning",
        )


def grant_access(database: Database, username: str, subject: str, kind: str):
    with database.connect() as connection:
        user = connection.execute(
            "SELECT user_id,role FROM users WHERE username=?", (username,)
        ).fetchone()
        if not user:
            raise ApiError(
                404,
                "not_found",
                "User not found. Create the account with create-user first",
            )
        if kind == "area":
            if user["role"] == "customer":
                raise ApiError(
                    403,
                    "operations_required",
                    "Customers cannot receive area-wide access",
                )
            if not connection.execute(
                "SELECT 1 FROM areas WHERE area_id=?", (subject,)
            ).fetchone():
                raise ApiError(404, "not_found", "Area not found")
            connection.execute(
                "INSERT OR IGNORE INTO user_areas VALUES (?,?)",
                (user["user_id"], subject),
            )
        elif kind == "site":
            if not connection.execute(
                "SELECT 1 FROM sites WHERE site_id=?", (subject,)
            ).fetchone():
                raise ApiError(404, "not_found", "Site not found")
            connection.execute(
                "INSERT OR IGNORE INTO user_sites VALUES (?,?)",
                (user["user_id"], subject),
            )
        else:
            raise ValueError("Access kind must be site or area")
        database.audit(
            connection,
            "local-admin",
            f"access.{kind}.granted",
            user["user_id"] + ":" + subject,
            "local-provisioning",
        )
