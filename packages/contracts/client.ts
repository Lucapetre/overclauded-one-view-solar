import type {
  Area,
  AreaSummary,
  EnergyHistory,
  EnergySnapshot,
  ErrorEnvelope,
  ProviderFrames,
  ProviderLatest,
  ProviderObservations,
  ProviderSite,
  SessionView,
  Site,
  Contract,
  ContractView,
  LessonCatalog,
  LessonResult,
  RequestType,
  SupportRequest,
  AutoDispatchResult,
  CapacityView,
  Incident,
  IncidentDetail,
  OpsMap,
  RevenueView,
  TeamsView,
  AuditEntry,
  ClientOffer,
  ManagerClient,
  ManagerOffer,
  ManagerOfferDetail,
  NotificationList,
  OfferDraft,
  OfferPreview,
  SavingsSummary,
  UserOffer,
  AcceptTask,
  ClockView,
  PlanDecision,
  ReviewTask,
  Task,
  TaskCreate,
  TaskProgress,
  TaskUpdate,
  EquipmentEvidence,
  EnergyOverview,
  EnergyPeriods,
  EquipmentSummary,
  AgendaView,
  ApplyRequest,
  CloseRequest,
  CrewPlanView,
  EpisodeDetail,
  OverrideRequest,
  ProgressRequest,
  ProposeRequest,
  QueueView,
  StatusProjection,
  UnmappedSites,
} from "./index";

/** Account offered on the local demo landing page (not part of the public API contract). */
export type DemoAccount = {
  username: string;
  role: "customer" | "dispatcher" | "technician" | "supervisor";
  account_type: "home" | "business";
  sites: string[];
  areas: string[];
  crews: string[];
};

export class SolarApiError extends Error {
  constructor(public readonly status: number, public readonly detail: ErrorEnvelope) {
    super(detail.message);
  }
}

/** Use one instance per signed-in browser profile. Never put the pipeline key here. */
export class SolarClient {
  private csrfToken: string | undefined;

  constructor(private readonly baseUrl = "") {}

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers);
    // JSON by default; an explicit Content-Type (e.g. a raw video upload) is respected.
    if (options.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (options.method === "POST" && this.csrfToken) {
      headers.set("X-CSRF-Token", this.csrfToken);
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      headers,
      credentials: "include",
    });
    if (!response.ok) {
      let detail: ErrorEnvelope;
      try {
        detail = await response.json() as ErrorEnvelope;
      } catch {
        detail = {
          code: "invalid_response",
          message: `API request failed (${response.status})`,
          request_id: response.headers.get("X-Request-ID") ?? "unknown",
        };
      }
      if (response.status === 401) this.csrfToken = undefined;
      throw new SolarApiError(response.status, detail);
    }
    return response.status === 204 ? undefined as T : response.json() as Promise<T>;
  }

  async login(username: string, password: string): Promise<SessionView> {
    const session = await this.request<SessionView>("/api/v1/auth/login", {
      method: "POST", body: JSON.stringify({ username, password }),
    });
    this.csrfToken = session.csrf_token;
    return session;
  }

  /** Local demo mode only (server started with SOLAR_DEMO_LOGIN=true, loopback client). */
  demoAccounts(signal?: AbortSignal): Promise<DemoAccount[]> {
    return this.request("/api/v1/auth/demo-accounts", { signal });
  }

  async demoLogin(username: string): Promise<SessionView> {
    const session = await this.request<SessionView>("/api/v1/auth/demo-login", {
      method: "POST", body: JSON.stringify({ username }),
    });
    this.csrfToken = session.csrf_token;
    return session;
  }

  async me(signal?: AbortSignal): Promise<SessionView> {
    const session = await this.request<SessionView>("/api/v1/me", { signal });
    this.csrfToken = session.csrf_token;
    return session;
  }

  async logout(): Promise<void> {
    if (!this.csrfToken) await this.me();
    await this.request<void>("/api/v1/auth/logout", { method: "POST" });
    this.csrfToken = undefined;
  }

  sites(signal?: AbortSignal): Promise<Site[]> {
    return this.request("/api/v1/sites", { signal });
  }

  site(siteId: string, signal?: AbortSignal): Promise<Site> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}`, { signal });
  }

  latest(siteId: string, signal?: AbortSignal): Promise<EnergySnapshot> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/energy/latest`, { signal });
  }

  history(
    siteId: string,
    from: string,
    to: string,
    resolution: EnergyHistory["resolution"] = "raw",
    signal?: AbortSignal,
  ): Promise<EnergyHistory> {
    const query = new URLSearchParams({ from, to, resolution });
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/energy?${query}`, { signal });
  }

  areas(signal?: AbortSignal): Promise<Area[]> {
    return this.request("/api/v1/areas", { signal });
  }

  areaSummary(areaId: string, signal?: AbortSignal): Promise<AreaSummary> {
    return this.request(`/api/v1/areas/${encodeURIComponent(areaId)}/summary`, { signal });
  }

  providerSites(signal?: AbortSignal): Promise<ProviderSite[]> {
    return this.request("/api/v1/provider/sites", { signal });
  }

  providerLatest(siteId: string, signal?: AbortSignal): Promise<ProviderLatest> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/provider/latest`, { signal });
  }

  providerObservations(siteId: string, options: ProviderHistoryQuery, signal?: AbortSignal): Promise<ProviderObservations> {
    return this.providerHistory(siteId, "observations", options, signal);
  }

  providerFrames(siteId: string, options: ProviderHistoryQuery, signal?: AbortSignal): Promise<ProviderFrames> {
    return this.providerHistory(siteId, "frames", options, signal);
  }

  contract(siteId: string, signal?: AbortSignal): Promise<ContractView> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/contract`, { signal });
  }

  saveContract(siteId: string, contract: Contract): Promise<ContractView> {
    return this.write(`/api/v1/sites/${encodeURIComponent(siteId)}/contract`, contract);
  }

  requestTypes(signal?: AbortSignal): Promise<RequestType[]> {
    return this.request("/api/v1/support/request-types", { signal });
  }

  supportRequests(signal?: AbortSignal): Promise<SupportRequest[]> {
    return this.request("/api/v1/support/requests", { signal });
  }

  createSupportRequest(body: { site_id: string; request_type: string; description: string; immediate_danger?: boolean }): Promise<SupportRequest> {
    return this.write("/api/v1/support/requests", body);
  }

  replyToSupportRequest(requestId: string, text: string): Promise<SupportRequest> {
    return this.write(`/api/v1/support/requests/${encodeURIComponent(requestId)}/replies`, { text });
  }

  lessons(signal?: AbortSignal): Promise<LessonCatalog> {
    return this.request("/api/v1/lessons", { signal });
  }

  completeLesson(lessonId: string, answers: number[]): Promise<LessonResult> {
    return this.write(`/api/v1/lessons/${encodeURIComponent(lessonId)}/complete`, { answers });
  }

  /** Raw MP4 or WebM body (not multipart), at most 30 MB; not allowed on danger reports. */
  async uploadSupportVideo(requestId: string, file: Blob, filename: string): Promise<SupportRequest> {
    if (!this.csrfToken) await this.me();
    const type = file.type || (filename.toLowerCase().endsWith(".webm") ? "video/webm" : "video/mp4");
    const query = new URLSearchParams({ filename });
    return this.request(`/api/v1/support/requests/${encodeURIComponent(requestId)}/media?${query}`, {
      method: "POST", body: file, headers: { "Content-Type": type },
    });
  }

  /** Same-origin URL for a <video src>; the session cookie authorizes it. */
  supportMediaUrl(mediaId: string): string {
    return `${this.baseUrl}/api/v1/support/media/${encodeURIComponent(mediaId)}`;
  }

  opsMap(signal?: AbortSignal): Promise<OpsMap> {
    return this.request("/api/v1/ops/map", { signal });
  }

  opsIncidents(status: "open" | "all" = "open", signal?: AbortSignal): Promise<Incident[]> {
    return this.request(`/api/v1/ops/incidents?${new URLSearchParams({ status })}`, { signal });
  }

  opsIncident(incidentId: string, signal?: AbortSignal): Promise<IncidentDetail> {
    return this.request(`/api/v1/ops/incidents/${encodeURIComponent(incidentId)}`, { signal });
  }

  resolveIncident(incidentId: string): Promise<IncidentDetail> {
    return this.write(`/api/v1/ops/incidents/${encodeURIComponent(incidentId)}/resolve`, {});
  }

  /** Dispatcher only. Without a crew the first eligible available crew (by name) is chosen. */
  assignIncident(incidentId: string, crewId?: string): Promise<IncidentDetail> {
    return this.write(`/api/v1/ops/incidents/${encodeURIComponent(incidentId)}/assign`, crewId ? { crew_id: crewId } : {});
  }

  /** Dispatcher only: assign open incidents in severity order until crews run out. */
  autoDispatch(): Promise<AutoDispatchResult> {
    return this.write("/api/v1/ops/dispatch/auto", {});
  }

  /** Technician only. */
  sendTeam(incidentId: string): Promise<IncidentDetail> {
    return this.write(`/api/v1/ops/incidents/${encodeURIComponent(incidentId)}/send-team`, {});
  }

  /** Technician only. Timezone-aware ISO 8601 times; at most 4 hours. */
  scheduleMeeting(incidentId: string, start: string, end: string): Promise<IncidentDetail> {
    return this.write(`/api/v1/ops/incidents/${encodeURIComponent(incidentId)}/meeting`, { start, end });
  }

  opsTeams(signal?: AbortSignal): Promise<TeamsView> {
    return this.request("/api/v1/ops/teams", { signal });
  }

  /** Supervisor only; a synthetic monthly estimate, not invoices. */
  opsRevenue(signal?: AbortSignal): Promise<RevenueView> {
    return this.request("/api/v1/ops/revenue", { signal });
  }

  opsCapacity(signal?: AbortSignal): Promise<CapacityView> {
    return this.request("/api/v1/ops/capacity", { signal });
  }

  /** Power Block Offers, manager (supervisor) only; scoped to the manager's areas. */
  managerOffers(status?: ManagerOffer["status"], signal?: AbortSignal): Promise<ManagerOffer[]> {
    const query = status ? `?${new URLSearchParams({ status })}` : "";
    return this.request(`/api/v1/manager/offers${query}`, { signal });
  }

  managerOffer(offerId: string, signal?: AbortSignal): Promise<ManagerOfferDetail> {
    return this.request(`/api/v1/manager/offers/${encodeURIComponent(offerId)}`, { signal });
  }

  /** Creates a draft (201). kWh and prices are decimal strings, e.g. "10" and "0.55". */
  createOffer(draft: OfferDraft): Promise<ManagerOfferDetail> {
    return this.write("/api/v1/manager/offers", draft);
  }

  /** Replaces the terms; 409 offer_locked once any client has accepted. */
  updateOffer(offerId: string, draft: OfferDraft): Promise<ManagerOfferDetail> {
    return this.write(`/api/v1/manager/offers/${encodeURIComponent(offerId)}`, draft);
  }

  /** Validates terms and audience without saving anything. */
  previewOfferDraft(draft: OfferDraft): Promise<OfferPreview> {
    return this.write("/api/v1/manager/offers/preview", draft);
  }

  previewOffer(offerId: string, signal?: AbortSignal): Promise<OfferPreview> {
    return this.request(`/api/v1/manager/offers/${encodeURIComponent(offerId)}/preview`, { signal });
  }

  publishOffer(offerId: string): Promise<ManagerOfferDetail> {
    return this.write(`/api/v1/manager/offers/${encodeURIComponent(offerId)}/publish`, {});
  }

  /** Running windows close now and settle what was delivered, with the penalty waived. */
  cancelOffer(offerId: string): Promise<ManagerOfferDetail> {
    return this.write(`/api/v1/manager/offers/${encodeURIComponent(offerId)}/cancel`, {});
  }

  offerAudit(offerId: string, signal?: AbortSignal): Promise<AuditEntry[]> {
    return this.request(`/api/v1/manager/offers/${encodeURIComponent(offerId)}/audit`, { signal });
  }

  /** Clients with sites in the manager's areas, for hand-picked targeting. */
  offerClients(areaId?: string, signal?: AbortSignal): Promise<ManagerClient[]> {
    const query = areaId ? `?${new URLSearchParams({ area_id: areaId })}` : "";
    return this.request(`/api/v1/manager/clients${query}`, { signal });
  }

  /** Customer only: open offers targeted at one of the caller's sites, not yet accepted. */
  offers(signal?: AbortSignal): Promise<ClientOffer[]> {
    return this.request("/api/v1/offers", { signal });
  }

  /**
   * Customer only. Pass a stable idempotencyKey (e.g. crypto.randomUUID() per click) so a
   * retried request returns the original acceptance instead of 409 already_accepted.
   */
  acceptOffer(offerId: string, siteId?: string, idempotencyKey?: string): Promise<UserOffer> {
    return this.write(
      `/api/v1/offers/${encodeURIComponent(offerId)}/accept`,
      siteId ? { site_id: siteId } : {},
      idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    );
  }

  /** Progress (metered_kwh, remaining_kwh, coverage_ratio) is computed live on every read. */
  myOffers(status: "active" | "history" | "all" = "all", signal?: AbortSignal): Promise<UserOffer[]> {
    return this.request(`/api/v1/offers/mine?${new URLSearchParams({ status })}`, { signal });
  }

  /** Savings/Earnings counter; money is integer bani (divide by 100 for RON). */
  offerSavings(signal?: AbortSignal): Promise<SavingsSummary> {
    return this.request("/api/v1/offers/savings", { signal });
  }

  notifications(unread = false, signal?: AbortSignal): Promise<NotificationList> {
    return this.request(`/api/v1/notifications?${new URLSearchParams({ unread: String(unread) })}`, { signal });
  }

  markNotificationRead(notificationId: string): Promise<NotificationList> {
    return this.write(`/api/v1/notifications/${encodeURIComponent(notificationId)}/read`, {});
  }

  markAllNotificationsRead(): Promise<NotificationList> {
    return this.write("/api/v1/notifications/read-all", {});
  }

  /** Analytical clock: live wall time, or the local forward-only scenario clock (read-only). */
  clock(signal?: AbortSignal): Promise<ClockView> {
    return this.request("/api/v1/clock", { signal });
  }

  /** Business task planner: flexible, non-interruptible tasks of one authorized site. */
  tasks(siteId: string, signal?: AbortSignal): Promise<Task[]> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/tasks`, { signal });
  }

  createTask(siteId: string, task: TaskCreate): Promise<Task> {
    return this.write(`/api/v1/sites/${encodeURIComponent(siteId)}/tasks`, task);
  }

  /** Rejected with 409 task_committed once accepted; review (release) it first. */
  updateTask(siteId: string, taskId: string, task: TaskUpdate): Promise<Task> {
    return this.write(`/api/v1/sites/${encodeURIComponent(siteId)}/tasks/${encodeURIComponent(taskId)}`, task);
  }

  cancelTask(siteId: string, taskId: string): Promise<Task> {
    return this.write(`/api/v1/sites/${encodeURIComponent(siteId)}/tasks/${encodeURIComponent(taskId)}/cancel`, {});
  }

  /** Recomputed at the analytical time on every read; costs are estimates (null = unknown). */
  plan(siteId: string, taskId: string, signal?: AbortSignal): Promise<PlanDecision> {
    return this.request(
      `/api/v1/sites/${encodeURIComponent(siteId)}/plan?${new URLSearchParams({ task: taskId })}`,
      { signal },
    );
  }

  /**
   * Accept the recommendation the customer saw (409 recommendation_changed if it moved).
   * Pass a stable idempotencyKey per click; a repeat returns the original commitment.
   */
  acceptTask(siteId: string, taskId: string, body: AcceptTask, idempotencyKey?: string): Promise<Task> {
    return this.write(
      `/api/v1/sites/${encodeURIComponent(siteId)}/tasks/${encodeURIComponent(taskId)}/accept`,
      body,
      idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    );
  }

  /** Explicit review: release an accepted plan that has not started yet. */
  reviewTask(siteId: string, taskId: string, body: ReviewTask): Promise<Task> {
    return this.write(`/api/v1/sites/${encodeURIComponent(siteId)}/tasks/${encodeURIComponent(taskId)}/review`, body);
  }

  /** Measured whole-site grid energy for the accepted window, plus a labelled estimate. */
  taskProgress(siteId: string, taskId: string, signal?: AbortSignal): Promise<TaskProgress> {
    return this.request(
      `/api/v1/sites/${encodeURIComponent(siteId)}/tasks/${encodeURIComponent(taskId)}/progress`,
      { signal },
    );
  }

  /**
   * Equipment evidence summary per family (meter, battery, weather): selected source,
   * recent values, freshness, capability decisions with reason codes, synthetic label.
   */
  equipmentSummary(siteId: string, signal?: AbortSignal): Promise<EquipmentSummary> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/equipment/summary`, { signal });
  }

  /**
   * Home cards: latest PV, grid import, grid export and DERIVED consumption (kW) plus today's kWh totals,
   * for provider sites with component meters. A missing input is `value: null` with a `reason`.
   */
  siteEnergyOverview(siteId: string, signal?: AbortSignal): Promise<EnergyOverview> {
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/energy/overview`, { signal });
  }

  /**
   * Production / consumption / grid import / export buckets for today (hourly), week and month (daily)
   * or year (monthly). Each bucket is `measured`, `derived` or a clearly labelled `synthetic_profile`.
   */
  siteEnergyPeriods(
    siteId: string,
    period: "today" | "week" | "month" | "year",
    signal?: AbortSignal,
  ): Promise<EnergyPeriods> {
    return this.request(
      `/api/v1/sites/${encodeURIComponent(siteId)}/energy/periods?period=${period}`,
      { signal },
    );
  }

  /** Bounded 15-minute evidence frames (at most 7 days, limit <= 1000); no raw payloads. */
  equipmentEvidence(siteId: string, options: EquipmentEvidenceQuery, signal?: AbortSignal): Promise<EquipmentEvidence> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined) query.set(key, String(value));
    }
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/equipment/evidence?${query}`, { signal });
  }

  /**
   * Ranked work queue (operations roles): priority band first, then the demo-policy score.
   * Every item carries rank explanation, episode summary and workflow at one ops revision.
   */
  opsQueue(status: "open" | "all" = "open", signal?: AbortSignal): Promise<QueueView> {
    return this.request(`/api/v1/ops/queue?${new URLSearchParams({ status })}`, { signal });
  }

  /** Episode drawer: hypothesis, evidence, rule, rank explanation/history, overrides, log. */
  opsEpisode(incidentId: string, signal?: AbortSignal): Promise<EpisodeDetail> {
    return this.request(`/api/v1/ops/episodes/${encodeURIComponent(incidentId)}`, { signal });
  }

  acknowledgeEpisode(incidentId: string): Promise<EpisodeDetail> {
    return this.write(`/api/v1/ops/episodes/${encodeURIComponent(incidentId)}/acknowledge`, {});
  }

  /** Authorized documented closure (dispatcher or the assigned crew); children stay open. */
  closeEpisode(incidentId: string, body: CloseRequest): Promise<EpisodeDetail> {
    return this.write(`/api/v1/ops/episodes/${encodeURIComponent(incidentId)}/close`, body);
  }

  /** Dispatcher only; expires on the analytical clock; the computed rank is preserved. */
  overridePriority(incidentId: string, body: OverrideRequest): Promise<EpisodeDetail> {
    return this.write(`/api/v1/ops/episodes/${encodeURIComponent(incidentId)}/priority-override`, body);
  }

  revokePriorityOverride(incidentId: string): Promise<EpisodeDetail> {
    return this.write(`/api/v1/ops/episodes/${encodeURIComponent(incidentId)}/priority-override/revoke`, {});
  }

  /** Common site-status projection (same revision as queue/map); scoped server-side. */
  opsStatus(signal?: AbortSignal): Promise<StatusProjection> {
    return this.request("/api/v1/ops/status", { signal });
  }

  opsUnmapped(signal?: AbortSignal): Promise<UnmappedSites> {
    return this.request("/api/v1/ops/unmapped", { signal });
  }

  /** Feasible heuristic proposal (draft) plus the FIFO baseline comparison. */
  proposeCrewPlan(body: ProposeRequest = { horizon_hours: 12 }): Promise<CrewPlanView> {
    return this.write("/api/v1/ops/plans", body);
  }

  latestCrewPlan(signal?: AbortSignal): Promise<CrewPlanView> {
    return this.request("/api/v1/ops/plans/latest", { signal });
  }

  crewPlan(planId: string, signal?: AbortSignal): Promise<CrewPlanView> {
    return this.request(`/api/v1/ops/plans/${encodeURIComponent(planId)}`, { signal });
  }

  /** Dispatch capability only (supervisors get 403). */
  reviewCrewPlan(planId: string): Promise<CrewPlanView> {
    return this.write(`/api/v1/ops/plans/${encodeURIComponent(planId)}/review`, {});
  }

  /**
   * Dispatch capability only. 409 plan_stale when inputs changed (a new draft is computed;
   * reload latestCrewPlan), plan_already_applied, plan_superseded or plan_not_reviewed.
   * Pass a stable idempotencyKey per click so a retry returns the applied plan.
   */
  applyCrewPlan(planId: string, expectedInputDigest: string, idempotencyKey?: string): Promise<CrewPlanView> {
    const body: ApplyRequest = { expected_input_digest: expectedInputDigest };
    return this.write(
      `/api/v1/ops/plans/${encodeURIComponent(planId)}/apply`,
      body,
      idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
    );
  }

  /** Technician: own crews' assignments; dispatch/supervisor: visible crews. */
  opsAgenda(signal?: AbortSignal): Promise<AgendaView> {
    return this.request("/api/v1/ops/agenda", { signal });
  }

  /** Technician of the assigned crew; forward-only en_route -> on_site -> done (note required). */
  updateAssignmentProgress(assignmentId: string, body: ProgressRequest): Promise<AgendaView> {
    return this.write(`/api/v1/ops/assignments/${encodeURIComponent(assignmentId)}/progress`, body);
  }

  /** State changes need the session's CSRF token; restore it after a page reload. */
  private async write<T>(path: string, body: unknown, headers?: Record<string, string>): Promise<T> {
    if (!this.csrfToken) await this.me();
    return this.request<T>(path, { method: "POST", body: JSON.stringify(body), headers });
  }

  private providerHistory<T>(siteId: string, kind: "observations" | "frames", options: ProviderHistoryQuery, signal?: AbortSignal): Promise<T> {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(options)) {
      if (value !== undefined) query.set(key, String(value));
    }
    return this.request(`/api/v1/sites/${encodeURIComponent(siteId)}/provider/${kind}?${query}`, { signal });
  }
}

export type EquipmentEvidenceQuery = {
  from: string;
  to: string;
  family?: "meter" | "battery" | "weather";
  metric?: string;
  limit?: number;
  offset?: number;
};

export type ProviderHistoryQuery = {
  from: string;
  to: string;
  metric?: string;
  endpoint?: string;
  device?: string;
  channel?: string;
  limit?: number;
  offset?: number;
};

/** Poll visible views every five seconds; stop on unmount or sign-out. */
export function poll<T>(
  load: (signal: AbortSignal) => Promise<T>,
  onData: (data: T) => void,
  onError: (error: unknown) => void,
): () => void {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  const tick = async (): Promise<void> => {
    try {
      const data = await load(controller.signal);
      if (controller.signal.aborted) return;
      failures = 0;
      onData(data);
    } catch (error) {
      if (controller.signal.aborted) return;
      onError(error);
      if (error instanceof SolarApiError && (error.status === 401 || error.status === 403 || error.status === 404)) return;
      failures += 1;
    }
    if (!controller.signal.aborted) timer = setTimeout(tick, Math.min(5000 * 2 ** failures, 30000));
  };
  void tick();
  return () => {
    controller.abort();
    if (timer !== undefined) clearTimeout(timer);
  };
}
