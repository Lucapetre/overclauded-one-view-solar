# Component source notes: feasibility gate and evidence matrix (meters, batteries, weather)

Research date: **15 November 2026**. Only public documentation was used. Nothing was logged into, no
credentials were used and no device or vendor API was called. Vendor PDF/XLSX files were read locally for
verification and are **not** stored in this repository. They are cited below.

The machine-readable version of this file is `config/component_evidence.yaml`. Generators and profiles must
take their field allowlist from that file. A field that is not listed there is unavailable.

All component values in this repository are **synthetic**. "Documented" means only that a public vendor
document describes the field. It does not prove that PPC has permission, a working connection or a live
integration. The access status of every profile is therefore *documented, simulated for demo* or
*not established*.

**Equipment reference sheet.** The product owner's sheet (*Fișă tehnică de referință*, transcribed in the
planning brief) is a **reference, not proof**. It does not establish legal obligations, universal vendor
support or access rights. Its inspection-ownership statements (DO vs ANRE technicians) are kept as
configurable context only.

Evidence status vocabulary: **documented** (stated in the pinned document), **inferred** (our reading or
configuration where the document is silent; stays visible in provenance), **explicitly simulated** (our own
configuration, e.g. TOA5 column names). Requirement classes are the existing three:
`integration_required`, `vendor_response_required` and `optional`. Legal references are kept separately
(section 13).

## 1. Gate outcomes at a glance

| Profile id | Outcome | One-line reason |
|---|---|---|
| `m1_schneider_iem3255_modbus` | **include** | DOCA0005EN-16 documents iEM3255 registers, types, units, the register/address rule and non-resettable totals. Word order is not stated, so it is configured (inferred). |
| `m2_fronius_smart_meter_solar_api` | **narrow** | The official PDF rev 021-15052025 documents the nesting, the channels per meter model and location-dependent signs. Meter channel units are not tabulated (inferred). Phase currents are unsigned on the 63A-3. |
| `m3_shelly_pro3em_rpc` | **include** | The official EM/EMData pages document keys, units, errors, CT `reverse` and `ResetCounters`. The sign of `act_power` and the unit of `total_act_power` are inferred. |
| `b1_victron_gx_battery_modbus` | **narrow** | Register list 3.81 (Rev 54) was retrieved and verified. int32 power is dropped because its word order is not documented. BMS limits exist only for CAN-bus BMS / Lynx NG. |
| `b2_solaredge_storagedata` | **narrow** | The official PDF was **unreachable** (HTTP 403 bot challenge). Only the fields pinned by the repository's 2026-11-14 review (R7) are kept. The `batteryState` labels are not established. |
| `b3_enphase_battery_telemetry` | **exclude** | The endpoint is documented, but no accessible published response schema or interval semantics exist, and there is no authorized sample. |
| `w1_imt_si_rs485tc` | **include** | The Modbus spec (January 2026, FW 2.03) and the selection table confirm registers 0/7/8, their types and gains, and the zero return for unsupported registers. |
| `w2_kipp_smp10x_modbus` | **include** | Manual 0374214 \| 02-0326 (data model 108) gives PDU addresses, S16 types, the scale-factor rule, body temperature and status bits. |
| `w3_campbell_toa5_station` | **include** | The TOA5 four-row header, TIMESTAMP/RECORD and processing descriptors are documented. Column names are our configuration. NAN is configured as the missing-value token. |

Delivered datasets: **meters 3, batteries 2 (both narrowed), weather 3 = 8 of 9**. They are parsed by
one shared engine configured through `config/component_profiles.yaml`; Enphase has no generated native
payload or adapter. These are documented acquisition paths exercised with synthetic local files, not
eight live vendor connections.

## 2. Corrections and refinements to the master-spec assumptions

| Item | Master spec said | Verified |
|---|---|---|
| IMT spec version | "January 2025 Modbus specification" | The currently hosted sheet is dated **January 2026** and covers **FW 2.03** (plus 1.51–1.55). Registers 7/8 need **FW ≥ 1.53**. The register 0 range is 0…1500 W/m², or 0…1400 up to FW 1.52. |
| IMT register numbering | "register 0 / 7 / 8" | Correct. The sheet uses "Register n" only. We treat n as the protocol (PDU) address (inferred: "Register 0" cannot be a 1-based number). |
| Schneider Int64 | "Int64" | The register table says Int64 and the energy text says "signed 64-bit integer", but the manual's unit table describes Int64 as "64 bit unsigned integer" (an inconsistency inside the manual). We decode as signed, expect ≥ 0 and flag negative values. |
| Schneider word order | (not stated) | **Not documented** in DOCA0005EN-16. It is configured as high word first and marked inferred. |
| Schneider 3208 export | applicable | Applicable to iEM3255. The note "Not applicable for iEM3150 / iEM3250 / iEM3350" excludes only the x50 models. |
| Schneider zero-based addresses | "differ" | Address = register − 1. 3060→0x0BF3 (3059), 3028/3030/3032→3027/3029/3031, 3110→0x0C25 (3109), 3204→0x0C83 (3203), 3208→0x0C87 (3207). |
| Fronius document | loxone PDF copy | The loxone mirror was unreachable (DNS). The **official Fronius-hosted** PDF 42,0410,2012,EN **021-15052025** was used. The repository's R6 cites 021-21012025 (Scribd mirror). |
| Fronius units | W / Wh | Not stated in the meter section. They are **inferred** from channel names and example magnitudes. |
| Fronius currents | "voltage/current subset" | `Current_AC_Phase_*` are **absolute values** on 63A-3/63A-1/50kA-3 ("only UL and TS meter provide directions"). |
| Fronius validity | — | `Visible` = 0 means "incomplete or outdated values", which is a documented quality gate. `Head.Timestamp` is the response time, not the time the data was queried. |
| Fronius on GEN24 | — | Availability: "Fronius GEN24/Tauro/Verto planned in 1.13". Do not pair the meter profile with a GEN24 site without further evidence. |
| Shelly sign | — | The EM page does not define the sign of `act_power`. The `total_act_power` unit is not given (per-phase values are [W]). Both are inferred. Pro 3EM must be in the **triphase** profile (FW ≥ 1.1.0). Monophase uses EM1/EM1Data. |
| Victron battery power | "power?" | Register 256 is int32 W and 258 is int16 W (an "older 16-bit variant"). We use **258** because the int32 word order is undocumented. |
| Victron limits | "if exposed" | 305–308 (max charge voltage, min discharge voltage, max charge/discharge current) are /Info paths of the battery service, marked "Not supported by all Victron products. Supported by third-party CAN.Bus batteries and Lynx NG". |
| Victron unit-id | "unit-id mapping" | Preferred **225** = CAN-bus BMS (device instance 512), but unit IDs have been **dynamic since Venus 2.60**, so they must be configured. |
| Kipp manual | URL `kippzonen.com/Download/1143/…` | That URL now returns the vendor "Resources" HTML page, which links the official CDN file *Operational_Manual_SMP10x_SMP22x_Smart_Pyranometers_V20.pdf* (0374214 \| 02-0326). |
| Campbell "Smp" | Avg/Min/Max/Smp | "Smp" appears in the LoggerNet TOA5 example row 4. The CR1000X help lists "Sample" without an abbreviation. Both are documented. TIMESTAMP labels the interval end. |
| Enphase | 15-min energy | Confirmed in prose only, with a maximum range of 7 days and a start within 2 years. **No schema**, so the profile is excluded. |
| SolarEdge | March 2026 PDF | **Not retrievable** in this phase, so the profile is narrowed to the fields pinned by the earlier R7 review. |

## 3. M1 — Schneider iEM3255, Modbus register snapshots — **include**

**Feasibility row**

- **Device:** Schneider Electric iEM3255 (iEM3200 series: CT inputs 1 A/5 A, VT inputs supported). The model table shows Modbus = yes, four-quadrant energy = yes and electrical measurements = yes for iEM3255 (p.15–16). Firmware is not pinned by the manual. The Present Firmware Version is in register 1637 and is declared in the asset registry. Accessories: external CTs (VTs optional) and an RS-485 link to a collector.
- **Acquisition:** a local documented read interface, Modbus RTU function 0x03 Read Holding Registers (p.56). It runs as a read-snapshot parser of raw 16-bit words. No Modbus network client is built.
- **Collector and permissions:** a site Modbus collector (simulated) adds the capture time and collector identity. Owner/network permission is not established.
- **Fields:** see the matrix. The native refresh rate is not specified. The chosen polling interval is 300 s. There is no vendor delay because the read is local.
- **Boundary:** configured. On the demo site the meter sits at the PCC with the source side toward the grid, so +P = import (p.120: "Energy delivered (imported) means positive real power flow (+P)").
- **Evidence:** DOCA0005EN-16, 05/2026, p.56 (table format: "register = address + 1"), p.62 (system registers), p.66–68 (meter data and energy), p.61 (partial reset command 2020), p.120 (power flow) and p.126 (diagnosis code 204).
- **Access status:** documented, simulated for demo.
- **Reset semantics:** "Total Energy (cannot be reset)" applies to 3204/3208. "Partial Active Energy Import" (3256) is resettable from the front panel, by digital input on iEM3255, or with command 2020. No partial export register exists, so the authoritative energy representation is the **Int64 Wh pair 3204/3208**. Float32 kWh 45100/45102 is a non-authoritative alternative. **Never inject a reset into 3204/3208.**
- **Invalid sentinel:** none documented. A non-finite Float32 is invalid under our rule.

**Field evidence matrix** (source: DOCA0005EN-16, 05/2026)

| Native | Register / address (hex) | Type | Signed | Scale | Native unit | Word order | Invalid | Canonical metric | Boundary | Aggregation | Page | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Total Active Power | 3060 / 3059 (0x0BF3) | Float32 | yes | 1 | kW | high word first* | none | grid_net_kw | configured (PCC) | instantaneous | 67 | optional | grid exchange view | documented (*inferred) |
| Active Power Phase 1/2/3 | 3054/3056/3058 / 3053/3055/3057 | Float32 | yes | 1 | kW | hw first* | none | phase_active_power_kw | configured | instantaneous | 66–67 | optional | phase sum check | documented |
| Voltage L1-N/L2-N/L3-N | 3028/3030/3032 / 3027/3029/3031 | Float32 | — | 1 | V | hw first* | none | phase_voltage_v | configured | instantaneous | 66 | optional | voltage evidence | documented |
| I1/I2/I3 | 3000/3002/3004 / 2999/3001/3003 | Float32 | — | 1 | A | hw first* | none | ac_current_a | configured | instantaneous | 66 | optional | phase detail | documented |
| Frequency | 3110 / 3109 (0x0C25) | Float32 | — | 1 | Hz | hw first* | none | grid_frequency_hz | configured | instantaneous | 67 | optional | context | documented |
| Total Active Energy Import | 3204 / 3203 (0x0C83), 4 words | Int64 | signed per text | 1 | Wh | hw first* | none | lifetime_grid_import_kwh | PCC | lifetime counter | 67 | optional | measured grid-energy verification | documented |
| Total Active Energy Export | 3208 / 3207 (0x0C87), 4 words | Int64 | signed per text | 1 | Wh | hw first* | none | lifetime_grid_export_kwh | PCC | lifetime counter | 67–68 | optional | measured grid-energy verification | documented |
| Energy Reset Date and Time | 3252 / 3251 | DATETIME (4 words) | — | — | — | DATETIME layout | — | (metadata) | — | state | 67 | optional | partial-reset audit | documented |
| Diagnostics error status | 45000 / 44999 (0xAFC7) | Bitmap | no | — | — | n/a | — | meter_status_raw | — | state | 62, 126 | optional | wiring/data-quality evidence (bit5 = code 204) | documented |

\* Word order: not stated in DOCA0005EN-16. It is configured and marked inferred. A fixture with the wrong word order must be flagged, not "repaired".

## 4. M2 — Fronius Smart Meter, Solar API GetMeterRealtimeData — **narrow**

**Feasibility row**

- **Device:** Fronius Smart Meter 63A-3 (article 43,0001,1473). Compatibility for the channel table: hw=0 and sw=2.7, or hw=1 and (sw=2.9 or sw=3.0). It is connected to a Fronius Datamanager/inverter serving Solar API V1. Endpoint availability: Fronius Hybrid "ALWAYS", Fronius Non Hybrid since 3.3.4-8, GEN24/Tauro/Verto "planned in 1.13", so it is **not paired with GEN24 sites**.
- **Acquisition:** a local documented read interface, `GET /solar_api/v1/GetMeterRealtimeData.cgi?Scope=System` (Scope=Device requires DeviceId 0..65535).
- **Collector and permissions:** a site LAN collector (simulated). LAN access is not established.
- **Fields:** see the matrix. The native rate is not specified. The chosen polling interval is 300 s. "Inactive channels are not included in the response and may vary depending on used metering device and software version" (4.8), so a missing optional channel is not a fault.
- **Boundary:** `Meter_Location_Current` must equal the registry boundary. 0 = grid interconnection point (primary, feed-in), 1 = load/consumption path (primary), 3 = external generator (secondary, multiple), 256–511 = subloads (secondary, unique). A mismatch is quarantined.
- **Sign** (4.8.6/4.8.7). Location 0: `PowerReal_P_Sum` + = consuming from grid, − = feeding in to grid. Location 1: + = producing power, − = normal consumption. Location 3: + = generation, − = consumption. Locations 256–511: + = load is producing power, − = normal consumption. Only location 0 maps to `grid_net_kw`.
- **Counters:** `EnergyReal_WAC_Sum_Consumed/Produced` are the meter-specific view. `EnergyReal_WAC_Plus/Minus_Absolute` are the system (Solar.web) view. At location 0, Consumed = import and Produced = export.
- **Times:** `Head.Timestamp` is "RFC3339 timestamp in localtime of the datalogger. This is the time the request was answered - NOT the time when the data was queried from the device." A per-device `TimeStamp` channel is mandatory for the 63A-3. Its epoch-seconds format is inferred from the example value 1561364909.
- **Evidence:** Fronius Solar API V1, 42,0410,2012,EN, revision 021-15052025, official Fronius host. Sections 4.8.1–4.8.8 (pp.45–48) and the common response header.
- **Access status:** documented, simulated for demo.
- **Narrowed because:** units are not tabulated for meter channels (W/Wh/V/A/Hz inferred), phase currents are absolute values on this model, and the TimeStamp format is inferred.

**Field evidence matrix** (path prefix `Body.Data.{DeviceId}.`; "m" = mandatory for 63A-3 in the 4.8.4 channel table)

| Native | Type | Signed | Unit | Invalid / quality | Canonical metric | Boundary | Aggregation | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| Details.Serial/Model/Manufacturer | string | — | — | — | identity | — | identity | vendor_response_required (m) | identity | documented |
| Meter_Location_Current | number | — | — | — | (boundary selector) | — | state | vendor_response_required (m) | direction resolution | documented |
| Enable | number | — | — | 0 = disabled | — | — | state | vendor_response_required (m) | quality | documented |
| Visible | number | — | — | **0 = incomplete or outdated values** | — | — | state | vendor_response_required (m) | quality gate | documented |
| TimeStamp | number | — | s epoch (inferred) | — | source time | — | measurement time | vendor_response_required (m) | time | documented key, inferred format |
| PowerReal_P_Sum | number | yes | W (inferred) | — | grid_net_kw (only at loc 0) | per location | instantaneous | vendor_response_required (m) | grid exchange | documented / unit inferred |
| PowerReal_P_Phase_1..3 | number | yes | W (inferred) | — | phase_active_power_kw | per location | instantaneous | vendor_response_required (m) | phase check | documented / unit inferred |
| EnergyReal_WAC_Sum_Consumed | number | no | Wh (inferred) | — | lifetime_grid_import_kwh (loc 0) | meter view | lifetime counter | vendor_response_required (m) | grid-energy verification | documented / unit inferred |
| EnergyReal_WAC_Sum_Produced | number | no | Wh (inferred) | — | lifetime_grid_export_kwh (loc 0) | meter view | lifetime counter | vendor_response_required (m) | grid-energy verification | documented / unit inferred |
| Voltage_AC_Phase_1..3 | number | — | V (inferred) | — | phase_voltage_v | location | instantaneous | vendor_response_required (m) | voltage evidence | documented / unit inferred |
| Current_AC_Phase_1..3 | number | **absolute** | A (inferred) | — | ac_current_a (magnitude only) | location | instantaneous | vendor_response_required (m) | magnitude only | documented |
| Frequency_Phase_Average | number | — | Hz (inferred) | — | grid_frequency_hz | location | instantaneous | vendor_response_required (m) | context | documented / unit inferred |
| Head.Timestamp | RFC3339 string | — | — | — | response time | — | response time | vendor_response_required | response time only | documented |
| Head.Status.Code | integer | — | — | ≠ 0 = problem | — | — | state | vendor_response_required | access failure | documented |

Do **not** copy the inverter `P_Grid`/`P_Load` assumptions from the existing PowerFlow profile into this endpoint.

## 5. M3 — Shelly Pro 3EM, Gen2 RPC — **include**

**Feasibility row**

- **Device:** Shelly Pro 3EM in the **triphase** profile (default). It exposes `em:0` and `emdata:0`. The monophase profile instead exposes 3× EM1/EM1Data and is not modelled. Profiles exist since FW 1.1.0, and the exact firmware is declared in the registry. Accessories: Shelly CTs. `ct_type` must be set, otherwise the device reports the error `ct_type_not_set`.
- **Acquisition:** a local documented read interface, RPC `EM.GetStatus {id:0}` and `EMData.GetStatus {id:0}`, as separate payloads. EMData stores one-minute records (device page). The instantaneous refresh rate is not stated. The chosen polling interval is 300 s. GetStatus carries no measurement timestamp, so the capture time belongs to the collector envelope.
- **Permissions:** LAN access and device authentication if enabled. Not established.
- **Boundary and CT orientation:** configured in the registry. `EM.SetConfig.reverse{a,b,c}` "Reverse CT measurement direction" (active power and energy, restart required) is a documented device setting. Ingestion **never auto-flips** an unexplained negative reading.
- **Sign:** not defined on the EM page. We infer that a negative `act_power` means the returned direction, consistent with the EMData "returned energy" wording. The directional counters `total_act` / `total_act_ret` (Wh) are documented and are the authoritative energy basis.
- **Reset:** `EMData.ResetCounters {id}` documents "Reset the total counters for the specified component". `EMData.DeleteAllData` also nullifies the perpetual counters. This is the **resettable counter for the known-reset defect case**.
- **Evidence:** Shelly Gen2 API docs, EM, EMData and Shelly Pro 3EM pages (page "Version 1.0", undated, accessed 2026-11-15).
- **Access status:** documented, simulated for demo.

**Field evidence matrix**

| Native (path) | Type | Signed | Unit | Invalid / errors | Canonical metric | Boundary | Aggregation | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| EM.GetStatus.total_act_power | number\|null | yes | W (inferred) | null | grid_net_kw | CT boundary | instantaneous | optional | grid exchange | documented key; unit & sign inferred |
| EM.GetStatus.{a,b,c}_act_power | number\|null | yes | W | null | phase_active_power_kw | CT boundary | instantaneous | optional | phase check, CT case | documented; sign inferred |
| EM.GetStatus.{a,b,c}_voltage | number\|null | — | V | null | phase_voltage_v | point | instantaneous | optional | voltage evidence | documented |
| EM.GetStatus.{a,b,c}_current | number\|null | — | A | null | ac_current_a | point | instantaneous | optional | detail | documented |
| EM.GetStatus.errors | array (if non-empty) | — | — | power_meter_failure, phase_sequence, ct_type_not_set | meter_status_raw | — | state | optional | native error evidence | documented |
| EM.GetStatus.{a,b,c}_errors | array (if non-empty) | — | — | out_of_range:active_power / apparent_power / voltage / current | meter_status_raw | — | state | optional | per-phase quality flag | documented |
| EMData.GetStatus.total_act | number | no | Wh | — | resettable_grid_import_kwh | CT boundary | resettable counter | optional | grid-energy verification, reset case | documented |
| EMData.GetStatus.total_act_ret | number | no | Wh | — | resettable_grid_export_kwh | CT boundary | resettable counter | optional | grid-energy verification | documented |
| EMData.GetStatus.{a,b,c}_total_act_energy / _total_act_ret_energy | number | no | Wh | — | (phase energy) | phase | resettable counter | optional | phase consistency test | documented |
| EMData.GetStatus.errors | array | — | — | database_error, ct_type_not_set | meter_status_raw | — | state | optional | counter quality | documented |

## 6. B1 — Victron GX Modbus-TCP battery service — **narrow**

**Feasibility row**

- **Device:** a Victron GX device (e.g. Cerbo GX) with a **CAN-bus BMS** lithium battery, which appears as `com.victronenergy.battery`. It runs Venus OS matching register list 3.81, declared in the registry. This is an independently monitored, AC-coupled demo battery as allowed by spec §6.
- **Not a BMS:** a BMV/SmartShunt is a battery monitor, not a BMS. With that variant, 305–308 are unavailable and battery-assisted planning must be withheld.
- **Acquisition:** a local documented read interface, Modbus-TCP on the GX (FC 3 or 4; "there is no difference between function code 3 and 4"). The unit-id is that of the battery service. The **preferred 225 = CAN-bus BMS (device instance 512)**, but "since Venus version 2.60, Unit Ids are assigned dynamically", so the unit-id is configured from *Settings → Integrations → Modbus TCP server → Available services*.
- **Collector and permissions:** a LAN collector (simulated). Modbus-TCP must be enabled by the owner. Not established.
- **Addressing and scale:** the Address column is the data address placed in the request (FAQ example). The value is raw ÷ Scalefactor (FAQ: "Divide it by 10, as specified in cell E3"; the Range column is consistent).
- **Errors:** exception 0x02 IllegalDataAddress (register does not exist), 0x0A GatewayPathUnavailable and 0x0B GatewayTargetDeviceFailedToRespond. "A canbus-connected lithium battery might not have all those parameters available". No sentinel value is documented.
- **Cadence:** the native rate is not specified. The chosen polling interval is 300 s.
- **Boundary:** DC battery. Native current is "+ charging / − discharging" and is inverted to the canonical +discharge convention with provenance.
- **Evidence:**
  - CCGX-Modbus-TCP-register-list-3.81.xlsx, sheets "Field list" (com.victronenergy.battery rows 258–323), "Unit ID mapping" and "Document versions" (latest Rev 54). File metadata: modified 2026-10-06.
  - The GX Modbus-TCP FAQ, last modified 2025-03-28.
- **Access status:** documented, simulated for demo.

**Field evidence matrix** (service `com.victronenergy.battery`; value = raw ÷ scalefactor)

| Native (dbus path) | Address | Type | Scalefactor | Unit | Notes / enum | Canonical metric | Boundary | Aggregation | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Battery voltage /Dc/0/Voltage | 259 | uint16 | 100 | V DC | — | battery_voltage_v | dc_battery | instantaneous | optional | state, voltage anomaly | documented |
| Current /Dc/0/Current | 261 | int16 | 10 | A DC | + charging / − discharging | battery_current_a | dc_battery | instantaneous | optional | direction, limit compliance | documented |
| Battery power /Dc/0/Power | 258 | int16 | 1 | W | "Older 16-bit variant of 256" | battery_net_kw | dc_battery | instantaneous | optional | power view | documented (sign inferred = current sign) |
| State of charge /Soc | 266 | uint16 | 10 | % | range 0–6553.6, so >100 is quarantined, never clamped | soc_pct | battery | last valid | optional | battery-assisted planning | documented |
| Battery temperature /Dc/0/Temperature | 262 | int16 | 10 | °C | — | battery_temperature_c | battery | instantaneous | optional | context | documented |
| Capacity /Capacity | 309 | uint16 | 10 | Ah | energy basis derived with nominal V (label derived) | battery_capacity_ah | battery | state | optional | capacity basis | documented |
| Max charge current /Info/MaxChargeCurrent | 307 | uint16 | 10 | A DC | CAN-bus BMS / Lynx NG only | battery_max_charge_current_a | dc_battery | state | optional | BMS-reported limit | documented |
| Max discharge current /Info/MaxDischargeCurrent | 308 | uint16 | 10 | A DC | CAN-bus BMS / Lynx NG only (derating observable here) | battery_max_discharge_current_a | dc_battery | state | optional | BMS-reported limit | documented |
| Max charge voltage /Info/MaxChargeVoltage | 305 | uint16 | 10 | V DC | CAN-bus BMS / Lynx NG only | battery_max_charge_voltage_v | dc_battery | state | optional | limit context | documented |
| Min discharge voltage /Info/BatteryLowVoltage | 306 | uint16 | 10 | V DC | CAN-bus BMS / Lynx NG only | battery_min_discharge_voltage_v | dc_battery | state | optional | limit context | documented |
| Alarms: LowVoltage, HighVoltage, LowSoc, LowTemperature, HighTemperature | 268, 269, 272, 273, 274 | uint16 | 1 | — | 0 = No alarm; 2 = Alarm | battery_alarm_raw | battery | state | optional | **reported battery fault → planner restriction** | documented |
| Alarms: HighChargeCurrent, HighDischargeCurrent, InternalFailure | 320, 321, 323 | uint16 | 1 | — | 0 = No alarm; 2 = Alarm | battery_alarm_raw | battery | state | optional | reported battery fault | documented |

Not selected:

- 256 (int32 power): word order undocumented.
- 267 /Alarms/Alarm: deprecated, "Value is always 0".
- 304 SoH and 318/319/1290/1291 cell values: exist for CAN-bus BMS, but no planned feature uses them and no cell or SoH claims are made.
- 1282/1283 State/Error: Lynx Ion / Lynx BMS only.
- History 281–302: "Not supported by CAN.Bus BMS batteries".

A read-back of a configurable ESS/system limit (system service) is **not** a BMS-reported limit and is not used.

## 7. B2 — SolarEdge storageData — **narrow**

**Feasibility row**

- **Device:** a SolarEdge StorEdge-integrated battery on an **existing SolarEdge provider site only**. It reuses the existing SolarEdge acquisition path and physical asset identity. Firmware is not established.
- **Acquisition:** vendor monitoring API, `GET /site/{siteId}/storageData` with local naive `startTime`/`endTime`. It needs an account API key, which is not established. The chosen polling interval is 900 s. The native cadence and query-window limits are **not established in this phase**.
- **Boundary:** DC battery. Native `power` is + charging / − discharging, which differs from currentPowerFlow. It is inverted to the canonical convention.
- **Times:** `timeStamp` is local naive "YYYY-MM-DD HH:MM:SS" and requires the declared site timezone.
- **Evidence:** SolarEdge Monitoring Server API, March 2026 — https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf.
  - **Retrieval failed on 2026-11-15** with an HTTP 403 bot challenge. The single alternative official URL (www.solaredge.com/sites/default/files/se_monitoring_api.pdf) also returned 403.
  - The retained facts come from the repository's own earlier review (SOURCE_NOTES.md R7, accessed 2026-11-14) and its existing storageData mapping (`se-storage-1.0`).
  - A third-party catalogue (apis.io, cited only as third party) corroborates only the endpoint path.
- **Access status:** documented, simulated for demo (re-verify against the PDF before extending).
- **Narrowed because:**
  - `batteryState` **label enumeration** is not established. It is kept as a raw integer, so there is no thermal-management/fault distinction.
  - `fullPackEnergyAvailable` and `ACGridCharging` units and semantics are not established. They are pass-through only, with no derived capacity or SoH.
  - `batteryCount`, `nameplate`, `modelNumber` and `telemetryCount` are not established.

**Field evidence matrix** (path `storageData.batteries[].telemetries[].` unless noted)

| Native | Type | Signed | Unit | Canonical metric | Boundary | Aggregation | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| batteries[].serialNumber | string | — | — | identity | — | identity | integration_required | identity | documented (prior review R7) |
| timeStamp | local naive string | — | — | source time | — | measurement time | integration_required | time | documented (R7) |
| power | number | yes (+charge/−discharge) | W | battery_net_kw | dc_battery | instantaneous | optional | power view | documented (R7) |
| stateOfCharge | number | — | % | soc_pct | battery | last valid | optional | battery planning (SoC) | documented (R7) |
| internalTemp | number | yes | °C | battery_temperature_c | battery_internal | instantaneous | optional | context | documented (R7) |
| batteryState | integer | — | — | battery_state_raw (raw only) | battery | state | optional | raw display only | documented key; **labels not established** |
| lifeTimeEnergyCharged | number | no | Wh | lifetime_battery_charge_kwh | dc_battery | lifetime counter | optional | throughput verification | documented (R7) |
| lifeTimeEnergyDischarged | number | no | Wh | lifetime_battery_discharge_kwh | dc_battery | lifetime counter | optional | throughput verification | documented (R7) |

Capability gaps that are actually documented here: no BMS-reported charge/discharge limits are present in this response, and there are no cell arrays. Without verified limits, B2 alone cannot support **battery-assisted planning**. It supports SoC and throughput display only.

## 8. B3 — Enphase battery telemetry — **exclude**

- **What is documented:** the support page states that "/api/v4/systems/{system_id}/telemetry/battery endpoint can retrieve site-level battery energy charged and discharged in 15 min intervals". The date range per request is at most 7 days, and the start must be within 2 years. A separate `/battery_lifetime` endpoint gives daily intervals.
- **Access constraints:** OAuth 2.0 bearer token plus an API `key` header. Authorization by the system owner is required. The Partner plan covers all endpoints for installed and maintained systems (≥ 10 installations). Coverage of the battery endpoint by other plans is not stated.
- **What is missing:** the accessible monitoring-API page contains no response schema. No field names (e.g. `intervals[].end_at`, `charge.enwh`), units or interval-boundary semantics could be confirmed. The page `developer-v4.enphase.com/docs.html` returns 404. There is no authorized sample.
- **Outcome:** per spec §5.2, the native profile is **excluded** from the delivered count. No fixture is generated and no response shape is invented. Access status: not established.

## 9. W1 — IMT Si-RS485TC-T-Tm-MB — **include**

**Feasibility row**

- **Device:** IMT Si-RS485TC-T-Tm-MB, serial prefix 485-4. The sheet's "Active Register" column gives **0, 7, 8**. The selection table (March 2026), solution 3, lists irradiance, cell temperature and "PV module temperature" from a permanently connected module sensor on a 3 m cable. There is no ambient temperature or wind on this model.
- **Firmware:** declared as 2.03. Registers 7/8 need FW ≥ 1.53.
- **Acquisition:** Modbus RTU, FC 0x04 Read Input Register (0x03 also supported). Factory default: 9600 baud, 8N1, address 1. The sensor starts Modbus operation 4 s after power-up.
- **Collector:** a site Modbus collector (simulated). Permission is not established. The native rate is not stated. The chosen polling interval is 60 s.
- **Unsupported registers:** "The Register 3, 8 and 9 are optional for some sensor types. If your sensor does not support this register, it will return the value 0". For this model, 3 (wind) and 9 (ext. temp no. 2) are **unavailable** and must never be ingested as real zeros.
- **Mounting:** POA only if the registry declares in-plane mounting.
- **Evidence:** IMT "Modbus Specification for Irradiance Sensors Si-RS485...-MB", dated January 2026, FW 2.03 (also 1.51–1.55), p.1 (register table), p.2 (optional registers) and p.5 (serial-prefix/active-register table). The IMT selection table is dated March 2026.
- **Access status:** documented, simulated for demo.

| Native | Register (= address, inferred) | Type | Signed | Gain | Offset | Unit | Range | Canonical metric | Boundary | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Irradiance | 0 | UINT16 | no | 0.1 | 0 | W/m² | 0…1500 (≤ FW 1.52: 0…1400) | irradiance_wm2 | registry plane (POA demo) | optional | irradiance explanation, PR review | documented |
| Cell Temperature | 7 | INT16 | **yes** | 0.1 | 0 | °C | −40…+90 | reference_cell_temperature_c | sensor cell | optional | negative INT16 decode case | documented |
| External Temp. no. 1 | 8 | INT16 | **yes** | 0.1 | 0 | °C | −40…+90 | module_temperature_c | back of module | optional | PV performance review | documented |

No invalid sentinel is documented. Out-of-range values are flagged by our bounds. The legacy registers 1/2/5/6 (offset-encoded UINT16) are not used.

## 10. W2 — Kipp & Zonen SMP10x — **include**

**Feasibility row**

- **Device:** Kipp & Zonen SMP10x (`IO_DEVICE_TYPE` = 635). `IO_DATAMODEL_VERSION` must be ≥ 108.
- **Interface:** RS-485 Modbus RTU. Factory defaults: 19200 baud, even parity, 8 data bits, 1 stop bit, address 1. Serial output range −400 to 2000 W/m². Response time < 0.7 s (63 %) and < 2 s (95 %). There is no internal data memory, and the manual recommends 1 s sampling with 1-minute averages.
- **Acquisition:** FC 0x04 Read input register. Collector simulated, permission not established, chosen polling interval 60 s.
- **Addressing:** "Input PDU Address + 1 = Modbus® register number".
- **Scale:** `IO_SCALE_FACTOR` (PDU 4). A value of 2 means x/100, 1 means x/10, 0 means x and −1 means x×10. It applies to radiation registers 5, 6, 10 and 11.
- **Boundary:** body temperature is the **instrument body**, not ambient or module temperature. Radiation is POA only if mounting metadata says so. A horizontal (GHI) test case is required.
- **Night offset:** "Zero offset type A" (a small negative signal; total zero offset < 9 W/m² for SMP10x) is documented. It is **not an equipment fault**. Coil `IO_CLAMP_IRR` (default 0) can prohibit negative values.
- **Evidence:** "SMP10x and SMP22x Smart Pyranometers Operational Manual", document 0374214 | 02-0326 (file V20), OTT HydroMet / Kipp & Zonen. Hosted on the vendor CDN and linked from kippzonen.com Resources. Sections 15.1–15.6 (pp.43–49) and 14.1.
- **Access status:** documented, simulated for demo.

| Native | PDU addr / register no. | Type | Signed | Scale | Unit | Invalid / quality | Canonical metric | Boundary | Req. class | Feature | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| IO_DEVICE_TYPE | 0 / 1 | U16 | no | 1 | — | — | identity (635 = SMP10x) | — | integration_required | model check | documented |
| IO_STATUS_FLAGS | 3 / 4 | U16 bitfield | no | — | — | bit0 invalid data, 1 overflow, 2 underflow, 3 error, 4 ADC, 5 DAC, 6 calibration, 7 NV update, 8 power failure, 10 RH, 11 desiccant, 12 body-temp sensor | sensor_status_raw | — | optional | validity gate | documented |
| IO_SCALE_FACTOR | 4 / 5 | S16 | yes | — | — | valid 2/1/0/−1 | (decode param) | — | integration_required | radiation decode | documented |
| IO_SENSOR1_DATA | 5 / 6 | S16 | yes | per scale factor | W/m² | status bits | irradiance_wm2 | registry plane | optional | irradiance explanation | documented |
| IO_BODY_TEMPERATURE | 8 / 9 | S16 | yes | 0.1 | °C | bit12 | sensor_body_temperature_c | instrument body | optional | context only | documented |
| IO_ERROR_CODE | 26 / 27 | U16 | no | — | — | raw | sensor_status_raw | — | optional | raw error evidence | documented |

The Float32 registers 10006+ are not used because their word order is not stated.

## 11. W3 — Campbell Scientific TOA5 configured station — **include**

**Feasibility row**

- **Device:** Campbell Scientific CR1000X logger running **our configured program**, as a shared **area resource** linked to eligible sites. The attached sensors are declared in station metadata: a POA pyranometer, a shielded ambient temperature sensor and a back-of-module temperature sensor.
- **Acquisition:** a configured datalogger export, a TOA5 file collected LoggerNet-style (simulated). Permission is not established. The output interval is configured at 60 s.
- **Format** (LoggerNet TOA5 page and CR1000X "About data tables"):
  - Header row 1: "TOA5", station name, datalogger type, serial number, OS version, program (DLD) name, program signature and table name (8 fields).
  - Row 2: field names. Row 3: units (TIMESTAMP → `TS`, RECORD → `RN`). Row 4: data process abbreviations (Avg, Max, Min, Tot, Std, SMM…; `Smp` in the LoggerNet example).
  - Then comma-separated records with a quoted timestamp.
- **Time meaning:** CR1000X examples label the **end** of the output interval ("average taken over the minute beginning at 14:26:01 and ending at 14:27:00"). The logger clock timezone must be configured because the file carries no offset.
- **Missing values:** configured token `"NAN"`. Campbell's Data Logger Web Server API 1.0.3 (2026-09-25) documents "Invalid or not-a-number floating-point values are written as the string "NAN"". The TOA5 page itself is silent.
- **Column names:** `POA_Irr_Avg`, `AirT_C_Avg`, `ModT_C_Avg`, `POA_Irr_Max` and `POA_Irr_Min` are **our configuration (explicitly simulated)**, not universal Campbell fields. A missing module temperature stays missing and is never replaced by ambient temperature.
- **Access status:** documented, simulated for demo.

| Column | Row 3 unit | Row 4 processing | Canonical metric | Boundary | Aggregation | Invalid | Req. class | Evidence |
|---|---|---|---|---|---|---|---|---|
| TIMESTAMP | TS | "" | source time (interval end) | — | — | — | integration_required | documented |
| RECORD | RN | "" | record number | — | — | — | integration_required | documented |
| POA_Irr_Avg | W/m^2 | Avg | irradiance_wm2 | POA | interval average | NAN | optional | explicitly simulated (format documented) |
| POA_Irr_Max / POA_Irr_Min | W/m^2 | Max / Min | irradiance_wm2 | POA | interval max / min | NAN | optional | explicitly simulated |
| AirT_C_Avg | Deg C | Avg | ambient_temperature_c | ambient | interval average | NAN | optional | explicitly simulated |
| ModT_C_Avg | Deg C | Avg | module_temperature_c | back of module | interval average | NAN | optional | explicitly simulated |

## 12. Excluded or narrowed: summary

- **Excluded: B3 Enphase.** There is no accessible response schema or interval semantics, and no authorized sample. The native profile is not delivered. The energy-only battery capability gap must not be demonstrated with an invented Enphase payload.
- **Narrowed: B2 SolarEdge.** The official PDF was unreachable this phase. Only the fields from the R7 review are kept. `batteryState` stays a raw integer with no labels. `fullPackEnergyAvailable`/`ACGridCharging` get no semantics, and query limits are not established.
- **Narrowed: B1 Victron.**
  - int32 power is dropped.
  - Limits 305–308 exist only for a CAN-bus BMS / Lynx NG battery. A SmartShunt/BMV variant has no limits.
  - The unit-id is configured, not fixed.
  - SoH and cell registers are not used.
- **Narrowed: M2 Fronius.**
  - Units are inferred.
  - Phase currents are magnitude only.
  - The TimeStamp format is inferred.
  - No GEN24 pairing.
- **Inferred items inside included profiles:**
  - M1: word order.
  - M3: the sign of `act_power` and the unit of `total_act_power`.
  - W1: register number = address.
  - Victron power sign (258), assumed equal to the documented current sign.

## 13. Legal and regulatory references (separate from telemetry requirement classes)

| Reference | What it is relevant to | Status in this phase |
|---|---|---|
| Regulation (EU) 2023/1542 (Batteries), Art. 14 and Annex VII — https://eur-lex.europa.eu/eli/reg/2023/1542/oj/eng | Per the master spec: health/expected-lifetime parameters held in the BMS of covered batteries, with read-only access in specified circumstances | **Unverified.** EUR-Lex returned an empty response to automated retrieval on 2026-11-15. Article text, scope and application dates are **not established** here. It does **not** establish that any chosen monitoring API exposes those parameters, nor a universal CAN/register map. No compliance claim is made. |
| Regulation (EU) 2023/2854 (Data Act) — https://eur-lex.europa.eu/eli/reg/2023/2854/oj/eng | General data-access framework | Relevance only, **not established** for any specific field. It is not a mandatory inverter, battery or meter API schema. |
| Romanian technical connection norm (Order 228/2018), repository R1 — https://legislatie.just.ro/Public/DetaliiDocumentAfis/209500 | Connection/protection and technical documentation to the network operator | Context only (accessed 2026-11-14 in the R1 review). It is not proof of third-party API access rights or a cloud telemetry contract. |

## 14. Unreachable documents (2026-11-15)

| Document | Result | Fallback |
|---|---|---|
| SolarEdge Monitoring API PDF (knowledge-center) | HTTP 403 (bot challenge), via both curl and WebFetch | One alternative official URL (solaredge.com/sites/default/files/…) also returned 403. B2 is narrowed using the prior R7 review. |
| Fronius Solar API PDF on api.library.loxone.com (third-party mirror) | DNS resolution failure | Official Fronius-hosted PDF 42,0410,2012,EN rev 021-15052025 (retrieved) |
| Kipp & Zonen `kippzonen.com/Download/1143/...` | Returns the Resources HTML page | Vendor-linked CDN file V20 (0374214 \| 02-0326), retrieved |
| Enphase battery telemetry response schema | Not present on accessible pages; docs.html returns 404 | None, so B3 is excluded |
| EUR-Lex 2023/1542 | Empty response (HTTP 202) | None, so the legal reference is marked unverified |


## 15. Generation assumptions, tolerances and exact commands

All component data are **synthetic**. They come from `generate_components.py` (`GENERATOR_VERSION` 1.0.0,
scenario `components-2026.11.15-1`).

### Commands

```
python generate_components.py --seed 42 --start 2026-07-15 --days 7 --out demo_components \
    --truth-out tests/component_truth --provider-data demo_data
python scraper.py --component all --config config/component_profiles.yaml --input demo_components \
    --out build/components --as-of 2026-07-22T00:00:00+03:00      # or --component meter|battery|weather
python -m pytest -q tests/test_components_engine.py tests/test_components_dataset.py tests/test_architecture.py
```

### Latent model and identities

- **Same latent model as the inverter fixtures.** The generator imports `generate_demo.Timeline`, `make_weather` and
  `simulate_site` with seed 42 and the same window (2026-07-15…21, Europe/Bucharest).
- **No changes to the original generator.** `generate_demo.py` is not modified, and its outputs reproduce
  byte-for-byte: `demo_data/manifest.json` is identical.
- **PV.** PV AC on F1 equals the existing F1 inverter `P_PV`/`PAC` to within 0.05 W (rounding). POA on S2 and F1 is
  the same plane-of-array irradiance that drives the existing PV.
- **F1 business overlay.** This is a versioned overlay record (`assets.json.business_overlays`); `demo_data/sites.json`
  is not edited.
  - Load: a fictional self-service laundry, open 07:00–22:00, with stochastic washer/dryer cycles.
  - Flexible task: the illustrative "commercial laundry batch", 4 kW × 2 h = 8 kWh, noninterruptible, allowed window
    08:00–20:00.
  - Executed history: the batch runs daily at 09:00, and at 11:00 on 2026-07-17. That log is evaluation-only.
  - It supersedes the household load of the original latent model for this scenario only.
- **F1 battery.** AC-coupled on L2: 51.2 V × 200 Ah (10.24 kWh capacity basis, *derived*), reserve 20 %, inverter
  3.0 kW.
  - Storage energy: E_next = E + 0.95·P_ch·dt − P_dis·dt/0.95.
  - DC terminal power = AC × 0.965 when charging, AC / 0.965 when discharging.
  - BMS limits: 70 A charge / 100 A discharge, derated to 25 A from 2026-07-18 09:40. The same latent event sets
    `/Alarms/InternalFailure` = 2, and dispatch honours the derated limit.
- **AC balance at the F1 PCC.** PV_ac + import + batt_dis_ac = load + export + batt_ch_ac + 0 (residual losses
  declared 0 at this boundary). It is asserted per minute (|error| < 1e-9 kW). The storage integration and the SoC
  bounds (20–100 %) are asserted as well.

### Counters, phases and snapshots

- **Counters.** They integrate the 1-min directional flows of the **net total**: import and export can both
  accumulate within one 5-min interval. The counter value at a snapshot is the energy before that minute, as exact
  integer Wh for Schneider/Fronius and 0.01 Wh floats for Shelly.
- **Tolerance.** 15-min counter energy matches the latent truth within 2.5 Wh (`tests/test_components_dataset.py`).
- **Per-phase values.** They sum to the total within 0.5 W (Float32 / 0.1 W rounding). Phase currents are synthesized
  as |P|/(V·0.97 to 0.98). That power factor is used only to make current magnitudes and is not a power-factor claim.
- **Snapshot timing.** A snapshot value is the latent value at the poll minute. Capture time = poll minute + 0.1–2.5 s
  (collector jitter). Received time = capture + 1–25 s (LAN upload). Frames allow ±10 s of boundary tolerance.
- **Shelly reset.** The Shelly counters restart from 0 after the logged `EMData.ResetCounters` at 2026-07-17
  11:02:30. Per-phase EMData energies are phase-wise directional (labelled assumption). The engine does not map them.

### Irradiance and temperatures

- **Irradiance.** Uses the generate_demo clear-sky/cloud model in the plane declared by the registry: F1 POA 35°/180°,
  S2 POA 30°/195°, station POA 30°/180°.
- **Temperatures.**
  - Module = ambient + POA·25/800 with a 5–6 min lag.
  - IMT reference cell = ambient + POA·0.018.
  - Kipp body = ambient + POA·0.010 + 0.5 °C (10 min lag).
  - Kipp night radiation is −0.4…−3.6 W/m² (zero offset type A).
- **Logger clock.** The station logger clock is configured to UTC+02:00 standard time (no DST), so in July the
  TOA5 TIMESTAMP reads 1 h behind local summer time. TIMESTAMP = interval end.

### Defects and fixture packaging

- **Defects.** They are listed with their expected handling in `tests/component_truth/fault_manifest.json`
  (evaluation-only, 18 cases). The scenario days are in `demo_components/manifest.json → scenario_days_local`.
- **Negative temperatures.** These cannot occur in July production data, so the negative-temperature decode
  (INT16/S16) is exercised on the test-only equivalence bench.
- **Packaging.**
  - Size: 10.7 MB. The 1-min register streams of W1 and W2 are gzip-compressed deterministically (mtime 0, no
    filename).
  - B2 and the F2 mirror reference the existing `demo_data` files by sha256. Nothing is copied.
- **Not generated.**
  - Enphase (excluded).
  - SoH, cell data, Victron int32 power 256, Kipp Float32 registers, Schneider partial/Float32 energy, Fronius
    `*_Absolute` counters, Shelly totals beyond the allowlist.
  - Battery inverter telemetry for F1, which is not in scope. The AC side of the battery is therefore unobserved:
    only the DC battery-service values exist.

## 16. Delivered-use boundaries

- **Business decision:** F1 uses the declared PCC meter, supported battery-service subset and an IMT sensor
  in its module plane. Capacity basis, reserve, efficiencies and inverter rating are explicit scenario
  declarations, separate from measurements. The battery is excluded when its alarm/limits make support
  unavailable. Advice does not control the appliance or battery.
- **Shared weather:** one Campbell station is linked as an area resource to H1/H2/H3. Its plane is compared
  with each site's arrays; the link alone does not establish an in-plane sensor. H2's irradiance and PV
  performance checks consistently report a plane mismatch and abstain from the dependent judgement.
- **Operations:** device evidence supports a reported battery restriction, sustained-voltage review,
  weather-consistent variation, collector troubleshooting and unexplained underperformance. It does not
  establish a failed cell/string, transient grid compliance or loss of supply. No common feeder relation
  is declared, so no feeder is inferred from the map.
- **Planning inputs:** `demo_components/operations_inputs.json` contains fictional qualifications, staffing,
  shifts/breaks, customer access windows, service durations, organization authorization, reported bases
  and approximate travel times. These are operations records, never native vendor fields. Manual repair
  price ranges are labelled demo catalog estimates. Neither visit-reduction nor diagnostic-accuracy
  percentages are validated by this replay.
- **Reproduction:** [README setup](../README.md#equipment-customer-planning-and-operations-replay) and the
  [four-scene script](./COMPONENT_DEMO.md) use a new external scenario database, explicit grants and one
  forward-only clock. Runtime code never reads evaluation-only truth labels.

The source review above is retained as recorded; this delivery did not establish hardware/PPC access or
refresh the unreachable documents. Legal applicability remains unverified; no compliance claim is made.
