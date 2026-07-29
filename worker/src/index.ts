import { corsHeaders, jsonResponse } from "./cors";
import { checkRateLimit, hashReporter } from "./rateLimit";
import { insertReport, listReports, summaryForCell } from "./reports";
import type { Env } from "./types";
import { validateBbox, validateReportInput } from "./validation";

const MAX_BODY_BYTES = 4096;
const DEFAULT_SUMMARY_WINDOW_HOURS = 12;
const DEFAULT_LIST_WINDOW_HOURS = 24;

async function handleHealth(request: Request, env: Env): Promise<Response> {
  try {
    await env.DB.prepare("SELECT 1").first();
    return jsonResponse({ status: "ok", time: new Date().toISOString() }, { status: 200 }, request, env);
  } catch (err) {
    return jsonResponse(
      { status: "degraded", error: "Database unavailable" },
      { status: 503 },
      request,
      env
    );
  }
}

async function handleSubmitReport(request: Request, env: Env): Promise<Response> {
  const contentLength = Number(request.headers.get("Content-Length") ?? "0");
  if (contentLength > MAX_BODY_BYTES) {
    return jsonResponse({ error: "Request body too large" }, { status: 413 }, request, env);
  }

  const rawBody = await request.text();
  if (rawBody.length > MAX_BODY_BYTES) {
    return jsonResponse({ error: "Request body too large" }, { status: 413 }, request, env);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawBody);
  } catch {
    return jsonResponse({ error: "Invalid JSON body" }, { status: 400 }, request, env);
  }

  const validation = validateReportInput(parsed);
  if (!validation.ok || !validation.value) {
    return jsonResponse({ error: "Validation failed", details: validation.errors }, { status: 400 }, request, env);
  }

  const reporterHash = await hashReporter(request, env);
  const rateLimit = await checkRateLimit(env.DB, reporterHash);
  if (!rateLimit.allowed) {
    return jsonResponse({ error: rateLimit.reason ?? "Rate limit exceeded" }, { status: 429 }, request, env);
  }

  try {
    const id = await insertReport(env.DB, validation.value, reporterHash);
    return jsonResponse({ id }, { status: 201 }, request, env);
  } catch (err) {
    // Never leak raw DB error details to the client.
    return jsonResponse({ error: "Could not save report" }, { status: 500 }, request, env);
  }
}

async function handleListReports(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const bbox = validateBbox(url.searchParams.get("bbox"));
  if (url.searchParams.get("bbox") && !bbox) {
    return jsonResponse({ error: "Invalid bbox parameter; expected minLon,minLat,maxLon,maxLat" }, { status: 400 }, request, env);
  }
  const since = url.searchParams.get("since") ?? new Date(Date.now() - DEFAULT_LIST_WINDOW_HOURS * 3600 * 1000).toISOString();

  try {
    const reports = await listReports(env.DB, { bbox, since });
    return jsonResponse({ reports }, { status: 200 }, request, env);
  } catch (err) {
    return jsonResponse({ error: "Could not load reports" }, { status: 500 }, request, env);
  }
}

async function handleReportSummary(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const cellId = url.searchParams.get("cell_id");
  if (!cellId || !/^[A-Z0-9_]{3,32}$/.test(cellId)) {
    return jsonResponse({ error: "cell_id query parameter is required" }, { status: 400 }, request, env);
  }
  const sinceParam = url.searchParams.get("since_hours");
  const sinceHours = sinceParam ? Math.min(168, Math.max(1, Number(sinceParam) || DEFAULT_SUMMARY_WINDOW_HOURS)) : DEFAULT_SUMMARY_WINDOW_HOURS;

  try {
    const summary = await summaryForCell(env.DB, cellId, sinceHours);
    return jsonResponse(summary, { status: 200 }, request, env);
  } catch (err) {
    return jsonResponse({ error: "Could not load report summary" }, { status: 500 }, request, env);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(request, env) });
    }

    try {
      if (url.pathname === "/api/health" && request.method === "GET") {
        return await handleHealth(request, env);
      }
      if (url.pathname === "/api/reports" && request.method === "POST") {
        return await handleSubmitReport(request, env);
      }
      if (url.pathname === "/api/reports" && request.method === "GET") {
        return await handleListReports(request, env);
      }
      if (url.pathname === "/api/reports/summary" && request.method === "GET") {
        return await handleReportSummary(request, env);
      }
      return jsonResponse({ error: "Not found" }, { status: 404 }, request, env);
    } catch (err) {
      return jsonResponse({ error: "Internal server error" }, { status: 500 }, request, env);
    }
  },
};
