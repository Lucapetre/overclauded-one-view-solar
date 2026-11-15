"""Operations integration of correlation, ranking, the status projection and crew planning.

* `DatabaseEvidenceSource` - the evidence adapter over the imported component snapshot,
  provider frames and the explicitly provisioned planning registry, bounded by the
  analytical clock (rows after it are never read).
* `run_correlation` - evaluates the rule library and reconciles episodes (= incidents/work
  orders) with evidence, rule revisions, parent-child links and rank snapshots.
* `ranked_queue` / `episode_detail` / `projection` - one ranking and one status model for the
  queue, incident drawer, map and planner, all carrying the same ops revision.
* `propose_plan` / `review_plan` / `apply_plan` - crew plan lifecycle (draft -> reviewed ->
  applied | superseded) with optimistic input digests and idempotent apply.
* `update_progress` / `close_episode` / overrides / acknowledgement - audited workflow.

All planning inputs (crews, shifts, windows, travel) are SYNTHETIC demo data.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend import correlation as corr
from backend import crew_planner as cp
from backend import ranking
from backend import status as status_model
from backend.clock import analytical_now
from backend.db import site_from_row, stamp
from backend.errors import ApiError
from backend.models import User

SLOT = timedelta(minutes=15)
FIELD_ACTIVITIES = ("field_visit",)
REMOTE_ACTIVITIES = ("remote_review", "remote_troubleshooting")
CUSTOMER_GUIDANCE = (
    "Customer copy: the responsible service has been informed of the reported status. Please "
    "contact your installer or service technician; do not open equipment, touch wiring, "
    "bypass protection or switch the installation off remotely."
)
ETA_LABEL = (
    "Estimate from the approximate demo travel matrix; not road routing or live GPS"
)
ROUTE_LABEL = (
    "Schematic straight lines between fictional demo coordinates; visit order and ETAs are "
    "estimates, not road routes"
)
CAPABILITIES = (
    "grid_power_measured",
    "grid_energy_measured",
    "pcc_phase_voltage",
    "battery_soc_available",
    "battery_limits_available",
    "battery_alarms_available",
    "irradiance_poa_available",
    "module_temperature_available",
)


def _parse(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, default=_default, separators=(",", ":"))


def _default(value):
    if isinstance(value, datetime):
        return stamp(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value))


# ---------------------------------------------------------------- revision


def current_revision(connection) -> int:
    return connection.execute("SELECT MAX(id) FROM ops_revisions").fetchone()[0] or 0


def bump(
    connection, reason: str, subject: str | None, as_of: datetime | None = None
) -> int:
    moment = as_of or analytical_now(connection)
    cursor = connection.execute(
        "INSERT INTO ops_revisions(reason,subject,created_at,created_as_of) VALUES (?,?,?,?)",
        (reason, subject, stamp(), stamp(moment)),
    )
    return cursor.lastrowid


# ---------------------------------------------------------------- evidence adapter


def _series(source_id, rows, mirror_of=None) -> corr.Series:
    return corr.Series(
        source_id,
        [
            corr.Sample(
                _parse(r["start"]), r["value"], r["evidence_id"], r.get("coverage", 1.0)
            )
            for r in rows
        ],
        mirror_of=mirror_of,
    )


class DatabaseEvidenceSource:
    """Evidence known at `as_of` for every provider site with an active component import."""

    def __init__(self, connection, lookback_days: int = 8):
        self.connection = connection
        self.lookback = timedelta(days=lookback_days)

    def _boundaries(self) -> dict:
        return {
            (row["scope"], row["boundary"]): (row["category"], row["service"])
            for row in self.connection.execute("SELECT * FROM service_boundaries")
        }

    def bundle(self, as_of: datetime) -> corr.EvidenceBundle:
        from backend import bridge, components

        connection = self.connection
        boundaries = self._boundaries()
        sites = {}
        rows = connection.execute(
            "SELECT cs.site_id, cs.site_key, s.alias, p.installed_kwp, p.module_arrays "
            "FROM component_sites cs JOIN sites s ON s.site_id=cs.site_id "
            "LEFT JOIN site_placements p ON p.site_id=cs.site_id ORDER BY cs.site_id"
        ).fetchall()
        for row in rows:
            site_id = row["site_id"]
            start = as_of - self.lookback
            recent = as_of - timedelta(hours=6)
            arrays = json.loads(row["module_arrays"]) if row["module_arrays"] else []
            responsibility = {
                boundary: value
                for (scope, boundary), value in boundaries.items()
                if scope == "*"
            }
            site = corr.SiteEvidence(
                site_id=site_id,
                label=row["alias"],
                installed_kwp=row["installed_kwp"],
                module_planes=[(float(a["tilt"]), float(a["az"])) for a in arrays],
                capabilities=components._capabilities(connection, site_id),
                responsibility=responsibility,
            )
            pv = bridge.pv_history(connection, site_id, start, as_of)
            if pv.samples:
                site.pv = corr.Series(
                    f"inverter:{site_id}",
                    [
                        corr.Sample(s.start, s.value, s.evidence_id or "")
                        for s in pv.samples
                    ],
                )
            poa = components.poa_history(connection, site_id, start, as_of)
            if poa is not None:
                site.poa = corr.Series(
                    poa.source,
                    [
                        corr.Sample(s.start, s.value, s.evidence_id or "")
                        for s in poa.samples
                    ],
                )
                site.poa_plane, site.poa_basis = poa.plane, poa.source
            for asset in components._assets(connection, site_id, "meter"):
                if asset["boundary"] != "grid_pcc":
                    continue
                site.pcc_asset_id = asset["asset_id"]
                frames = components._frames(
                    connection,
                    site_id,
                    asset["source_site_key"],
                    "phase_voltage_v",
                    recent,
                    as_of,
                    asset_id=asset["asset_id"],
                )
                for aggregation, target in (
                    ("mean", site.pcc_voltage_mean),
                    ("max", site.pcc_voltage_max),
                ):
                    grouped: dict[str, list] = {}
                    for f in frames:
                        if (
                            f["frame_aggregation"] == aggregation
                            and f["value"] is not None
                        ):
                            grouped.setdefault(f["channel"] or "L1", []).append(
                                {
                                    "start": f["frame_start_utc"],
                                    "value": f["value"],
                                    "coverage": f["coverage_ratio"],
                                    "evidence_id": components._frame_id(f),
                                }
                            )
                    for phase, items in grouped.items():
                        target[phase] = _series(asset["asset_id"], items)
                break
            inverter: dict[str, list] = {}
            for frame in bridge._provider_frames(
                connection, site_id, ("phase_voltage_v",), recent, as_of
            ):
                payload = json.loads(frame["payload"])
                if payload.get("value") is None:
                    continue
                inverter.setdefault(payload.get("channel") or "L1", []).append(
                    {
                        "start": frame["frame_start"],
                        "value": payload["value"],
                        "coverage": payload.get("coverage_ratio", 1.0),
                        "evidence_id": f"frame:{frame['endpoint_key']}:phase_voltage_v:"
                        f"{frame['frame_start']}",
                    }
                )
            site.inverter_voltage = {
                phase: _series(f"inverter:{site_id}", items)
                for phase, items in inverter.items()
            }
            battery = components._battery_asset(connection, site_id)
            if battery is not None:
                site.battery_asset_id = battery["asset_id"]
                details = battery["details"]
                site.battery_nominal = details.get("declared_nominal_limits", {}) or {}
                service = details.get("responsible_service")
                if ("asset_service", service) in boundaries:
                    site.responsibility["battery_service"] = boundaries[
                        ("asset_service", service)
                    ]
                frames = components._frames(
                    connection,
                    site_id,
                    battery["source_site_key"],
                    "battery_alarm_raw",
                    recent,
                    as_of,
                    asset_id=battery["asset_id"],
                )
                grouped = {}
                for f in frames:
                    grouped.setdefault(f["channel"] or "alarm", []).append(
                        {
                            "start": f["frame_start_utc"],
                            "value": f["value"],
                            "coverage": 1.0,
                            "evidence_id": components._frame_id(f),
                        }
                    )
                site.battery_alarms = {
                    k: _series(battery["asset_id"], v) for k, v in grouped.items()
                }
                for metric in site.battery_nominal:
                    frames = components._frames(
                        connection,
                        site_id,
                        battery["source_site_key"],
                        metric,
                        recent,
                        as_of,
                        asset_id=battery["asset_id"],
                    )
                    site.battery_limits[metric] = _series(
                        battery["asset_id"],
                        [
                            {
                                "start": f["frame_start_utc"],
                                "value": f["value"],
                                "coverage": 1.0,
                                "evidence_id": components._frame_id(f),
                            }
                            for f in frames
                        ],
                    )
            sites[site_id] = site
        return corr.EvidenceBundle(
            as_of,
            sites,
            collectors=self._collectors(as_of),
            relations=self._relations(),
            source="component_snapshot+provider_frames",
        ).clipped(as_of)

    def _relations(self) -> list[corr.TopologyRelation]:
        grouped: dict[str, list] = {}
        for row in self.connection.execute(
            "SELECT * FROM topology_relations ORDER BY site_id"
        ):
            grouped.setdefault(row["relation_id"], []).append(row)
        return [
            corr.TopologyRelation(
                rid,
                rows[0]["kind"],
                tuple(r["site_id"] for r in rows),
                rows[0]["basis"],
            )
            for rid, rows in sorted(grouped.items())
        ]

    def _collectors(self, as_of: datetime) -> list[corr.CollectorEvidence]:
        from backend import components
        from backend.providers import readonly

        grouped: dict[str, list] = {}
        for row in self.connection.execute(
            "SELECT * FROM collector_declarations ORDER BY collector_id, site_id"
        ):
            grouped.setdefault(row["collector_id"], []).append(row)
        result = []
        boundary = self._boundaries().get(
            ("*", "monitoring_path"), ("monitoring_provider", "monitoring provider")
        )
        for collector_id, rows in sorted(grouped.items()):
            evidence = corr.CollectorEvidence(
                collector_id, sorted({r["site_id"] for r in rows}), responsible=boundary
            )
            for row in rows:
                active = components._active(self.connection, row["site_id"])
                if not active:
                    continue
                with readonly(Path(active["database_path"])) as snapshot:
                    events = snapshot.execute(
                        "SELECT delivery_hash, status_class, start_ms FROM delivery_events "
                        "WHERE site_key=? AND endpoint_key=? AND start_ms<=? "
                        "ORDER BY start_ms LIMIT 2000",
                        (
                            active["site_key"],
                            row["endpoint_key"],
                            int(as_of.timestamp() * 1000),
                        ),
                    ).fetchall()
                for event in events:
                    evidence.failures.append(
                        corr.CollectionFailure(
                            datetime.fromtimestamp(event["start_ms"] / 1000, UTC),
                            row["site_id"],
                            event["status_class"],
                            f"delivery:{event['delivery_hash'][:16]}",
                        )
                    )
                frames = components._frames(
                    self.connection,
                    row["site_id"],
                    active["site_key"],
                    "inverter_ac_output_kw",
                    as_of - timedelta(hours=12),
                    as_of,
                )
                evidence.successes[row["site_id"]] = [
                    corr.Sample(
                        _parse(f["frame_start_utc"]),
                        f["value"],
                        components._frame_id(f),
                    )
                    for f in frames
                    if f["endpoint_key"] == row["endpoint_key"]
                    and f["value"] is not None
                    and (f["n_obs"] or 0) > 0
                ]
            result.append(evidence)
        return result


# ---------------------------------------------------------------- correlation runner


def _episodes(connection, ids=None) -> dict[str, dict]:
    sql = "SELECT * FROM episodes"
    args: tuple = ()
    if ids is not None:
        ids = list(ids)
        if not ids:
            return {}
        sql += f" WHERE incident_id IN ({','.join('?' * len(ids))})"
        args = tuple(ids)
    result = {}
    for row in connection.execute(sql, args):
        item = dict(row)
        for key in (
            "hypothesis",
            "metrics",
            "impact",
            "reason_codes",
            "site_ids",
            "asset_ids",
        ):
            item[key] = json.loads(item[key]) if item[key] else None
        result[row["incident_id"]] = item
    if result:
        marks = ",".join("?" * len(result))
        for row in connection.execute(
            f"SELECT parent_incident_id, child_incident_id FROM episode_links "
            f"WHERE parent_incident_id IN ({marks})",
            tuple(result),
        ):
            result[row["parent_incident_id"]].setdefault("children", []).append(
                row["child_incident_id"]
            )
    return result


def _add_evidence(connection, incident_id, refs, revision, as_of) -> int:
    added = 0
    for ref in refs:
        added += connection.execute(
            "INSERT OR IGNORE INTO episode_evidence(incident_id,evidence_id,kind,source_id,"
            "independent_group,mirror_of,observed_from,observed_to,summary,added_revision,"
            "added_as_of) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                incident_id,
                ref.evidence_id,
                ref.kind,
                ref.source_id,
                ref.independent_group,
                ref.mirror_of,
                stamp(ref.observed_from) if ref.observed_from else None,
                stamp(ref.observed_to) if ref.observed_to else None,
                ref.summary,
                revision,
                stamp(as_of),
            ),
        ).rowcount
    return added


def _site_alias(connection, site_ids) -> str:
    aliases = [
        r["alias"]
        for r in connection.execute(
            f"SELECT alias FROM sites WHERE site_id IN ({','.join('?' * len(site_ids))}) "
            "ORDER BY alias",
            tuple(site_ids),
        )
    ]
    return " + ".join(aliases)


def run_correlation(
    database,
    *,
    source=None,
    actor: str = "system",
    request_id: str = "local-correlation",
) -> dict:
    """Evaluate the rule library at the analytical time and reconcile episodes. Idempotent at
    one analytical time: a repeat run changes nothing."""
    from backend.ops import log_incident, open_incident

    policy = ranking.load_policy()
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        as_of = analytical_now(connection)
        bundle = (source or DatabaseEvidenceSource(connection)).bundle(as_of)
        results = corr.evaluate(bundle, as_of)
        for rule_id, rule in corr.RULES.items():
            connection.execute(
                "INSERT OR IGNORE INTO rule_revisions VALUES (?,?,?,?,?,?)",
                (
                    rule_id,
                    rule["revision"],
                    corr.RULESET_VERSION,
                    corr.rule_hash(rule_id),
                    _json(rule),
                    stamp(as_of),
                ),
            )
        known_sites = {
            r["site_id"] for r in connection.execute("SELECT site_id FROM sites")
        }
        results = [
            r
            for r in results
            if r.status == "not_evaluated" or all(s in known_sites for s in r.site_ids)
        ]
        active_rows = connection.execute(
            "SELECT e.incident_id, e.identity, e.rule_id, e.hold_note, EXISTS (SELECT 1 FROM "
            "assignments a WHERE a.incident_id=e.incident_id AND a.status IN "
            "('assigned','team_sent','meeting_scheduled')) AS assigned "
            "FROM episodes e WHERE e.state='active'"
        ).fetchall()
        active = [
            corr.EpisodeState(
                r["incident_id"],
                r["identity"],
                r["rule_id"],
                {
                    e[0]
                    for e in connection.execute(
                        "SELECT evidence_id FROM episode_evidence WHERE incident_id=?",
                        (r["incident_id"],),
                    )
                },
                bool(r["assigned"]),
            )
            for r in active_rows
        ]
        holds = {r["incident_id"]: r["hold_note"] for r in active_rows}
        actions = corr.reconcile(active, results)
        revision = current_revision(connection) + 1
        counts = dict.fromkeys(
            ("opened", "updated", "recovered", "held", "unchanged"), 0
        )
        changed = False
        now_text = stamp(as_of)
        identity_to_incident = {e.identity: e.incident_id for e in active}
        for action in actions:
            result = action.result
            if action.kind == "open":
                sequence = connection.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM episodes WHERE identity=?",
                    (action.identity,),
                ).fetchone()[0]
                incident_id = corr.episode_key(action.identity, sequence)
                band = policy["rule_bands"].get(result.rule_id, "P2")
                title = f"{result.title}: {_site_alias(connection, result.site_ids)}"
                open_incident(
                    connection,
                    incident_id=incident_id,
                    site_id=result.site_ids[0],
                    title=title[:200],
                    family=result.family,
                    tier=band,
                    source="synthetic_replay",
                    evidence=(
                        result.hypothesis.interpretation if result.hypothesis else title
                    )
                    + " Synthetic replay evidence; demo policy, not a diagnosis.",
                    actor="correlation",
                    detail=f"Opened by rule {result.rule_id} r{result.rule_revision}; "
                    f"confidence {result.confidence} ({result.confidence_basis}); proposed "
                    f"responsibility {result.responsibility} ({result.responsibility_basis}); "
                    "nothing is sent externally",
                    now=now_text,
                )
                connection.execute(
                    "INSERT INTO episodes(incident_id,identity,sequence,rule_id,rule_revision,"
                    "state,confidence,confidence_basis,action,responsibility,"
                    "responsibility_basis,service_key,hypothesis,metrics,impact,reason_codes,"
                    "site_ids,asset_ids,first_observed_at,last_observed_at,window_start,"
                    "window_end,opened_as_of,updated_as_of,repeat_count,revision) "
                    "VALUES (?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)",
                    (
                        incident_id,
                        action.identity,
                        sequence,
                        result.rule_id,
                        result.rule_revision,
                        result.confidence,
                        result.confidence_basis,
                        result.action,
                        result.responsibility,
                        result.responsibility_basis,
                        result.service_key,
                        _json(result.hypothesis.as_dict()),
                        _json(result.metrics),
                        _json(result.impact),
                        _json(result.reason_codes),
                        _json(result.site_ids),
                        _json(result.asset_ids),
                        stamp(result.first_observed or result.window_start or as_of),
                        stamp(result.window_end or as_of),
                        stamp(result.window_start) if result.window_start else None,
                        stamp(result.window_end) if result.window_end else None,
                        now_text,
                        now_text,
                        sequence - 1,
                    ),
                )
                for index, site_id in enumerate(result.site_ids):
                    connection.execute(
                        "INSERT INTO episode_sites VALUES (?,?,?)",
                        (incident_id, site_id, "primary" if index == 0 else "affected"),
                    )
                _add_evidence(connection, incident_id, result.evidence, 1, as_of)
                identity_to_incident[action.identity] = incident_id
                counts["opened"] += 1
                changed = True
            elif action.kind in ("update", "unchanged"):
                bump_revision = 1 if action.kind == "update" else 0
                connection.execute(
                    "UPDATE episodes SET metrics=?, last_observed_at=?, window_end=?, "
                    "updated_as_of=?, hold_note=NULL, revision=revision+?, confidence=? "
                    "WHERE incident_id=?",
                    (
                        _json(result.metrics),
                        stamp(result.window_end or as_of),
                        stamp(result.window_end) if result.window_end else None,
                        now_text,
                        bump_revision,
                        result.confidence,
                        action.incident_id,
                    ),
                )
                if action.kind == "update":
                    episode_revision = connection.execute(
                        "SELECT revision FROM episodes WHERE incident_id=?",
                        (action.incident_id,),
                    ).fetchone()[0]
                    added = _add_evidence(
                        connection,
                        action.incident_id,
                        action.new_evidence,
                        episode_revision,
                        as_of,
                    )
                    log_incident(
                        connection,
                        action.incident_id,
                        "correlation",
                        "evidence_updated",
                        f"{added} new evidence item(s); the condition persists",
                        now_text,
                    )
                    counts["updated"] += 1
                    changed = True
                else:
                    counts["unchanged"] += 1
            elif action.kind == "recover":
                connection.execute(
                    "UPDATE episodes SET state='resolved', resolved_as_of=?, "
                    "resolution_kind='recovery_rule', resolution_detail=?, resolved_by='system', "
                    "updated_as_of=?, revision=revision+1 WHERE incident_id=?",
                    (now_text, action.note, now_text, action.incident_id),
                )
                connection.execute(
                    "UPDATE incidents SET status='resolved', updated_at=? WHERE incident_id=?",
                    (now_text, action.incident_id),
                )
                log_incident(
                    connection,
                    action.incident_id,
                    "correlation",
                    "resolved",
                    action.note,
                    now_text,
                )
                counts["recovered"] += 1
                changed = True
            elif action.kind == "hold":
                counts["held"] += 1
                if holds.get(action.incident_id) != action.note:
                    connection.execute(
                        "UPDATE episodes SET hold_note=?, updated_as_of=? WHERE incident_id=?",
                        (action.note, now_text, action.incident_id),
                    )
                    log_incident(
                        connection,
                        action.incident_id,
                        "correlation",
                        "evidence_hold",
                        action.note,
                        now_text,
                    )
                    changed = True
        for result in results:
            if result.rule_id != "common_upstream" or result.status != "matched":
                continue
            parent = identity_to_incident.get(result.identity)
            for child_identity in result.children:
                child = identity_to_incident.get(child_identity)
                if not parent or not child:
                    continue
                inserted = connection.execute(
                    "INSERT OR IGNORE INTO episode_links VALUES (?,?,?,?,?,?)",
                    (
                        parent,
                        child,
                        result.metrics.get("relation_id", ""),
                        result.metrics.get("relation_basis", ""),
                        _json({"loss": "child", "parent_counts": "once"}),
                        now_text,
                    ),
                ).rowcount
                if inserted:
                    connection.execute(
                        "UPDATE episodes SET parent_incident_id=? WHERE incident_id=?",
                        (parent, child),
                    )
                    changed = True
        site_results: dict[str, dict] = {}
        for result in results:
            for site_id in result.site_ids:
                entry = site_results.setdefault(
                    site_id, {"evaluated": [], "not_evaluated": []}
                )
                if result.status == "not_evaluated":
                    entry["not_evaluated"].append(
                        {"rule_id": result.rule_id, "reason_codes": result.reason_codes}
                    )
                elif result.rule_id not in entry["evaluated"]:
                    entry["evaluated"].append(result.rule_id)
        run_id = uuid.uuid4().hex
        counts["not_evaluated"] = sum(1 for r in results if r.status == "not_evaluated")
        connection.execute(
            "INSERT INTO correlation_runs VALUES (?,?,?,?,?,?,?)",
            (
                run_id,
                now_text,
                corr.RULESET_VERSION,
                bundle.source,
                _json(site_results),
                _json(counts),
                stamp(),
            ),
        )
        if changed:
            revision = bump(connection, "correlation", run_id, as_of)
            snapshot_ranks(connection, "correlation", revision, as_of)
        else:
            revision = current_revision(connection)
        database.audit(
            connection,
            actor,
            "correlation.run",
            run_id,
            request_id,
            {"analytical_at": now_text, **counts},
        )
        return {"run_id": run_id, "as_of": now_text, "revision": revision, **counts}


# ---------------------------------------------------------------- ranking facts


def _valuation(connection, site_id, policy) -> ranking.Valuation:
    contract = connection.execute(
        "SELECT import_price_ron_kwh, export_price_ron_kwh FROM contracts WHERE site_id=?",
        (site_id,),
    ).fetchone()
    tariff = policy["economics"]["default_tariff"]
    low, high = (
        (contract["export_price_ron_kwh"], contract["import_price_ron_kwh"])
        if contract
        else (tariff["export_price_ron_kwh"], tariff["import_price_ron_kwh"])
    )
    basis = policy["economics"]["customer_lost_pv_value"]["basis"].strip() + (
        " Prices: saved contract." if contract else " Prices: default demo tariff."
    )
    return ranking.Valuation(
        policy["economics"]["customer_lost_pv_value"]["stakeholder"], low, high, basis
    )


def _repair(connection, rule_id) -> ranking.RepairEstimate | None:
    for row in connection.execute(
        "SELECT spec FROM job_templates WHERE rule_id=? ORDER BY seq", (rule_id,)
    ):
        estimate = json.loads(row["spec"]).get("repair_estimate")
        if estimate:
            return ranking.RepairEstimate(
                estimate["currency"],
                estimate["low"],
                estimate["high"],
                estimate["source"],
                estimate["as_of"],
            )
    return None


def _override(connection, incident_id, now) -> dict | None:
    row = connection.execute(
        "SELECT * FROM priority_overrides WHERE incident_id=? AND revoked_at IS NULL "
        "AND expires_at>? ORDER BY created_as_of DESC, override_id DESC LIMIT 1",
        (incident_id, stamp(now)),
    ).fetchone()
    if not row:
        return None
    return {
        "override_id": row["override_id"],
        "band": row["band"],
        "original_band": row["original_band"],
        "reason": row["reason"],
        "created_by": row["created_by"],
        "created_as_of": row["created_as_of"],
        "expires_at": _parse(row["expires_at"]),
        "revoked": False,
    }


def job_facts(
    connection, row, episode: dict | None, now: datetime, policy
) -> ranking.JobFacts:
    impact = (episode or {}).get("impact") or {}
    evidence = []
    if episode:
        evidence = [
            r[0]
            for r in connection.execute(
                "SELECT evidence_id FROM episode_evidence WHERE incident_id=? "
                "ORDER BY id DESC LIMIT 20",
                (row["incident_id"],),
            )
        ]
    first = _parse((episode or {}).get("first_observed_at"))
    last = _parse((episode or {}).get("last_observed_at"))
    lost = impact.get("expected_lost_kwh_per_day")
    return ranking.JobFacts(
        incident_id=row["incident_id"],
        band=row["tier"],
        created_at=_parse(row["created_at"]),
        title=row["title"],
        family=row["family"],
        site_ids=(episode or {}).get("site_ids") or [row["site_id"]],
        hazard=row["tier"] == "P0",
        confidence=(episode or {}).get("confidence"),
        persistence_minutes=(last - first).total_seconds() / 60
        if first and last
        else None,
        repeat_count=(episode or {}).get("repeat_count") or 0,
        parent_id=(episode or {}).get("parent_incident_id"),
        lost_function=impact.get("lost_function"),
        expected_lost_kwh_per_day=lost,
        lost_kwh_reason=impact.get("lost_kwh_reason")
        or (None if episode else "no_correlated_evidence"),
        recoverable=impact.get("recoverable"),
        valuation=_valuation(connection, row["site_id"], policy)
        if lost is not None
        else None,
        repair=_repair(connection, episode["rule_id"]) if episode else None,
        action=(episode or {}).get("action"),
        has_commitment=bool(row["assignment_id"]),
        evidence_ids=evidence,
        override=_override(connection, row["incident_id"], now),
    )


def _rank(connection, rows, now) -> dict[str, ranking.RankResult]:
    policy = ranking.load_policy()
    episodes = _episodes(connection, [r["incident_id"] for r in rows])
    facts = [
        job_facts(connection, r, episodes.get(r["incident_id"]), now, policy)
        for r in rows
    ]
    return {r.incident_id: r for r in ranking.rank_all(facts, now, policy)}


def snapshot_ranks(connection, context: str, revision: int, as_of: datetime, ids=None):
    from backend.ops import INCIDENT_SELECT

    moment = ranking.rank_as_of(as_of)
    where = "WHERE i.status != 'resolved'"
    args: tuple = ()
    if ids is not None:
        ids = list(ids)
        if not ids:
            return
        where += f" AND i.incident_id IN ({','.join('?' * len(ids))})"
        args = tuple(ids)
    rows = connection.execute(INCIDENT_SELECT + where + " LIMIT 500", args).fetchall()
    for result in _rank(connection, rows, moment).values():
        connection.execute(
            "INSERT INTO rank_snapshots(incident_id,ops_revision,context,policy_version,band,"
            "computed_band,score,digest,explanation,rank_as_of,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                result.incident_id,
                revision,
                context,
                result.policy_version,
                result.band,
                result.computed_band,
                result.score,
                result.digest(),
                _json(result.as_dict()),
                stamp(moment),
                stamp(),
            ),
        )


# ---------------------------------------------------------------- queue / detail


def _assignments(connection, incident_ids) -> dict[str, dict]:
    ids = list(incident_ids)
    if not ids:
        return {}
    rows = connection.execute(
        "SELECT a.*, c.name AS crew_name FROM assignments a JOIN crews c ON c.crew_id=a.crew_id "
        f"WHERE a.status IN ('assigned','team_sent','meeting_scheduled') "
        f"AND a.incident_id IN ({','.join('?' * len(ids))})",
        tuple(ids),
    ).fetchall()
    return {
        r["incident_id"]: {
            "assignment_id": r["assignment_id"],
            "crew_id": r["crew_id"],
            "crew_name": r["crew_name"],
            "status": r["status"],
            "progress": r["progress"],
            "eta": _parse(r["eta_arrival"] or r["scheduled_start"]),
            "kind": r["kind"],
            "revision": r["revision"],
        }
        for r in rows
    }


def _proposed_ids(connection) -> set[str]:
    row = connection.execute(
        "SELECT plan_id FROM crew_plans WHERE status IN ('draft','reviewed') "
        "ORDER BY created_at DESC, plan_id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return set()
    return {
        r[0]
        for r in connection.execute(
            "SELECT incident_id FROM crew_plan_items WHERE plan_id=?", (row["plan_id"],)
        )
    }


def _episode_row(row, episode, assignment, proposed, rank_position=None):
    return status_model.EpisodeRow(
        incident_id=row["incident_id"],
        site_ids=(episode or {}).get("site_ids") or [row["site_id"]],
        title=row["title"],
        family=row["family"],
        band=row["tier"],
        status=row["status"],
        active=row["status"] != "resolved",
        confidence=(episode or {}).get("confidence")
        or ("reported" if row["source"] == "customer_request" else None),
        action=(episode or {}).get("action"),
        rule_id=(episode or {}).get("rule_id"),
        responsibility=(episode or {}).get("responsibility"),
        parent_id=(episode or {}).get("parent_incident_id"),
        asset_ids=(episode or {}).get("asset_ids") or [],
        acknowledged=bool((episode or {}).get("acknowledged_by")),
        proposed=row["incident_id"] in proposed,
        assignment=assignment,
        rank_position=rank_position,
        revision=(episode or {}).get("revision") or 1,
    )


def _summary(episode: dict | None) -> dict | None:
    if not episode:
        return None
    return {
        "rule_id": episode["rule_id"],
        "rule_revision": episode["rule_revision"],
        "state": episode["state"],
        "confidence": episode["confidence"],
        "confidence_basis": episode["confidence_basis"],
        "action": episode["action"],
        "responsibility": episode["responsibility"],
        "responsibility_basis": episode["responsibility_basis"],
        "site_ids": episode["site_ids"],
        "asset_ids": episode["asset_ids"],
        "parent_incident_id": episode["parent_incident_id"],
        "child_incident_ids": sorted(episode.get("children", [])),
        "first_observed_at": episode["first_observed_at"],
        "last_observed_at": episode["last_observed_at"],
        "repeat_count": episode["repeat_count"],
        "revision": episode["revision"],
        "acknowledged": bool(episode["acknowledged_by"]),
        "resolution_kind": episode["resolution_kind"],
        "resolution_detail": episode["resolution_detail"],
        "hold_note": episode["hold_note"],
    }


def _scoped_rows(connection, user, status_filter: str = "open"):
    from backend.ops import INCIDENT_SELECT, _scope

    clause, ids = _scope(connection, user)
    where = f"WHERE i.site_id {clause}"
    if status_filter == "open":
        where += " AND i.status != 'resolved'"
    return connection.execute(
        INCIDENT_SELECT
        + where
        + " ORDER BY i.tier, i.created_at, i.incident_id LIMIT 500",
        ids,
    ).fetchall()


def ranked_queue(connection, user: User, status_filter: str = "open") -> dict:
    from backend.ops import _incident, require_operations

    require_operations(user)
    now = ranking.rank_as_of(analytical_now(connection))
    rows = _scoped_rows(connection, user, status_filter)
    ranks = _rank(connection, rows, now)
    episodes = _episodes(connection, [r["incident_id"] for r in rows])
    assignments = _assignments(connection, [r["incident_id"] for r in rows])
    proposed = _proposed_ids(connection)
    policy = ranking.load_policy()
    items = []
    for row in sorted(rows, key=lambda r: ranks[r["incident_id"]].position):
        rank = ranks[row["incident_id"]]
        episode = episodes.get(row["incident_id"])
        items.append(
            {
                "incident": _incident(row),
                "episode": _summary(episode),
                "workflow": status_model.episode_workflow(
                    _episode_row(
                        row,
                        episode,
                        assignments.get(row["incident_id"]),
                        proposed,
                        rank.position,
                    )
                ),
                "rank": rank.as_dict(),
            }
        )
    actions = [(i["episode"] or {}).get("action") for i in items]
    return {
        "revision": current_revision(connection),
        "rank_as_of": now,
        "policy_version": policy["policy_version"],
        "policy_label": policy["label"],
        "items": items,
        "remote_review_count": sum(
            a in REMOTE_ACTIVITIES or a == "external_review" for a in actions
        ),
        "field_count": sum(a == "field_visit" for a in actions),
        "monitoring_count": sum(a == "monitor" for a in actions),
    }


NEXT_ACTIONS = {
    "monitor": ["acknowledge", "keep_monitoring"],
    "remote_review": ["acknowledge", "plan_remote_review", "close_documented"],
    "remote_troubleshooting": [
        "acknowledge",
        "plan_remote_troubleshooting",
        "close_documented",
    ],
    "field_visit": ["acknowledge", "propose_crew_plan", "close_documented"],
    "external_review": ["acknowledge", "propose_external_review_not_auto_sent"],
}


def episode_detail(connection, user: User, incident_id: str) -> dict:
    from backend.ops import _visible_incident, get_incident, ops_sites

    row = _visible_incident(connection, user, incident_id)
    detail = get_incident(connection, user, incident_id)
    now = ranking.rank_as_of(analytical_now(connection))
    if row["status"] == "resolved":
        rank = _rank(connection, [row], now)[incident_id]
    else:
        rank = _rank(connection, _scoped_rows(connection, user), now)[incident_id]
    episode = _episodes(connection, [incident_id]).get(incident_id)
    scope = {r["site_id"] for r in ops_sites(connection, user)}
    evidence = [
        dict(r)
        for r in connection.execute(
            "SELECT evidence_id, kind, source_id, independent_group, mirror_of, observed_from, "
            "observed_to, summary, added_revision, added_as_of FROM episode_evidence "
            "WHERE incident_id=? ORDER BY id LIMIT 200",
            (incident_id,),
        )
    ]
    history = [
        dict(r)
        for r in connection.execute(
            "SELECT ops_revision, context, band, score, digest, rank_as_of FROM rank_snapshots "
            "WHERE incident_id=? ORDER BY id DESC LIMIT 10",
            (incident_id,),
        )
    ]
    overrides = [
        {
            "override_id": r["override_id"],
            "band": r["band"],
            "original_band": r["original_band"],
            "reason": r["reason"],
            "created_by": r["created_by"],
            "created_as_of": r["created_as_of"],
            "expires_at": r["expires_at"],
            "revoked": r["revoked_at"] is not None,
        }
        for r in connection.execute(
            "SELECT * FROM priority_overrides WHERE incident_id=? ORDER BY created_as_of DESC",
            (incident_id,),
        )
    ]
    assignments = [
        dict(r)
        for r in connection.execute(
            "SELECT assignment_id, crew_id, revision, status, progress, plan_id, "
            "scheduled_start, scheduled_end, changed_as_of, reason FROM assignment_revisions "
            "WHERE incident_id=? ORDER BY id LIMIT 100",
            (incident_id,),
        )
    ]
    active = _assignments(connection, [incident_id])
    summary = _summary(episode)
    if summary:
        # A shared parent never grants visibility into other customers' sites.
        summary["site_ids"] = [s for s in summary["site_ids"] if s in scope]
    workflow = status_model.episode_workflow(
        _episode_row(
            row,
            episode,
            active.get(incident_id),
            _proposed_ids(connection),
            rank.position,
        )
    )
    return {
        "revision": current_revision(connection),
        "incident": detail,
        "episode": summary,
        "hypothesis": (episode or {}).get("hypothesis"),
        "metrics": (episode or {}).get("metrics") or {},
        "impact": (episode or {}).get("impact") or {},
        "reason_codes": (episode or {}).get("reason_codes") or [],
        "rule": corr.RULES.get(episode["rule_id"]) if episode else None,
        "evidence": evidence,
        "rank": rank.as_dict(),
        "rank_history": history,
        "overrides": overrides,
        "assignment_history": assignments,
        "workflow": workflow,
        "next_actions": NEXT_ACTIONS.get(
            (episode or {}).get("action"), ["assign", "resolve"]
        )
        if row["status"] != "resolved"
        else [],
        "customer_guidance": CUSTOMER_GUIDANCE,
    }


# ---------------------------------------------------------------- projection


def _positions(connection, site_ids) -> dict[str, dict]:
    ids = list(site_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    result = {}
    for row in connection.execute(
        f"SELECT site_id, latitude, longitude, location_label, segment, installed_kwp "
        f"FROM site_placements WHERE site_id IN ({marks})",
        tuple(ids),
    ):
        result[row["site_id"]] = {
            **dict(row),
            "fictional": True,
            "population": "provider_scenario",
        }
    for row in connection.execute(
        f"SELECT site_id, latitude, longitude, zone AS location_label, segment, installed_kwp "
        f"FROM site_profiles WHERE site_id IN ({marks})",
        tuple(ids),
    ):
        result.setdefault(
            row["site_id"], {**dict(row), "fictional": True, "population": "compact"}
        )
    return result


def _access_errors(connection, site_id, now) -> list[dict]:
    from backend import components
    from backend.providers import readonly

    active = components._active(connection, site_id)
    if not active:
        return []
    with readonly(Path(active["database_path"])) as snapshot:
        rows = snapshot.execute(
            "SELECT endpoint_key, status_class, COUNT(*) AS n, MAX(start_ms) AS last FROM "
            "delivery_events WHERE site_key=? AND start_ms<=? AND start_ms>? "
            "GROUP BY endpoint_key, status_class ORDER BY endpoint_key",
            (
                active["site_key"],
                int(now.timestamp() * 1000),
                int((now - timedelta(minutes=30)).timestamp() * 1000),
            ),
        ).fetchall()
    return [
        {
            "source": r["endpoint_key"],
            "failure_class": r["status_class"],
            "last_at": datetime.fromtimestamp(r["last"] / 1000, UTC),
            "count": r["n"],
        }
        for r in rows
    ]


def _telemetry(connection, site_row, now) -> tuple[dict, list[str]]:
    from backend import bridge, components
    from backend.energy import snapshot

    site_id = site_row["site_id"]
    if (
        components._active(connection, site_id)
        or connection.execute(
            "SELECT 1 FROM provider_sites WHERE site_id=?", (site_id,)
        ).fetchone()
    ):
        sources = [
            {
                k: v
                for k, v in s.items()
                if k in ("source", "status", "last_observed_at", "age_seconds")
            }
            for s in bridge.source_freshness(connection, site_id, now)
            if s["source"] != "compact_telemetry"
        ]
        caps = components._capabilities(connection, site_id)
        unsupported = [c for c in CAPABILITIES if caps.get(c) in (None, "not_declared")]
        return status_model.telemetry_state(
            sources, _access_errors(connection, site_id, now)
        ), (unsupported)
    freshness = snapshot(connection, site_from_row(site_row)).freshness
    state = {"fresh": "fresh", "stale": "stale"}.get(freshness.status, "missing")
    sources = [
        {
            "source": "compact_telemetry",
            "status": state,
            "last_observed_at": getattr(freshness, "latest_interval_end", None),
            "age_seconds": None,
        }
    ]
    capabilities = json.loads(site_row["capabilities"])
    unsupported = [
        m
        for m in ("battery_soc", "voltage", "temperature", "grid_import")
        if m not in capabilities
    ]
    return status_model.telemetry_state(sources, []), unsupported


def projection(connection, user: User) -> dict:
    from backend.ops import INCIDENT_SELECT, _scope, _user_crews, ops_sites

    now = analytical_now(connection)
    as_of = ranking.rank_as_of(now)
    site_rows = ops_sites(connection, user)
    scope = {r["site_id"] for r in site_rows}
    positions = _positions(connection, scope)
    areas = {
        r["area_id"]: r["alias"] for r in connection.execute("SELECT * FROM areas")
    }
    sites, telemetry, unsupported = [], {}, {}
    for row in site_rows:
        place = positions.get(row["site_id"]) or {}
        sites.append(
            status_model.SiteRow(
                site_id=row["site_id"],
                alias=row["alias"],
                area_id=row["area_id"],
                area_alias=areas.get(row["area_id"]),
                latitude=place.get("latitude"),
                longitude=place.get("longitude"),
                coordinates_fictional=bool(place),
                location_label=place.get("location_label"),
                segment=place.get("segment"),
                installed_kwp=place.get("installed_kwp"),
                population=place.get("population")
                or (
                    "provider_scenario"
                    if row["site_id"].startswith("provider-")
                    else "compact"
                ),
            )
        )
        telemetry[row["site_id"]], unsupported[row["site_id"]] = _telemetry(
            connection, row, now
        )
    clause, ids = _scope(connection, user)
    rows = connection.execute(
        INCIDENT_SELECT
        + f"WHERE (i.site_id {clause} OR EXISTS (SELECT 1 FROM episode_sites es "
        f"WHERE es.incident_id=i.incident_id AND es.site_id {clause})) AND (i.status != "
        "'resolved' OR i.incident_id IN (SELECT incident_id FROM episodes WHERE resolved_as_of>?))"
        " LIMIT 1000",
        (*ids, *ids, stamp(now - timedelta(hours=24))),
    ).fetchall()
    episodes = _episodes(connection, [r["incident_id"] for r in rows])
    assignments = _assignments(connection, [r["incident_id"] for r in rows])
    if user.role == "technician":
        mine = {c["crew_id"] for c in _user_crews(connection, user)}
        assignments = {k: v for k, v in assignments.items() if v["crew_id"] in mine}
    open_rows = [r for r in rows if r["status"] != "resolved"]
    ranks = _rank(connection, open_rows, as_of)
    proposed = _proposed_ids(connection)
    episode_rows = []
    for row in rows:
        episode = episodes.get(row["incident_id"])
        item = _episode_row(
            row,
            episode,
            assignments.get(row["incident_id"]),
            proposed,
            ranks[row["incident_id"]].position if row["incident_id"] in ranks else None,
        )
        item.site_ids = [s for s in item.site_ids if s in scope]
        episode_rows.append(item)
    run = connection.execute(
        "SELECT site_results FROM correlation_runs WHERE as_of<=? ORDER BY as_of DESC, "
        "created_at DESC LIMIT 1",
        (stamp(now),),
    ).fetchone()
    results = json.loads(run["site_results"]) if run else {}
    view = status_model.build_projection(
        sites=sites,
        episodes=episode_rows,
        telemetry=telemetry,
        unsupported=unsupported,
        evaluated={k: v["evaluated"] for k, v in results.items()},
        not_evaluated={k: v["not_evaluated"] for k, v in results.items()},
        revision=current_revision(connection),
        status_as_of=as_of,
        crews_visible=user.role in ("dispatcher", "supervisor", "technician"),
    )
    return view


def _node_position(connection, node_id) -> dict | None:
    row = connection.execute(
        "SELECT * FROM planning_nodes WHERE node_id=?", (node_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "fictional": True,
        "label": row["label"],
    }


def crew_markers(connection, user: User) -> list[dict]:
    from backend.ops import _visible_crews

    markers = []
    for crew in _visible_crews(connection, user):
        profile = connection.execute(
            "SELECT * FROM crew_profiles WHERE crew_id=?", (crew["crew_id"],)
        ).fetchone()
        if not profile:
            continue
        markers.append(
            {
                "crew_id": crew["crew_id"],
                "name": crew["name"],
                "kind": profile["kind"],
                "position": _node_position(connection, profile["base_node"])
                if profile["base_node"]
                else None,
                "location_reported_at": profile["location_reported_at"],
                "location_basis": profile["location_basis"],
            }
        )
    return markers


def routes(connection, user: User) -> list[dict]:
    from backend.ops import _visible_crews, ops_sites

    scope = {r["site_id"] for r in ops_sites(connection, user)}
    crews = {c["crew_id"] for c in _visible_crews(connection, user)}
    lines = []

    def stop(seq, incident_id, site_id, start, finish):
        return {
            "sequence": seq,
            "incident_id": incident_id,
            "site_id": site_id,
            "position": _node_position(connection, site_id),
            "start_at": start,
            "finish_at": finish,
        }

    grouped: dict[str, list] = {}
    for row in connection.execute(
        "SELECT a.*, i.site_id FROM assignments a JOIN incidents i ON i.incident_id=a.incident_id "
        "WHERE a.status IN ('assigned','team_sent') AND a.kind='dispatch' "
        "AND a.scheduled_start IS NOT NULL ORDER BY a.crew_id, a.scheduled_start"
    ):
        grouped.setdefault(row["crew_id"], []).append(row)
    for crew_id, rows in sorted(grouped.items()):
        if crew_id not in crews:
            continue
        visible = [r for r in rows if r["site_id"] in scope]
        lines.append(
            {
                "crew_id": crew_id,
                "plan_id": rows[0]["plan_id"],
                "state": "applied",
                "stops": [
                    stop(
                        i + 1,
                        r["incident_id"],
                        r["site_id"],
                        r["scheduled_start"],
                        r["scheduled_end"],
                    )
                    for i, r in enumerate(visible)
                ],
                "redacted_stops": len(rows) - len(visible),
                "label": ROUTE_LABEL,
            }
        )
    plan = connection.execute(
        "SELECT plan_id FROM crew_plans WHERE status IN ('draft','reviewed') "
        "ORDER BY created_at DESC, plan_id DESC LIMIT 1"
    ).fetchone()
    if plan:
        grouped = {}
        for row in connection.execute(
            "SELECT p.*, i.site_id FROM crew_plan_items p JOIN incidents i ON "
            "i.incident_id=p.incident_id WHERE p.plan_id=? AND p.activity='field_visit' "
            "ORDER BY p.crew_id, p.start_at",
            (plan["plan_id"],),
        ):
            grouped.setdefault(row["crew_id"], []).append(row)
        for crew_id, rows in sorted(grouped.items()):
            if crew_id not in crews:
                continue
            visible = [r for r in rows if r["site_id"] in scope]
            lines.append(
                {
                    "crew_id": crew_id,
                    "plan_id": plan["plan_id"],
                    "state": "proposed",
                    "stops": [
                        stop(
                            i + 1,
                            r["incident_id"],
                            r["site_id"],
                            r["start_at"],
                            r["finish_at"],
                        )
                        for i, r in enumerate(visible)
                    ],
                    "redacted_stops": len(rows) - len(visible),
                    "label": ROUTE_LABEL,
                }
            )
    return lines


# ---------------------------------------------------------------- planning inputs


def _local_windows(spec: list[dict], start: datetime, end: datetime) -> list[cp.Window]:
    """Daily local-time windows [{start,end}] expanded over [start, end] (DST-safe)."""
    windows = []
    day = corr.local_day(start) - timedelta(days=1)
    while True:
        lower, _ = corr.day_bounds(day)
        if lower > end:
            break
        for item in spec:
            h1, m1 = map(int, item["start"].split(":"))
            h2, m2 = map(int, item["end"].split(":"))
            a = datetime(day.year, day.month, day.day, h1, m1, tzinfo=corr.LOCAL)
            b = datetime(day.year, day.month, day.day, h2, m2, tzinfo=corr.LOCAL)
            a, b = a.astimezone(UTC), b.astimezone(UTC)
            if b > start and a < end:
                windows.append(cp.Window(a, b))
        day += timedelta(days=1)
    return windows


def build_inputs(connection, user: User, now: datetime, horizon_hours: int):
    from backend.ops import _visible_crews, ops_sites

    policy = ranking.load_policy()
    horizon_end = now + timedelta(hours=horizon_hours)
    scope = {r["site_id"]: r for r in ops_sites(connection, user)}
    rows = [r for r in _scoped_rows(connection, user) if not r["assignment_id"]]
    ranks = _rank(connection, _scoped_rows(connection, user), ranking.rank_as_of(now))
    episodes = _episodes(connection, [r["incident_id"] for r in rows])
    nodes = {
        r["node_id"] for r in connection.execute("SELECT node_id FROM planning_nodes")
    }
    jobs, monitoring = [], []
    for row in rows:
        episode = episodes.get(row["incident_id"])
        rank = ranks[row["incident_id"]]
        templates = (
            []
            if not episode
            else [
                json.loads(t["spec"]) | {"activity": t["activity"]}
                for t in connection.execute(
                    "SELECT activity, spec FROM job_templates WHERE rule_id=? ORDER BY seq",
                    (episode["rule_id"],),
                )
            ]
        )
        if episode and episode["action"] == "monitor":
            monitoring.append(
                {
                    "incident_id": row["incident_id"],
                    "site_id": row["site_id"],
                    "title": row["title"],
                    "band": rank.band,
                    "reason": "monitoring only: no field visit or remote job",
                }
            )
            continue
        if episode and episode.get("parent_incident_id"):
            parent = connection.execute(
                "SELECT status FROM incidents WHERE incident_id=?",
                (episode["parent_incident_id"],),
            ).fetchone()
            if parent and parent["status"] != "resolved":
                monitoring.append(
                    {
                        "incident_id": row["incident_id"],
                        "site_id": row["site_id"],
                        "title": row["title"],
                        "band": rank.band,
                        "reason": "child of an active shared parent: handled by "
                        "the parent work order unless inspection is required",
                    }
                )
                continue
        if not templates:
            templates = [{"activity": "field_visit", "service_minutes": None}]
        window = connection.execute(
            "SELECT windows FROM site_access_windows WHERE site_id=?", (row["site_id"],)
        ).fetchone()
        site_windows = (
            _local_windows(json.loads(window["windows"]), now, horizon_end)
            if window
            else None
        )
        for template in templates:
            activity = template["activity"]
            remote = activity in REMOTE_ACTIVITIES
            service_key = template.get("service_key") or (
                (episode or {}).get("service_key")
                or (episode or {}).get("responsibility")
                or "unknown"
            )
            if remote:
                service_key = template.get("service_key") or (
                    "monitoring_provider"
                    if episode and episode["action"] == "remote_troubleshooting"
                    else "customer_installation_service"
                )
            jobs.append(
                cp.JobInput(
                    job_id=f"{row['incident_id']}:{activity}",
                    incident_id=row["incident_id"],
                    site_id=row["site_id"],
                    title=row["title"],
                    band=rank.band,
                    rank_position=rank.position,
                    rank_score=rank.score,
                    created_at=_parse(row["created_at"]),
                    activity=activity,
                    service_key=service_key,
                    area=row["area_id"],
                    node=None
                    if remote
                    else (row["site_id"] if row["site_id"] in nodes else None),
                    service_minutes=template.get("service_minutes"),
                    access_windows=[cp.Window(now, horizon_end)]
                    if remote
                    else site_windows,
                    qualifications=set(template.get("qualifications", [])),
                    tools=set(template.get("tools", [])),
                    parts_required=template.get("parts_required", []),
                    parts_ready=template.get("parts_ready"),
                    crew_size=template.get("crew_size", 1),
                    deadline=rank.deadline_at,
                    deadline_mandatory=rank.deadline_mandatory,
                    depends_on=[
                        f"{row['incident_id']}:{d}"
                        for d in template.get("depends_on", [])
                    ],
                    expected_lost_kwh_per_day=((episode or {}).get("impact") or {}).get(
                        "expected_lost_kwh_per_day"
                    ),
                )
            )
    crews = []
    for crew in _visible_crews(connection, user):
        profile = connection.execute(
            "SELECT * FROM crew_profiles WHERE crew_id=?", (crew["crew_id"],)
        ).fetchone()
        if not profile:
            continue
        shift = connection.execute(
            "SELECT * FROM crew_shifts WHERE crew_id=? AND shift_end>? AND shift_start<? "
            "ORDER BY shift_start LIMIT 1",
            (crew["crew_id"], stamp(now), stamp(horizon_end)),
        ).fetchone()
        members = [
            r[0]
            for r in connection.execute(
                "SELECT user_id FROM crew_members WHERE crew_id=? ORDER BY user_id",
                (crew["crew_id"],),
            )
        ]
        commitments = []
        for a in connection.execute(
            "SELECT a.*, i.site_id FROM assignments a JOIN incidents i ON "
            "i.incident_id=a.incident_id WHERE a.crew_id=? AND a.status IN "
            "('assigned','team_sent','meeting_scheduled') ORDER BY a.scheduled_start",
            (crew["crew_id"],),
        ):
            start = _parse(a["scheduled_start"]) or now
            end = _parse(a["scheduled_end"]) or start + timedelta(hours=1)
            if end <= now and a["progress"] != "on_site":
                end = now + SLOT  # an overrunning job still occupies the crew
            commitments.append(
                cp.Commitment(
                    f"{a['incident_id']}:{a['activity'] or a['kind']}",
                    a["incident_id"],
                    a["site_id"] if profile["kind"] == "field" else None,
                    start,
                    end,
                    started=a["status"] == "team_sent"
                    or a["progress"] in ("en_route", "on_site"),
                )
            )
        crews.append(
            cp.CrewInput(
                crew_id=crew["crew_id"],
                name=crew["name"],
                kind=profile["kind"],
                organisation=profile["organisation"],
                authorised_services=set(json.loads(profile["authorised_services"])),
                qualifications=set(json.loads(profile["qualifications"])),
                tools=set(json.loads(profile["tools"])),
                areas=set(json.loads(profile["areas"])),
                members=members,
                shift=cp.Window(
                    _parse(shift["shift_start"]), _parse(shift["shift_end"])
                )
                if shift
                else None,
                breaks=[
                    cp.Window(_parse(b[0]), _parse(b[1]))
                    for b in json.loads(shift["breaks"])
                ]
                if shift
                else [],
                base_node=profile["base_node"],
                location_reported_at=_parse(profile["location_reported_at"]),
                commitments=commitments,
            )
        )
    members = {m for c in crews for m in c.members}
    unavailable = [
        (
            r["user_id"],
            cp.Window(_parse(r["start_at"]), _parse(r["end_at"])),
            r["reason"],
        )
        for r in connection.execute(
            "SELECT * FROM member_unavailability WHERE end_at>? AND start_at<?",
            (stamp(now), stamp(horizon_end)),
        )
        if r["user_id"] in members
    ]
    travel, source = {}, "no travel matrix provisioned"
    for r in connection.execute("SELECT * FROM travel_times"):
        travel[(r["from_node"], r["to_node"])] = r["minutes"]
        source = r["source"]
    inputs = cp.PlanningInputs(
        now=now,
        horizon_end=horizon_end,
        crews=crews,
        jobs=jobs,
        travel=travel,
        travel_source=source,
        member_unavailability=unavailable,
        overtime_minutes=policy["planning"]["max_overtime_minutes"]
        if policy["planning"]["overtime_allowed"]
        else 0,
        local_improvement_passes=policy["planning"]["local_improvement_passes"],
        max_evaluations=policy["planning"]["max_insertion_evaluations"],
        monitoring=monitoring,
    )
    scope_digest = hashlib.sha256("|".join(sorted(scope)).encode()).hexdigest()[:16]
    return inputs, scope_digest


# ---------------------------------------------------------------- plans


def _require_dispatch(user: User):
    from backend.ops import require_operations

    require_operations(user)
    if user.role != "dispatcher":
        raise ApiError(
            403,
            "dispatch_capability_required",
            "Applying or reviewing a crew plan needs the dispatch capability",
        )


def _require_plan_reader(user: User):
    from backend.ops import require_operations

    require_operations(user)
    if user.role not in ("dispatcher", "supervisor"):
        raise ApiError(
            403,
            "planning_access_required",
            "Crew plans are visible to dispatch and supervisory accounts only",
        )


def _store_plan(connection, user, inputs, scope_digest, result, revision) -> str:
    plan_id = "plan-" + uuid.uuid4().hex[:20]
    policy = ranking.load_policy()
    connection.execute(
        "INSERT INTO crew_plans(plan_id,ops_revision,status,created_by,created_at,created_as_of,"
        "horizon_start,horizon_end,scope_digest,input_digest,input_snapshot,travel_source,"
        "policy_version,result) VALUES (?,?,'draft',?,?,?,?,?,?,?,?,?,?,?)",
        (
            plan_id,
            revision,
            user.user_id,
            stamp(),
            stamp(inputs.now),
            stamp(inputs.now),
            stamp(inputs.horizon_end),
            scope_digest,
            result["input_digest"],
            _json(cp._snapshot(inputs)),
            inputs.travel_source,
            policy["policy_version"],
            _json(result),
        ),
    )
    seq = 0
    for item in sorted(
        result["visits"] + result["remote_items"],
        key=lambda v: (v["start_at"], v["crew_id"], v["job_id"]),
    ):
        seq += 1
        job = next(j for j in inputs.jobs if j.job_id == item["job_id"])
        connection.execute(
            "INSERT INTO crew_plan_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'proposed',NULL)",
            (
                plan_id,
                seq,
                item["crew_id"],
                item["incident_id"],
                item["job_id"],
                item["activity"],
                _json(job.depends_on),
                stamp(item["depart_at"]),
                stamp(item["arrive_at"]),
                stamp(item["start_at"]),
                stamp(item["finish_at"]),
                item["travel_minutes"],
                item["service_minutes"],
            ),
        )
    return plan_id


def propose_plan(
    database, connection, user: User, rid: str, horizon_hours: int = 12
) -> dict:
    _require_plan_reader(user)
    connection.execute("BEGIN IMMEDIATE")
    now = analytical_now(connection)
    inputs, scope_digest = build_inputs(connection, user, now, horizon_hours)
    result = cp.plan(inputs)
    revision = current_revision(connection)
    plan_id = _store_plan(connection, user, inputs, scope_digest, result, revision)
    snapshot_ranks(
        connection, "plan", revision, now, [j.incident_id for j in inputs.jobs]
    )
    database.audit(
        connection,
        user.user_id,
        "crew_plan.proposed",
        plan_id,
        rid,
        {
            "analytical_at": stamp(now),
            "jobs": len(inputs.jobs),
            "visits": len(result["visits"]),
            "remote": len(result["remote_items"]),
            "unassigned": len(result["unassigned"]),
            "verdict": result["comparison"]["verdict"],
        },
    )
    return plan_view(connection, user, plan_id)


def plan_view(connection, user: User, plan_id: str) -> dict:
    from backend.ops import ops_sites

    _require_plan_reader(user)
    row = connection.execute(
        "SELECT * FROM crew_plans WHERE plan_id=?", (plan_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    scope = {r["site_id"] for r in ops_sites(connection, user)}
    result = json.loads(row["result"])
    redacted = 0

    def visible(items):
        nonlocal redacted
        kept = [i for i in items if i["site_id"] in scope]
        redacted += len(items) - len(kept)
        return kept

    if not any(
        i["site_id"] in scope
        for i in result["visits"] + result["remote_items"] + result["unassigned"]
    ) and (result["visits"] or result["unassigned"]):
        raise ApiError(404, "not_found", "Resource not found")
    applied = [
        r[0]
        for r in connection.execute(
            "SELECT assignment_id FROM crew_plan_items WHERE plan_id=? AND assignment_id IS NOT NULL "
            "ORDER BY seq",
            (plan_id,),
        )
    ]
    users = {
        r["user_id"]: r["username"]
        for r in connection.execute(
            "SELECT user_id, username FROM users WHERE user_id IN (?,?,?)",
            (row["created_by"], row["reviewed_by"] or "", row["applied_by"] or ""),
        )
    }
    return {
        "plan_id": row["plan_id"],
        "status": row["status"],
        "ops_revision": row["ops_revision"],
        "current_revision": current_revision(connection),
        "created_at": row["created_at"],
        "created_as_of": row["created_as_of"],
        "horizon_start": row["horizon_start"],
        "horizon_end": row["horizon_end"],
        "label": result["label"],
        "method": result["method"],
        "travel_source": row["travel_source"],
        "policy_version": row["policy_version"],
        "input_digest": row["input_digest"],
        "input_completeness": result["input_completeness"],
        "visits": visible(result["visits"]),
        "remote_items": visible(result["remote_items"]),
        "unassigned": visible(result["unassigned"]),
        "urgent_exceptions": [
            e
            for e in result["urgent_exceptions"]
            if e["incident_id"]
            in {
                v["incident_id"]
                for v in result["visits"]
                + result["unassigned"]
                + result["remote_items"]
                if v["site_id"] in scope
            }
        ],
        "monitoring": [m for m in result["monitoring"] if m["site_id"] in scope],
        "baseline": {
            k: visible(result["baseline"][k])
            for k in ("visits", "remote_items", "unassigned")
        },
        "comparison": result["comparison"],
        "approval": {
            "created_by": users.get(row["created_by"], row["created_by"]),
            "reviewed_by": users.get(row["reviewed_by"])
            if row["reviewed_by"]
            else None,
            "reviewed_at": row["reviewed_at"],
            "applied_by": users.get(row["applied_by"]) if row["applied_by"] else None,
            "applied_at": row["applied_at"],
            "applied_as_of": row["applied_as_of"],
        },
        "superseded_reason": row["superseded_reason"],
        "superseded_by": row["superseded_by"],
        "redacted_items": redacted,
        "applied_assignment_ids": applied,
    }


def latest_plan(connection, user: User) -> dict:
    _require_plan_reader(user)
    row = connection.execute(
        "SELECT plan_id FROM crew_plans ORDER BY created_at DESC, plan_id DESC LIMIT 1"
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "No crew plan has been proposed yet")
    return plan_view(connection, user, row["plan_id"])


def review_plan(database, connection, user: User, plan_id: str, rid: str) -> dict:
    _require_dispatch(user)
    connection.execute("BEGIN IMMEDIATE")
    plan_view(connection, user, plan_id)  # scope check
    updated = connection.execute(
        "UPDATE crew_plans SET status='reviewed', reviewed_by=?, reviewed_at=? "
        "WHERE plan_id=? AND status='draft'",
        (user.user_id, stamp(), plan_id),
    ).rowcount
    if not updated:
        status = connection.execute(
            "SELECT status FROM crew_plans WHERE plan_id=?", (plan_id,)
        ).fetchone()["status"]
        if status != "reviewed":
            raise ApiError(409, "plan_not_draft", f"The plan is {status}")
    database.audit(connection, user.user_id, "crew_plan.reviewed", plan_id, rid)
    return plan_view(connection, user, plan_id)


def _supersede(connection, plan_id, reason, by=None):
    connection.execute(
        "UPDATE crew_plans SET status='superseded', superseded_reason=?, superseded_by=? "
        "WHERE plan_id=? AND status IN ('draft','reviewed')",
        (reason, by, plan_id),
    )


def _revise_assignment(connection, assignment_id, user_id, reason, as_of):
    row = connection.execute(
        "SELECT * FROM assignments WHERE assignment_id=?", (assignment_id,)
    ).fetchone()
    connection.execute(
        "INSERT INTO assignment_revisions(assignment_id,incident_id,crew_id,revision,status,"
        "progress,plan_id,scheduled_start,scheduled_end,changed_by,changed_at,changed_as_of,"
        "reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            assignment_id,
            row["incident_id"],
            row["crew_id"],
            row["revision"],
            row["status"],
            row["progress"],
            row["plan_id"],
            row["scheduled_start"],
            row["scheduled_end"],
            user_id,
            stamp(),
            stamp(as_of),
            reason,
        ),
    )


def _create_from_item(connection, user: User, plan_id, item, as_of) -> str:
    from backend.ops import _create_assignment, _set_status, log_incident

    remote = item["activity"] in REMOTE_ACTIVITIES
    kind, status = (
        ("meeting", "meeting_scheduled") if remote else ("dispatch", "assigned")
    )
    assignment_id = _create_assignment(
        connection,
        item["incident_id"],
        item["crew_id"],
        kind,
        status,
        user,
        stamp(),
        item["start_at"],
        item["finish_at"],
    )
    connection.execute(
        "UPDATE assignments SET plan_id=?, activity=?, eta_arrival=?, travel_minutes=? "
        "WHERE assignment_id=?",
        (
            plan_id,
            item["activity"],
            item["arrive_at"],
            item["travel_minutes"],
            assignment_id,
        ),
    )
    connection.execute(
        "UPDATE crew_plan_items SET state='assigned', assignment_id=? WHERE plan_id=? AND seq=?",
        (assignment_id, plan_id, item["seq"]),
    )
    _set_status(connection, item["incident_id"], status, stamp(as_of))
    crew = connection.execute(
        "SELECT name FROM crews WHERE crew_id=?", (item["crew_id"],)
    ).fetchone()["name"]
    log_incident(
        connection,
        item["incident_id"],
        user.username,
        "plan_assigned",
        f"{item['activity']} assigned to {crew} by plan {plan_id}; start "
        f"{item['start_at'][11:16]} UTC (estimate, approximate demo travel matrix)",
        stamp(as_of),
    )
    _revise_assignment(
        connection, assignment_id, user.user_id, f"plan {plan_id} applied", as_of
    )
    return assignment_id


def apply_plan(
    database,
    connection,
    user: User,
    plan_id: str,
    expected_digest: str,
    idempotency_key: str | None,
    rid: str,
) -> dict:
    _require_dispatch(user)
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute(
        "SELECT * FROM crew_plans WHERE plan_id=?", (plan_id,)
    ).fetchone()
    if not row:
        raise ApiError(404, "not_found", "Resource not found")
    plan_view(connection, user, plan_id)  # scope check
    if row["status"] == "applied":
        if idempotency_key and idempotency_key == row["apply_idempotency_key"]:
            return plan_view(connection, user, plan_id)
        raise ApiError(
            409, "plan_already_applied", "This plan has already been applied"
        )
    if row["status"] == "superseded":
        raise ApiError(
            409,
            "plan_superseded",
            f"This plan was superseded ({row['superseded_reason']})",
        )
    if row["status"] != "reviewed":
        raise ApiError(
            409, "plan_not_reviewed", "Review the proposal before applying it"
        )
    if expected_digest != row["input_digest"]:
        raise ApiError(
            409, "plan_changed", "The proposal differs from the one you reviewed"
        )
    now = analytical_now(connection)
    started = _parse(row["horizon_start"])
    hours = round((_parse(row["horizon_end"]) - started).total_seconds() / 3600)
    inputs, scope_digest = build_inputs(connection, user, started, hours)
    reason = None
    if now - started > timedelta(minutes=30):
        reason = "plan_outdated: the analytical clock moved more than 30 minutes"
    elif scope_digest != row["scope_digest"]:
        reason = "scope_changed"
    elif inputs.digest() != row["input_digest"]:
        reason = (
            "inputs_changed: incidents, crew availability, locks or assignments changed"
        )
    if reason:
        fresh_inputs, fresh_scope = build_inputs(connection, user, now, hours)
        fresh = cp.plan(fresh_inputs)
        new_id = _store_plan(
            connection,
            user,
            fresh_inputs,
            fresh_scope,
            fresh,
            current_revision(connection),
        )
        _supersede(connection, plan_id, reason, new_id)
        database.audit(
            connection,
            user.user_id,
            "crew_plan.stale_rejected",
            plan_id,
            rid,
            {"reason": reason, "new_plan_id": new_id, "analytical_at": stamp(now)},
        )
        connection.commit()
        raise ApiError(
            409,
            "plan_stale",
            f"The proposal is stale ({reason}); a new proposal {new_id} was "
            "computed for review",
        )
    items = [
        dict(r)
        for r in connection.execute(
            "SELECT * FROM crew_plan_items WHERE plan_id=? ORDER BY start_at, seq",
            (plan_id,),
        )
    ]
    first: dict[str, dict] = {}
    for item in items:
        if item["incident_id"] not in first:
            first[item["incident_id"]] = item
    for item in items:
        if first[item["incident_id"]] is not item:
            connection.execute(
                "UPDATE crew_plan_items SET state='deferred' WHERE plan_id=? AND seq=?",
                (plan_id, item["seq"]),
            )
            continue
        overlap = connection.execute(
            "SELECT 1 FROM assignments WHERE crew_id=? AND status IN "
            "('assigned','team_sent','meeting_scheduled') AND scheduled_start<? "
            "AND scheduled_end>?",
            (item["crew_id"], item["finish_at"], item["start_at"]),
        ).fetchone()
        if overlap:
            raise ApiError(409, "crew_double_booked", "A crew would be booked twice")
        _create_from_item(connection, user, plan_id, item, now)
    connection.execute(
        "UPDATE crew_plans SET status='applied', applied_by=?, applied_at=?, applied_as_of=?, "
        "apply_idempotency_key=? WHERE plan_id=?",
        (user.user_id, stamp(), stamp(now), idempotency_key, plan_id),
    )
    for other in connection.execute(
        "SELECT plan_id FROM crew_plans WHERE status IN ('draft','reviewed') AND plan_id!=?",
        (plan_id,),
    ).fetchall():
        _supersede(connection, other["plan_id"], "another plan was applied", plan_id)
    revision = bump(connection, "crew_plan.applied", plan_id, now)
    snapshot_ranks(connection, "plan", revision, now, list(first))
    database.audit(
        connection,
        user.user_id,
        "crew_plan.applied",
        plan_id,
        rid,
        {
            "analytical_at": stamp(now),
            "assignments": len(first),
            "deferred": len(items) - len(first),
        },
    )
    return plan_view(connection, user, plan_id)


# ---------------------------------------------------------------- workflow


def _resolve_episode(connection, incident_id, kind, detail, actor, as_of):
    connection.execute(
        "UPDATE episodes SET state='resolved', resolved_as_of=?, resolution_kind=?, "
        "resolution_detail=?, resolved_by=?, updated_as_of=?, revision=revision+1 "
        "WHERE incident_id=? AND state='active'",
        (stamp(as_of), kind, detail, actor, stamp(as_of), incident_id),
    )
    connection.execute(
        "UPDATE crew_plan_items SET state='cancelled' WHERE incident_id=? AND state='deferred'",
        (incident_id,),
    )
    children = connection.execute(
        "SELECT child_incident_id FROM episode_links WHERE parent_incident_id=?",
        (incident_id,),
    ).fetchall()
    return [c[0] for c in children]


def on_resolved(connection, incident_id: str, user: User, detail: str):
    """Hook for ops.resolve_incident: documented authorized closure; children stay open."""
    from backend.ops import log_incident

    now = analytical_now(connection)
    children = _resolve_episode(
        connection, incident_id, "authorized_closure", detail, user.username, now
    )
    for child in children:
        log_incident(
            connection,
            child,
            user.username,
            "parent_closed",
            f"Parent {incident_id} was closed; this child stays open until its own "
            "recovery or closure",
            stamp(now),
        )
    bump(connection, "incident.resolved", incident_id, now)


def close_episode(
    database,
    connection,
    user: User,
    incident_id: str,
    reason_code: str,
    note: str,
    rid: str,
) -> dict:
    from backend.ops import resolve_incident

    detail = f"Authorized documented closure ({reason_code}) by {user.username}: {note}"
    connection.execute("BEGIN IMMEDIATE")
    resolve_incident(
        database, connection, user, incident_id, rid, detail=detail, began=True
    )
    return episode_detail(connection, user, incident_id)


def acknowledge(database, connection, user: User, incident_id: str, rid: str) -> dict:
    from backend.ops import _visible_incident, log_incident, require_operations

    require_operations(user)
    connection.execute("BEGIN IMMEDIATE")
    _visible_incident(connection, user, incident_id)
    now = analytical_now(connection)
    if connection.execute(
        "UPDATE episodes SET acknowledged_by=?, acknowledged_as_of=? WHERE incident_id=? "
        "AND acknowledged_by IS NULL",
        (user.username, stamp(now), incident_id),
    ).rowcount:
        log_incident(
            connection,
            incident_id,
            user.username,
            "acknowledged",
            f"Acknowledged by {user.username}",
            stamp(now),
        )
        bump(connection, "episode.acknowledged", incident_id, now)
        database.audit(
            connection, user.user_id, "episode.acknowledged", incident_id, rid
        )
    return episode_detail(connection, user, incident_id)


def set_override(
    database,
    connection,
    user: User,
    incident_id: str,
    band: str,
    reason: str,
    expires_at: datetime,
    rid: str,
) -> dict:
    from backend.ops import _visible_incident, log_incident

    _require_dispatch(user)
    connection.execute("BEGIN IMMEDIATE")
    row = _visible_incident(connection, user, incident_id)
    if row["status"] == "resolved":
        raise ApiError(409, "incident_resolved", "This incident is already resolved")
    now = analytical_now(connection)
    if expires_at.tzinfo is None:
        raise ApiError(422, "invalid_expiry", "Use a timezone-aware expiry")
    expires_at = expires_at.astimezone(UTC)
    if not now < expires_at <= now + timedelta(days=7):
        raise ApiError(422, "invalid_expiry", "The override must expire within 7 days")
    override_id = "ovr-" + uuid.uuid4().hex[:16]
    connection.execute(
        "INSERT INTO priority_overrides(override_id,incident_id,band,original_band,reason,"
        "created_by,created_at,created_as_of,expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            override_id,
            incident_id,
            band,
            row["tier"],
            reason,
            user.user_id,
            stamp(),
            stamp(now),
            stamp(expires_at),
        ),
    )
    log_incident(
        connection,
        incident_id,
        user.username,
        "priority_override",
        f"Priority override {row['tier']} -> {band} until {stamp(expires_at)}: "
        f"{reason} (computed rank preserved)",
        stamp(now),
    )
    revision = bump(connection, "priority.override", incident_id, now)
    snapshot_ranks(connection, "override", revision, now, [incident_id])
    database.audit(
        connection,
        user.user_id,
        "priority.override",
        incident_id,
        rid,
        {"band": band, "expires_at": stamp(expires_at), "analytical_at": stamp(now)},
    )
    return episode_detail(connection, user, incident_id)


def revoke_override(
    database, connection, user: User, incident_id: str, rid: str
) -> dict:
    from backend.ops import _visible_incident, log_incident

    _require_dispatch(user)
    connection.execute("BEGIN IMMEDIATE")
    _visible_incident(connection, user, incident_id)
    now = analytical_now(connection)
    if connection.execute(
        "UPDATE priority_overrides SET revoked_by=?, revoked_at=?, revoked_as_of=? "
        "WHERE incident_id=? AND revoked_at IS NULL",
        (user.user_id, stamp(), stamp(now), incident_id),
    ).rowcount:
        log_incident(
            connection,
            incident_id,
            user.username,
            "priority_override_revoked",
            "Priority override revoked; the computed rank applies",
            stamp(now),
        )
        bump(connection, "priority.override_revoked", incident_id, now)
        database.audit(
            connection, user.user_id, "priority.override_revoked", incident_id, rid
        )
    return episode_detail(connection, user, incident_id)


def agenda(connection, user: User) -> dict:
    from backend.ops import _user_crews, _visible_crews, require_operations

    require_operations(user)
    crews = (
        _user_crews(connection, user)
        if user.role == "technician"
        else _visible_crews(connection, user)
    )
    ids = [c["crew_id"] for c in crews]
    now = analytical_now(connection)
    items, deferred, history = [], [], []
    select = (
        "SELECT a.*, c.name AS crew_name, i.title, i.tier, i.site_id, i.evidence, "
        "i.support_request_id, s.alias AS site_alias, "
        "COALESCE(sp.location_label, pr.zone) AS zone, m.media_id, m.filename AS media_filename, "
        "m.content_type AS media_content_type, m.size_bytes AS media_size_bytes "
        "FROM assignments a JOIN crews c ON c.crew_id=a.crew_id JOIN incidents i ON "
        "i.incident_id=a.incident_id JOIN sites s ON s.site_id=i.site_id "
        "LEFT JOIN site_placements sp ON sp.site_id=i.site_id "
        "LEFT JOIN site_profiles pr ON pr.site_id=i.site_id "
        "LEFT JOIN support_media m ON m.request_id=i.support_request_id "
    )

    def window(r):
        if not r["scheduled_start"]:
            return None
        local = ZoneInfo("Europe/Bucharest")
        first = _parse(r["scheduled_start"]).astimezone(local).strftime("%H:%M")
        last = _parse(r["scheduled_end"])
        return first + (f"-{last.astimezone(local).strftime('%H:%M')}" if last else "")

    def item(r):
        return {
            "assignment_id": r["assignment_id"],
            "crew_id": r["crew_id"],
            "crew_name": r["crew_name"],
            "incident_id": r["incident_id"],
            "title": r["title"],
            "tier": r["tier"],
            "site_id": r["site_id"],
            "site_alias": r["site_alias"],
            "activity": r["activity"],
            "kind": r["kind"],
            "status": r["status"],
            "progress": r["progress"],
            "revision": r["revision"],
            "scheduled_start": r["scheduled_start"],
            "scheduled_end": r["scheduled_end"],
            "eta_arrival": r["eta_arrival"],
            "travel_minutes": r["travel_minutes"],
            "position": _node_position(connection, r["site_id"]),
            "plan_id": r["plan_id"],
            "zone": r["zone"],
            "reason": (r["evidence"] or "")[:300] or None,
            "window_label": window(r),
            "support_request_id": r["support_request_id"],
            "media": {
                "media_id": r["media_id"],
                "filename": r["media_filename"],
                "content_type": r["media_content_type"],
                "size_bytes": r["media_size_bytes"],
            }
            if r["media_id"]
            else None,
        }

    if ids:
        marks = ",".join("?" * len(ids))
        for r in connection.execute(
            select + f"WHERE a.crew_id IN ({marks}) AND a.status IN "
            "('assigned','team_sent','meeting_scheduled') "
            "ORDER BY a.scheduled_start, a.created_at LIMIT 200",
            tuple(ids),
        ):
            items.append(item(r))
        for r in connection.execute(
            select + f"WHERE a.crew_id IN ({marks}) AND a.status='completed' "
            "AND COALESCE(a.completed_at, a.scheduled_end, a.created_at) >= ? "
            "ORDER BY COALESCE(a.completed_at, a.scheduled_end) DESC LIMIT 30",
            (*ids, stamp(now - timedelta(hours=72))),
        ):
            history.append(item(r))
        for r in connection.execute(
            f"SELECT * FROM crew_plan_items WHERE crew_id IN ({marks}) AND state='deferred' "
            "ORDER BY start_at LIMIT 100",
            tuple(ids),
        ):
            deferred.append(
                {
                    "plan_id": r["plan_id"],
                    "crew_id": r["crew_id"],
                    "incident_id": r["incident_id"],
                    "activity": r["activity"],
                    "start_at": r["start_at"],
                    "reason": "planned after its prerequisite (remote review)",
                }
            )
    return {
        "as_of": now,
        "crews": [c["name"] for c in crews],
        "items": items,
        "deferred": deferred,
        "eta_label": ETA_LABEL,
        "history": history,
    }


def update_progress(
    database,
    connection,
    user: User,
    assignment_id: str,
    state: str,
    expected_revision: int,
    outcome: str | None,
    note: str | None,
    rid: str,
) -> dict:
    from backend.ops import _set_status, _user_crews, log_incident, require_role

    require_role(user, "technician")
    connection.execute("BEGIN IMMEDIATE")
    mine = {c["crew_id"] for c in _user_crews(connection, user)}
    row = connection.execute(
        "SELECT * FROM assignments WHERE assignment_id=?", (assignment_id,)
    ).fetchone()
    if not row or row["crew_id"] not in mine:
        raise ApiError(404, "not_found", "Resource not found")
    if row["status"] not in ("assigned", "team_sent", "meeting_scheduled"):
        raise ApiError(409, "assignment_closed", "This assignment is no longer active")
    if row["revision"] != expected_revision:
        raise ApiError(409, "assignment_changed", "The assignment changed; reload it")
    now = analytical_now(connection)
    incident_id = row["incident_id"]
    order = {"en_route": 1, "on_site": 2, "done": 3}
    if row["progress"] and order[state] <= order[row["progress"]]:
        raise ApiError(409, "progress_not_forward", "Progress only moves forward")
    if state == "done" and not note:
        raise ApiError(422, "note_required", "Document the outcome with a short note")
    status = row["status"]
    if state == "en_route" and row["kind"] == "dispatch":
        status = "team_sent"
        _set_status(connection, incident_id, "team_sent", stamp(now))
    completed = None
    if state == "done":
        status, completed = "completed", stamp()
    connection.execute(
        "UPDATE assignments SET progress=?, status=?, completed_at=COALESCE(?, completed_at), "
        "revision=revision+1 WHERE assignment_id=?",
        (state, status, completed, assignment_id),
    )
    log_incident(
        connection,
        incident_id,
        user.username,
        f"progress_{state}",
        f"{state.replace('_', ' ')} reported by {user.username}"
        + (f": {note}" if note else ""),
        stamp(now),
    )
    _revise_assignment(
        connection, assignment_id, user.user_id, f"progress {state}", now
    )
    if state == "done":
        outcome = outcome or "resolved"
        pending = connection.execute(
            "SELECT * FROM crew_plan_items WHERE incident_id=? AND state='deferred' "
            "ORDER BY start_at LIMIT 1",
            (incident_id,),
        ).fetchone()
        if outcome == "field_visit_needed" and pending:
            item = dict(pending)
            item["start_at"], item["finish_at"] = (
                pending["start_at"],
                pending["finish_at"],
            )
            _create_from_item(connection, user, pending["plan_id"], item, now)
        elif outcome == "resolved":
            detail = f"Technician closure by {user.username}: {note}"
            connection.execute(
                "UPDATE incidents SET status='resolved', updated_at=? WHERE incident_id=?",
                (stamp(now), incident_id),
            )
            log_incident(
                connection, incident_id, user.username, "resolved", detail, stamp(now)
            )
            children = _resolve_episode(
                connection,
                incident_id,
                "authorized_closure",
                detail,
                user.username,
                now,
            )
            for child in children:
                log_incident(
                    connection,
                    child,
                    user.username,
                    "parent_closed",
                    f"Parent {incident_id} closed; this child stays open",
                    stamp(now),
                )
        else:
            _set_status(connection, incident_id, "new", stamp(now))
    bump(connection, f"assignment.{state}", assignment_id, now)
    database.audit(
        connection,
        user.user_id,
        f"assignment.{state}",
        assignment_id,
        rid,
        {"analytical_at": stamp(now), "outcome": outcome},
    )
    return agenda(connection, user)
