"""Local, idempotent enrichment of a SCENARIO demo database (`python -m backend enrich-demo`).

SYNTHETIC. Loads the 60-site city demo next to the nine provider sites, gives staff and customer
accounts explicit demo grants, and adds mock contracts, offers, incidents, crews on the map and
technician agenda items. Never run on import; refuses unless a scenario clock is active.
Every step is guarded so a second run changes nothing.
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.clock import clock_state
from backend.customer import create_request, store_contract
from backend.customer_models import Contract, SupportRequestCreate, TariffBand
from backend.db import Database, stamp
from backend.errors import ApiError
from backend.ingestion import ingest
from backend.models import Metric, User
from backend.offers import accept_offer, create_offer, publish_offer
from backend.offers_models import OfferDraft
from backend.offers_worker import settle_due
from backend.ops import _create_assignment, log_incident, open_incident, profile_source
from backend.provisioning import set_password
from backend.security import hash_password
from backend.seed import (
    NO_TELEMETRY,
    PV_MISSING,
    PV_ONLY,
    SCENARIO_BANDS,
    SCENARIO_CONTRACT_FROM,
    SOC_ONLY,
    STALE,
    seed_demo,
)

LOCAL = ZoneInfo("Europe/Bucharest")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/O/1/l/I look-alikes, no symbols
ALL_AREAS = [f"sector-{n}" for n in range(1, 7)] + ["ilfov"]
H2 = "provider-4d119fc90c8c2cf7b55b314c"
F1 = "provider-e2f35075482123a2267dd143"
SUPERVISOR = User(
    user_id="scenario-supervisor",
    username="elena",
    role="supervisor",
    account_type="home",
)
PROVENANCE = "SYNTHETIC enrichment (python -m backend enrich-demo); fictional crews, depots and data"


def readable_password() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(16))


def _local(day: str, clock: str) -> datetime:
    hours, minutes = map(int, clock.split(":"))
    year, month, date = map(int, day.split("-"))
    return datetime(year, month, date, hours, minutes, tzinfo=LOCAL).astimezone(UTC)


# ---------------------------------------------------------------- compact telemetry at the clock


def _compact_profiles() -> dict[str, dict]:
    return {p["site_id"]: p for p in profile_source()["profiles"]}


def _compact_record(site_id: str, profile: dict, start: datetime) -> dict:
    from backend.energy_views import profile_day

    local = start.astimezone(LOCAL)
    production, consumption = profile_day(
        profile["installed_kwp"],
        profile["segment"],
        profile.get("business_type"),
        site_id,
        local.date(),
    )
    pv = production[local.hour]
    load = consumption[local.hour]
    direct = min(pv, load)

    def reading(value, requirement="optional", boundary="ac", unit="kW"):
        return {
            "value": round(value, 3),
            "unit": unit,
            "requirement": requirement,
            "boundary": boundary,
        }

    measurements = {
        "pv_power": reading(pv, "mandatory"),
        "grid_import": reading(load - direct),
        "grid_export": reading(pv - direct),
    }
    if site_id == PV_ONLY:
        measurements = {"pv_power": measurements["pv_power"]}
    if site_id == PV_MISSING:
        measurements["pv_power"] = {
            "value": None,
            "unit": "kW",
            "requirement": "mandatory",
            "availability": "missing",
            "boundary": "ac",
        }
    if site_id in (SOC_ONLY, "s3-02"):
        measurements["battery_soc"] = reading(
            62 + 8 * ((start.hour % 3) - 1), boundary="not_applicable", unit="%"
        )
    if site_id == "s3-02":
        measurements["battery_charge"] = reading(max(0.0, pv - load) * 0.5)
        measurements["battery_discharge"] = reading(0.0)
    end = start + timedelta(minutes=15)
    return {
        "schema_version": "1.0",
        "record_id": f"{site_id}-{end:%Y%m%dT%H%M}",
        "site_id": site_id,
        "device_id": f"meter-{site_id}",
        "source_id": "synthetic-demo",
        "interval_start": stamp(start).replace("+00:00", "Z"),
        "interval_end": stamp(end).replace("+00:00", "Z"),
        "received_at": stamp(end).replace("+00:00", "Z"),
        "source_mode": "synthetic",
        "raw_record_ref": f"enrich://scenario/{site_id}/{end:%Y%m%dT%H%M}",
        "measurements": measurements,
        "quality_flags": [],
        "vendor_codes": [],
    }


def load_compact_telemetry(database: Database, connection, now: datetime) -> int:
    """Eight 15-minute synthetic records per compact site ending at the scenario clock."""
    floor = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)
    written = 0
    for site_id, profile in _compact_profiles().items():
        if site_id == NO_TELEMETRY:
            continue
        last = floor - timedelta(minutes=75) if site_id == STALE else floor
        for step in range(8):
            start = last - timedelta(minutes=15 * (step + 1))
            if connection.execute(
                "SELECT 1 FROM telemetry WHERE site_id=? AND interval_start<? AND interval_end>?",
                (site_id, stamp(start + timedelta(minutes=15)), stamp(start)),
            ).fetchone():
                continue
            ingest(
                database,
                _compact_record(site_id, profile, start),
                "enrich-demo",
                within=connection,
            )
            written += 1
    return written


# ---------------------------------------------------------------- accounts, contracts


def _tou_contract(kwp: float | None) -> Contract:
    return Contract(
        supplier="Demo Supply (fictional)",
        pricing="time_of_use",
        import_price_ron_kwh=1.28,
        export_price_ron_kwh=0.45,
        installed_kwp=kwp,
        export_compensation="payment",
        bands=[
            TariffBand(
                band_id=band_id,
                label=label,
                days=days,
                start_minute=start,
                end_minute=end,
                import_rate_ron_kwh=rate,
                export_value_ron_kwh=value,
            )
            for band_id, label, days, start, end, rate, value in SCENARIO_BANDS
        ],
    )


def _fixed_contract(kwp: float | None, price: float) -> Contract:
    return Contract(
        supplier="Demo Supply (fictional)",
        pricing="fixed",
        import_price_ron_kwh=price,
        export_price_ron_kwh=0.45,
        installed_kwp=kwp,
        export_compensation="payment",
    )


def grant_areas_and_accounts(database: Database, connection) -> dict[str, str]:
    """Supervisor and dispatcher cover every area; `victor` is the Ilfov area manager."""
    created = {}
    for user_id in ("scenario-supervisor", "scenario-dispatcher"):
        for area in ALL_AREAS:
            connection.execute(
                "INSERT OR IGNORE INTO user_areas VALUES (?,?)", (user_id, area)
            )
    if not connection.execute("SELECT 1 FROM users WHERE username='victor'").fetchone():
        secret = readable_password()
        connection.execute(
            "INSERT INTO users(user_id,username,password_hash,role,account_type) "
            "VALUES ('victor','victor',?, 'supervisor','home')",
            (hash_password(secret),),
        )
        created["victor"] = secret
    connection.execute("INSERT OR IGNORE INTO user_areas VALUES ('victor','ilfov')")
    return created


def add_contracts(connection, now: datetime):
    plans = (
        (H2, "h2-resident", _fixed_contract(8.1, 1.30)),
        ("s6-01", "customer", _fixed_contract(6.0, 1.25)),
        ("s4-01", "other-customer", _fixed_contract(5.0, 1.32)),
        ("s3-06", "business-customer", _tou_contract(30.0)),
    )
    for site_id, user_id, contract in plans:
        if (
            connection.execute(
                "SELECT 1 FROM contracts WHERE site_id=?", (site_id,)
            ).fetchone()
            or not connection.execute(
                "SELECT 1 FROM sites WHERE site_id=?", (site_id,)
            ).fetchone()
        ):
            continue
        store_contract(
            connection,
            site_id,
            contract,
            user_id,
            now,
            effective_from=SCENARIO_CONTRACT_FROM,
        )


# ---------------------------------------------------------------- crews on the map


def crew_depots(connection, now: datetime):
    """A fictional depot for every crew without one, so the ops map can show crew markers."""
    areas = profile_source()["areas"]
    for index, crew in enumerate(
        connection.execute("SELECT * FROM crews ORDER BY crew_id").fetchall()
    ):
        if connection.execute(
            "SELECT 1 FROM crew_profiles WHERE crew_id=?", (crew["crew_id"],)
        ).fetchone():
            continue
        area = areas.get(crew["area_id"])
        if not area:
            continue
        node = f"depot-{crew['crew_id']}"
        label = f"Fictional depot, {area['label']}"
        connection.execute(
            "INSERT OR IGNORE INTO planning_nodes VALUES (?,?,?,?,?,1)",
            (
                node,
                None,
                round(area["latitude"] + 0.004 * ((index % 3) - 1), 5),
                round(area["longitude"] + 0.005 * ((index % 2) - 0.5), 5),
                label,
            ),
        )
        connection.execute(
            "INSERT INTO crew_profiles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                crew["crew_id"],
                "field",
                "PPC field service (fictional)",
                json.dumps(["customer_installation_service", "distributor_service"]),
                json.dumps([]),
                json.dumps([]),
                json.dumps([crew["area_id"]]),
                node,
                stamp(now),
                "last reported base depot (fictional), not live GPS",
                "city-demo",
                PROVENANCE,
            ),
        )
        for day in (
            "2026-07-17",
            "2026-07-18",
            "2026-07-19",
            "2026-07-20",
            "2026-07-21",
        ):
            connection.execute(
                "INSERT OR IGNORE INTO crew_shifts VALUES (?,?,?,?)",
                (
                    crew["crew_id"],
                    stamp(_local(day, "08:00")),
                    stamp(_local(day, "18:00")),
                    json.dumps(
                        [[stamp(_local(day, "12:30")), stamp(_local(day, "13:00"))]]
                    ),
                ),
            )


# ---------------------------------------------------------------- incidents and agenda

# (id, site, tier, family, title, evidence, minutes before the clock, crew, state)
# state: open | assigned | en_route | resolved
CITY_INCIDENTS = (
    (
        "enrich-inc-s2-01-smoke",
        "s2-01",
        "P0",
        "Temperature",
        "Safety: customer reports a burning smell near the inverter",
        "Customer phoned the call centre; keep clear of the equipment until a team arrives.",
        22,
        "sector-2-solar-care",
        "en_route",
    ),
    (
        "enrich-inc-s5-02-battery",
        "s5-02",
        "P1",
        "Battery",
        "Battery module over-temperature warning",
        "Synthetic rule: battery temperature above its demo threshold for 3 intervals.",
        55,
        "sector-5-solar-care",
        "assigned",
    ),
    (
        "enrich-inc-s4-03-production",
        "s4-03",
        "P1",
        "Production",
        "Production 40 % below the expectation band",
        "Synthetic rule: PV power well below the demo expectation for a clear morning.",
        75,
        None,
        "open",
    ),
    (
        "enrich-inc-s1-04-voltage",
        "s1-04",
        "P2",
        "Voltage",
        "Voltage above the demo band on one phase",
        "Synthetic rule: phase voltage above its configured band.",
        48,
        "sector-1-solar-care",
        "assigned",
    ),
    (
        "enrich-inc-ilfov-03-monitoring",
        "ilfov-03",
        "P2",
        "Telemetry",
        "Monitoring gateway offline",
        "No telemetry from the gateway for two reporting intervals.",
        95,
        None,
        "open",
    ),
    (
        "enrich-inc-ilfov-06-production",
        "ilfov-06",
        "P1",
        "Production",
        "Production drop on an Ilfov business site",
        "Synthetic rule: PV power below band while a neighbouring site produces normally.",
        38,
        "ilfov-field-service",
        "en_route",
    ),
    (
        "enrich-inc-s3-05-request",
        "s3-05",
        "P2",
        "Local issue",
        "Customer request: panel dirt after construction work",
        "Customer asks for a cleaning visit.",
        130,
        None,
        "open",
    ),
    (
        "enrich-inc-s6-05-battery",
        "s6-05",
        "P3",
        "Battery",
        "Battery state of charge not reported",
        "Optional battery metric missing for 6 hours; no safety impact.",
        180,
        None,
        "open",
    ),
    (
        "enrich-inc-s2-05-done",
        "s2-05",
        "P2",
        "Voltage",
        "Voltage flag cleared after tap adjustment",
        "Resolved by the Sector 2 crew.",
        300,
        "sector-2-solar-care",
        "resolved",
    ),
    (
        "enrich-inc-s4-09-done",
        "s4-09",
        "P3",
        "Telemetry",
        "Gateway reboot restored the feed",
        "Resolved remotely after a reboot.",
        420,
        "sector-4-solar-care",
        "resolved",
    ),
)


def _incident(connection, dispatcher: str, now: datetime, spec):
    incident_id, site_id, tier, family, title, evidence, minutes, crew, state = spec
    if not connection.execute(
        "SELECT 1 FROM sites WHERE site_id=?", (site_id,)
    ).fetchone():
        return
    opened = stamp(now - timedelta(minutes=minutes))
    created = open_incident(
        connection,
        incident_id=incident_id,
        site_id=site_id,
        title=title,
        family=family,
        tier=tier,
        source="synthetic_replay",
        evidence=f"{evidence} Synthetic demo data.",
        actor="system",
        detail="Opened by the synthetic enrichment",
        now=opened,
    )
    if created is None or state == "open" or crew is None:
        return
    _assign(connection, dispatcher, now, incident_id, crew, state, minutes)


def _assign(connection, dispatcher, now, incident_id, crew, state, minutes_ago=30):
    if connection.execute(
        "SELECT 1 FROM assignments WHERE incident_id=? AND crew_id=?",
        (incident_id, crew),
    ).fetchone():
        return
    user = User(user_id=dispatcher, username="andrei", role="dispatcher")
    start = now + timedelta(minutes=20)
    status = {
        "assigned": "assigned",
        "en_route": "team_sent",
        "resolved": "completed",
    }[state]
    if state == "resolved":
        start = now - timedelta(minutes=minutes_ago - 20)
    elif state == "en_route":
        start = now - timedelta(minutes=10)
    assignment_id = _create_assignment(
        connection,
        incident_id,
        crew,
        "dispatch",
        status,
        user,
        stamp(now - timedelta(minutes=minutes_ago // 2)),
        stamp(start),
        stamp(start + timedelta(hours=1)),
    )
    connection.execute(
        "UPDATE assignments SET activity='field_visit', progress=?, completed_at=? "
        "WHERE assignment_id=?",
        (
            "en_route" if state == "en_route" else None,
            stamp(start + timedelta(minutes=50)) if state == "resolved" else None,
            assignment_id,
        ),
    )
    incident_status = {
        "assigned": "assigned",
        "en_route": "team_sent",
        "resolved": "resolved",
    }[state]
    connection.execute(
        "UPDATE incidents SET status=?, updated_at=? WHERE incident_id=?",
        (incident_status, stamp(now), incident_id),
    )
    log_incident(
        connection,
        incident_id,
        "andrei",
        {"assigned": "assigned", "en_route": "team_sent", "resolved": "resolved"}[
            state
        ],
        f"Dispatcher assigned {crew}"
        + ("; resolved on site" if state == "resolved" else ""),
        stamp(now),
    )


# Technician agenda (provider-site crews). (incident, site key, tier, family, title, evidence,
# crew, local day, start, end, state, activity, kind)
AGENDA = (
    (
        "enrich-ag-f2-battery",
        "provider-89c51a61990828f2e6027c6f",
        "P1",
        "Battery",
        "Battery module temperature check",
        "BMS reports a module temperature trend above the demo comfort band; visit to inspect airflow and cabling.",
        "scn-battery-service",
        "2026-07-17",
        "09:00",
        "10:30",
        "assigned",
        "battery_inspection",
        "dispatch",
    ),
    (
        "enrich-ag-h3-comms",
        "provider-3cf3aeacbce278b4207de1bd",
        "P2",
        "Telemetry",
        "Inverter communication reset",
        "Intermittent reporting from the Huawei inverter; reset the dongle and confirm the feed.",
        "scn-battery-service",
        "2026-07-17",
        "11:30",
        "12:30",
        "assigned",
        "field_visit",
        "dispatch",
    ),
    (
        "enrich-ag-s2-strings",
        "provider-5f758c0e29543b7dcf57a7e6",
        "P2",
        "Production",
        "PV string inspection",
        "Underperformance versus the neighbouring array; check connectors and shading.",
        "scn-pv-om",
        "2026-07-17",
        "14:30",
        "16:00",
        "assigned",
        "field_visit",
        "dispatch",
    ),
    (
        "enrich-ag-f1-bms-done",
        "provider-e2f35075482123a2267dd143",
        "P2",
        "Battery",
        "Battery BMS firmware check",
        "Routine BMS check completed; no fault found.",
        "scn-battery-service",
        "2026-07-16",
        "10:00",
        "11:00",
        "resolved",
        "battery_inspection",
        "dispatch",
    ),
    (
        "enrich-ag-s1-survey-done",
        "provider-65a9712309ce0c5bd8397af2",
        "P3",
        "Local issue",
        "Cleaning and shading survey",
        "Panels cleaned; tree shading noted for the customer.",
        "scn-pv-om",
        "2026-07-16",
        "14:00",
        "15:30",
        "resolved",
        "field_visit",
        "dispatch",
    ),
    (
        "enrich-ag-h1-remote",
        "provider-d97b13196637185888be23c1",
        "P2",
        "Telemetry",
        "Remote review of a monitoring gap",
        "Monitoring gap on H1; review the provider portal and the collector.",
        "scn-remote-desk",
        "2026-07-17",
        "10:00",
        "10:30",
        "assigned",
        "remote_review",
        "meeting",
    ),
    (
        "enrich-ag-s3-remote",
        "provider-ee134e1a6c0c4c87f7e5a752",
        "P3",
        "Telemetry",
        "Remote check of battery limits data",
        "Battery limits are not reported; confirm with the provider documentation.",
        "scn-remote-desk",
        "2026-07-17",
        "11:00",
        "11:30",
        "assigned",
        "remote_review",
        "meeting",
    ),
)


def agenda_items(connection, dispatcher: str, now: datetime):
    user = User(user_id=dispatcher, username="andrei", role="dispatcher")
    for (
        incident_id,
        site_id,
        tier,
        family,
        title,
        evidence,
        crew,
        day,
        begin,
        finish,
        state,
        activity,
        kind,
    ) in AGENDA:
        if not connection.execute(
            "SELECT 1 FROM crews WHERE crew_id=?", (crew,)
        ).fetchone():
            continue
        start, end = _local(day, begin), _local(day, finish)
        created = open_incident(
            connection,
            incident_id=incident_id,
            site_id=site_id,
            title=title,
            family=family,
            tier=tier,
            source="synthetic_replay",
            evidence=f"{evidence} Synthetic demo data.",
            actor="system",
            detail="Opened by the synthetic enrichment",
            now=stamp(min(now, start) - timedelta(hours=18)),
        )
        if created is None:
            continue
        done = state == "resolved"
        assignment_id = _create_assignment(
            connection,
            incident_id,
            crew,
            kind,
            "completed"
            if done
            else ("meeting_scheduled" if kind == "meeting" else "assigned"),
            user,
            stamp(min(now, start) - timedelta(hours=12)),
            stamp(start),
            stamp(end),
        )
        connection.execute(
            "UPDATE assignments SET activity=?, completed_at=?, progress=? WHERE assignment_id=?",
            (
                activity,
                stamp(end) if done else None,
                "done" if done else None,
                assignment_id,
            ),
        )
        connection.execute(
            "UPDATE incidents SET status=?, updated_at=? WHERE incident_id=?",
            (
                "resolved"
                if done
                else ("meeting_scheduled" if kind == "meeting" else "assigned"),
                stamp(now),
                incident_id,
            ),
        )
        log_incident(
            connection,
            incident_id,
            "andrei",
            "resolved" if done else "assigned",
            f"{activity.replace('_', ' ')} {'completed' if done else 'scheduled'} for {crew}",
            stamp(now),
        )


WEBM_DEMO = bytes.fromhex(
    "1a45dfa3a34286810142f7810142f2810442f381084282847765626d"
) + bytes(2048)


def support_video_visit(database: Database, media_dir: Path, now: datetime):
    """One customer request with a small WebM video, linked to mihai's crew by an assignment."""
    from backend.media import store_media

    maria = User(
        user_id="h2-resident", username="maria", role="customer", account_type="home"
    )
    description = "Inverter shows an orange light and a fan noise since this morning. Video attached."
    with database.connect() as connection:
        existing = connection.execute(
            "SELECT request_id FROM support_requests WHERE user_id='h2-resident' "
            "AND description=?",
            (description,),
        ).fetchone()
        if existing:
            request_id = existing["request_id"]
        else:
            request_id = create_request(
                database,
                connection,
                maria,
                SupportRequestCreate(
                    site_id=H2, request_type="device-warning", description=description
                ),
                "enrich-demo",
            ).request_id
            earlier = stamp(now - timedelta(hours=3))
            connection.execute(
                "UPDATE support_requests SET created_at=?, updated_at=? WHERE request_id=?",
                (earlier, earlier, request_id),
            )
            connection.execute(
                "UPDATE incidents SET created_at=?, updated_at=? WHERE support_request_id=?",
                (earlier, earlier, request_id),
            )
    with database.connect() as connection:
        has_media = connection.execute(
            "SELECT 1 FROM support_media WHERE request_id=?", (request_id,)
        ).fetchone()
        if not has_media:
            store_media(
                database,
                connection,
                maria,
                request_id,
                "inverter-light.webm",
                "video/webm",
                WEBM_DEMO,
                media_dir,
                30 * 1024 * 1024,
                "enrich-demo",
            )
    with database.connect() as connection:
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE support_request_id=?",
            (request_id,),
        ).fetchone()["incident_id"]
        if connection.execute(
            "SELECT 1 FROM assignments WHERE incident_id=?", (incident,)
        ).fetchone():
            return
        user = User(user_id="scenario-dispatcher", username="andrei", role="dispatcher")
        assignment_id = _create_assignment(
            connection,
            incident,
            "scn-battery-service",
            "dispatch",
            "assigned",
            user,
            stamp(now),
            stamp(_local("2026-07-17", "16:00")),
            stamp(_local("2026-07-17", "17:00")),
        )
        connection.execute(
            "UPDATE assignments SET activity='site_visit' WHERE assignment_id=?",
            (assignment_id,),
        )
        connection.execute(
            "UPDATE incidents SET status='assigned', updated_at=? WHERE incident_id=?",
            (stamp(now), incident),
        )
        log_incident(
            connection,
            incident,
            "andrei",
            "assigned",
            "Dispatcher reviewed the customer's video and scheduled a site visit",
            stamp(now),
        )


# ---------------------------------------------------------------- offers


def _offer_exists(connection, title: str, area: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM offers WHERE title=? AND area_id=?", (title, area)
        ).fetchone()
    )


def publish_demo_offers(database: Database, now: datetime):
    expires = now + timedelta(days=4)
    plans = (
        (
            "consume",
            "Midday solar surplus",
            "3",
            "0.85",
            120,
            "per_unfulfilled_kwh",
            "0.3",
        ),
        (
            "export",
            "Evening peak support",
            "4",
            "0.78",
            120,
            "percent_of_unfulfilled_value",
            "20",
        ),
    )
    with database.connect() as connection:
        # Only areas where a customer account has a site can have an audience (Ilfov has none).
        areas = [
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT s.area_id FROM users u JOIN user_sites us ON us.user_id=u.user_id "
                "JOIN sites s ON s.site_id=us.site_id WHERE u.role='customer' "
                "AND s.area_id IS NOT NULL ORDER BY s.area_id"
            )
        ]
    for area in areas:
        for kind, title, energy, price, window, penalty, value in plans:
            label = f"{title} ({area})"
            with database.connect() as connection:
                if _offer_exists(connection, label, area):
                    continue
                draft = OfferDraft(
                    type=kind,
                    title=label,
                    energy_kwh=energy,
                    offer_price_ron_per_kwh=price,
                    window_minutes=window,
                    penalty_type=penalty,
                    penalty_value=value,
                    offer_expires_at=expires,
                    area_id=area,
                )
                detail = create_offer(
                    database, connection, SUPERVISOR, draft, "enrich-demo", now
                )
            with database.connect() as connection:
                publish_offer(
                    database,
                    connection,
                    SUPERVISOR,
                    detail.offer_id,
                    "enrich-demo",
                    now,
                )


def settled_offers(database: Database, now: datetime, settings) -> int:
    """One historical consume offer per scenario customer: accepted on 16 July, settled now."""
    from backend import bridge

    published = datetime(2026, 7, 16, 14, 0, tzinfo=UTC)
    accepted = datetime(2026, 7, 16, 17, 0, tzinfo=UTC)
    window_end = accepted + timedelta(minutes=120)
    count = 0
    people = (
        ("h2-resident", "maria", H2, "sector-1"),
        ("laundry-owner", "albert", F1, "sector-1"),
    )
    for user_id, username, site_id, area in people:
        title = f"Evening shift ({username}, settled demo)"
        with database.connect() as connection:
            if _offer_exists(connection, title, area) or window_end > now:
                continue
            metered = bridge.meter_series(
                connection, site_id, Metric.grid_import, accepted, window_end
            ).energy_kwh()
            if not metered or metered < 0.5:
                continue
            energy = max(0.5, int(metered * 0.7 * 2) / 2)
            draft = OfferDraft(
                type="consume",
                title=title,
                energy_kwh=str(energy),
                offer_price_ron_per_kwh="0.90",
                window_minutes=120,
                penalty_type="per_unfulfilled_kwh",
                penalty_value="0.3",
                offer_expires_at=published + timedelta(days=1),
                area_id=area,
                target_mode="clients",
                target_user_ids=[user_id],
            )
            detail = create_offer(
                database, connection, SUPERVISOR, draft, "enrich-demo", published
            )
            offer_id = detail.offer_id
        with database.connect() as connection:
            publish_offer(
                database, connection, SUPERVISOR, offer_id, "enrich-demo", published
            )
        customer = User(user_id=user_id, username=username, role="customer")
        with database.connect() as connection:
            accept_offer(
                database,
                connection,
                customer,
                offer_id,
                site_id,
                f"enrich-settled-{username}",
                "enrich-demo",
                accepted,
                5,
            )
        count += 1
    if count:
        settle_due(database, now, settings)
    return count


# ---------------------------------------------------------------- logins file


CITY_ACCOUNTS = (
    ("customer", "Home customer, site s6-01 (Sector 6)", "/consumer"),
    ("other-customer", "Home customer, site s4-01 (Sector 4)", "/consumer"),
    ("business-customer", "Business customer, site s3-06 (Sector 3)", "/consumer"),
    ("dispatcher", "City demo dispatcher (Sector 6)", "/ops"),
    ("supervisor", "City demo manager, all areas", "/ops"),
    ("area-manager", "City demo area manager (Sector 6)", "/ops"),
    ("technician", "Technician, Sector 6 crew", "/ops"),
    *(
        (f"technician-{s}", f"Technician, {s} crew", "/ops")
        for s in ("s1", "s2", "s3", "s4", "s5", "ilfov")
    ),
)
MAIN_ACCOUNTS = (
    ("Albert, laundry owner (business customer, site F1)", "albert", "/consumer"),
    ("Maria, home customer (site H2)", "maria", "/consumer"),
    ("Andrei, PPC dispatcher (all 7 areas; can apply crew plans)", "andrei", "/ops"),
    ("Elena, PPC supervisor (all 7 areas; view only, cannot apply)", "elena", "/ops"),
    ("Victor, area manager (supervisor, Ilfov only)", "victor", "/ops"),
    ("Mihai, technician (battery crew + PV crew)", "mihai", "/ops"),
    ("Ana, technician (battery crew)", "ana", "/ops"),
    ("Radu, technician (PV maintenance crew)", "radu", "/ops"),
    ("Ioana, technician (remote desk)", "ioana", "/ops"),
)


def write_logins(directory: Path, credentials: dict[str, str]):
    lines = [
        "# Demo logins (local, synthetic, do not commit)",
        "",
        "App: http://127.0.0.1:8020",
        "",
        "| Person | Username | Password | Open |",
        "|---|---|---|---|",
    ]
    for person, username, open_at in MAIN_ACCOUNTS:
        lines.append(
            f"| {person} | `{username}` | `{credentials.get(username, '(unchanged)')}` | {open_at} |"
        )
    lines += [
        "",
        "## City demo accounts",
        "",
        "| Person | Username | Password | Open |",
        "|---|---|---|---|",
    ]
    for username, person, open_at in CITY_ACCOUNTS:
        lines.append(
            f"| {person} | `{username}` | `{credentials.get(username, '(unchanged)')}` | {open_at} |"
        )
    (directory / "LOGINS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def enrich_demo(database: Database, settings, *, allow_live: bool = False) -> dict:
    database.migrate()
    with database.connect() as connection:
        state = clock_state(connection)
    if state.mode != "scenario" and not allow_live:
        raise ApiError(
            409,
            "scenario_required",
            "enrich-demo only runs against a scenario database (python -m backend scenario start); "
            "pass --allow-live to override",
        )
    now = state.now
    directory = database.path.parent
    credentials_path = directory / "demo-credentials.json"
    credentials = (
        json.loads(credentials_path.read_text(encoding="utf-8"))
        if credentials_path.exists()
        else {}
    )

    def remember(accounts: dict[str, str]):
        """Persist new passwords at once so an interrupted run never loses them."""
        credentials.update(accounts)
        if accounts:
            credentials_path.write_text(
                json.dumps(credentials, indent=2) + "\n", encoding="utf-8"
            )

    new_accounts = seed_demo(database, None, as_of=now)
    # Readable passwords (no look-alike characters) for every account this run created.
    for username in list(new_accounts):
        new_accounts[username] = readable_password()
        set_password(database, username, new_accounts[username])
    remember(new_accounts)
    with database.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        created = grant_areas_and_accounts(database, connection)
        new_accounts.update(created)
        remember(created)
        telemetry = load_compact_telemetry(database, connection, now)
        add_contracts(connection, now)
        crew_depots(connection, now)
        for spec in CITY_INCIDENTS:
            _incident(connection, "scenario-dispatcher", now, spec)
        agenda_items(connection, "scenario-dispatcher", now)
        from backend.dispatch import bump

        bump(connection, "demo.enriched", "city-demo", now)
    support_video_visit(database, settings.media_dir, now)
    publish_demo_offers(database, now)
    settled = settled_offers(database, now, settings)
    from backend.dispatch import run_correlation

    correlation = run_correlation(database)
    write_logins(directory, credentials)
    with database.connect() as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "sites",
                "site_profiles",
                "telemetry",
                "incidents",
                "assignments",
                "crews",
                "crew_profiles",
                "offers",
                "user_offers",
                "contracts",
                "support_requests",
                "users",
            )
        }
    return {
        "new_accounts": sorted(new_accounts),
        "telemetry_records_written": telemetry,
        "settled_offers_created": settled,
        "correlation": {
            k: correlation.get(k) for k in ("opened", "updated", "recovered")
        },
        "counts": counts,
    }
