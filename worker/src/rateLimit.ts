import type { Env } from "./types";

// Hashes the submitter's IP (never stored in plaintext) with a
// deployment-specific salt, purely to support short-window spam/rate
// limiting. The result cannot be reversed to recover the original IP.
export async function hashReporter(request: Request, env: Env): Promise<string> {
  const ip = request.headers.get("CF-Connecting-IP") ?? "unknown";
  const encoder = new TextEncoder();
  const data = encoder.encode(`${env.REPORT_HASH_SALT}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

const MIN_SECONDS_BETWEEN_REPORTS = 30;
const MAX_REPORTS_PER_DAY = 30;

export async function checkRateLimit(
  db: D1Database,
  reporterHash: string
): Promise<{ allowed: boolean; reason?: string }> {
  const now = Date.now();
  const thirtySecondsAgo = new Date(now - MIN_SECONDS_BETWEEN_REPORTS * 1000).toISOString();
  const oneDayAgo = new Date(now - 24 * 3600 * 1000).toISOString();

  const recent = await db
    .prepare("SELECT COUNT(*) as count FROM mosquito_reports WHERE reporter_hash = ? AND created_at > ?")
    .bind(reporterHash, thirtySecondsAgo)
    .first<{ count: number }>();
  if (recent && recent.count > 0) {
    return { allowed: false, reason: "Please wait a bit before submitting another report." };
  }

  const daily = await db
    .prepare("SELECT COUNT(*) as count FROM mosquito_reports WHERE reporter_hash = ? AND created_at > ?")
    .bind(reporterHash, oneDayAgo)
    .first<{ count: number }>();
  if (daily && daily.count >= MAX_REPORTS_PER_DAY) {
    return { allowed: false, reason: "Daily report limit reached." };
  }

  return { allowed: true };
}
