import { describe, expect, it } from "vitest";
import { parseUrlState, serializeUrlState } from "../urlState";

describe("parseUrlState", () => {
  it("parses a fully specified query string", () => {
    const state = parseUrlState(
      "?lat=59.3293&lon=18.0686&date=2026-07-29&hour=5&activity=camping&layer=population_potential"
    );
    expect(state.lat).toBeCloseTo(59.3293);
    expect(state.lon).toBeCloseTo(18.0686);
    expect(state.date).toBe("2026-07-29");
    expect(state.hour).toBe(5);
    expect(state.activity).toBe("camping");
    expect(state.layer).toBe("population_potential");
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

  it("maps the legacy 'risk' layer value (pre-products) to daily_peak_risk", () => {
    const state = parseUrlState("?layer=risk");
    expect(state.layer).toBe("daily_peak_risk");
  });

  it("redirects retired layer values (confidence/biting_activity/current_risk) to daily_peak_risk", () => {
    // Only Myggrisk/Myggläge are public views now (UX clarity pass item 2)
    // -- a bookmark carrying one of the three retired layer values should
    // land on the closest current equivalent, not on a state no UI control
    // can produce.
    expect(parseUrlState("?layer=confidence").layer).toBe("daily_peak_risk");
    expect(parseUrlState("?layer=biting_activity").layer).toBe("daily_peak_risk");
    expect(parseUrlState("?layer=current_risk").layer).toBe("daily_peak_risk");
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
      layer: "current_risk",
    });
    expect(search).toContain("daypart=night");
    expect(search).not.toContain("hour=");
  });
});
