import { describe, expect, it } from "vitest";
import { clamp, confidenceLabel, exposureForActivity, finalRiskForActivity, riskCategory } from "../riskModel";

describe("clamp", () => {
  it("bounds values within range", () => {
    expect(clamp(5, 0, 10)).toBe(5);
    expect(clamp(-5, 0, 10)).toBe(0);
    expect(clamp(15, 0, 10)).toBe(10);
  });
});

describe("riskCategory", () => {
  it("maps boundary scores to the documented categories", () => {
    expect(riskCategory(0).key).toBe("very_low");
    expect(riskCategory(1.9).key).toBe("very_low");
    expect(riskCategory(2.0).key).toBe("low");
    expect(riskCategory(5.9).key).toBe("moderate");
    expect(riskCategory(6.0).key).toBe("high");
    expect(riskCategory(8.0).key).toBe("very_high");
    expect(riskCategory(10.0).key).toBe("very_high");
  });
});

describe("confidenceLabel", () => {
  it("maps confidence values to Low/Medium/High", () => {
    expect(confidenceLabel(0.1)).toBe("Low");
    expect(confidenceLabel(0.39)).toBe("Low");
    expect(confidenceLabel(0.4)).toBe("Medium");
    expect(confidenceLabel(0.69)).toBe("Medium");
    expect(confidenceLabel(0.7)).toBe("High");
    expect(confidenceLabel(1.0)).toBe("High");
  });
});

describe("exposureForActivity", () => {
  it("scales with the activity multiplier and stays within [0,10]", () => {
    const general = exposureForActivity(0.5, 1.0);
    const camping = exposureForActivity(0.5, 1.35);
    expect(camping).toBeGreaterThan(general);
    expect(camping).toBeLessThanOrEqual(10);
    expect(exposureForActivity(0, 1.0)).toBe(0);
  });
});

describe("finalRiskForActivity", () => {
  it("stays within [0, 10]", () => {
    const risk = finalRiskForActivity(8, 8, 0.8, 1.35);
    expect(risk).toBeGreaterThanOrEqual(0);
    expect(risk).toBeLessThanOrEqual(10);
  });

  it("is zero when any component is zero", () => {
    expect(finalRiskForActivity(0, 8, 0.8, 1.0)).toBe(0);
    expect(finalRiskForActivity(8, 0, 0.8, 1.0)).toBe(0);
    expect(finalRiskForActivity(8, 8, 0, 1.0)).toBe(0);
  });

  it("increases monotonically with the activity multiplier", () => {
    const running = finalRiskForActivity(6, 6, 0.6, 0.75);
    const camping = finalRiskForActivity(6, 6, 0.6, 1.35);
    expect(camping).toBeGreaterThan(running);
  });
});
