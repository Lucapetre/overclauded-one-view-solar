export type Role =
  "client" | "ceo" | "manager" | "dispatcher" | "technician" | "support";
export type SafetyTier = "P0" | "P1" | "P2" | "P3";
export interface SessionUser {
  id: string;
  name: string;
  role: Role;
  sites: string[];
  area: string;
}
export interface ApiError {
  code: string;
  message: string;
  request_id: string;
}
export interface EnergySnapshot {
  site_id: string;
  interval_start_utc: string;
  interval_end_utc: string;
  received_at_utc: string;
  source_mode: "synthetic" | "observed" | "replayed";
  pv_kw: number | null;
  home_kw: number | null;
  import_kw: number | null;
  export_kw: number | null;
  battery_charge_kw: number | null;
  battery_discharge_kw: number | null;
  soc_percent: number | null;
  quality: "recent" | "stale" | "missing";
}
export interface Recommendation {
  id: string;
  task_id: string;
  start_utc: string;
  end_utc: string;
  expiry_utc: string;
  revision: number;
  baseline_cost_ron: number;
  proposed_cost_ron: number;
  incremental_saving_ron: number;
  status: "offered" | "accepted" | "declined" | "cancelled" | "expired";
  assumptions: string[];
}
export interface DecisionPatch {
  expected_revision: number;
  status: string;
  confirmed_owner?: string;
  outcome_reason?: string;
  idempotency_key: string;
}
export interface SolarApi {
  login(email: string, password: string): Promise<SessionUser>;
  logout(): Promise<void>;
  energy(siteId: string): Promise<EnergySnapshot>;
  accept(
    id: string,
    revision: number,
    idempotencyKey: string,
  ): Promise<Recommendation>;
}
