// Connected frontend types come from the backend's generated OpenAPI contract.
export type {
  ApiRoutes,
  User as SessionUser,
  SessionView,
  ErrorEnvelope as ApiError,
  EnergySnapshot,
  EnergyHistory,
  Site,
  Area,
  AreaSummary,
  ProviderSite,
  ProviderLatest,
  ProviderFrame,
  ProviderObservation,
  ProviderFrames,
  ProviderObservations,
} from "../../packages/contracts";
export type { ProviderHistoryQuery } from "../../packages/contracts/client";
export type Role = import("../../packages/contracts").User["role"];
