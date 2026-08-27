import { describe, expect, it } from "vitest";
import { computeStaleness, STALE_THRESHOLD_HOURS } from "../freshness";

const NOW = new Date("2026-08-27T16:00:00Z").getTime();

describe("computeStaleness", () => {
  it("is NOT stale when the manifest was generated recently", () => {
    const generatedAt = new Date(NOW - 2 * 3600000).toISOString(); // 2h old
    const result = computeStaleness(generatedAt, NOW);
    expect(result.stale).toBe(false);
    expect(result.ageHours).toBeCloseTo(2, 5);
  });

  it("IS stale when the manifest is older than the threshold", () => {
    const generatedAt = new Date(NOW - (STALE_THRESHOLD_HOURS + 1) * 3600000).toISOString();
    const result = computeStaleness(generatedAt, NOW);
    expect(result.stale).toBe(true);
    expect(result.ageHours).toBeGreaterThan(STALE_THRESHOLD_HOURS);
  });

  it("parses a 'Z'-suffixed timestamp as absolute UTC, independent of local timezone", () => {
    // A naive implementation that treated this as local time (e.g. dropped
    // the "Z" or used a non-UTC-aware parser) would compute a different age
    // depending on the host's timezone offset -- this must not happen.
    const generatedAt = "2026-08-27T14:00:00Z"; // exactly 2h before NOW
    const result = computeStaleness(generatedAt, NOW);
    expect(result.ageHours).toBeCloseTo(2, 5);
    expect(result.stale).toBe(false);
  });

  it("stays fresh even when the frontend build/deploy is old, as long as generated_at is recent", () => {
    // No build timestamp is ever consulted -- passing an arbitrarily "old"
    // notion of build time alongside a fresh generated_at must not affect
    // the result (there is no build-time parameter to computeStaleness at
    // all, which is itself the point: freshness is a pure function of the
    // manifest's own timestamp).
    const freshGeneratedAt = new Date(NOW - 1 * 3600000).toISOString();
    const result = computeStaleness(freshGeneratedAt, NOW);
    expect(result.stale).toBe(false);
  });

  it("stays fresh across a frozen/unchanged build_sha as generated_at advances", () => {
    // build_sha never enters this calculation -- simulate two publish
    // cycles under r2-cutover (frozen build_sha, advancing generated_at)
    // and confirm both read as fresh.
    const cycle1 = computeStaleness(new Date(NOW - 1 * 3600000).toISOString(), NOW);
    const cycle2 = computeStaleness(new Date(NOW - 0.5 * 3600000).toISOString(), NOW + 3600000);
    expect(cycle1.stale).toBe(false);
    expect(cycle2.stale).toBe(false);
  });

  it("treats invalid or missing generated_at as unknown, not stale", () => {
    expect(computeStaleness(undefined, NOW)).toEqual({ stale: false, ageHours: null });
    expect(computeStaleness("", NOW)).toEqual({ stale: false, ageHours: null });
    expect(computeStaleness("not-a-timestamp", NOW)).toEqual({ stale: false, ageHours: null });
  });

  it("respects a custom threshold when provided", () => {
    const generatedAt = new Date(NOW - 3 * 3600000).toISOString();
    expect(computeStaleness(generatedAt, NOW, 2).stale).toBe(true);
    expect(computeStaleness(generatedAt, NOW, 4).stale).toBe(false);
  });
});
