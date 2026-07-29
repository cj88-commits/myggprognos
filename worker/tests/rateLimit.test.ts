import { describe, expect, it } from "vitest";
import { hashReporter } from "../src/rateLimit";
import type { Env } from "../src/types";

function makeEnv(salt: string): Env {
  return { DB: {} as D1Database, ALLOWED_ORIGINS: "http://localhost:5173", REPORT_HASH_SALT: salt };
}

function requestWithIp(ip: string): Request {
  return new Request("https://example.com/api/reports", { headers: { "CF-Connecting-IP": ip } });
}

describe("hashReporter", () => {
  it("produces a stable 64-char hex digest", async () => {
    const hash = await hashReporter(requestWithIp("1.2.3.4"), makeEnv("salt"));
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("is deterministic for the same IP and salt", async () => {
    const env = makeEnv("salt");
    const a = await hashReporter(requestWithIp("1.2.3.4"), env);
    const b = await hashReporter(requestWithIp("1.2.3.4"), env);
    expect(a).toBe(b);
  });

  it("differs for different IPs", async () => {
    const env = makeEnv("salt");
    const a = await hashReporter(requestWithIp("1.2.3.4"), env);
    const b = await hashReporter(requestWithIp("5.6.7.8"), env);
    expect(a).not.toBe(b);
  });

  it("differs for different salts (so the raw IP cannot be brute-forced across deployments)", async () => {
    const a = await hashReporter(requestWithIp("1.2.3.4"), makeEnv("salt-one"));
    const b = await hashReporter(requestWithIp("1.2.3.4"), makeEnv("salt-two"));
    expect(a).not.toBe(b);
  });

  it("falls back gracefully when no IP header is present", async () => {
    const hash = await hashReporter(new Request("https://example.com/api/reports"), makeEnv("salt"));
    expect(hash).toMatch(/^[0-9a-f]{64}$/);
  });
});
