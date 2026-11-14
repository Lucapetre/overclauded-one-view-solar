import type {
  Area,
  AreaSummary,
  EnergyHistory,
  EnergySnapshot,
  ErrorEnvelope,
  SessionView,
  Site,
} from "./index";

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
    if (options.body !== undefined) headers.set("Content-Type", "application/json");
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
}

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
