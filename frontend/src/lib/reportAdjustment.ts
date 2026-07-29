import type { ReportSummary } from "./reportsApi";
import { clamp } from "./riskModel";

// Mirrors the tiered report-weighting rules in forecast/model.yaml
// (report_adjustment). The Worker's /api/reports/summary endpoint applies
// the same tiers server-side and returns recommended_report_weight; this
// is a client-side fallback/duplicate so the UI can compute an adjustment
// even if that field is ever missing from the response.
export function recommendedReportWeight(reportCount: number): number {
  if (reportCount < 3) return 0;
  if (reportCount <= 5) return 0.1;
  if (reportCount <= 15) return 0.2;
  return 0.3;
}

export function severityToRiskScale(averageSeverity: number): number {
  return clamp(averageSeverity * 25, 0, 100);
}

export interface AdjustedRisk {
  modelRisk: number;
  adjustedRisk: number;
  weight: number;
  applied: boolean;
}

export function computeAdjustedRisk(modelRisk: number, summary: ReportSummary | null): AdjustedRisk {
  if (!summary || summary.report_count < 3 || summary.average_severity === null) {
    return { modelRisk, adjustedRisk: modelRisk, weight: 0, applied: false };
  }
  const weight = clamp(
    summary.recommended_report_weight ?? recommendedReportWeight(summary.report_count),
    0,
    0.3
  );
  const reportRisk = severityToRiskScale(summary.average_severity);
  const adjusted = clamp(modelRisk * (1 - weight) + reportRisk * weight, 0, 100);
  return { modelRisk, adjustedRisk: adjusted, weight, applied: weight > 0 };
}
