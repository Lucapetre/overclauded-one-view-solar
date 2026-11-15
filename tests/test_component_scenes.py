"""Cross-cutting acceptance: the real snapshots and four forward-only scenes.

Set SOLAR_SCENE_TEST_WORKSPACE to a completed runner workspace to validate its
recorded API evidence and durable state without replaying it. Without that setting,
the fixture makes a new isolated run. No old backend/engine suite is invoked.
"""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from backend.db import Database
from scripts.demo_scenes import ROOT, SCENARIO, run_stage, safe_workspace, setup


@pytest.fixture(scope="module")
def scenes(tmp_path_factory):
    supplied = os.getenv("SOLAR_SCENE_TEST_WORKSPACE")
    workspace = (
        safe_workspace(Path(supplied))
        if supplied
        else tmp_path_factory.mktemp("four-scenes")
    )
    if not supplied:
        if not (ROOT / "build/components/component.sqlite").exists():
            pytest.skip("Generate the component snapshot before full scene acceptance")
        setup(workspace)
        for stage in "ABCD":
            run_stage(workspace, stage)
    report = json.loads((workspace / "demo-report.json").read_text(encoding="utf-8"))
    state = json.loads((workspace / "demo-state.json").read_text(encoding="utf-8"))
    assert state["scenario"] == report["scenario"] == SCENARIO
    assert state["completed"] == ["setup", "A", "B", "C", "D"]
    return workspace, report


def test_runner_refuses_checkout_root_local_and_existing_unowned_data(tmp_path):
    for path in (
        ROOT,
        ROOT / "build/scenario",
        Path(ROOT.anchor),
        tmp_path / ".local/demo",
    ):
        with pytest.raises(ValueError):
            safe_workspace(path)
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    marker = occupied / "important.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="empty directory"):
        setup(occupied)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_customer_decision_acceptance_and_measured_progress_share_the_replay(scenes):
    _, report = scenes
    scene = report["A"]
    plan = scene["plan"]
    assert plan["estimated_cost_ron"] < plan["baseline_cost_ron"]
    assert plan["estimated_difference_ron"] == pytest.approx(
        plan["estimated_cost_ron"] - plan["baseline_cost_ron"], abs=0.01
    )
    assert scene["commitment"]["start"] == plan["recommended_start"]
    assert scene["repeated_accept_same_commitment"]
    assert scene["running_status"] == "running"
    assert scene["progress"]["status"] == "completed"
    assert scene["progress"]["measured"]["import_coverage"] == 1
    assert (
        "whole site" in scene["progress"]["attribution_note"].lower()
        or "whole-site" in scene["progress"]["attribution_note"].lower()
    )
    assert datetime.fromisoformat(
        plan["forecast"]["issue_time"].replace("Z", "+00:00")
    ) <= datetime.fromisoformat(
        scene["commitment"]["accepted_at"].replace("Z", "+00:00")
    )


def test_new_battery_evidence_changes_advice_without_changing_accepted_terms(scenes):
    _, report = scenes
    scene = report["B"]
    assert scene["before"]["battery"]["available"]
    assert not scene["after"]["battery"]["available"]
    assert (
        "battery_alarm_active_restricted" in scene["after"]["battery"]["reason_codes"]
    )
    assert "battery_limit_derated_by_bms" in scene["after"]["battery"]["reason_codes"]
    # The recorded data recalculate the estimate (the slot happens to stay 13:30).
    assert (
        scene["after"]["recommended_start"] != scene["before"]["recommended_start"]
        or scene["after"]["estimated_cost_ron"] != scene["before"]["estimated_cost_ron"]
    )
    assert scene["after"]["review_suggested"]
    assert (
        "current_recommendation_differs_from_commitment"
        in scene["after"]["reason_codes"]
    )
    assert scene["commitment_unchanged"]
    assert scene["commitment"]["start"] == scene["before"]["recommended_start"]


def test_quality_boundary_and_financial_idempotency_are_visible_in_the_same_run(scenes):
    _, report = scenes
    scene = report["C"]
    assert scene["shelly_duplicate_records_suppressed"] > 0
    assert len(scene["counter_reset_intervals"]) == 2
    assert all(
        row["energy_kwh"] is None and row["allocatable"] == 0
        for row in scene["counter_reset_intervals"]
    )
    settlement = scene["offer"]["settlement"]
    assert settlement["coverage_ratio"] < 0.8
    assert settlement["penalty_waived_reason"] == "meter_data_incomplete"
    assert settlement["penalty_bani"] == 0
    assert scene["totals_unchanged"]
    assert scene["durable_counts_before"] == scene["durable_counts_after"]
    assert scene["repeated_import"]["status"] == "duplicate"
    assert all(
        row["selected_asset_id"] == "F2-M2-FEEDIN"
        for row in scene["f2_authority_window"]
    )


def test_dispatch_map_baseline_permissions_staleness_and_closure_are_consistent(scenes):
    _, report = scenes
    scene = report["D"]
    assert scene["queue_before"]["revision"] == scene["map_before"]["revision"]
    assert scene["queue_after"]["revision"] == scene["map_after"]["revision"]
    assert scene["map_before"]["counts"]["unique_episodes"] == 7
    assert scene["map_after"]["counts"]["unique_episodes"] == 6
    assert scene["map_before"]["counts"]["affected_sites"] == 4
    plan = scene["plan"]
    assert plan["comparison"]["verdict"] == "no_improvement"
    assert len(plan["unassigned"]) == 1
    assert (
        "crew_not_authorised_for_responsible_service"
        in plan["unassigned"][0]["reasons"]
    )
    assert len(plan["monitoring"]) == 3
    assert scene["repeated_apply_same_assignments"]
    assert scene["supervisor_apply"]["code"] == "dispatch_capability_required"
    assert scene["supervisor_review"]["code"] == "dispatch_capability_required"
    assert scene["stale_apply"]["code"] == "plan_stale"
    assert scene["legacy_assign"]["code"] == "episode_workflow_required"
    assert scene["replacement_plan_status"] == "draft"
    assert scene["override_computed_band"] == "P2"
    assert scene["closure"]["episode"]["resolution_kind"] == "authorized_closure"
    assert scene["closure"]["incident"]["status"] == "resolved"
    assert any(
        item["progress"] == "en_route" for item in scene["final_agenda"]["items"]
    )
    assert any(
        item["activity"] == "field_visit" and item["crew_id"] == "scn-pv-om"
        for item in scene["final_agenda"]["items"]
    )


def test_finished_stage_is_read_only_and_database_identity_matches_report(scenes):
    workspace, report = scenes
    with Database(workspace / "api.sqlite3").connect() as connection:
        before = connection.execute(
            "SELECT COUNT(*) FROM scenario_clock_events"
        ).fetchone()[0]
        stored = json.loads(
            connection.execute(
                "SELECT value FROM settings WHERE key='scenario'"
            ).fetchone()[0]
        )
        assert stored["run_id"] == report["setup"]["clock"]["run_id"]
        assert (
            connection.execute("SELECT COUNT(*) FROM offer_settlements").fetchone()[0]
            == 1
        )
    assert run_stage(workspace, "A") == report["A"]
    with Database(workspace / "api.sqlite3").connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM scenario_clock_events").fetchone()[
                0
            ]
            == before
        )
