import { describe, expect, it } from "vitest";
import {
  abundanceCategory,
  abundanceColorStops,
  clamp,
  DEFAULT_ABUNDANCE_THRESHOLDS,
  dataQualityCategory,
  exposureForActivity,
  finalRiskForActivity,
  riskCategory,
} from "../riskModel";

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

describe("abundanceCategory", () => {
  it("uses its own bounds, not risk's 0/20/40/60/80", () => {
    // A score of 65 is "very_high" risk (>=80? no -- "high" under risk
    // bounds) but under abundance's real-data-calibrated bounds (28/38/48/58)
    // it should already read as very_high.
    expect(riskCategory(65).key).toBe("high");
    expect(abundanceCategory(65).key).toBe("very_high");
  });

  it("maps boundary scores to the configured edges", () => {
    const edges = [28, 38, 48, 58];
    expect(abundanceCategory(0, edges).key).toBe("very_low");
    expect(abundanceCategory(27.9, edges).key).toBe("very_low");
    expect(abundanceCategory(28, edges).key).toBe("low");
    expect(abundanceCategory(47.9, edges).key).toBe("moderate");
    expect(abundanceCategory(58, edges).key).toBe("very_high");
  });

  it("respects custom edges from the manifest instead of the hardcoded default", () => {
    const custom = [10, 20, 30, 40];
    expect(abundanceCategory(35, custom).key).toBe("high");
    expect(abundanceCategory(35, DEFAULT_ABUNDANCE_THRESHOLDS).key).toBe("low");
  });
});

describe("abundanceColorStops", () => {
  it("produces 6 stops spanning 0-100 anchored to the given edges", () => {
    const stops = abundanceColorStops([28, 38, 48, 58]);
    expect(stops.map((s) => s.value)).toEqual([0, 28, 38, 48, 58, 100]);
  });
});

describe("dataQualityCategory", () => {
  it("maps 0-100 confidence values to the four public-facing quality bands", () => {
    expect(dataQualityCategory(0)).toBe("low");
    expect(dataQualityCategory(39)).toBe("low");
    expect(dataQualityCategory(40)).toBe("limited");
    expect(dataQualityCategory(64)).toBe("limited");
    expect(dataQualityCategory(65)).toBe("good");
    expect(dataQualityCategory(84)).toBe("good");
    expect(dataQualityCategory(85)).toBe("very_good");
    expect(dataQualityCategory(100)).toBe("very_good");
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

  it("is zero when population is zero -- population is the biological gate", () => {
    expect(finalRiskForActivity(0, 80, 0.8, 1.0)).toBe(0);
  });

  it("is NOT zero when only activity or exposure is zero -- they modify, not gate", () => {
    // This is the specific behavior this iteration's formula redesign
    // targets (see docs/model-audit-before.md worked examples B/C): a real
    // population signal should not be crushed to nothing by a single weak
    // modifier the way the old population*activity*exposure product did.
    expect(finalRiskForActivity(80, 0, 0.8, 1.0)).toBeGreaterThan(0);
    expect(finalRiskForActivity(80, 80, 0, 1.0)).toBeGreaterThan(0);
  });

  it("moderate population is not crushed to near zero by low midday activity", () => {
    // Mirrors audit-before.md Example B: population=60 (moderate, real
    // habitat), activity=25 (cool/windy midday), exposure=45 (moderate).
    const risk = finalRiskForActivity(60, 25, 0.45, 1.0);
    expect(risk).toBeGreaterThan(15);
  });

  it("very low activity still meaningfully reduces current nuisance", () => {
    const highActivity = finalRiskForActivity(60, 90, 0.5, 1.0);
    const lowActivity = finalRiskForActivity(60, 10, 0.5, 1.0);
    expect(lowActivity).toBeLessThan(highActivity);
    expect(lowActivity).toBeLessThan(highActivity * 0.7);
  });

  it("exposure adjusts the result but does not dominate it", () => {
    const lowExposure = finalRiskForActivity(70, 70, 0.1, 1.0);
    const highExposure = finalRiskForActivity(70, 70, 0.9, 1.0);
    // Exposure should meaningfully move the score...
    expect(highExposure).toBeGreaterThan(lowExposure);
    // ...but not swing it by more than exposure_modifier's own range
    // (0.75-1.25, i.e. at most ~1.67x), the way a raw 0-1 gate could.
    expect(highExposure / lowExposure).toBeLessThan(2);
  });

  it("increases monotonically with the activity multiplier", () => {
    const running = finalRiskForActivity(60, 60, 0.6, 0.75);
    const camping = finalRiskForActivity(60, 60, 0.6, 1.35);
    expect(camping).toBeGreaterThan(running);
  });

  it("uses manifest-provided combination params instead of a hardcoded copy when given", () => {
    const withDefaults = finalRiskForActivity(60, 60, 0.6, 1.0);
    const withCustom = finalRiskForActivity(60, 60, 0.6, 1.0, {
      activity_floor: 0.1,
      activity_weight: 0.9,
      exposure_floor: 0.5,
      exposure_weight: 1.0,
      scale: 150,
    });
    expect(withCustom).not.toBeCloseTo(withDefaults, 1);
  });
});
