"""Crew planner: hard constraints, unassigned reasons, determinism and the FIFO baseline."""

from datetime import UTC, datetime, timedelta

from backend.crew_planner import (
    Commitment,
    CrewInput,
    JobInput,
    PlanningInputs,
    Window,
    plan,
)

NOW = datetime(2026, 7, 19, 5, 0, tzinfo=UTC)  # 08:00 local
DAY_END = NOW + timedelta(hours=12)


def at(hours, minutes=0):
    return NOW + timedelta(hours=hours, minutes=minutes)


def crew(crew_id, **extra):
    base = dict(
        crew_id=crew_id,
        name=crew_id,
        kind="field",
        organisation="installer",
        authorised_services={"customer_installation_service"},
        qualifications={"pv_string_inspection"},
        tools={"iv_curve_tracer"},
        areas={"a1"},
        members=[f"{crew_id}-m1", f"{crew_id}-m2"],
        shift=Window(at(0), at(8)),
        breaks=[Window(at(4), at(4, 30))],
        base_node="DEPOT",
    )
    base.update(extra)
    return CrewInput(**base)


def job(job_id, band="P2", **extra):
    base = dict(
        job_id=job_id,
        incident_id=job_id.split(":")[0],
        site_id=job_id.split(":")[0],
        title=job_id,
        band=band,
        rank_position=1,
        rank_score=0.5,
        created_at=NOW - timedelta(hours=1),
        activity="field_visit",
        service_key="customer_installation_service",
        area="a1",
        node=job_id.split(":")[0],
        service_minutes=60,
        access_windows=[Window(at(0), at(12))],
        qualifications={"pv_string_inspection"},
    )
    base.update(extra)
    return JobInput(**base)


TRAVEL = {
    ("DEPOT", "A"): 10,
    ("DEPOT", "B"): 30,
    ("A", "B"): 25,
    ("DEPOT", "C"): 15,
    ("A", "C"): 10,
    ("B", "C"): 20,
    ("DEPOT", "D"): 20,
    ("A", "D"): 15,
    ("B", "D"): 15,
    ("C", "D"): 10,
}


def inputs(crews, jobs, **extra):
    return PlanningInputs(
        now=NOW,
        horizon_end=DAY_END,
        crews=crews,
        jobs=jobs,
        travel=TRAVEL,
        travel_source="approximate demo matrix (test)",
        **extra,
    )


def reasons(result, job_id):
    return next(u["reasons"] for u in result["unassigned"] if u["job_id"] == job_id)


def test_hard_constraints_skills_scope_parts_and_unknowns_give_specific_reasons():
    jobs = [
        job("A", qualifications={"battery_storage_service"}),
        job("B", area="elsewhere"),
        job("C", service_key="distributor_network_review"),
        job("D", parts_required=["bms_module"], parts_ready=None),
        job("E", node=None),
        job("F", service_minutes=None),
        job("G", access_windows=None),
        job("H", crew_size=3),
    ]
    result = plan(inputs([crew("crew1")], jobs))
    assert not result["visits"]
    assert any("missing_qualification" in r for r in reasons(result, "A"))
    assert "outside_crew_area_permission" in reasons(result, "B")
    assert "crew_not_authorised_for_responsible_service" in reasons(result, "C")
    assert reasons(result, "D") == ["parts_readiness_unknown"]
    assert reasons(result, "E") == ["job_location_unknown"]  # no fabricated ETA
    assert reasons(result, "F") == ["service_duration_unknown"]
    assert reasons(result, "G") == ["access_window_unknown"]
    assert "crew_too_small" in reasons(result, "H")
    assert result["input_completeness"]["status"] == "partial"


def test_shifts_breaks_windows_travel_and_no_overlap():
    jobs = [
        job("A", service_minutes=120, access_windows=[Window(at(5), at(8))]),
        job("B", service_minutes=90),
        job("C", service_minutes=60),
    ]
    result = plan(inputs([crew("crew1")], jobs))
    visits = sorted(result["visits"], key=lambda v: v["start_at"])
    assert len(visits) == 3
    for a, b in zip(visits, visits[1:], strict=False):
        assert a["finish_at"] <= b["depart_at"]
        assert b["arrive_at"] - b["depart_at"] == timedelta(minutes=b["travel_minutes"])
    lunch = Window(at(4), at(4, 30))
    for visit in visits:
        assert not lunch.overlaps(visit["start_at"], visit["finish_at"])
        assert visit["finish_at"] <= at(8)  # no silent overtime
    a = next(v for v in visits if v["job_id"] == "A")
    assert at(5) <= a["start_at"] and a["finish_at"] <= at(8)
    too_long = plan(inputs([crew("crew1")], [job("A", service_minutes=9 * 60)]))
    assert "no_feasible_insertion" in reasons(too_long, "A")


def test_locked_commitments_dependencies_and_member_level_availability():
    locked = Commitment("X:field_visit", "X", "C", at(1), at(2), started=False)
    crew1 = crew("crew1", commitments=[locked], members=["shared", "m2"])
    crew2 = crew("crew2", members=["shared"], qualifications={"pv_string_inspection"})
    jobs = [
        job(
            "A:remote_review",
            activity="remote_review",
            node=None,
            qualifications=set(),
            service_minutes=30,
        ),
        job("A:field_visit", node="A", depends_on=["A:remote_review"]),
    ]
    desk = crew(
        "desk",
        kind="remote_desk",
        base_node=None,
        tools=set(),
        qualifications=set(),
        members=["op"],
    )
    result = plan(inputs([crew1, desk], jobs))
    remote = result["remote_items"][0]
    field = next(v for v in result["visits"] if v["job_id"] == "A:field_visit")
    assert remote["finish_at"] <= field["start_at"] and remote["travel_minutes"] == 0
    assert not (field["start_at"] < locked.end and locked.start < field["finish_at"])
    # "shared" works in two crews: crew2 (only "shared") cannot run at the same time as crew1.
    busy = plan(inputs([crew1, crew2], [job("A"), job("B", crew_size=1)]))
    shared = {}
    for visit in busy["visits"]:
        shared.setdefault(visit["crew_id"], []).append(
            (visit["depart_at"], visit["finish_at"])
        )
    for s1, e1 in shared.get("crew1", []):
        for s2, e2 in shared.get("crew2", []):
            assert not (s1 < e2 and s2 < e1), "one person scheduled in two places"
    unavailable = plan(
        inputs(
            [crew("crew1", members=["solo"])],
            [job("A")],
            member_unavailability=[("solo", Window(at(0), at(8)), "leave")],
        )
    )
    assert "no_feasible_insertion" in reasons(unavailable, "A")


def test_priority_bands_first_mandatory_deadlines_and_urgent_exceptions():
    jobs = [
        job("B", band="P2", service_minutes=240, created_at=NOW - timedelta(hours=5)),
        job(
            "A",
            band="P1",
            service_minutes=240,
            deadline=at(2),
            deadline_mandatory=True,
            created_at=NOW - timedelta(minutes=10),
        ),
        job(
            "C", band="P0", service_minutes=60, deadline=at(1), deadline_mandatory=True
        ),
    ]
    one = crew("crew1", shift=Window(at(0), at(6)), breaks=[])
    result = plan(inputs([one], jobs))
    served = [
        v["job_id"] for v in sorted(result["visits"], key=lambda v: v["start_at"])
    ]
    assert (
        served[:2] == ["C", "A"] and "B" not in served
    )  # lower band never displaces higher
    assert [u["job_id"] for u in result["urgent_exceptions"]] == ["C"]
    assert "emergency_escalation_required" in result["urgent_exceptions"][0]["reason"]
    baseline = result["baseline"]
    assert baseline["visits"][0]["job_id"] == "B"  # FIFO serves the oldest first
    comparison = result["comparison"]
    assert comparison["heuristic"]["by_band"]["P1"]["timely"] == 1
    assert comparison["baseline"]["by_band"]["P1"]["timely"] == 0
    assert comparison["verdict"] in ("heuristic_improves", "mixed")
    impossible = plan(
        inputs([one], [job("A", band="P1", deadline=at(0, 5), deadline_mandatory=True)])
    )
    assert "mandatory_deadline_unreachable" in reasons(impossible, "A")
    assert impossible["urgent_exceptions"][0]["reason"].startswith(
        "urgent_job_unserved"
    )


def test_proposal_is_deterministic_and_baseline_reported_honestly():
    jobs = [job("A"), job("B"), job("C"), job("D")]
    crews = [crew("crew1"), crew("crew2", base_node="DEPOT")]
    first, second = plan(inputs(crews, jobs)), plan(inputs(crews, jobs))
    assert first == second
    assert first["label"].startswith("feasible heuristic proposal")
    assert first["input_digest"] == second["input_digest"]
    comparison = first["comparison"]
    assert "FIFO" in comparison["baseline_definition"]
    assert (
        comparison["heuristic"]["travel_minutes"]
        <= comparison["baseline"]["travel_minutes"]
    )
    single = plan(inputs([crew("crew1")], [job("A")]))
    assert single["comparison"]["verdict"] == "no_improvement"  # reported, not hidden
