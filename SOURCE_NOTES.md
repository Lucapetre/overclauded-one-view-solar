# Source notes (research basis and what is NOT claimed)

Research was checked on 14 November 2026. All values in this repository are **synthetic**. The references below
justify field names, units, signs and structures only.

## References

| Id | Source | Used for | Limits |
| --- | --- | --- | --- |
| R1 | Order 228/2018 technical connection norm, Art. 15 + annex — https://legislatie.just.ro/Public/DetaliiDocumentAfis/209500 | Shape of `regulatory_metadata.json` (connection point, nominal voltage, kW/kVA, inverter AC ratings, DC limits, battery limits) | Network-operator connection data. **Not** a universal manufacturer telemetry API. Field-level applicability unverified. |
| R2 | ANRE press release, 10 Nov 2026 — https://anre.ro/comunicat-de-presa-anre-aproba-noi-reguli-pentru-prosumatori-compensare-lunara-utilizarea-excedentului-pentru-mai-multe-locuri-de-consum-si-plata-sumelor-restante/ | Context: DSO monthly import/export readings | DSO metering, not inverter telemetry; verify applicability with the mentor |
| R3 | Huawei SmartPVMS 25.2.0 Northbound API Reference, issue 2025-07-28 (public mirror) — https://www.scribd.com/document/980589962/SmartPVMS-25-2-0-Northbound-API-Reference | `success/data/failCode/message/params`, `devId`, `dataItemMap`, `collectTime` (epoch ms), getDevHistoryKpi / getDevRealKpi shapes; dt38 and dt39 fields and units | Public mirror, not a tested customer endpoint. Units differ by device type/version, and there is **no** global "active_power is kW" rule. |
| R4 | Huawei FAQ: Northbound API application permissions — https://info.support.huawei.com/DpinfoAppDoc/pro_erp_slice001/doc/fusion_solar/faq/installer/en/en-us_topic_0000001867081537.html | Access prerequisites (why credentials are separate from platform roles) | Physical-control instructions on that page are deliberately **not** implemented |
| R5 | Fronius Solar API overview — https://www.fronius.com/en/help-center/solar-energy/products/monitoring-control/solutions/open-interfaces/fronius-solar-api-json- | Interface scope | — |
| R6 | Fronius Solar API V1, 42,0410,2012,EN rev 021-21012025 (mirror) — https://www.scribd.com/document/1001917583/42-0410-2012-3 (older cross-check PDF in the task brief) | `Head`/`Body.Data`, `Head.Timestamp` as response time, `P_Grid` (+import/−export), `P_Load` (negative consumption), `P_Akku` (−charge/+discharge), `P_PV` AC on SnapInverter vs DC on GEN24/SymoHybrid, `E_Day/E_Year/E_Total` Wh (model dependent), CommonInverterData `{Unit, Value}` | Versioned mirror; not proof of compatibility with every device/firmware |
| R7 | SolarEdge Monitoring Server API (March 2026) — https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf | Technical telemetry (`date` local naive, `totalActivePower` W, `totalEnergy` Wh, `temperature`, `inverterMode`, phase data), `currentPowerFlow` (nonnegative magnitudes + `connections`, `STORAGE.chargeLevel`, `{}` if unsupported), `storageData` (+charge/−discharge power, SOC, `internalTemp`, lifetime Wh) | JSON only; legacy API; site timezone needed for local naive times |

## Per-profile pinning (`config/provider_profiles.yaml`)

* **huawei_smartpvms_nbi_2025_07_28**: device type 38 history (5-min `collectTime`), optional real-time fixture
  (server `currentTime` = **response** time, never sensor time), and device type 39 battery.
  * `ch_discharge_power` sign: **assumed_demo** (positive = charging). The reviewed material did not establish it.
  * `failCode` 407 → rate_limited and 305 → session_expired are marked `verified: false`.
  * `inverter_state` / `battery_status` are kept raw, with no label mapping.
* **fronius_solar_api_v1_rev021**: the SnapInverter and GEN24 variants are selected by site metadata
  (`profile_variant`).
  * GEN24 `E_Day`/`E_Year` are always null (`model_behaviour: always_null`), which is a legitimate capability state.
  * The `Head.Status.Code` mapping (12 device not available, 11 unsupported, 5 timeout, 6 argument error) and the
    SnapInverter `StatusCode` labels 7/8 are marked "verify". Other codes are kept raw.
* **solaredge_monitoring_api_2026_03**: `equipment_data` (technical telemetry, 15-min cadence in this demo),
  `currentPowerFlow` and `storageData`. Mapping version `se-tel-1.1-synthetic-alias` is a **synthetic**
  schema-drift test registered for the demo. It is not a documented SolarEdge change.

## Demo serialization choices (not vendor promises)

* Huawei 5-min history pulled hourly, Fronius 1-min PowerFlow and 5-min CommonInverterData snapshots, SolarEdge
  15-min telemetry pulled hourly and power flow every 15 min. These cadences are capture choices, not claims about
  vendor refresh latency or rate limits.
* The latent simulation is a one-minute physical model:
  * Clear-sky (Haurwitz) irradiance with a shared regional cloud plan.
  * Plane-of-array irradiance with temperature derating.
  * An inverter efficiency curve and clipping.
  * A self-consumption battery dispatch with reserve, power limits and charge/discharge efficiency.
  * AR(1) household load with appliance cycles and EV charging.
  * A first-order inverter temperature model and a voltage rise with export.
  * The AC-boundary identity `pv_dc + import + discharge = load + export + charge + losses` is asserted every minute.
* The phase-voltage event (H2), the garage heat soak (H1) and the string loss (S2) are labelled physical scenarios
  with declared assumptions. They are not observed statistics.

## Explicitly not claimed

* No legal rule is claimed that requires all inverter brands to expose the same API fields.
* "integration_required" fields are this contract's engineering choice, not legal requirements
  (see `config/requirements_registry.yaml`).
* No real certificate, compliance status, root cause, field fault-detection accuracy or manufacturer threshold is
  claimed. The review policies are demo policies.
* No device commands, write endpoints, vendor logins or portal scraping are used. No credentials exist in the repo.
