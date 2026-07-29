import { describe, expect, it } from "vitest";
import { recommendedReportWeight } from "../src/reports";

describe("recommendedReportWeight", () => {
  it("applies the tiered caps from model.yaml report_adjustment", () => {
    expect(recommendedReportWeight(0)).toBe(0);
    expect(recommendedReportWeight(2)).toBe(0);
    expect(recommendedReportWeight(3)).toBe(0.1);
    expect(recommendedReportWeight(5)).toBe(0.1);
    expect(recommendedReportWeight(6)).toBe(0.2);
    expect(recommendedReportWeight(15)).toBe(0.2);
    expect(recommendedReportWeight(16)).toBe(0.3);
    expect(recommendedReportWeight(500)).toBe(0.3);
  });
});
