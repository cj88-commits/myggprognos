// Client for the optional Cloudflare Worker reporting API. The app must
// stay fully usable when this API is unreachable (offline, not yet
// deployed, etc.) -- every function here fails soft and returns a
// clearly-marked "unavailable" result rather than throwing into the UI.

export interface ReportPayload {
  cell_id: string;
  latitude_rounded: number;
  longitude_rounded: number;
  severity: number; // 0-4 (None..Unbearable)
  terrain?: string;
  activity?: string;
  repellent_used?: boolean;
  comment?: string;
  forecast_score?: number;
  model_version?: string;
  // Forecast context at submission time (docs/wind-calm-investigation.md
  // item 10) -- lets a future false-negative analysis join reports back to
  // exactly what the model knew, without needing forecast archives that
  // may no longer be retained.
  forecast_wind_ms?: number;
  effective_wind_ms?: number;
  temperature_c?: number;
  humidity_pct?: number;
  population_potential?: number;
  biting_activity?: number;
  target_timestamp?: string;
}

export interface ReportSummary {
  cell_id: string;
  report_count: number;
  average_severity: number | null;
  most_recent_at: string | null;
  recommended_report_weight: number;
}

const API_BASE = (import.meta.env.VITE_REPORT_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export const SEVERITY_LABELS = ["None", "A few", "Noticeable", "Many", "Unbearable"];
export const TERRAIN_OPTIONS = ["Urban", "Open countryside", "Forest", "Wetland", "Waterside"];
export const ACTIVITY_OPTIONS = ["Stationary", "Walking", "Running", "Camping", "Fishing", "Gardening"];

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await promise;
  } finally {
    clearTimeout(timer);
  }
}

export function isReportingConfigured(): boolean {
  return API_BASE.length > 0;
}

export async function checkHealth(): Promise<ApiResult<{ status: string }>> {
  if (!isReportingConfigured()) return { ok: false, error: "Reporting API is not configured" };
  try {
    const res = await withTimeout(fetch(`${API_BASE}/api/health`), 5000);
    if (!res.ok) return { ok: false, error: `Health check failed (${res.status})` };
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
}

export async function submitReport(payload: ReportPayload): Promise<ApiResult<{ id: string }>> {
  if (!isReportingConfigured()) return { ok: false, error: "Reporting API is not configured" };
  try {
    const res = await withTimeout(
      fetch(`${API_BASE}/api/reports`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }),
      8000
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { ok: false, error: body.error ?? `Submission failed (${res.status})` };
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
}

export async function getReportSummary(cellId: string): Promise<ApiResult<ReportSummary>> {
  if (!isReportingConfigured()) return { ok: false, error: "Reporting API is not configured" };
  try {
    const res = await withTimeout(
      fetch(`${API_BASE}/api/reports/summary?cell_id=${encodeURIComponent(cellId)}`),
      6000
    );
    if (!res.ok) return { ok: false, error: `Summary request failed (${res.status})` };
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: (err as Error).message };
  }
}
