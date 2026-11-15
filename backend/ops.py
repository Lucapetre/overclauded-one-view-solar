"""Operations: incidents and their log, crews, assignments, revenue and capacity.

Every query resolves the caller's scope on the server; objects outside it are 404.
All incidents, profiles and billing figures are synthetic demo data.
"""

import json
import uuid
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from backend.db import site_from_row, stamp
from backend.energy import snapshot
from backend.errors import ApiError
from backend.models import User, utc
from backend.ops_models import (
    TIERS,
    AreaCapacity,
    AreaRevenue,
    AssignmentReportRow,
    AssignmentSummary,
    AutoAssigned,
    AutoDispatchResult,
    AutoSkipped,
    BusinessAccount,
    CapacityView,
    Crew,
    CrewActiveAssignment,
    CrewReport,
    Incident,
    IncidentDetail,
    IncidentLogEntry,
    MapCenter,
    MapCluster,
    MapSite,
    OpsMap,
    RevenueBySegment,
    RevenueTotals,
    RevenueView,
    SegmentRevenue,
    TeamsView,
    TierCounts,
)
from backend.security import accessible_sites

ACTIVE = ("assigned", "team_sent", "meeting_scheduled")
BLOCKING = ("assigned", "team_sent")
MAX_MEETING = timedelta(hours=4)
ACTIVE_SQL = "('assigned','team_sent','meeting_scheduled')"
REVENUE_BASIS = (
    "Estimate from synthetic monthly billing profiles multiplied by each site's saved "
    "contract prices, or the default demo tariff when no contract is saved. "
    "These are not invoices or measured settlement figures."
)


@lru_cache
def profile_source() -> dict:
    return json.loads(
        (Path(__file__).parent / "fixtures" / "site_profiles.json").read_text(
            encoding="utf-8"
        )
    )


def require_operations(user: User):
    if user.role == "customer":
        raise ApiError(403, "operations_required", "An operations role is required")


def require_role(user: User, role: str):
    require_operations(user)
    if user.role != role:
        raise ApiError(403, f"{role}_required", f"A {role} account is required")


def ops_sites(connection, user: User):
    """Sites for incidents, map, teams and capacity.

    Supervisors and dispatchers use their normal grants. Technicians additionally
    cover every site in the area of each crew they belong to ("their zone").
    """
    require_operations(user)
    if user.role != "technician":
        return accessible_sites(connection, user)
    return connection.execute(
        "SELECT s.* FROM sites s WHERE "
        "EXISTS (SELECT 1 FROM user_sites us WHERE us.site_id=s.site_id AND us.user_id=?) "
        "OR EXISTS (SELECT 1 FROM user_areas ua WHERE ua.area_id=s.area_id AND ua.user_id=?) "
        "OR EXISTS (SELECT 1 FROM crews c JOIN crew_members m ON m.crew_id=c.crew_id "
        "WHERE c.area_id=s.area_id AND m.user_id=?) "
        # A planned assignment authorizes its crew for that site.
        "OR EXISTS (SELECT 1 FROM assignments a JOIN incidents i ON i.incident_id=a.incident_id "
        "JOIN crew_members m ON m.crew_id=a.crew_id WHERE i.site_id=s.site_id AND m.user_id=? "
        f"AND a.status IN {ACTIVE_SQL}) ORDER BY s.site_id",
        (user.user_id, user.user_id, user.user_id, user.user_id),
    ).fetchall()


def _scope(connection, user: User) -> tuple[str, tuple]:
    """An SQL membership clause for `site_id` restricted to the caller's ops scope."""
    ids = tuple(row["site_id"] for row in ops_sites(connection, user))
    if not ids:
        return "IN (NULL)", ()
    return f"IN ({','.join('?' * len(ids))})", ids


def _bump(connection, reason: str, subject: str):
    from backend.dispatch import bump

    bump(connection, reason, subject)


def log_incident(
    connection,
    incident_id: str,
    actor: str,
    action: str,
    detail: str,
    now: str | None = None,
):
    connection.execute(
        "INSERT INTO incident_log(incident_id,actor,action,detail,created_at) "
        "VALUES (?,?,?,?,?)",
        (incident_id, actor, action, detail, now or stamp()),
    )


def open_incident(
    connection,
    *,
    site_id: str,
    title: str,
    family: str,
    tier: str,
    source: str,
    evidence: str,
    actor: str,
    detail: str,
    support_request_id: str | None = None,
    incident_id: str | None = None,
    now: str | None = None,
) -> str | None:
    """Open an incident with its first log entry. Returns None if the id exists."""
    identifier = incident_id or uuid.uuid4().hex
    now = now or stamp()
    inserted = connection.execute(
        "INSERT OR IGNORE INTO incidents(incident_id,site_id,title,family,tier,status,"
        "source,support_request_id,evidence,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            site_id,
            title,
            family,
            tier,
            "new",
            source,
            support_request_id,
            evidence,
            now,
            now,
        ),
    ).rowcount
    if not inserted:
        return None
    log_incident(connection, identifier, actor, "opened", detail, now)
    return identifier


INCIDENT_SELECT = (
    "SELECT i.*, s.alias AS site_alias, s.area_id AS area_id, p.zone AS zone, "
    "p.segment AS segment, a.assignment_id, a.crew_id, c.name AS crew_name, "
    "a.kind AS assignment_kind, a.status AS assignment_status, "
    "a.scheduled_start, a.scheduled_end "
    "FROM incidents i JOIN sites s ON s.site_id=i.site_id "
    "LEFT JOIN site_profiles p ON p.site_id=i.site_id "
    f"LEFT JOIN assignments a ON a.incident_id=i.incident_id AND a.status IN {ACTIVE_SQL} "
    "LEFT JOIN crews c ON c.crew_id=a.crew_id "
)
SEVERITY_ORDER = " ORDER BY i.tier, i.created_at, i.incident_id"


def _incident(row) -> Incident:
    return Incident(
        **{
            key: row[key]
            for key in (
                "incident_id",
                "site_id",
                "site_alias",
                "area_id",
                "zone",
                "segment",
                "title",
                "family",
                "tier",
                "status",
                "source",
                "evidence",
                "created_at",
                "updated_at",
                "support_request_id",
            )
        },
        assignment=AssignmentSummary(
            assignment_id=row["assignment_id"],
            crew_id=row["crew_id"],
            crew_name=row["crew_name"],
            kind=row["assignment_kind"],
            status=row["assignment_status"],
            scheduled_start=row["scheduled_start"],
            scheduled_end=row["scheduled_end"],
        )
        if row["assignment_id"]
        else None,
    )


def list_incidents(connection, user: User, status: str = "open") -> list[Incident]:
    clause, ids = _scope(connection, user)
    where = f"WHERE i.site_id {clause}"
    if status == "open":
        where += " AND i.status != 'resolved'"
    rows = connection.execute(
        INCIDENT_SELECT + where + SEVERITY_ORDER + " LIMIT 500", ids
    ).fetchall()
    return [_incident(row) for row in rows]


def _visible_incident(connection, user: User, incident_id: str):
    clause, ids = _scope(connection, user)
    row = connection.execute(
        INCIDENT_SELECT + f"WHERE i.incident_id=? AND i.site_id {clause}",
        (incident_id, *ids),
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    return row


def get_incident(connection, user: User, incident_id: str) -> IncidentDetail:
    row = _visible_incident(connection, user, incident_id)
    log = connection.execute(
        "SELECT actor,action,detail,created_at FROM incident_log "
        "WHERE incident_id=? ORDER BY created_at, id",
        (incident_id,),
    ).fetchall()
    return IncidentDetail(
        **_incident(row).model_dump(),
        log=[IncidentLogEntry(**dict(entry)) for entry in log],
    )


def _skills(crew) -> list[str]:
    return json.loads(crew["skills"])


def _eligible(crew, incident) -> bool:
    return crew["area_id"] == incident["area_id"] and incident["family"] in _skills(
        crew
    )


def _busy(connection, crew_id: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM assignments WHERE crew_id=? AND kind='dispatch' "
            "AND status IN ('assigned','team_sent')",
            (crew_id,),
        ).fetchone()
    )


CREW_SELECT = (
    "SELECT c.*, ar.alias AS area_alias FROM crews c "
    "JOIN areas ar ON ar.area_id=c.area_id "
)


def _user_crews(connection, user: User):
    return connection.execute(
        CREW_SELECT + "JOIN crew_members m ON m.crew_id=c.crew_id "
        "WHERE m.user_id=? ORDER BY c.name",
        (user.user_id,),
    ).fetchall()


def _set_status(connection, incident_id: str, status: str, now: str):
    connection.execute(
        "UPDATE incidents SET status=?, updated_at=? WHERE incident_id=?",
        (status, now, incident_id),
    )


def _create_assignment(
    connection,
    incident_id: str,
    crew_id: str,
    kind: str,
    status: str,
    user: User,
    now: str,
    start: str | None = None,
    end: str | None = None,
) -> str:
    identifier = uuid.uuid4().hex
    connection.execute(
        "INSERT INTO assignments(assignment_id,incident_id,crew_id,kind,status,"
        "scheduled_start,scheduled_end,created_by,created_at,completed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,NULL)",
        (identifier, incident_id, crew_id, kind, status, start, end, user.user_id, now),
    )
    return identifier


def _require_open(row):
    if row["status"] == "resolved":
        raise ApiError(409, "incident_resolved", "This incident is already resolved")


def _require_legacy_workflow(connection, incident_id: str):
    """Correlated work must keep the plan constraints and documented closure audit."""
    if connection.execute(
        "SELECT 1 FROM episodes WHERE incident_id=?", (incident_id,)
    ).fetchone():
        raise ApiError(
            409,
            "episode_workflow_required",
            "Use a reviewed crew plan, assignment progress or documented episode closure "
            "for correlated incidents",
        )


def assign_incident(
    database, connection, user: User, incident_id: str, crew_id: str | None, rid: str
) -> IncidentDetail:
    require_role(user, "dispatcher")
    connection.execute("BEGIN IMMEDIATE")
    row = _visible_incident(connection, user, incident_id)
    _require_legacy_workflow(connection, incident_id)
    _require_open(row)
    if row["assignment_id"]:
        raise ApiError(
            409, "already_assigned", "This incident already has an active assignment"
        )
    if crew_id:
        crew = connection.execute(
            "SELECT * FROM crews WHERE crew_id=?", (crew_id,)
        ).fetchone()
        if not crew:
            raise ApiError(404, "not_found", "Resource not found")
        if not _eligible(crew, row):
            raise ApiError(
                422,
                "crew_not_eligible",
                "The crew must work in the incident's area and cover its family",
            )
        if _busy(connection, crew_id):
            raise ApiError(
                409, "crew_unavailable", "The crew already has an active dispatch"
            )
    else:
        crew = next(
            (
                candidate
                for candidate in connection.execute(
                    "SELECT * FROM crews ORDER BY name"
                ).fetchall()
                if _eligible(candidate, row)
                and not _busy(connection, candidate["crew_id"])
            ),
            None,
        )
        if not crew:
            raise ApiError(
                409, "no_available_crew", "No eligible crew is available right now"
            )
    now = stamp()
    _create_assignment(
        connection, incident_id, crew["crew_id"], "dispatch", "assigned", user, now
    )
    _set_status(connection, incident_id, "assigned", now)
    log_incident(
        connection,
        incident_id,
        user.username,
        "assigned",
        f"Assigned to crew {crew['name']} by {user.username}",
        now,
    )
    database.audit(connection, user.user_id, "incident.assigned", incident_id, rid)
    _bump(connection, "incident.assigned", incident_id)
    return get_incident(connection, user, incident_id)


def auto_dispatch(database, connection, user: User, rid: str) -> AutoDispatchResult:
    require_role(user, "dispatcher")
    connection.execute("BEGIN IMMEDIATE")
    clause, ids = _scope(connection, user)
    incidents = connection.execute(
        INCIDENT_SELECT
        + f"WHERE i.site_id {clause} AND i.status != 'resolved' AND a.assignment_id IS NULL"
        + " AND NOT EXISTS (SELECT 1 FROM episodes e WHERE e.incident_id=i.incident_id)"
        + SEVERITY_ORDER,
        ids,
    ).fetchall()
    crews = connection.execute("SELECT * FROM crews ORDER BY name").fetchall()
    busy = {crew["crew_id"] for crew in crews if _busy(connection, crew["crew_id"])}
    assigned, skipped = [], []
    now = stamp()
    for row in incidents:
        eligible = [crew for crew in crews if _eligible(crew, row)]
        free = [crew for crew in eligible if crew["crew_id"] not in busy]
        if not free:
            skipped.append(
                AutoSkipped(
                    incident_id=row["incident_id"],
                    tier=row["tier"],
                    reason="no_available_crew" if eligible else "no_eligible_crew",
                )
            )
            continue
        crew = free[0]
        busy.add(crew["crew_id"])
        _create_assignment(
            connection,
            row["incident_id"],
            crew["crew_id"],
            "dispatch",
            "assigned",
            user,
            now,
        )
        _set_status(connection, row["incident_id"], "assigned", now)
        log_incident(
            connection,
            row["incident_id"],
            user.username,
            "auto_assigned",
            f"Auto-assigned by severity ({row['tier']}) to crew {crew['name']} by {user.username}",
            now,
        )
        database.audit(
            connection, user.user_id, "incident.auto_assigned", row["incident_id"], rid
        )
        assigned.append(
            AutoAssigned(
                incident_id=row["incident_id"], crew_name=crew["name"], tier=row["tier"]
            )
        )
    if assigned:
        _bump(connection, "incident.auto_assigned", "auto-dispatch")
    return AutoDispatchResult(assigned=assigned, skipped=skipped)


def _technician_crew(connection, user: User, row):
    """The technician's crew for this incident and its active assignment, if any."""
    mine = _user_crews(connection, user)
    if row["assignment_id"]:
        crew = next((c for c in mine if c["crew_id"] == row["crew_id"]), None)
        if not crew:
            raise ApiError(
                409,
                "assigned_to_other_crew",
                "Another crew is already assigned to this incident",
            )
        return crew
    crew = next((c for c in mine if _eligible(c, row)), None)
    if not crew:
        raise ApiError(
            422,
            "crew_not_eligible",
            "None of your crews covers this incident's area and family",
        )
    return crew


def send_team(
    database, connection, user: User, incident_id: str, rid: str
) -> IncidentDetail:
    require_role(user, "technician")
    connection.execute("BEGIN IMMEDIATE")
    row = _visible_incident(connection, user, incident_id)
    _require_legacy_workflow(connection, incident_id)
    _require_open(row)
    crew = _technician_crew(connection, user, row)
    now = stamp()
    if row["assignment_id"] and row["assignment_kind"] == "dispatch":
        if row["assignment_status"] == "team_sent":
            raise ApiError(409, "team_already_sent", "The team is already on its way")
        connection.execute(
            "UPDATE assignments SET status='team_sent' WHERE assignment_id=?",
            (row["assignment_id"],),
        )
    else:
        if _busy(connection, crew["crew_id"]):
            raise ApiError(
                409, "crew_unavailable", "Your crew already has an active dispatch"
            )
        if row["assignment_id"]:
            # A scheduled meeting becomes an on-site visit.
            connection.execute(
                "UPDATE assignments SET kind='dispatch', status='team_sent', "
                "scheduled_start=NULL, scheduled_end=NULL WHERE assignment_id=?",
                (row["assignment_id"],),
            )
        else:
            _create_assignment(
                connection,
                incident_id,
                crew["crew_id"],
                "dispatch",
                "team_sent",
                user,
                now,
            )
    _set_status(connection, incident_id, "team_sent", now)
    log_incident(
        connection,
        incident_id,
        user.username,
        "team_sent",
        f"Crew {crew['name']} sent to the site by {user.username}",
        now,
    )
    database.audit(connection, user.user_id, "incident.team_sent", incident_id, rid)
    _bump(connection, "incident.team_sent", incident_id)
    return get_incident(connection, user, incident_id)


def _clock(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC")


def schedule_meeting(
    database,
    connection,
    user: User,
    incident_id: str,
    start: datetime,
    end: datetime,
    rid: str,
) -> IncidentDetail:
    require_role(user, "technician")
    try:
        start, end = utc(start), utc(end)
    except ValueError as exc:
        raise ApiError(422, "invalid_meeting", str(exc)) from exc
    if not start < end or end - start > MAX_MEETING:
        raise ApiError(
            422, "invalid_meeting", "A meeting must end after it starts, within 4 hours"
        )
    connection.execute("BEGIN IMMEDIATE")
    row = _visible_incident(connection, user, incident_id)
    _require_legacy_workflow(connection, incident_id)
    _require_open(row)
    crew = _technician_crew(connection, user, row)
    begins, ends = stamp(start), stamp(end)
    if connection.execute(
        "SELECT 1 FROM assignments WHERE crew_id=? AND kind='meeting' "
        "AND status='meeting_scheduled' AND scheduled_start < ? AND scheduled_end > ? "
        "AND assignment_id != ?",
        (crew["crew_id"], ends, begins, row["assignment_id"] or ""),
    ).fetchone():
        raise ApiError(
            409, "meeting_overlap", "Your crew already has a meeting at that time"
        )
    now = stamp()
    if row["assignment_id"]:
        connection.execute(
            "UPDATE assignments SET kind='meeting', status='meeting_scheduled', "
            "scheduled_start=?, scheduled_end=? WHERE assignment_id=?",
            (begins, ends, row["assignment_id"]),
        )
    else:
        _create_assignment(
            connection,
            incident_id,
            crew["crew_id"],
            "meeting",
            "meeting_scheduled",
            user,
            now,
            begins,
            ends,
        )
    _set_status(connection, incident_id, "meeting_scheduled", now)
    log_incident(
        connection,
        incident_id,
        user.username,
        "meeting_scheduled",
        f"Meeting scheduled {_clock(start)}–{_clock(end)} by {user.username} "
        f"for crew {crew['name']}",
        now,
    )
    database.audit(
        connection, user.user_id, "incident.meeting_scheduled", incident_id, rid
    )
    _bump(connection, "incident.meeting_scheduled", incident_id)
    return get_incident(connection, user, incident_id)


def resolve_incident(
    database,
    connection,
    user: User,
    incident_id: str,
    rid: str,
    detail: str | None = None,
    began: bool = False,
) -> IncidentDetail:
    """Authorized closure. A correlated episode records it as its resolution provenance;
    children of a closed parent stay open."""
    require_operations(user)
    if not began:
        connection.execute("BEGIN IMMEDIATE")
    row = _visible_incident(connection, user, incident_id)
    if not began or detail is None:
        _require_legacy_workflow(connection, incident_id)
    if row["status"] == "resolved":
        raise ApiError(409, "already_resolved", "This incident is already resolved")
    if user.role == "technician" and not (
        row["assignment_id"]
        and any(c["crew_id"] == row["crew_id"] for c in _user_crews(connection, user))
    ):
        raise ApiError(
            403,
            "crew_member_required",
            "Only a member of the assigned crew can resolve this incident",
        )
    from backend.dispatch import on_resolved

    now = stamp()
    detail = detail or f"Resolved by {user.username}"
    if row["assignment_id"]:
        connection.execute(
            "UPDATE assignments SET status='completed', completed_at=? WHERE assignment_id=?",
            (now, row["assignment_id"]),
        )
        detail += f"; crew {row['crew_name']} completed the assignment and is free"
    _set_status(connection, incident_id, "resolved", now)
    log_incident(connection, incident_id, user.username, "resolved", detail, now)
    on_resolved(connection, incident_id, user, detail)
    database.audit(connection, user.user_id, "incident.resolved", incident_id, rid)
    return get_incident(connection, user, incident_id)


def request_meeting(connection, incident_id: str):
    return connection.execute(
        "SELECT a.scheduled_start AS start, a.scheduled_end AS end, c.name AS crew_name "
        "FROM assignments a JOIN crews c ON c.crew_id=a.crew_id "
        "WHERE a.incident_id=? AND a.kind='meeting' AND a.status='meeting_scheduled' "
        "ORDER BY a.created_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()


def ops_map(connection, user: User) -> OpsMap:
    clause, ids = _scope(connection, user)
    rows = connection.execute(
        "SELECT s.*, ar.alias AS area_alias, p.latitude, p.longitude, p.zone, "
        "p.character, p.segment, p.business_type, p.installed_kwp, p.cluster "
        "FROM sites s JOIN site_profiles p ON p.site_id=s.site_id "
        "LEFT JOIN areas ar ON ar.area_id=s.area_id "
        f"WHERE s.site_id {clause} "
        "ORDER BY s.site_id",
        ids,
    ).fetchall()
    open_counts = {
        row["site_id"]: row
        for row in connection.execute(
            "SELECT site_id, COUNT(*) AS open_incidents, MIN(tier) AS worst_tier "
            f"FROM incidents WHERE status != 'resolved' AND site_id {clause} "
            "GROUP BY site_id",
            ids,
        )
    }
    from backend import dispatch

    view = dispatch.projection(connection, user)
    status = {item["site_id"]: item for item in view["sites"] + view["unmapped"]}

    def overlay(site_id):
        item = status.get(site_id)
        if not item:
            return {}
        return {
            "condition": item["condition"],
            "telemetry_state": item["telemetry"]["state"],
            "workflow": item["workflow"],
            "highest_priority": item["highest_priority"],
            "episode_ids": item["episode_ids"],
        }

    source = profile_source()
    in_scope = {row["cluster"] for row in rows}
    return OpsMap(
        revision=view["revision"],
        status_as_of=view["status_as_of"],
        status_sites=view["sites"],
        unmapped=view["unmapped"],
        counts=view["counts"],
        crews=dispatch.crew_markers(connection, user),
        routes=dispatch.routes(connection, user),
        center=MapCenter(**source["center"]),
        note=source["note"],
        clusters=[
            MapCluster(**cluster)
            for cluster in source["clusters"]
            if cluster["id"] in in_scope
        ],
        sites=[
            MapSite(
                **{
                    key: row[key]
                    for key in (
                        "site_id",
                        "alias",
                        "area_id",
                        "area_alias",
                        "cluster",
                        "latitude",
                        "longitude",
                        "zone",
                        "character",
                        "segment",
                        "business_type",
                        "installed_kwp",
                    )
                },
                freshness_status=snapshot(
                    connection, site_from_row(row)
                ).freshness.status,
                open_incidents=open_counts[row["site_id"]]["open_incidents"]
                if row["site_id"] in open_counts
                else 0,
                worst_tier=open_counts[row["site_id"]]["worst_tier"]
                if row["site_id"] in open_counts
                else None,
                **overlay(row["site_id"]),
            )
            for row in rows
        ],
    )


def _visible_crews(connection, user: User):
    require_operations(user)
    if user.role == "technician":
        return _user_crews(connection, user)
    return connection.execute(
        CREW_SELECT + "WHERE c.area_id IN "
        "(SELECT area_id FROM user_areas WHERE user_id=?) ORDER BY c.name",
        (user.user_id,),
    ).fetchall()


ACTIVE_ASSIGNMENT_SELECT = (
    "SELECT a.*, i.title AS incident_title, i.tier, i.site_id, s.alias AS site_alias "
    "FROM assignments a JOIN incidents i ON i.incident_id=a.incident_id "
    "JOIN sites s ON s.site_id=i.site_id "
)


def _crew_view(connection, crew) -> Crew:
    members = [
        row["username"]
        for row in connection.execute(
            "SELECT u.username FROM crew_members m JOIN users u ON u.user_id=m.user_id "
            "WHERE m.crew_id=? ORDER BY u.username",
            (crew["crew_id"],),
        )
    ]
    # The blocking on-site dispatch first, otherwise the next scheduled meeting.
    active = connection.execute(
        ACTIVE_ASSIGNMENT_SELECT + f"WHERE a.crew_id=? AND a.status IN {ACTIVE_SQL} "
        "ORDER BY CASE WHEN a.kind='dispatch' THEN 0 ELSE 1 END, "
        "a.scheduled_start, a.created_at LIMIT 1",
        (crew["crew_id"],),
    ).fetchone()
    counts = connection.execute(
        "SELECT a.status, i.tier, COUNT(*) AS n FROM assignments a "
        "JOIN incidents i ON i.incident_id=a.incident_id "
        "WHERE a.crew_id=? AND a.status != 'cancelled' GROUP BY a.status, i.tier",
        (crew["crew_id"],),
    ).fetchall()
    open_by_tier = dict.fromkeys(TIERS, 0)
    completed_by_tier = dict.fromkeys(TIERS, 0)
    for row in counts:
        if row["status"] == "completed":
            completed_by_tier[row["tier"]] += row["n"]
        elif row["status"] in ACTIVE:
            open_by_tier[row["tier"]] += row["n"]
    return Crew(
        crew_id=crew["crew_id"],
        name=crew["name"],
        area_id=crew["area_id"],
        area_alias=crew["area_alias"],
        skills=_skills(crew),
        shift=crew["shift"],
        members=members,
        available=not _busy(connection, crew["crew_id"]),
        active_assignment=CrewActiveAssignment(
            **{
                key: active[key]
                for key in (
                    "assignment_id",
                    "incident_id",
                    "incident_title",
                    "tier",
                    "site_id",
                    "site_alias",
                    "kind",
                    "status",
                    "scheduled_start",
                    "scheduled_end",
                )
            }
        )
        if active
        else None,
        profile=_crew_profile(connection, crew["crew_id"]),
        report=CrewReport(
            assigned_total=sum(row["n"] for row in counts),
            completed_total=sum(
                row["n"] for row in counts if row["status"] == "completed"
            ),
            open_by_tier=TierCounts(**open_by_tier),
            completed_by_tier=TierCounts(**completed_by_tier),
        ),
    )


def _crew_profile(connection, crew_id: str) -> dict | None:
    """Synthetic planning profile (qualifications, base, current shift) when provisioned."""
    from backend.clock import analytical_now
    from backend.dispatch import _node_position

    row = connection.execute(
        "SELECT * FROM crew_profiles WHERE crew_id=?", (crew_id,)
    ).fetchone()
    if not row:
        return None
    now = stamp(analytical_now(connection))
    shift = connection.execute(
        "SELECT shift_start, shift_end FROM crew_shifts WHERE crew_id=? AND shift_end>? "
        "ORDER BY shift_start LIMIT 1",
        (crew_id, now),
    ).fetchone()
    return {
        "kind": row["kind"],
        "organisation": row["organisation"],
        "authorised_services": json.loads(row["authorised_services"]),
        "qualifications": json.loads(row["qualifications"]),
        "tools": json.loads(row["tools"]),
        "areas": json.loads(row["areas"]),
        "base": _node_position(connection, row["base_node"])
        if row["base_node"]
        else None,
        "location_reported_at": row["location_reported_at"],
        "location_basis": row["location_basis"],
        "shift_start": shift["shift_start"] if shift else None,
        "shift_end": shift["shift_end"] if shift else None,
        "label": "Synthetic planning inputs (fictional crew, shift and depot)",
    }


def teams(connection, user: User) -> TeamsView:
    crews = [_crew_view(connection, crew) for crew in _visible_crews(connection, user)]
    clause, ids = _scope(connection, user)
    unassigned = connection.execute(
        "SELECT COUNT(*) FROM incidents i WHERE i.status != 'resolved' "
        f"AND i.site_id {clause} AND NOT EXISTS (SELECT 1 FROM assignments a "
        f"WHERE a.incident_id=i.incident_id AND a.status IN {ACTIVE_SQL})",
        ids,
    ).fetchone()[0]
    report = connection.execute(
        "SELECT a.assignment_id, a.incident_id, i.title AS incident_title, i.tier, "
        "s.alias AS site_alias, s.area_id, c.name AS crew_name, a.kind, a.status, "
        "u.username AS created_by, a.created_at, a.scheduled_start, a.scheduled_end, "
        "a.completed_at FROM assignments a "
        "JOIN incidents i ON i.incident_id=a.incident_id "
        "JOIN sites s ON s.site_id=i.site_id JOIN crews c ON c.crew_id=a.crew_id "
        "JOIN users u ON u.user_id=a.created_by "
        f"WHERE i.site_id {clause} ORDER BY a.created_at DESC, a.assignment_id LIMIT 200",
        ids,
    ).fetchall()
    from backend.dispatch import current_revision

    return TeamsView(
        revision=current_revision(connection),
        crews=crews,
        unassigned_incidents=unassigned,
        assignments=[AssignmentReportRow(**dict(row)) for row in report],
    )


def _money(value: float) -> float:
    return round(value + 0.0, 2)


AMOUNTS = ("energy_sales_ron", "export_payments_ron", "service_fees_ron")


def _amounts(total: dict) -> dict:
    values = {key: _money(total[key]) for key in AMOUNTS}
    values["net_revenue_ron"] = _money(
        total["energy_sales_ron"]
        + total["service_fees_ron"]
        - total["export_payments_ron"]
    )
    return values


def _net(total: dict) -> float:
    return (
        total["energy_sales_ron"]
        + total["service_fees_ron"]
        - total["export_payments_ron"]
    )


def _provider_billing_rows(connection, user: User) -> list[dict]:
    """Billing profiles for the provider scenario sites (which have no `site_profiles` row).

    Monthly energy is the measured PCC meter energy of the imported week scaled to 30 days when the
    site has an authoritative meter; otherwise a labelled demo profile from the installed kWp.
    Service fees are demo assumptions. These are estimates, never invoices.
    """
    placed = connection.execute(
        "SELECT p.site_id, s.alias, s.area_id, p.location_label AS zone, p.segment, "
        "p.business_type, p.installed_kwp, c.import_price_ron_kwh, c.export_price_ron_kwh "
        "FROM site_placements p JOIN sites s ON s.site_id=p.site_id "
        "LEFT JOIN contracts c ON c.site_id=p.site_id "
        "WHERE s.area_id IN (SELECT area_id FROM user_areas WHERE user_id=?) "
        "AND NOT EXISTS (SELECT 1 FROM site_profiles sp WHERE sp.site_id=p.site_id) "
        "ORDER BY p.site_id",
        (user.user_id,),
    ).fetchall()
    rows = []
    for row in placed:
        kwp = row["installed_kwp"] or 5.0
        business = row["segment"] == "business"
        measured = {
            metric: connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(value_kwh),0) FROM component_grid_frames "
                "WHERE site_id=? AND metric=? AND value_origin='measured' "
                "AND value_kwh IS NOT NULL",
                (row["site_id"], metric),
            ).fetchone()
            for metric in ("grid_import", "grid_export")
        }
        frames = min(measured["grid_import"][0], measured["grid_export"][0])
        if frames >= 96:
            scale = 30 * 96 / frames
            monthly_import = measured["grid_import"][1] * scale
            monthly_export = measured["grid_export"][1] * scale
        else:
            monthly_import = (900 + 120 * kwp) if business else (130 + 25 * kwp)
            monthly_export = (40 * kwp) if business else (90 * kwp)
        rows.append(
            {
                **dict(row),
                "installed_kwp": kwp,
                "monthly_import_kwh": round(monthly_import, 1),
                "monthly_export_kwh": round(monthly_export, 1),
                "service_fee_ron": 120.0 if business else 25.0,
            }
        )
    return rows


def revenue(connection, user: User) -> RevenueView:
    require_role(user, "supervisor")
    tariff = profile_source()["default_tariff"]
    areas = connection.execute(
        "SELECT a.* FROM areas a JOIN user_areas ua ON ua.area_id=a.area_id "
        "WHERE ua.user_id=? ORDER BY a.area_id",
        (user.user_id,),
    ).fetchall()
    rows = connection.execute(
        "SELECT s.site_id, s.alias, s.area_id, p.*, c.import_price_ron_kwh, "
        "c.export_price_ron_kwh FROM sites s JOIN site_profiles p ON p.site_id=s.site_id "
        "LEFT JOIN contracts c ON c.site_id=s.site_id "
        "WHERE s.area_id IN (SELECT area_id FROM user_areas WHERE user_id=?) "
        "ORDER BY s.site_id",
        (user.user_id,),
    ).fetchall()

    rows = [*rows, *_provider_billing_rows(connection, user)]

    def empty():
        return {key: 0.0 for key in AMOUNTS} | {"sites": 0}

    totals = empty()
    segments = {"home": empty(), "business": empty()}
    by_area = {
        area["area_id"]: empty() | {"business_sites": 0, "business_net": 0.0}
        for area in areas
    }
    accounts = []
    for row in rows:
        contract = row["import_price_ron_kwh"] is not None
        import_price = (
            row["import_price_ron_kwh"] if contract else tariff["import_price_ron_kwh"]
        )
        export_price = (
            row["export_price_ron_kwh"] if contract else tariff["export_price_ron_kwh"]
        )
        site = {
            "energy_sales_ron": row["monthly_import_kwh"] * import_price,
            "export_payments_ron": row["monthly_export_kwh"] * export_price,
            "service_fees_ron": row["service_fee_ron"],
        }
        targets = [totals, segments[row["segment"]], by_area[row["area_id"]]]
        for target in targets:
            for key in AMOUNTS:
                target[key] += site[key]
            target["sites"] += 1
        if row["segment"] == "business":
            by_area[row["area_id"]]["business_sites"] += 1
            by_area[row["area_id"]]["business_net"] += _net(site)
            accounts.append(
                (
                    _net(site),
                    BusinessAccount(
                        **{
                            key: row[key]
                            for key in (
                                "site_id",
                                "alias",
                                "area_id",
                                "zone",
                                "business_type",
                                "installed_kwp",
                                "monthly_import_kwh",
                                "monthly_export_kwh",
                            )
                        },
                        **_amounts(site),
                        import_price_ron_kwh=import_price,
                        export_price_ron_kwh=export_price,
                        price_source="contract" if contract else "default_tariff",
                    ),
                )
            )
    net = _net(totals)
    accounts.sort(key=lambda item: (-item[0], item[1].site_id))
    return RevenueView(
        period="monthly",
        basis=REVENUE_BASIS,
        currency="RON",
        totals=RevenueTotals(**_amounts(totals), sites=totals["sites"]),
        by_segment=RevenueBySegment(
            **{
                name: SegmentRevenue(
                    **_amounts(segment),
                    sites=segment["sites"],
                    share_of_net=round(_net(segment) / net, 4) if net > 0 else 0.0,
                )
                for name, segment in segments.items()
            }
        ),
        by_area=[
            AreaRevenue(
                area_id=area["area_id"],
                alias=area["alias"],
                **_amounts(by_area[area["area_id"]]),
                sites=by_area[area["area_id"]]["sites"],
                business_sites=by_area[area["area_id"]]["business_sites"],
                business_net_revenue_ron=_money(
                    by_area[area["area_id"]]["business_net"]
                ),
            )
            for area in areas
        ],
        business_accounts=[account for _, account in accounts],
        annualized_net_revenue_ron=_money(net * 12),
    )


def capacity(connection, user: User) -> CapacityView:
    clause, ids = _scope(connection, user)
    rows = connection.execute(
        "SELECT s.area_id, ar.alias, COUNT(*) AS sites, SUM(p.installed_kwp) AS installed_kwp "
        "FROM sites s JOIN site_profiles p ON p.site_id=s.site_id "
        "JOIN areas ar ON ar.area_id=s.area_id "
        f"WHERE s.site_id {clause} GROUP BY s.area_id, ar.alias ORDER BY s.area_id",
        ids,
    ).fetchall()
    areas = [
        AreaCapacity(
            area_id=row["area_id"],
            alias=row["alias"],
            sites=row["sites"],
            installed_kwp=round(row["installed_kwp"], 3),
        )
        for row in rows
    ]
    return CapacityView(
        areas=areas,
        total_installed_kwp=round(sum(area.installed_kwp for area in areas), 3),
    )
