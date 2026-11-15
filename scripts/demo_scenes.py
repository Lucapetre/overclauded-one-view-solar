"""Run the four synthetic component scenes against an isolated, forward-only database.

Usage (from the checkout, using its Python environment)::

    python -m scripts.demo_scenes --workspace C:/Temp/one-view-rehearsal setup
    python -m scripts.demo_scenes --workspace C:/Temp/one-view-rehearsal A
    python -m scripts.demo_scenes --workspace C:/Temp/one-view-rehearsal B
    python -m scripts.demo_scenes --workspace C:/Temp/one-view-rehearsal C
    python -m scripts.demo_scenes --workspace C:/Temp/one-view-rehearsal D

``all`` performs setup and all unfinished scenes. Repeating a completed stage only
prints its recorded result; it never rewinds. Passwords stay in demo-credentials.json.
The public report contains evidence and result values, never cookies or credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import Database
from backend.main import create_app

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = "component-four-scenes-v1"
F1 = "provider-e2f35075482123a2267dd143"
F2 = "provider-89c51a61990828f2e6027c6f"
H2 = "provider-4d119fc90c8c2cf7b55b314c"
TASK_A = "f1-laundry-batch-2026-07-17"
PREFIX = "/api/v1"
STAGES = ["setup", "A", "B", "C", "D"]


def safe_workspace(path: Path) -> Path:
    """Require an explicitly chosen directory outside the user's checkout."""
    path = path.expanduser().resolve()
    if path == ROOT or ROOT in path.parents or path == Path(path.anchor):
        raise ValueError("Use a dedicated scratch directory outside the checkout")
    if any(part.lower() == ".local" for part in path.parts):
        raise ValueError("The user's .local directory is off limits")
    return path


def write_json(path: Path, payload: dict):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def command(workspace: Path, *args: str) -> str:
    """Print a reviewable exact argv and run it without a shell."""
    argv = [sys.executable, *args]
    print("$ " + subprocess.list2cmdline(argv), flush=True)
    environment = os.environ.copy()
    environment.update(
        SOLAR_DATABASE=str(workspace / "api.sqlite3"),
        SOLAR_MEDIA_DIR=str(workspace / "media"),
        SOLAR_OFFER_WORKER="false",
        PYTHONIOENCODING="utf-8",
    )
    result = subprocess.run(
        argv,
        cwd=ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr, flush=True)
    return result.stdout


def read_state(workspace: Path) -> dict:
    marker = workspace / "demo-state.json"
    if not marker.exists():
        raise ValueError("Run setup in a new scratch directory first")
    state = json.loads(marker.read_text(encoding="utf-8"))
    if state.get("scenario") != SCENARIO:
        raise ValueError("This directory belongs to a different scenario")
    with sqlite3.connect(workspace / "api.sqlite3") as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key='scenario'"
        ).fetchone()
    if not row or json.loads(row[0]).get("run_id") != state.get("run_id"):
        raise ValueError(
            "Scenario identity differs from the recorded run; refusing mutations"
        )
    return state


def settings_for(workspace: Path) -> Settings:
    return Settings(
        database_path=workspace / "api.sqlite3",
        media_dir=workspace / "media",
        offer_worker=False,
    )


@contextmanager
def account(workspace: Path, username: str):
    credentials = json.loads(
        (workspace / "demo-credentials.json").read_text(encoding="utf-8")
    )
    entry = credentials[username]
    password = entry["password"] if isinstance(entry, dict) else entry
    with TestClient(create_app(settings_for(workspace))) as client:
        response = client.post(
            f"{PREFIX}/auth/login", json={"username": username, "password": password}
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Login failed for {username}: HTTP {response.status_code}"
            )
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        yield client


def request(client, method, path, body=None, *, expected=(200, 201), key=None):
    kwargs = {"json": body} if body is not None else {}
    if key:
        kwargs["headers"] = {"Idempotency-Key": key}
    response = client.request(method, PREFIX + path, **kwargs)
    if response.status_code not in expected:
        raise RuntimeError(
            f"{method} {path}: HTTP {response.status_code}: {response.text}"
        )
    return response.json()


def setup(workspace: Path, rebuild=False) -> dict:
    workspace = safe_workspace(workspace)
    if (workspace / "demo-state.json").exists():
        read_state(workspace)
        return json.loads((workspace / "demo-report.json").read_text(encoding="utf-8"))[
            "setup"
        ]
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError(
            "Setup requires an empty directory; existing data are never deleted"
        )
    ancestor = workspace
    while not ancestor.exists():
        ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < 2 * 1024**3:
        raise ValueError(
            "Choose a scratch drive with at least 2 GiB free for immutable snapshots"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    component = ROOT / "build/components/component.sqlite"
    generate = [
        "generate_components.py",
        "--seed",
        "42",
        "--start",
        "2026-07-15",
        "--days",
        "7",
        "--out",
        "demo_components",
        "--truth-out",
        "tests/component_truth",
        "--provider-data",
        "demo_data",
    ]
    if rebuild or not (ROOT / "demo_components/manifest.json").exists():
        command(workspace, *generate)
    else:
        print(
            "Using committed deterministic component fixtures; regeneration: "
            + subprocess.list2cmdline([sys.executable, *generate]),
            flush=True,
        )
    if rebuild or not component.exists():
        command(
            workspace,
            "scraper.py",
            "--component",
            "all",
            "--config",
            "config/component_profiles.yaml",
            "--input",
            "demo_components",
            "--out",
            "build/components",
            "--as-of",
            "2026-07-22T00:00:00+03:00",
        )
    command(workspace, "-m", "backend", "migrate")
    provider = ROOT / "build/scraper.sqlite.gz"
    provider_result = json.loads(
        command(
            workspace,
            "-m",
            "backend",
            "import-provider",
            "--database",
            str(provider),
            "--sites",
            "demo_data/sites.json",
            "--frames",
            "build/site_frames_15min.csv",
        )
    )
    component_result = json.loads(
        command(
            workspace,
            "-m",
            "backend",
            "import-components",
            "--database",
            str(component),
        )
    )
    command(workspace, "-m", "backend", "provision-component-scenario")
    command(workspace, "-m", "backend", "provision-scenario-operations")
    clock = json.loads(
        command(
            workspace,
            "-m",
            "backend",
            "scenario",
            "start",
            SCENARIO,
            "--at",
            "2026-07-17T07:30:00+03:00",
        )
    )
    state = {"scenario": SCENARIO, "run_id": clock["run_id"], "completed": ["setup"]}
    result = {
        "provider_import": provider_result,
        "component_import": component_result,
        "clock": clock,
        "synthetic": True,
    }
    write_json(workspace / "demo-state.json", state)
    write_json(
        workspace / "demo-report.json",
        {"scenario": SCENARIO, "synthetic": True, "setup": result},
    )
    return result


def advance(workspace, to, *, correlate=False, settle=False):
    args = ["-m", "backend", "scenario", "advance", "--to", to]
    if correlate:
        args.append("--correlate")
    if settle:
        args.append("--settle")
    return json.loads(command(workspace, *args))


def plan_summary(plan):
    return {
        key: plan.get(key)
        for key in (
            "recommended_start",
            "recommended_end",
            "estimated_cost_ron",
            "baseline_start",
            "baseline_kind",
            "baseline_cost_ron",
            "estimated_difference_ron",
            "forecast",
            "battery",
            "review_suggested",
            "reason_codes",
        )
    }


def scene_a(workspace, state):
    with account(workspace, "laundry-owner") as owner:
        equipment = request(owner, "GET", f"/sites/{F1}/equipment/summary")
        plan = request(owner, "GET", f"/sites/{F1}/plan?task={TASK_A}")
        body = {"recommendation_revision": plan["recommendation_revision"]}
        accepted = request(
            owner,
            "POST",
            f"/sites/{F1}/tasks/{TASK_A}/accept",
            body,
            key="scene-a-accept",
        )
        repeated = request(
            owner,
            "POST",
            f"/sites/{F1}/tasks/{TASK_A}/accept",
            body,
            key="scene-a-accept",
        )
        if accepted["commitment"] != repeated["commitment"]:
            raise RuntimeError("Repeated task acceptance changed the commitment")
        advance(workspace, "2026-07-17T12:00:00+03:00")
        running = request(owner, "GET", f"/sites/{F1}/tasks/{TASK_A}/progress")
        advance(workspace, "2026-07-17T14:00:00+03:00")
        progress = request(owner, "GET", f"/sites/{F1}/tasks/{TASK_A}/progress")
    # Accept the trust scene's offer before the historical gap: no wall-time data injection.
    with account(workspace, "scenario-supervisor") as supervisor:
        offer = request(
            supervisor,
            "POST",
            "/manager/offers",
            {
                "type": "consume",
                "title": "Scene C: measured coverage matters",
                "energy_kwh": "10",
                "offer_price_ron_per_kwh": "0.55",
                "window_minutes": 120,
                "penalty_type": "per_unfulfilled_kwh",
                "penalty_value": "0.30",
                "offer_expires_at": "2026-07-17T18:00:00+03:00",
                "area_id": "sector-1",
            },
        )
        request(supervisor, "POST", f"/manager/offers/{offer['offer_id']}/publish", {})
    with account(workspace, "h2-resident") as resident:
        taken = request(
            resident,
            "POST",
            f"/offers/{offer['offer_id']}/accept",
            {"site_id": H2},
            key="scene-c-offer",
        )
    state["gap_offer_id"] = taken["user_offer_id"]
    return {
        "plan": plan_summary(plan),
        "equipment": equipment,
        "commitment": accepted["commitment"],
        "repeated_accept_same_commitment": True,
        "running_status": running["status"],
        "progress": progress,
        "gap_offer": taken,
    }


def scene_b(workspace, state):
    advance(workspace, "2026-07-18T07:30:00+03:00")
    with account(workspace, "laundry-owner") as owner:
        task = request(
            owner,
            "POST",
            f"/sites/{F1}/tasks",
            {
                "label": "18 July laundry batch",
                "kind": "laundry_batch",
                "power_kw": 4,
                "energy_kwh": 8,
                "earliest_start": "2026-07-18T10:00:00+03:00",
                "deadline": "2026-07-18T20:00:00+03:00",
                "usual_start": "2026-07-18T10:00:00+03:00",
                "site_import_limit_kw": 17.3,
            },
        )
        task_id = task["task_id"]
        before = request(owner, "GET", f"/sites/{F1}/plan?task={task_id}")
        accepted = request(
            owner,
            "POST",
            f"/sites/{F1}/tasks/{task_id}/accept",
            {"recommendation_revision": before["recommendation_revision"]},
            key="scene-b-accept",
        )
        advance(workspace, "2026-07-18T10:00:00+03:00")
        after = request(owner, "GET", f"/sites/{F1}/plan?task={task_id}")
        tasks = request(owner, "GET", f"/sites/{F1}/tasks")
        retained = next(t for t in tasks if t["task_id"] == task_id)["commitment"]
        equipment = request(owner, "GET", f"/sites/{F1}/equipment/summary")
    if accepted["commitment"] != retained:
        raise RuntimeError("New evidence silently changed the accepted commitment")
    state["scene_b_task_id"] = task_id
    return {
        "task_id": task_id,
        "before": plan_summary(before),
        "after": plan_summary(after),
        "commitment": retained,
        "commitment_unchanged": True,
        "equipment": equipment,
        "note": "Correlation is first run in Scene D, so its response deadlines start when reviewed there.",
    }


def durable_counts(workspace):
    with Database(workspace / "api.sqlite3").connect() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "component_imports",
                "component_grid_frames",
                "user_offers",
                "offer_settlements",
                "notifications",
                "assignments",
            )
        }
        counts["savings"] = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM savings_totals ORDER BY user_id"
            )
        ]
        return counts


def scene_c(workspace, state):
    first_worker = command(workspace, "-m", "backend", "offers-worker", "--once")
    with account(workspace, "h2-resident") as resident:
        offer = next(
            item
            for item in request(resident, "GET", "/offers/mine")
            if item["user_offer_id"] == state["gap_offer_id"]
        )
    before = durable_counts(workspace)
    duplicate = json.loads(
        command(
            workspace,
            "-m",
            "backend",
            "import-components",
            "--database",
            str(ROOT / "build/components/component.sqlite"),
        )
    )
    repeated_worker = command(workspace, "-m", "backend", "offers-worker", "--once")
    after = durable_counts(workspace)
    with Database(workspace / "api.sqlite3").connect() as connection:
        path = connection.execute(
            "SELECT database_path FROM component_imports ORDER BY imported_at DESC LIMIT 1"
        ).fetchone()[0]
        mirrors = [
            dict(row)
            for row in connection.execute(
                "SELECT selected_asset_id, value_origin, COUNT(*) AS frames, ROUND(SUM(value_kwh),6) AS energy_kwh FROM component_grid_frames WHERE site_id=? AND metric='grid_import' AND frame_start >= '2026-07-17T11:00:00Z' AND frame_end <= '2026-07-17T13:00:00Z' GROUP BY selected_asset_id,value_origin",
                (F2,),
            )
        ]
    with sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True
    ) as snapshot:
        snapshot.row_factory = sqlite3.Row
        duplicates = snapshot.execute(
            "SELECT COUNT(*) FROM raw_records WHERE status='exact_duplicate' AND endpoint_key='EMData.GetStatus'"
        ).fetchone()[0]
        resets = [
            dict(row)
            for row in snapshot.execute(
                "SELECT status, energy_kwh, allocatable FROM interval_energy WHERE status='segment_start_known_reset'"
            )
        ]
        all_quality = [
            dict(row)
            for row in snapshot.execute(
                "SELECT issue_code,COUNT(*) AS count FROM quality_issues WHERE issue_code IN ('exact_duplicate_suppressed','known_counter_reset_new_segment') GROUP BY issue_code"
            )
        ]
    if before != after:
        raise RuntimeError(
            "Repeated import/worker changed durable financial or measurement totals"
        )
    if offer["settlement"]["penalty_waived_reason"] != "meter_data_incomplete":
        raise RuntimeError("The incomplete meter offer did not waive its penalty")
    return {
        "offer": offer,
        "shelly_duplicate_records_suppressed": duplicates,
        "counter_reset_intervals": resets,
        "quality_counts": all_quality,
        "f2_authority_window": mirrors,
        "repeated_import": duplicate,
        "first_worker": first_worker.strip(),
        "repeated_worker": repeated_worker.strip(),
        "durable_counts_before": before,
        "durable_counts_after": after,
        "totals_unchanged": before == after,
    }


def scene_d(workspace, state):
    advance(workspace, "2026-07-19T11:30:00+03:00", correlate=True)
    with account(workspace, "scenario-dispatcher") as dispatcher:
        queue = request(dispatcher, "GET", "/ops/queue")
        map_before = request(dispatcher, "GET", "/ops/map")
        episodes = {
            item["episode"]["rule_id"]: item["incident"]["incident_id"]
            for item in queue["items"]
            if item["episode"]
        }
        plan = request(dispatcher, "POST", "/ops/plans", {"horizon_hours": 12})
        request(dispatcher, "POST", f"/ops/plans/{plan['plan_id']}/review", {})
        with account(workspace, "scenario-supervisor") as supervisor:
            review_denied = request(
                supervisor,
                "POST",
                f"/ops/plans/{plan['plan_id']}/review",
                {},
                expected=(403,),
            )
            apply_denied = request(
                supervisor,
                "POST",
                f"/ops/plans/{plan['plan_id']}/apply",
                {"expected_input_digest": plan["input_digest"]},
                expected=(403,),
            )
        applied = request(
            dispatcher,
            "POST",
            f"/ops/plans/{plan['plan_id']}/apply",
            {"expected_input_digest": plan["input_digest"]},
            key="scene-d-apply",
        )
        repeated = request(
            dispatcher,
            "POST",
            f"/ops/plans/{plan['plan_id']}/apply",
            {"expected_input_digest": plan["input_digest"]},
            key="scene-d-apply",
        )
        stale_plan = request(dispatcher, "POST", "/ops/plans", {"horizon_hours": 12})
        request(dispatcher, "POST", f"/ops/plans/{stale_plan['plan_id']}/review", {})
        voltage_id = episodes["pcc_voltage_sustained"]
        legacy_assign = request(
            dispatcher,
            "POST",
            f"/ops/incidents/{voltage_id}/assign",
            {},
            expected=(409,),
        )
        override = request(
            dispatcher,
            "POST",
            f"/ops/episodes/{voltage_id}/priority-override",
            {
                "band": "P1",
                "reason": "Demo: customer reports flicker; temporary review priority",
                "expires_at": "2026-07-19T14:00:00+03:00",
            },
        )
        stale = request(
            dispatcher,
            "POST",
            f"/ops/plans/{stale_plan['plan_id']}/apply",
            {"expected_input_digest": stale_plan["input_digest"]},
            key="scene-d-stale",
            expected=(409,),
        )
        latest = request(dispatcher, "GET", "/ops/plans/latest")
        request(
            dispatcher,
            "POST",
            f"/ops/episodes/{voltage_id}/priority-override/revoke",
            {},
        )
    with account(workspace, "tech-battery-2") as technician:
        agenda = request(technician, "GET", "/ops/agenda")
        battery = next(
            item
            for item in agenda["items"]
            if item["incident_id"] == episodes["battery_operational_restriction"]
        )
        request(
            technician,
            "POST",
            f"/ops/assignments/{battery['assignment_id']}/progress",
            {"state": "en_route", "expected_revision": battery["revision"]},
        )
    with account(workspace, "desk-operator") as desk:
        agenda = request(desk, "GET", "/ops/agenda")
        review = next(
            item for item in agenda["items"] if item["activity"] == "remote_review"
        )
        request(
            desk,
            "POST",
            f"/ops/assignments/{review['assignment_id']}/progress",
            {
                "state": "done",
                "expected_revision": review["revision"],
                "outcome": "field_visit_needed",
                "note": "Synthetic remote review: persistent deficit needs an authorised PV inspection.",
            },
        )
        advance(workspace, "2026-07-19T12:30:00+03:00", correlate=True)
        agenda = request(desk, "GET", "/ops/agenda")
        outage = next(
            item
            for item in agenda["items"]
            if item["activity"] == "remote_troubleshooting"
        )
        request(
            desk,
            "POST",
            f"/ops/assignments/{outage['assignment_id']}/progress",
            {
                "state": "done",
                "expected_revision": outage["revision"],
                "outcome": "resolved",
                "note": "Synthetic collector access recovered; remote desk verified both feeds.",
            },
        )
    with account(workspace, "scenario-dispatcher") as dispatcher:
        final_queue = request(dispatcher, "GET", "/ops/queue")
        final_map = request(dispatcher, "GET", "/ops/map")
        closure = request(dispatcher, "GET", f"/ops/episodes/{outage['incident_id']}")
        final_agenda = request(dispatcher, "GET", "/ops/agenda")
    return {
        "queue_before": queue,
        "map_before": map_before,
        "plan": plan,
        "applied_assignment_ids": applied["applied_assignment_ids"],
        "repeated_apply_same_assignments": applied["applied_assignment_ids"]
        == repeated["applied_assignment_ids"],
        "supervisor_review": review_denied,
        "supervisor_apply": apply_denied,
        "stale_apply": stale,
        "legacy_assign": legacy_assign,
        "replacement_plan_status": latest["status"],
        "override_computed_band": override["rank"]["computed_band"],
        "technician_agenda": agenda,
        "queue_after": final_queue,
        "map_after": final_map,
        "closure": closure,
        "final_agenda": final_agenda,
    }


def _hhmm(value):
    """Europe/Bucharest wall time."""
    if not value:
        return "unknown"
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment.astimezone(ZoneInfo("Europe/Bucharest")).strftime("%d %b %H:%M")


def _ron(value):
    return "unknown" if value is None else f"{value:.2f} RON"


def _plan_line(plan):
    battery = plan.get("battery") or {}
    return (
        f"recommended {_hhmm(plan.get('recommended_start'))}-"
        f"{_hhmm(plan.get('recommended_end'))[-5:]} at "
        f"{_ron(plan.get('estimated_cost_ron'))} vs {plan.get('baseline_kind')} "
        f"{_hhmm(plan.get('baseline_start'))} at {_ron(plan.get('baseline_cost_ron'))} "
        f"(difference {_ron(plan.get('estimated_difference_ron'))}); battery "
        f"{'included' if battery.get('available') else 'excluded'} "
        f"{battery.get('reason_codes') or ''}"
    )


def summarize(stage: str, result: dict) -> list[str]:
    """Plain-text actual values for the presenters (no credentials, no cookies)."""
    if stage == "setup":
        clock = result.get("clock") or {}
        return [f"Scenario clock: {json.dumps(clock, ensure_ascii=False)}"]
    if stage == "A":
        progress = result["progress"]
        measured = progress["measured"]
        return [
            "F1 laundry 4 kW x 2 h, 17 Jul: " + _plan_line(result["plan"]),
            f"Accepted start {_hhmm(result['commitment'].get('start'))}; repeat accept "
            "with the same Idempotency-Key returned the same commitment",
            f"At 12:00 status={result['running_status']}; at 14:00 "
            f"status={progress['status']}, measured connection-point import "
            f"{measured.get('grid_import_kwh')} kWh (coverage "
            f"{measured.get('import_coverage')}), measured site cost "
            f"{_ron(progress.get('measured_site_cost_ron'))} vs estimated "
            f"{_ron(progress.get('estimated_site_cost_ron'))}",
            f"Note: {progress.get('attribution_note')}",
        ]
    if stage == "B":
        return [
            "18 Jul 07:30 before new evidence: " + _plan_line(result["before"]),
            "18 Jul 10:00 after clouds + Victron alarm/derate: "
            + _plan_line(result["after"]),
            f"review_suggested={result['after'].get('review_suggested')}; accepted "
            f"commitment unchanged={result['commitment_unchanged']} (start "
            f"{_hhmm(result['commitment'].get('start'))})",
        ]
    if stage == "C":
        settlement = result["offer"].get("settlement") or {}
        return [
            "H2 Shelly exact duplicates suppressed: "
            f"{result['shelly_duplicate_records_suppressed']}",
            "Counter-reset intervals (no invented delta): "
            f"{result['counter_reset_intervals']}",
            f"Quality issue counts: {result['quality_counts']}",
            "F2 grid import 17 Jul 14:00-16:00 local by selected authority: "
            f"{result['f2_authority_window']}",
            "Offer on H2 across the meter gap: coverage "
            f"{settlement.get('coverage_ratio')}, penalty before waiver "
            f"{settlement.get('penalty_before_waiver_bani')} bani, penalty "
            f"{settlement.get('penalty_bani')} bani, waived reason "
            f"{settlement.get('penalty_waived_reason')}",
            f"Repeated import status={result['repeated_import'].get('status')}; "
            f"durable totals unchanged={result['totals_unchanged']}",
        ]
    if stage != "D":
        return []
    before, after = result["map_before"]["counts"], result["map_after"]["counts"]
    lines = [
        f"19 Jul 11:30 queue revision {result['queue_before']['revision']} = map "
        f"revision {result['map_before']['revision']}; {before['unique_episodes']} "
        f"unique episodes on {before['affected_sites']} affected sites; by band "
        f"{before['episodes_by_band']}"
    ]
    for item in result["queue_before"]["items"]:
        episode = item.get("episode") or {}
        lines.append(
            f"  {item['rank']['band']} {episode.get('rule_id')}: "
            f"{item['incident']['title']} [{episode.get('action')}, "
            f"{episode.get('confidence')}]"
        )
    plan = result["plan"]
    lines.append(f"Plan: {plan['label']}")
    for visit in plan["visits"] + plan["remote_items"]:
        lines.append(
            f"  {visit['crew_name']}: {visit['title']} ({visit['activity']}) "
            f"{_hhmm(visit['start_at'])}-{_hhmm(visit['finish_at'])[-5:]}, "
            f"deadline met={visit.get('deadline_met')}"
        )
    for item in plan["unassigned"]:
        lines.append(f"  Unassigned: {item.get('title')} {item.get('reasons')}")
    lines.append(f"  Monitoring only: {len(plan['monitoring'])} items")
    comparison = plan["comparison"]
    lines.append(
        f"Baseline verdict: {comparison['verdict']}; findings: "
        f"{comparison.get('findings')}"
    )
    lines.append(
        f"Supervisor review -> {result['supervisor_review'].get('code')}, apply -> "
        f"{result['supervisor_apply'].get('code')}; repeated apply same "
        f"assignments={result['repeated_apply_same_assignments']}; legacy assign "
        f"on a correlated incident -> {result['legacy_assign'].get('code')}"
    )
    lines.append(
        f"Override H2 to P1 (computed band {result['override_computed_band']} kept); "
        f"old plan apply -> {result['stale_apply'].get('code')}; replacement plan "
        f"status {result['replacement_plan_status']}"
    )
    closure = result["closure"]
    lines.append(
        f"12:30 outage closed: incident {closure['incident']['status']}, "
        f"resolution {closure['episode'].get('resolution_kind')}; unique episodes "
        f"{before['unique_episodes']} -> {after['unique_episodes']}; affected "
        f"sites {before['affected_sites']} -> {after['affected_sites']}; workflow "
        f"{after['sites_by_workflow']}; telemetry {after['sites_by_telemetry']}"
    )
    for item in result["final_agenda"]["items"]:
        lines.append(
            f"  Agenda {item.get('crew_id')}: {item.get('title')} "
            f"({item.get('activity')}) progress={item.get('progress')}"
        )
    return lines


def print_summary(stage: str, result: dict):
    print(
        "--- Setup ---" if stage == "setup" else f"--- Scene {stage} actual values ---"
    )
    for line in summarize(stage, result):
        print(line, flush=True)


def run_stage(workspace: Path, stage: str) -> dict:
    workspace = safe_workspace(workspace)
    state = read_state(workspace)
    report_path = workspace / "demo-report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if stage in state["completed"]:
        print(
            f"Scene {stage} already completed; retaining forward-only state.",
            flush=True,
        )
        print_summary(stage, report[stage])
        return report[stage]
    previous = STAGES[STAGES.index(stage) - 1]
    if previous not in state["completed"]:
        raise ValueError(
            f"Complete {previous} before {stage}; the replay never rewinds"
        )
    result = {"A": scene_a, "B": scene_b, "C": scene_c, "D": scene_d}[stage](
        workspace, state
    )
    report[stage] = result
    write_json(report_path, report)
    state["completed"].append(stage)
    write_json(workspace / "demo-state.json", state)
    print(f"Scene {stage} complete. Evidence: {report_path}", flush=True)
    print_summary(stage, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="Dedicated scratch directory outside this checkout",
    )
    parser.add_argument(
        "--rebuild-components",
        action="store_true",
        help="Regenerate synthetic component fixtures and snapshot during setup",
    )
    parser.add_argument("stage", choices=[*STAGES, "all"])
    args = parser.parse_args(argv)
    try:
        workspace = safe_workspace(args.workspace)
        if args.stage in ("setup", "all"):
            print_summary("setup", setup(workspace, args.rebuild_components))
        for stage in STAGES[1:]:
            if args.stage in (stage, "all"):
                run_stage(workspace, stage)
        print(f"Database: {workspace / 'api.sqlite3'}")
        print(f"Private credentials: {workspace / 'demo-credentials.json'}")
        print(f"Public evidence report: {workspace / 'demo-report.json'}")
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout or "", file=sys.stderr)
            print(error.stderr or "", file=sys.stderr)
        parser.exit(1, f"Demo stopped: {error}\n")


if __name__ == "__main__":
    main()
