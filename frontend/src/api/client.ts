import type { components } from "./schema";

export type Health = components["schemas"]["HealthResponse"];
export type RunSummary = components["schemas"]["RunSummaryResponse"];
export type RunDetail = components["schemas"]["RunDetailResponse"];
export type RunEvent = components["schemas"]["RunEventResponse"];
export type Asset = components["schemas"]["AssetResponse"];
export type AssetStatus = components["schemas"]["AssetStatus"];
export type AssetPatch = components["schemas"]["AssetPatchRequest"];
export type RunCreated = components["schemas"]["RunCreatedResponse"];
export type ManualURLRequest = components["schemas"]["ManualURLRequest"];
export type ApprovalRequest = components["schemas"]["ApprovalRequest"];
export type BudgetSummary = components["schemas"]["BudgetSummaryResponse"];
export type Clip = components["schemas"]["ClipResponse"];
export type ClipList = components["schemas"]["ClipListResponse"];
export type DashboardSummary = components["schemas"]["DashboardSummaryResponse"];
export type JsonObject = Record<string, unknown>;
export type RenderRevision = components["schemas"]["RenderRevisionResponse"];
export type SavedRenderRecipe = components["schemas"]["SavedNewsRenderRequest"];

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" }, signal });
  if (response.status === 204) return null as T;
  if (!response.ok) {
    let message = response.status >= 500 ? "ClipFactory API is unavailable. Start the backend and retry." : `Request failed (${response.status})`;
    try {
      const payload: unknown = await response.json();
      if (isApiErrorPayload(payload)) message = payload.error.message;
    } catch {
      if (response.status < 500) message = response.statusText || message;
    }
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as T;
}

async function apiMutation<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let message = response.status >= 500 ? "ClipFactory API is unavailable. Start the backend and retry." : `Request failed (${response.status})`;
    let details: unknown;
    try {
      const payload: unknown = await response.json();
      if (isApiErrorPayload(payload)) {
        message = payload.error.message;
        details = payload.error.details;
      }
    } catch {
      // Keep the status-derived message when the response is not JSON.
    }
    throw new ApiError(message, response.status, details);
  }
  return (await response.json()) as T;
}

export function startRunNow(): Promise<RunCreated> {
  return apiMutation<RunCreated>("POST", "/api/runs");
}

export function continueRun(runId: string): Promise<RunCreated> {
  return apiMutation<RunCreated>("POST", `/api/runs/${encodeURIComponent(runId)}/continue`);
}

export function stopRun(runId: string): Promise<RunCreated> {
  return apiMutation<RunCreated>("POST", `/api/runs/${encodeURIComponent(runId)}/stop`);
}

export function renderSavedNews(request: SavedRenderRecipe): Promise<RenderRevision> {
  return apiMutation<RenderRevision>("POST", "/api/render-revisions", request);
}

export function startManualURL(request: ManualURLRequest): Promise<RunCreated> {
  return apiMutation<RunCreated>("POST", "/api/runs/manual-url", request);
}

export function updateSettings(section: string, value: JsonObject): Promise<unknown> {
  return apiMutation("PUT", `/api/settings/${encodeURIComponent(section)}`, value);
}

export function updateContentProfile(value: JsonObject): Promise<unknown> {
  return apiMutation("PUT", "/api/content-profile", value);
}

export function decideApproval(clipId: string, request: ApprovalRequest): Promise<unknown> {
  return apiMutation("POST", `/api/clips/${encodeURIComponent(clipId)}/approval`, request);
}

export function getHealth(signal?: AbortSignal): Promise<Health> {
  return apiGet<Health>("/api/health", signal);
}

export function getRuns(limit = 10, status?: string, signal?: AbortSignal): Promise<{ items: RunSummary[] }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  return apiGet(`/api/runs?${params.toString()}`, signal);
}

export function getActiveRun(signal?: AbortSignal): Promise<RunSummary | null> {
  return fetch("/api/runs/active", { headers: { Accept: "application/json" }, signal }).then(async (response) => {
    if (response.status === 204) return null;
    if (!response.ok) throw new ApiError(response.statusText || `Request failed (${response.status})`, response.status);
    return (await response.json()) as RunSummary;
  });
}

export function getRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
  return apiGet(`/api/runs/${encodeURIComponent(runId)}`, signal);
}

export function getAssets(status: AssetStatus | "all", signal?: AbortSignal): Promise<{ items: Asset[] }> {
  const query = new URLSearchParams({ limit: "500" });
  if (status !== "all") query.set("status", status);
  return apiGet(`/api/assets?${query.toString()}`, signal);
}

export async function patchAsset(assetId: string, changes: AssetPatch): Promise<Asset> {
  const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    const message = response.status >= 500 ? "ClipFactory API is unavailable. Start the backend and retry." : `Request failed (${response.status})`;
    throw new ApiError(message, response.status);
  }
  return (await response.json()) as Asset;
}

function isApiErrorPayload(value: unknown): value is { error: { message: string; details?: unknown } } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = value.error;
  return typeof error === "object" && error !== null && "message" in error && typeof error.message === "string";
}