"""One site-status projection for the map, queue, detail and counts.

Independent dimensions per site, computed from the same evidence/workflow revision:

* condition  - observed_active | suspected | no_active_issue_under_evaluated_rules |
               not_evaluated ("no active issue detected in available data" never certifies
               a healthy installation; missing data is unknown, not green)
* telemetry  - fresh | partial | stale | missing | access_error, plus coverage and
               unsupported capabilities
* workflow   - needs_review | monitoring | remote_triage | field_action_needed | proposed |
               assigned | en_route | on_site | resolved | none
* highest active priority, parent episodes, affected assets and the crew/ETA when authorized.

Counts distinguish unique affected sites from unique episodes. Sites without coordinates are
listed as unmapped and never placed at (0,0) or at another site's position.

`build_projection` is pure; `backend/ops.py` gathers the rows inside the caller's scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

BANDS = ("P0", "P1", "P2", "P3")
WORKFLOW_ORDER = (
    "on_site",
    "en_route",
    "assigned",
    "proposed",
    "field_action_needed",
    "remote_triage",
    "needs_review",
    "monitoring",
    "resolved",
    "none",
)
ATTENTION = {
    "P0": "critical",
    "P1": "high",
    "P2": "elevated",
    "P3": "monitor",
}
TELEMETRY_SEVERITY = ("access_error", "missing", "stale", "partial", "fresh")


@dataclass
class SiteRow:
    site_id: str
    alias: str
    area_id: str | None
    area_alias: str | None
    latitude: float | None
    longitude: float | None
    coordinates_fictional: bool = False
    location_label: str | None = None
    segment: str | None = None
    installed_kwp: float | None = None
    population: str = "compact"  # compact | provider_scenario


@dataclass
class EpisodeRow:
    incident_id: str
    site_ids: list[str]
    title: str
    family: str
    band: str
    status: str  # incident status
    active: bool
    confidence: str | None
    action: str | None
    rule_id: str | None
    responsibility: str | None
    parent_id: str | None = None
    asset_ids: list[str] = field(default_factory=list)
    acknowledged: bool = False
    proposed: bool = False
    assignment: dict | None = None  # {crew_id, crew_name, status, progress, eta, kind}
    rank_position: int | None = None
    revision: int = 1


def episode_workflow(row: EpisodeRow) -> str:
    if not row.active:
        return "resolved"
    assignment = row.assignment
    if assignment:
        if assignment.get("progress") == "on_site":
            return "on_site"
        if (
            assignment.get("status") == "team_sent"
            or assignment.get("progress") == "en_route"
        ):
            return "en_route"
        return "assigned"
    if row.proposed:
        return "proposed"
    if row.action == "field_visit":
        return "field_action_needed"
    if row.action in ("remote_review", "remote_troubleshooting"):
        return "remote_triage"
    if row.action == "monitor":
        return "monitoring"
    return "needs_review"


def episode_condition(row: EpisodeRow) -> str:
    if row.confidence in ("reported", "corroborated"):
        return "observed_active"
    return "suspected"


def telemetry_state(sources: list[dict], access_errors: list[dict]) -> dict:
    """Aggregate source freshness; an access error dominates; missing data is not fresh."""
    if access_errors:
        state = "access_error"
    elif not sources:
        state = "missing"
    else:
        states = {s["status"] for s in sources}
        if states == {"fresh"}:
            state = "fresh"
        elif "fresh" in states:
            state = "partial"
        elif "stale" in states:
            state = "stale"
        else:
            state = "missing"
    fresh = sum(1 for s in sources if s["status"] == "fresh")
    return {
        "state": state,
        "coverage": round(fresh / len(sources), 3) if sources else 0.0,
        "sources": sources,
        "access_errors": access_errors,
    }


def build_projection(
    *,
    sites: list[SiteRow],
    episodes: list[EpisodeRow],
    telemetry: dict[str, dict],
    unsupported: dict[str, list[str]],
    evaluated: dict[str, list[str]],
    not_evaluated: dict[str, list[dict]],
    revision: int,
    status_as_of: datetime,
    crews_visible: bool,
) -> dict:
    by_site: dict[str, list[EpisodeRow]] = {s.site_id: [] for s in sites}
    for episode in episodes:
        for site_id in episode.site_ids:
            if site_id in by_site:
                by_site[site_id].append(episode)
    items, unmapped = [], []
    for site in sorted(sites, key=lambda s: s.site_id):
        rows = by_site[site.site_id]
        active = [e for e in rows if e.active]
        bands = sorted((e.band for e in active), key=BANDS.index)
        highest = bands[0] if bands else None
        if active:
            conditions = {episode_condition(e) for e in active}
            condition = (
                "observed_active" if "observed_active" in conditions else "suspected"
            )
        elif evaluated.get(site.site_id):
            condition = "no_active_issue_under_evaluated_rules"
        else:
            condition = "not_evaluated"
        top = sorted(
            active,
            key=lambda e: (
                BANDS.index(e.band),
                e.rank_position or 10**6,
                e.incident_id,
            ),
        )
        workflow = episode_workflow(top[0]) if top else ("resolved" if rows else "none")
        tele = telemetry.get(site.site_id) or telemetry_state([], [])
        crew = None
        if crews_visible:
            assigned = [e for e in top if e.assignment]
            if assigned:
                a = assigned[0].assignment
                crew = {
                    "crew_id": a.get("crew_id"),
                    "crew_name": a.get("crew_name"),
                    "status": a.get("status"),
                    "progress": a.get("progress"),
                    "eta": a.get("eta"),
                    "eta_label": "estimate (approximate demo travel matrix)",
                }
        attention = (
            ATTENTION.get(highest)
            if highest
            else (
                "data_gap"
                if tele["state"] in ("access_error", "missing", "stale")
                else ("unknown" if condition == "not_evaluated" else "none")
            )
        )
        item = {
            "site_id": site.site_id,
            "alias": site.alias,
            "area_id": site.area_id,
            "area_alias": site.area_alias,
            "population": site.population,
            "position": None
            if site.latitude is None or site.longitude is None
            else {
                "latitude": site.latitude,
                "longitude": site.longitude,
                "fictional": site.coordinates_fictional,
                "label": site.location_label,
            },
            "segment": site.segment,
            "installed_kwp": site.installed_kwp,
            "condition": condition,
            "condition_note": "No active issue detected in available data; this does not "
            "certify a healthy installation"
            if condition.startswith("no_active")
            else None,
            "telemetry": {
                **tele,
                "unsupported_capabilities": unsupported.get(site.site_id, []),
            },
            "workflow": workflow,
            "highest_priority": highest,
            "attention": attention,
            "badges": sorted({attention, f"telemetry_{tele['state']}"}),
            "episode_ids": [e.incident_id for e in top],
            "resolved_episode_ids": sorted(e.incident_id for e in rows if not e.active),
            "parent_episode_ids": sorted({e.parent_id for e in active if e.parent_id}),
            "affected_assets": sorted({a for e in active for a in e.asset_ids}),
            "evaluated_rules": evaluated.get(site.site_id, []),
            "not_evaluated_rules": not_evaluated.get(site.site_id, []),
            "crew": crew,
        }
        (unmapped if item["position"] is None else items).append(item)
    all_items = items + unmapped
    active = [e for e in episodes if e.active and any(s in by_site for s in e.site_ids)]
    counts = {
        "sites": len(all_items),
        "mapped_sites": len(items),
        "unmapped_sites": len(unmapped),
        "affected_sites": sum(1 for i in all_items if i["episode_ids"]),
        "unique_episodes": len({e.incident_id for e in active}),
        "episodes_by_band": {b: sum(1 for e in active if e.band == b) for b in BANDS},
        "affected_sites_by_band": {
            b: sum(1 for i in all_items if i["highest_priority"] == b) for b in BANDS
        },
        "sites_by_workflow": {
            w: sum(1 for i in all_items if i["workflow"] == w) for w in WORKFLOW_ORDER
        },
        "sites_by_telemetry": {
            t: sum(1 for i in all_items if i["telemetry"]["state"] == t)
            for t in TELEMETRY_SEVERITY
        },
        "sites_by_condition": {
            c: sum(1 for i in all_items if i["condition"] == c)
            for c in (
                "observed_active",
                "suspected",
                "no_active_issue_under_evaluated_rules",
                "not_evaluated",
            )
        },
    }
    return {
        "revision": revision,
        "status_as_of": status_as_of,
        "sites": items,
        "unmapped": unmapped,
        "counts": counts,
        "note": "Fictional demo coordinates and synthetic evidence. Missing data is unknown, "
        "not healthy. Counts distinguish affected sites from episodes.",
    }
