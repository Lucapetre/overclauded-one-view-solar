"""Pure Power Block Offer math: decimals, penalties, settlement, FIFO attribution, terms text.

No database or clock access. Money is `Decimal` RON until it is stored, when it becomes
integer bani rounded half-up (away from zero) exactly once per stored amount.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
KWH = Decimal("0.001")
HOUR = Decimal(3_600_000_000)  # microseconds
COVERAGE_THRESHOLD = Decimal("0.8")


def decimal_text(value: Decimal) -> str:
    """Canonical plain decimal string: no exponent, no trailing zeros ("10", "0.55")."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def kwh(value: Decimal) -> Decimal:
    return value.quantize(KWH, rounding=ROUND_HALF_UP)


def bani(ron: Decimal) -> int:
    """The single rounding step for a stored money amount."""
    return int((ron * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ron_text(amount_bani: int) -> str:
    sign = "-" if amount_bani < 0 else ""
    whole, cents = divmod(abs(amount_bani), 100)
    return f"{sign}{whole}.{cents:02d} RON"


def price_text(price: Decimal) -> str:
    """At least two decimals, more when the price has them: 0.55, 0.5525, 1.30."""
    places = max(2, -price.normalize().as_tuple().exponent)
    return f"{price:.{places}f}"


def window_text(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if rest:
        parts.append(f"{rest} minute{'s' if rest != 1 else ''}")
    return " ".join(parts)


def penalty_ron(
    penalty_type: str, value: Decimal, unfulfilled_kwh: Decimal, offer_price: Decimal
) -> Decimal:
    """Penalty in RON for the unfulfilled part, before any waiver."""
    if unfulfilled_kwh <= 0:
        return ZERO
    if penalty_type == "per_unfulfilled_kwh":
        return unfulfilled_kwh * value
    if penalty_type == "percent_of_unfulfilled_value":
        return unfulfilled_kwh * offer_price * value / 100
    if penalty_type == "flat":
        return value
    raise ValueError(f"Unknown penalty type {penalty_type}")


@dataclass(frozen=True)
class Settlement:
    outcome: str
    metered_kwh: Decimal
    fulfilled_kwh: Decimal
    unfulfilled_kwh: Decimal
    excess_kwh: Decimal
    coverage_ratio: Decimal
    penalty_before_waiver_bani: int
    penalty_waived_reason: str | None
    energy_value_bani: int
    penalty_bani: int
    amount_bani: int
    direction: str
    savings_bani: int


def settle(
    *,
    offer_type: str,
    energy_kwh: Decimal,
    metered_kwh: Decimal,
    offer_price: Decimal,
    reference_price: Decimal,
    penalty_type: str,
    penalty_value: Decimal,
    coverage_ratio: Decimal,
    cancelled: bool = False,
) -> Settlement:
    """Settle one accepted block. Savings/gain may be negative and are never clamped."""
    metered = kwh(metered_kwh)
    fulfilled = min(metered, energy_kwh)
    unfulfilled = energy_kwh - fulfilled
    excess = metered - fulfilled
    raw_penalty = penalty_ron(penalty_type, penalty_value, unfulfilled, offer_price)
    reason = None
    penalty = raw_penalty
    if unfulfilled > 0 and cancelled:
        reason, penalty = "cancelled_by_distributor", ZERO
    elif unfulfilled > 0 and coverage_ratio < COVERAGE_THRESHOLD:
        # Missing meter data is never the client's fault.
        reason, penalty = "meter_data_incomplete", ZERO
    value = fulfilled * offer_price
    if offer_type == "consume":
        amount, direction = value + penalty, "charge"
        savings = fulfilled * (reference_price - offer_price) - penalty
    else:
        amount, direction = value - penalty, "credit"
        savings = fulfilled * (offer_price - reference_price) - penalty
    if cancelled:
        outcome = "cancelled"
    elif fulfilled == energy_kwh:
        outcome = "completed"
    elif fulfilled > 0:
        outcome = "partial"
    else:
        outcome = "expired_unfulfilled"
    return Settlement(
        outcome=outcome,
        metered_kwh=metered,
        fulfilled_kwh=fulfilled,
        unfulfilled_kwh=unfulfilled,
        excess_kwh=excess,
        coverage_ratio=coverage_ratio,
        penalty_before_waiver_bani=bani(raw_penalty),
        penalty_waived_reason=reason,
        energy_value_bani=bani(value),
        penalty_bani=bani(penalty),
        amount_bani=bani(amount),
        direction=direction,
        savings_bani=bani(savings),
    )


@dataclass(frozen=True)
class MeterInterval:
    """One telemetry interval's average power for the offer's metric (kW).

    `kw is None` means the metric was not available, so it counts for neither energy nor coverage.
    """

    start: datetime
    end: datetime
    kw: Decimal | None


@dataclass(frozen=True)
class Commitment:
    user_offer_id: str
    accepted_at: datetime
    window_start: datetime
    window_end: datetime
    capacity_kwh: Decimal


@dataclass(frozen=True)
class Allocation:
    metered_kwh: Decimal  # attributed + excess, rounded to 3 decimals
    attributed_kwh: Decimal
    excess_kwh: Decimal
    coverage_ratio: Decimal


def _hours(delta: timedelta) -> Decimal:
    return Decimal(delta // timedelta(microseconds=1)) / HOUR


def attribute(
    intervals: list[MeterInterval], commitments: list[Commitment]
) -> dict[str, Allocation]:
    """FIFO attribution of metered energy to overlapping commitments on one site and metric.

    Each time slice's energy (kW x overlapped hours, uniform within an interval) goes to the
    earliest-accepted (accepted_at, then user_offer_id) unfilled commitment whose window covers
    the slice, overflowing to the next one. Energy left once every covering commitment is full is
    excess, recorded on the earliest covering commitment and never charged here.
    """
    available = [item for item in intervals if item.kw is not None]
    ordered = sorted(commitments, key=lambda c: (c.accepted_at, c.user_offer_id))
    edges = sorted(
        {edge for item in available for edge in (item.start, item.end)}
        | {edge for c in ordered for edge in (c.window_start, c.window_end)}
    )
    remaining = {c.user_offer_id: c.capacity_kwh for c in ordered}
    attributed = {c.user_offer_id: ZERO for c in ordered}
    excess = {c.user_offer_id: ZERO for c in ordered}
    covered = {c.user_offer_id: timedelta(0) for c in ordered}
    for lower, upper in zip(edges, edges[1:], strict=False):
        sources = [
            item for item in available if item.start <= lower and item.end >= upper
        ]
        candidates = [
            c for c in ordered if c.window_start <= lower and c.window_end >= upper
        ]
        if not sources or not candidates:
            continue
        for c in candidates:
            covered[c.user_offer_id] += upper - lower
        energy = sum((item.kw for item in sources), ZERO) * _hours(upper - lower)
        for c in candidates:
            take = min(remaining[c.user_offer_id], energy)
            if take > 0:
                remaining[c.user_offer_id] -= take
                attributed[c.user_offer_id] += take
                energy -= take
            if energy <= 0:
                break
        if energy > 0:
            excess[candidates[0].user_offer_id] += energy
    result = {}
    for c in ordered:
        span = c.window_end - c.window_start
        ratio = (
            min(Decimal(1), _hours(covered[c.user_offer_id]) / _hours(span))
            if span > timedelta(0)
            else ZERO
        )
        result[c.user_offer_id] = Allocation(
            metered_kwh=kwh(attributed[c.user_offer_id] + excess[c.user_offer_id]),
            attributed_kwh=attributed[c.user_offer_id],
            excess_kwh=excess[c.user_offer_id],
            coverage_ratio=ratio,
        )
    return result


VERBS = {
    "consume": ("use", "used", "from the grid"),
    "export": ("feed", "delivered", "into the grid"),
}


def penalty_rule_text(
    offer_type: str,
    energy_kwh: Decimal,
    window_minutes: int,
    penalty_type: str,
    penalty_value: Decimal,
    offer_price: Decimal,
) -> str:
    verb, done, where = VERBS[offer_type]
    target = f"{verb} less than {decimal_text(energy_kwh)} kWh"
    if offer_type == "export":
        target += f" {where}"
    condition = f"If you {target} within {window_text(window_minutes)}"
    if penalty_value == 0:
        paid = (
            "only pay for what you use"
            if offer_type == "consume"
            else ("are paid only for what you deliver")
        )
        return (
            f"There is no penalty: {condition[0].lower()}{condition[1:]}, you {paid}."
        )
    if penalty_type == "per_unfulfilled_kwh":
        return (
            f"{condition}, you pay {price_text(penalty_value)} RON "
            f"for each kWh not {done}."
        )
    if penalty_type == "percent_of_unfulfilled_value":
        per_kwh = offer_price * penalty_value / 100
        exact = per_kwh == per_kwh.quantize(Decimal("0.0001"))
        return (
            f"{condition}, you pay {decimal_text(penalty_value)}% of the offer value "
            f"of the energy not {done}"
            + (f" ({price_text(per_kwh)} RON per kWh)." if exact else ".")
        )
    return f"{condition}, you pay a flat {ron_text(bani(penalty_value))}."


def terms_text(
    offer_type: str,
    energy_kwh: Decimal,
    window_minutes: int,
    penalty_type: str,
    penalty_value: Decimal,
    offer_price: Decimal,
) -> str:
    verb, _, where = VERBS[offer_type]
    block = ron_text(bani(energy_kwh * offer_price))
    amount = decimal_text(energy_kwh)
    worst = ron_text(
        bani(penalty_ron(penalty_type, penalty_value, energy_kwh, offer_price))
    )
    if offer_type == "consume":
        deal = (
            f"Use {amount} kWh {where} within {window_text(window_minutes)} of accepting "
            f"at {price_text(offer_price)} RON/kWh ({block} for the full block)."
        )
        beyond = f"Energy beyond {amount} kWh is billed at your normal tariff."
    else:
        deal = (
            f"Feed {amount} kWh {where} within {window_text(window_minutes)} of accepting "
            f"at {price_text(offer_price)} RON/kWh (you receive {block} for the full block)."
        )
        beyond = f"Energy beyond {amount} kWh is paid at your normal export tariff."
    rule = penalty_rule_text(
        offer_type, energy_kwh, window_minutes, penalty_type, penalty_value, offer_price
    )
    return (
        f"{deal} {rule} The most you can pay as a penalty is {worst}. {beyond} "
        f"No penalty applies if your meter data for the window is incomplete or if the "
        f"distributor cancels the offer."
    )
