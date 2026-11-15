# Equipment reference sheet supplied by the product owner (transcribed, Romanian original)

Title: "Fișă tehnică de referință · Telemetrie & inspecție FV — Echipamente Adiționale Fotovoltaice: Date Inspectate și Formate de Transmisie" (2 pages). It is a REFERENCE summary, not proof of legal obligations or of universal vendor support (see master spec §4.1).

## 1. Inspection boundary: Distribution Operator vs ANRE service
- Distribution Operator (DO) technicians (PPC / Rețele Electrice România) inspect only the delimitation point with the public grid, the DO's bidirectional meter and the interface protections (anti-islanding and export limitation per the connection approval, "Aviz Tehnic de Racordare").
- ANRE-authorised technicians and O&M teams check internal DC equipment, batteries, optimisers and monitoring gateways (compliance, diagnosis, warranty).

## 2. Matrix (equipment — who inspects & parameters — interface & protocol — raw format & export)
1. **DO bidirectional smart meter (AMR/AMI at the connection)** — [PPC / Rețele Electrice] metrological seal, active energy imported (OBIS 1.8.0) and exported (2.8.0), reactive energy (3.8.0–8.8.0), 15-min load profiles, voltage events — optical IR port (IEC 62056-21), PLC, GSM/NB-IoT/4G; DLMS/COSEM — standard OBIS codes; binary HDLC / ASCII frames on optical port; XML/CSV export in the DO's HES systems.
2. **Prosumer internal meter & protection relays (CT sensors, interface relays)** — [PPC/Rețele Electrice & ANRE] zero-export function (export limitation), current direction per phase (CT), automatic disconnection on grid loss (EN 50549-1) — RS485 (Modbus RTU), Ethernet/Wi-Fi (Modbus TCP), auxiliary contacts — 16-bit Big-Endian registers / IEEE 754 Float32; JSON (MQTT/REST) for IoT meters.
3. **BMS (LiFePO4 battery bank)** — [ANRE technicians / service] SoC %, SoH %, per-cell voltage and temperature, balancing, cycle count, alarm logs — CAN bus (500 kbps), RS485 (Modbus RTU / proprietary), Bluetooth BLE — CAN 2.0A/B hex frames (11/29-bit), ASCII/Hex packets; historical CSV/JSON reports.
4. **Optimisers & microinverters (MLPE)** — [ANRE technicians / firefighters] per-module V, A, W, temperature; Rapid Shutdown (1 V/panel) — DC cable PLC, Zigbee or sub-GHz/2.4 GHz RF to gateway — SunSpec Modbus (Model 160) in gateway; JSON via REST API; CSV export.
5. **MPPT regulators, string box & AFCI** — [ANRE / O&M] per-string V/A, fuse and SPD state, insulation resistance (Riso), DC arc detection (AFCI) — RS485 (Modbus RTU), VE.Direct / VE.Can, dry-contact relays — 16-bit integer registers with SunSpec Scale Factor; ASCII text pairs (VE.Direct); binary 0/1.
6. **Weather stations & irradiance sensors (POA pyranometers, cell temp.)** — [energy auditors / O&M] plane-of-array irradiance (W/m²), module and ambient temperature (°C), wind — for Performance Ratio (PR%) — RS485 (Modbus RTU), SDI-12 serial, 4–20 mA analog loop — SunSpec Modbus (models 302–305); SDI-12 ASCII strings (1200 bps); analog signal; CSV files.
7. **EMS gateway & power-quality analyser (datalogger, PQA)** — [DO for large plants & ANRE] THD %, phase imbalance, power factor (cos φ), curtailment commands, event logs — Ethernet LAN, 4G/LTE; Modbus TCP, MQTT, IEC 61850, OPC UA — JSON (MQTT/API), PQDIF (IEEE 1159.3), XML/CSV.

## 3. Field decoding notes
- OBIS on the PPC/Rețele Electrice meter display: 1.8.0 total active energy imported from the grid (kWh), 2.8.0 total active energy exported (kWh), 3.8.0/4.8.0 reactive inductive/capacitive.
- SunSpec Modbus rule: raw int16/uint16 × 10^SF where SF is read from an adjacent dedicated register (raw 2345, SF = −1 → 234.5 V).
- Recommended archiving for audit/warranty: periodic CSV exports (5–15 min time series) and JSON/XML event logs of inverter and BMS, needed for grid-overvoltage complaints or warranty claims.
- Commissioning note: the DO team does NOT access the inverter manufacturer's cloud apps; their verification relies on optical/telemetric reading of the bidirectional meter (DLMS/COSEM) and a physical trip test of the interface protection.
