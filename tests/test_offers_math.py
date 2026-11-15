"""Pure Power Block Offer math: penalties, settlement, rounding, FIFO attribution, texts."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from backend.offers_math import (
    Commitment,
    MeterInterval,
    attribute,
    bani,
    decimal_text,
    penalty_ron,
    penalty_rule_text,
    ron_text,
    settle,
    terms_text,
)

T = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


def consume(**changes):
    terms = {
        "offer_type": "consume",
        "energy_kwh": D("10"),
        "metered_kwh": D("10"),
        "offer_price": D("0.55"),
        "reference_price": D("1.3"),
        "penalty_type": "per_unfulfilled_kwh",
        "penalty_value": D("0.3"),
        "coverage_ratio": D(1),
    }
    return settle(**(terms | changes))


def export(**changes):
    return consume(
        **(
            {
                "offer_type": "export",
                "offer_price": D("0.7"),
                "reference_price": D("0.55"),
                "penalty_type": "percent_of_unfulfilled_value",
                "penalty_value": D("20"),
            }
            | changes
        )
    )


def test_penalty_functions():
    assert penalty_ron("per_unfulfilled_kwh", D("0.3"), D("2"), D("0.55")) == D("0.6")
    assert penalty_ron("percent_of_unfulfilled_value", D("20"), D("4"), D("0.7")) == D(
        "0.56"
    )
    assert penalty_ron("flat", D("5"), D("0.001"), D("0.55")) == D("5")
    for kind in ("per_unfulfilled_kwh", "percent_of_unfulfilled_value", "flat"):
        assert penalty_ron(kind, D("5"), D("0"), D("0.55")) == 0


def test_consume_full_partial_zero_and_over_fulfilment():
    full = consume()
    assert (full.outcome, full.direction) == ("completed", "charge")
    assert (full.amount_bani, full.penalty_bani, full.savings_bani) == (550, 0, 750)
    partial = consume(metered_kwh=D("8"))
    assert partial.outcome == "partial"
    assert (partial.fulfilled_kwh, partial.unfulfilled_kwh) == (D("8"), D("2"))
    assert (partial.energy_value_bani, partial.penalty_bani) == (440, 60)
    assert (partial.amount_bani, partial.savings_bani) == (500, 540)
    zero = consume(metered_kwh=D("0"))
    assert zero.outcome == "expired_unfulfilled"
    assert (zero.amount_bani, zero.penalty_bani, zero.savings_bani) == (300, 300, -300)
    over = consume(metered_kwh=D("12.5"))
    assert over.outcome == "completed"
    assert (over.fulfilled_kwh, over.excess_kwh) == (D("10"), D("2.5"))
    # Excess is recorded but never charged here.
    assert (over.amount_bani, over.savings_bani) == (550, 750)


def test_export_credit_gain_and_negative_results():
    partial = export(metered_kwh=D("6"))
    assert (partial.direction, partial.outcome) == ("credit", "partial")
    assert (partial.energy_value_bani, partial.penalty_bani) == (420, 56)
    assert (partial.amount_bani, partial.savings_bani) == (364, 34)
    assert export().savings_bani == 150
    # A flat penalty with nothing delivered is a negative credit; never clamped.
    nothing = export(
        metered_kwh=D(0), offer_price=D("0.1"), penalty_type="flat", penalty_value=D(5)
    )
    assert (nothing.amount_bani, nothing.savings_bani) == (-500, -500)
    # An offer price worse than the reference yields negative savings.
    worse = consume(offer_price=D("1.5"))
    assert (worse.amount_bani, worse.savings_bani) == (1500, -200)
    assert export(offer_price=D("0.4")).savings_bani == -150


def test_rounding_happens_once_per_stored_amount_half_up():
    tiny = consume(
        energy_kwh=D("1"),
        metered_kwh=D("0.5"),
        offer_price=D("0.01"),
        reference_price=D("0.01"),
        penalty_value=D("0.01"),
    )
    # 0.005 RON energy + 0.005 RON penalty: each rounds to 1 ban, the total 0.01 RON to 1.
    assert (tiny.energy_value_bani, tiny.penalty_bani, tiny.amount_bani) == (1, 1, 1)
    assert tiny.savings_bani == -1  # -0.005 RON rounds half away from zero
    awkward = consume(
        energy_kwh=D("7.777"),
        metered_kwh=D("3.3334"),
        offer_price=D("0.4321"),
        reference_price=D("1.2345"),
        penalty_type="percent_of_unfulfilled_value",
        penalty_value=D("12.5"),
    )
    assert awkward.metered_kwh == D("3.333")  # kWh rounded to 3 decimals first
    assert awkward.unfulfilled_kwh == D("4.444")
    assert awkward.energy_value_bani == 144  # 1.4401893 RON
    assert awkward.penalty_bani == 24  # 0.24003155 RON
    assert awkward.amount_bani == 168  # 1.68022085 RON
    assert awkward.savings_bani == 243  # 2.6743992 - 0.24003155 = 2.43436765 RON
    assert bani(D("0.125")) == 13 and bani(D("-0.125")) == -13
    assert ron_text(750) == "7.50 RON" and ron_text(-5) == "-0.05 RON"


def test_penalty_waivers():
    incomplete = consume(metered_kwh=D("4"), coverage_ratio=D("0.79"))
    assert incomplete.penalty_waived_reason == "meter_data_incomplete"
    assert (incomplete.penalty_bani, incomplete.penalty_before_waiver_bani) == (0, 180)
    assert incomplete.amount_bani == 220
    enough = consume(metered_kwh=D("4"), coverage_ratio=D("0.8"))
    assert (enough.penalty_waived_reason, enough.penalty_bani) == (None, 180)
    # Nothing to waive when the block was delivered.
    assert consume(coverage_ratio=D("0.1")).penalty_waived_reason is None
    cancelled = consume(metered_kwh=D("3"), cancelled=True)
    assert (cancelled.outcome, cancelled.penalty_waived_reason) == (
        "cancelled",
        "cancelled_by_distributor",
    )
    assert (cancelled.penalty_bani, cancelled.amount_bani) == (0, 165)


def slots(start, count, kw, minutes=15):
    return [
        MeterInterval(
            start + timedelta(minutes=minutes * index),
            start + timedelta(minutes=minutes * (index + 1)),
            None if kw is None else D(str(kw)),
        )
        for index in range(count)
    ]


def commitment(name, start, minutes, capacity, accepted=None):
    return Commitment(
        user_offer_id=name,
        accepted_at=accepted or start,
        window_start=start,
        window_end=start + timedelta(minutes=minutes),
        capacity_kwh=D(capacity),
    )


def test_fifo_attribution_between_overlapping_offers_and_excess():
    # 8 kW = 2 kWh per 15 minutes from 10:00 to 12:30 (20 kWh in total).
    intervals = slots(T, 10, 8)
    a = commitment("a", T, 120, "5")
    b = commitment("b", T + timedelta(minutes=30), 120, "5")
    result = attribute(intervals, [b, a])
    assert result["a"].attributed_kwh == result["b"].attributed_kwh == D(5)
    # Leftover goes to the earliest covering offer as excess; after 12:00 only b covers.
    assert (result["a"].excess_kwh, result["b"].excess_kwh) == (D(6), D(4))
    assert (result["a"].metered_kwh, result["b"].metered_kwh) == (D(11), D(9))
    assert result["a"].coverage_ratio == result["b"].coverage_ratio == 1
    assert sum(r.attributed_kwh + r.excess_kwh for r in result.values()) == 20


def test_fifo_prefers_earliest_acceptance_then_identifier():
    intervals = slots(T, 4, 4)  # 4 kWh in one hour
    first = commitment("z", T, 60, "3", accepted=T)
    tie = commitment("b", T, 60, "3", accepted=T + timedelta(seconds=1))
    other = commitment("a", T, 60, "3", accepted=T + timedelta(seconds=1))
    result = attribute(intervals, [tie, other, first])
    assert result["z"].attributed_kwh == 3
    assert (result["a"].attributed_kwh, result["b"].attributed_kwh) == (1, 0)


def test_partial_interval_overlap_and_coverage_gaps():
    # Window 10:05-10:35; intervals 10:00-10:15 and 10:30-10:45 at 6 kW, 10:15-10:30 missing.
    intervals = [
        *slots(T, 1, 6),
        *slots(T + timedelta(minutes=15), 1, None),
        *slots(T + timedelta(minutes=30), 1, 6),
    ]
    result = attribute(intervals, [commitment("x", T + timedelta(minutes=5), 30, "10")])
    # 10 minutes and 5 minutes overlap at 6 kW = 1.0 + 0.5 kWh.
    assert result["x"].metered_kwh == D("1.5")
    assert result["x"].coverage_ratio == D(15) / D(30)
    assert attribute([], [commitment("y", T, 30, "1")])["y"].coverage_ratio == 0


def test_plain_language_terms():
    assert (
        penalty_rule_text(
            "consume", D(10), 120, "per_unfulfilled_kwh", D("0.3"), D("0.55")
        )
        == "If you use less than 10 kWh within 2 hours, you pay 0.30 RON for each kWh not used."
    )
    assert penalty_rule_text(
        "export", D(10), 120, "percent_of_unfulfilled_value", D(20), D("0.7")
    ) == (
        "If you feed less than 10 kWh into the grid within 2 hours, you pay 20% of the "
        "offer value of the energy not delivered (0.14 RON per kWh)."
    )
    assert penalty_rule_text("consume", D(5), 90, "flat", D(5), D("0.45")) == (
        "If you use less than 5 kWh within 1 hour 30 minutes, you pay a flat 5.00 RON."
    )
    assert penalty_rule_text("export", D(5), 15, "flat", D(0), D("0.45")).startswith(
        "There is no penalty"
    )
    terms = terms_text(
        "consume", D(10), 120, "per_unfulfilled_kwh", D("0.3"), D("0.55")
    )
    assert "0.55 RON/kWh" in terms and "5.50 RON for the full block" in terms
    assert "The most you can pay as a penalty is 3.00 RON." in terms


@pytest.mark.parametrize(
    ("value", "text"),
    [(D("10.000"), "10"), (D("1E+1"), "10"), (D("0.550"), "0.55"), (D("0"), "0")],
)
def test_decimal_text(value, text):
    assert decimal_text(value) == text
