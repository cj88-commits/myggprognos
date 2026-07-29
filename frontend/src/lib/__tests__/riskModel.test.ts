import { describe, expect, it } from "vitest";
import { clamp, confidenceCategory, exposureForActivity, finalRiskForActivity, riskCategory } from "../riskModel";

describe("clamp", () => {
  it("bounds values within range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(15, 0, 10)).toBe(10);
  });
});

describe("riskCategory", () => {
  it("maps boundary scores to the documented 0-100 categories", () => {
    expect(riskCategory(0).key).toBe("very_low");
    expect(riskCategory(19).key).toBe("very_low");
    expect(riskCategory(20).key).toBe("low");
    expect(riskCategory(59).key).toBe("moderate");
    expect(riskCategory(60).key).toBe("high");
    expect(riskCategory(80).key).toBe("very_high");
    expect(riskCategory(100).key).toBe("very_high");
  });

  it("handles fractional scores between integer bounds", () => {
    // Regression test: real scores are floats (e.g. 19.13), not just the
    // exact integer band edges. A prior implementation used `min <= x <=
    // max` against adjacent integer bounds (...19 / 20...), so any
    // fractional value strictly between two bands matched nothing and
    // silently fell back to the *last* (very_high) entry.
    expect(riskCategory(19.13).key).toBe("very_low");
    expect(riskCategory(19.99).key).toBe("very_low");
    expect(riskCategory(39.5).key).toBe("low");
    expect(riskCategory(59.9).key).toBe("moderate");
    expect(riskCategory(79.99).key).toBe("high");
  });
});

describe("confidenceCategory", () => {
  it("maps 0-100 confidence values to low/medium/high", () => {
    expect(confidenceCategory(10)).toBe("low");
    expect(confidenceCategory(39)).toBe("low");
    expect(confidenceCategory(40)).toBe("medium");
    expect(confidenceCategory(69)).toBe("medium");
    expect(confidenceCategory(70)).toBe("high");
    expect(confidenceCategory(100)).toBe("high");
  });
});

describe("exposureForActivity", () => {
  it("scales with the activity multiplier and stays within [0,100]", () => {
    const general = exposureForActivity(0.5, 1.0);
    const camping = exposureForActivity(0.5, 1.35);
    expect(camping).toBeGreaterThan(general);
    expect(camping).toBeLessThanOrEqual(100);
    expect(exposureForActivity(0, 1.0)).toBe(0);
  });
});

describe("finalRiskForActivity", () => {
  it("stays within [0, 100]", () => {
    const risk = finalRiskForActivity(80, 80, 0.8, 1.35);
    expect(risk).toBeGreaterThanOrEqual(0);
    expect(risk).toBeLessThanOrEqual(100);
  });

  it("is zero when any component is zero", () => {
    expect(finalRiskForActivity(0, 80, 0.8, 1.0)).toBe(0);
    expect(finalRiskForActivity(80, 0, 0.8, 1.0)).toBe(0);
    expect(finalRiskForActivity(80, 80, 0, 1.0)).toBe(0);
  });

  it("increases monotonically with the activity multiplier", () => {
    const running = finalRiskForActivity(60, 60, 0.6, 0.75);
    const camping = finalRiskForActivity(60, 60, 0.6, 1.35);
    expect(camping).toBeGreaterThan(running);
  });
});
