import { describe, expect, it } from "vitest";
import { validateBbox, validateReportInput } from "../src/validation";

const validBody = {
  cell_id: "SE_STHLM",
  latitude_rounded: 59.33,
  longitude_rounded: 18.07,
  severity: 2,
};

describe("validateReportInput", () => {
  it("accepts a minimal valid report", () => {
    const result = validateReportInput(validBody);
    expect(result.ok).toBe(true);
    expect(result.value?.cell_id).toBe("SE_STHLM");
  });

  it("accepts a fully populated valid report", () => {
    const result = validateReportInput({
      ...validBody,
      terrain: "Forest",
      activity: "Camping",
      repellent_used: true,
      comment: "Lots of mosquitoes near the lake this evening.",
      forecast_score: 72,
      model_version: "0.1.0",
    });
    expect(result.ok).toBe(true);
  });

  it("rejects a non-object body", () => {
    expect(validateReportInput(null).ok).toBe(false);
    expect(validateReportInput("hello").ok).toBe(false);
  });

  it("rejects missing or malformed cell_id", () => {
    expect(validateReportInput({ ...validBody, cell_id: undefined }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, cell_id: "../../etc/passwd" }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, cell_id: "x".repeat(50) }).ok).toBe(false);
  });

  it("rejects coordinates outside Sweden", () => {
    expect(validateReportInput({ ...validBody, latitude_rounded: 10.0 }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, longitude_rounded: 100.0 }).ok).toBe(false);
  });

  it("rejects an out-of-range severity", () => {
    expect(validateReportInput({ ...validBody, severity: 5 }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, severity: -1 }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, severity: 1.5 }).ok).toBe(false);
  });

  it("rejects invalid terrain/activity enum values", () => {
    expect(validateReportInput({ ...validBody, terrain: "Volcano" }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, activity: "Skydiving" }).ok).toBe(false);
  });

  it("rejects comments that look like they contain contact info", () => {
    expect(validateReportInput({ ...validBody, comment: "call me at 555-123-4567" }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, comment: "email me at foo@example.com" }).ok).toBe(false);
  });

  it("rejects overly long comments", () => {
    expect(validateReportInput({ ...validBody, comment: "a".repeat(281) }).ok).toBe(false);
  });

  it("rejects an out-of-range forecast_score", () => {
    expect(validateReportInput({ ...validBody, forecast_score: 150 }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, forecast_score: -1 }).ok).toBe(false);
  });

  it("accepts a report with full wind-diagnostics forecast context", () => {
    const result = validateReportInput({
      ...validBody,
      forecast_wind_ms: 4.2,
      effective_wind_ms: 3.1,
      temperature_c: 19.5,
      humidity_pct: 68,
      population_potential: 42.3,
      biting_activity: 55.1,
      target_timestamp: "2026-08-05T20:00:00Z",
    });
    expect(result.ok).toBe(true);
    expect(result.value?.effective_wind_ms).toBe(3.1);
    expect(result.value?.target_timestamp).toBe("2026-08-05T20:00:00Z");
  });

  it("rejects an implausible temperature or a malformed target_timestamp", () => {
    expect(validateReportInput({ ...validBody, temperature_c: 200 }).ok).toBe(false);
    expect(validateReportInput({ ...validBody, target_timestamp: "not-a-date" }).ok).toBe(false);
  });
});

describe("validateBbox", () => {
  it("returns null for a missing bbox", () => {
    expect(validateBbox(null)).toBeNull();
  });

  it("parses a valid bbox", () => {
    const result = validateBbox("10,55,24,69");
    expect(result).toEqual({ minLon: 10, minLat: 55, maxLon: 24, maxLat: 69 });
  });

  it("rejects a malformed bbox", () => {
    expect(validateBbox("not,valid")).toBeNull();
    expect(validateBbox("1,2,3")).toBeNull();
    expect(validateBbox("24,69,10,55")).toBeNull(); // min > max
  });
});
