import { describe, expect, it } from "vitest";
import { parseUrlState, serializeUrlState } from "../urlState";

describe("parseUrlState", () => {
  it("parses a fully specified query string", () => {
    const state = parseUrlState("?lat=59.3293&lon=18.0686&date=2026-07-29&hour=5&activity=camping&layer=confidence");
    expect(state.lat).toBeCloseTo(59.3293);
    expect(state.lon).toBeCloseTo(18.0686);
    expect(state.date).toBe("2026-07-29");
    expect(state.hour).toBe(5);
    expect(state.activity).toBe("camping");
    expect(state.layer).toBe("confidence");
  });

  it("ignores out-of-range or malformed values", () => {
    const state = parseUrlState("?lat=999&lon=abc&date=not-a-date&layer=nonsense");
    expect(state.lat).toBeUndefined();
    expect(state.lon).toBeUndefined();
    expect(state.date).toBeUndefined();
    expect(state.layer).toBeUndefined();
  });

  it("parses a daypart when hour is absent", () => {
    const state = parseUrlState("?daypart=evening");
    expect(state.daypart).toBe("evening");
    expect(state.hour).toBeUndefined();
  });
});

describe("serializeUrlState", () => {
  it("round-trips through parse", () => {
    const original = {
      lat: 57.7089,
      lon: 11.9746,
      date: "2026-08-01",
      hour: 12,
      daypart: "evening",
      activity: "fishing",
      layer: "population_potential" as const,
    };
    const search = serializeUrlState(original);
    const parsed = parseUrlState(search);
    expect(parsed.lat).toBeCloseTo(original.lat, 3);
    expect(parsed.lon).toBeCloseTo(original.lon, 3);
    expect(parsed.date).toBe(original.date);
    expect(parsed.hour).toBe(original.hour);
    expect(parsed.activity).toBe(original.activity);
    expect(parsed.layer).toBe(original.layer);
  });

  it("prefers daypart over hour when hour is null", () => {
    const search = serializeUrlState({
      lat: 60,
      lon: 15,
      date: "2026-08-01",
      hour: null,
      daypart: "night",
      activity: "general",
      layer: "risk",
    });
    expect(search).toContain("daypart=night");
    expect(search).not.toContain("hour=");
  });
});
