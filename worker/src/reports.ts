import type { Env, ReportInput, ReportRow } from "./types";

const MAX_LIST_RESULTS = 500;

export function recommendedReportWeight(reportCount: number): number {
  if (reportCount < 3) return 0;
  if (reportCount <= 5) return 0.1;
  if (reportCount <= 15) return 0.2;
  return 0.3;
}

export async function insertReport(db: D1Database, input: ReportInput, reporterHash: string): Promise<string> {
  const id = crypto.randomUUID();
  const createdAt = new Date().toISOString();

  await db
    .prepare(
      `INSERT INTO mosquito_reports
        (id, created_at, cell_id, latitude_rounded, longitude_rounded, severity, terrain, activity, repellent_used, comment, forecast_score, model_version, reporter_hash)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    )
    .bind(
      id,
      createdAt,
      input.cell_id,
      input.latitude_rounded,
      input.longitude_rounded,
      input.severity,
      input.terrain ?? null,
      input.activity ?? null,
      input.repellent_used === undefined ? null : input.repellent_used ? 1 : 0,
      input.comment ?? null,
      input.forecast_score ?? null,
      input.model_version ?? null,
      reporterHash
    )
    .run();

  return id;
}

export interface ListReportsOptions {
  bbox: { minLat: number; minLon: number; maxLat: number; maxLon: number } | null;
  since: string | null;
}

export async function listReports(db: D1Database, options: ListReportsOptions) {
  const conditions: string[] = [];
  const bindings: unknown[] = [];

  if (options.bbox) {
    conditions.push("latitude_rounded BETWEEN ? AND ? AND longitude_rounded BETWEEN ? AND ?");
    bindings.push(options.bbox.minLat, options.bbox.maxLat, options.bbox.minLon, options.bbox.maxLon);
  }
  if (options.since) {
    conditions.push("created_at > ?");
    bindings.push(options.since);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
  const query = `SELECT id, created_at, cell_id, latitude_rounded, longitude_rounded, severity, terrain, activity, repellent_used, comment, forecast_score, model_version
                 FROM mosquito_reports ${where}
                 ORDER BY created_at DESC
                 LIMIT ${MAX_LIST_RESULTS}`;

  const result = await db.prepare(query).bind(...bindings).all<ReportRow>();
  return result.results ?? [];
}

export async function summaryForCell(db: D1Database, cellId: string, sinceHours: number) {
  const since = new Date(Date.now() - sinceHours * 3600 * 1000).toISOString();

  const row = await db
    .prepare(
      `SELECT COUNT(*) as report_count, AVG(severity) as average_severity, MAX(created_at) as most_recent_at
       FROM mosquito_reports WHERE cell_id = ? AND created_at > ?`
    )
    .bind(cellId, since)
    .first<{ report_count: number; average_severity: number | null; most_recent_at: string | null }>();

  const reportCount = row?.report_count ?? 0;

  return {
    cell_id: cellId,
    report_count: reportCount,
    average_severity: row?.average_severity ?? null,
    most_recent_at: row?.most_recent_at ?? null,
    recommended_report_weight: recommendedReportWeight(reportCount),
  };
}
