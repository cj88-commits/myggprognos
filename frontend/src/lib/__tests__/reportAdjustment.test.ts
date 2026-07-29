import { describe, expect, it } from "vitest";
import { computeAdjustedRisk, recommendedReportWeight, severityToRiskScale } from "../reportAdjustment";
import type { ReportSummary } from "../reportsApi";

describe("recommendedReportWeight", () => {
  it("applies the tiered caps from the product spec", () => {
    expect(recommendedReportWeight(0)).toBe(0);
    expect(recommendedReportWeight(2)).toBe(0);
    expect(recommendedReportWeight(3)).toBe(0.1);
    expect(recommendedReportWeight(5)).toBe(0.1);
    expect(recommendedReportWeight(6)).toBe(0.2);
    expect(recommendedReportWeight(15)).toBe(0.2);
    expect(recommendedReportWeight(16)).toBe(0.3);
    expect(recommendedReportWeight(1000)).toBe(0.3);
  });
});

describe("severityToRiskScale", () => {
  it("maps 0-4 severity onto the 0-10 risk scale", () => {
    expect(severityToRiskScale(0)).toBe(0);
    expect(severityToRiskScale(4)).toBe(10);
    expect(severityToRiskScale(2)).toBe(5);
  });
});

function summary(overrides: Partial<ReportSummary>): ReportSummary {
  return {
    cell_id: "SE_TEST",
    report_count: 0,
    average_severity: null,
    most_recent_at: null,
    recommended_report_weight: 0,
    ...overrides,
  };
}

describe("computeAdjustedRisk", () => {
  it("never adjusts with fewer than 3 reports", () => {
    const result = computeAdjustedRisk(5.0, summary({ report_count: 2, average_severity: 4 }));
    expect(result.applied).toBe(false);
    expect(result.adjustedRisk).toBe(5.0);
  });

  it("never adjusts with no reports at all", () => {
    const result = computeAdjustedRisk(5.0, null);
    expect(result.applied).toBe(false);
    expect(result.adjustedRisk).toBe(5.0);
  });

  it("blends model and report risk within the capped weight", () => {
    const result = computeAdjustedRisk(
      2.0,
      summary({ report_count: 10, average_severity: 4, recommended_report_weight: 0.2 })
    );
    expect(result.applied).toBe(true);
    expect(result.weight).toBe(0.2);
    // 2.0 * 0.8 + 10.0 * 0.2 = 3.6
    expect(result.adjustedRisk).toBeCloseTo(3.6, 5);
  });

  it("caps the effective weight at 0.3 even if the server sends more", () => {
    const result = computeAdjustedRisk(
      0.0,
      summary({ report_count: 100, average_severity: 4, recommended_report_weight: 0.9 })
    );
    expect(result.weight).toBe(0.3);
  });
});
