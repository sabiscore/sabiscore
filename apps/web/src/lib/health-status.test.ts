import { describe, expect, it } from "vitest";
import {
  backendHealthIssues,
  deriveBackendReadiness,
  deriveProviderActivation,
  derivePlatformHealth,
  isHealthyBackendStatus,
  liveMetricLabel,
  mergeProviderEvidence,
  normalizeCapabilityStatus,
  normalizeProviderEvidence,
} from "./health-status";

describe("health status normalization", () => {
  it.each(["ok", "ready", "healthy", "OK"])(
    "accepts %s as healthy",
    (status) => {
      expect(isHealthyBackendStatus(status)).toBe(true);
    },
  );

  it.each(["degraded", "unavailable", "unknown", null])(
    "rejects %s as healthy",
    (status) => {
      expect(isHealthyBackendStatus(status)).toBe(false);
    },
  );

  it("does not emit a contradictory issue for the live backend ok state", () => {
    expect(backendHealthIssues("ok")).toEqual([]);
    expect(backendHealthIssues("degraded")).toEqual([
      "Backend status: degraded",
    ]);
  });
});

describe("provider evidence normalization", () => {
  it("normalizes the backend provider-keyed evidence object", () => {
    expect(normalizeProviderEvidence({
      football_data_org: {
        state: "LIVE_VERIFIED",
        status: "VERIFIED",
        observations: 12,
      },
      the_odds_api: {
        state: "STALE",
        status: "VERIFIED",
        observations: 4,
      },
    })).toEqual([
      {
        provider: "football_data_org",
        state: "LIVE_VERIFIED",
        status: "VERIFIED",
        observations: 12,
      },
      {
        provider: "the_odds_api",
        state: "STALE",
        status: "VERIFIED",
        observations: 4,
      },
    ]);
  });

  it("fails closed for malformed evidence payloads", () => {
    expect(normalizeProviderEvidence(null)).toEqual([]);
    expect(normalizeProviderEvidence("LIVE_VERIFIED")).toEqual([]);
    expect(normalizeProviderEvidence({ football_data_org: null })).toEqual([]);
  });

  it("merges registry configuration with durable evidence without losing raw status", () => {
    expect(mergeProviderEvidence(
      [
        {
          provider: "football_data_org",
          configured: true,
          enabled: true,
          status: "CONFIGURED_UNVERIFIED",
          trust_tier: "OFFICIAL_AUTHENTICATED",
        },
        {
          provider: "espn",
          configured: true,
          enabled: true,
          status: "CONFIGURED_UNVERIFIED",
        },
      ],
      {
        football_data_org: {
          state: "LIVE_VERIFIED",
          status: "VERIFIED",
          observations: 386,
        },
        espn: {
          state: "UNKNOWN",
          status: null,
          observations: 0,
        },
      },
    )).toEqual([
      {
        provider: "football_data_org",
        configured: true,
        enabled: true,
        status: "LIVE_VERIFIED",
        state: "LIVE_VERIFIED",
        trust_tier: "OFFICIAL_AUTHENTICATED",
        observations: 386,
        registry_status: "CONFIGURED_UNVERIFIED",
        evidence_status: "VERIFIED",
      },
      {
        provider: "espn",
        configured: true,
        enabled: true,
        status: "UNKNOWN",
        state: "UNKNOWN",
        observations: 0,
        registry_status: "CONFIGURED_UNVERIFIED",
        evidence_status: null,
      },
    ]);
  });
});

describe("platform provider health", () => {
  it("keeps configured, enabled, and live provider counts distinct", () => {
    const health = derivePlatformHealth({
      backendStatus: "ok",
      backendChecks: { models: { status: "ready" } },
      providers: [
        { configured: true, enabled: true, status: "LIVE_VERIFIED" },
        { configured: true, enabled: true, status: "UNKNOWN" },
        { configured: false, enabled: false, status: "UNKNOWN" },
      ],
    });
    expect(health.configured).toBe(2);
    expect(health.enabled).toBe(2);
    expect(health.live).toBe(1);
    expect(health.degraded).toBe(0);
    expect(health.modelsReady).toBe(true);
    expect(health.providerActivation.label).toBe("Partial");
  });

  it("reports ready only when every configured enabled provider is live-verified", () => {
    expect(deriveProviderActivation([
      { configured: true, enabled: true, status: "LIVE_VERIFIED" },
      { configured: true, enabled: true, state: "LIVE_VERIFIED", status: "VERIFIED" },
    ])).toMatchObject({
      total: 2,
      configured: 2,
      enabled: 2,
      live: 2,
      degraded: 0,
      label: "Ready",
    });
  });

  it("reports partial while configured providers lack live evidence", () => {
    expect(deriveProviderActivation([
      { configured: true, enabled: true, status: "LIVE_VERIFIED" },
      { configured: true, enabled: true, status: "UNKNOWN" },
    ])).toMatchObject({
      configured: 2,
      enabled: 2,
      live: 1,
      degraded: 0,
      label: "Partial",
    });
  });

  it("treats durable rate-limit and stale evidence as degraded", () => {
    expect(deriveProviderActivation([
      { configured: true, enabled: true, status: "LIVE_VERIFIED" },
      { configured: true, enabled: true, status: "RATE_LIMITED" },
      { configured: true, enabled: true, state: "STALE", status: "VERIFIED" },
    ])).toMatchObject({
      configured: 3,
      enabled: 3,
      live: 1,
      degraded: 2,
      label: "Partial",
    });
  });

  it("fails closed instead of throwing when providers is not an array", () => {
    // Regression guard: /api/health crosses an unchecked fetch/JSON boundary
    // (fetchPlatformHealth's `as Promise<BackendHealthPayload>` cast), and this
    // is called from the root layout on every page — a malformed shape here
    // must degrade, not crash the whole app shell.
    expect(deriveProviderActivation({} as never)).toMatchObject({
      total: 0,
      configured: 0,
      enabled: 0,
      live: 0,
      degraded: 0,
      label: "Unavailable",
    });
  });
});

describe("backend readiness aggregation", () => {
  it("reports all four required infrastructure checks as ready", () => {
    expect(
      deriveBackendReadiness({
        backendStatus: "ok",
        backendChecks: {
          database: { status: "ready" },
          migrations: { status: "ready" },
          cache: { status: "ready" },
          models: { status: "ready" },
        },
      }),
    ).toEqual({
      total: 4,
      ready: 4,
      unavailable: 0,
      score: 1,
      label: "Core ready",
      capability: "unknown",
      capabilityMessage: undefined,
    });
  });

  it("does not infer readiness from a healthy aggregate when checks are absent", () => {
    expect(deriveBackendReadiness({ backendStatus: "ok" })).toEqual({
      total: 4,
      ready: 0,
      unavailable: 4,
      score: 0,
      label: "Core unavailable",
      capability: "unknown",
      capabilityMessage: undefined,
    });
  });
});

describe("readiness capability probe (D6)", () => {
  it.each(["verified", "unverified_no_fixtures", "failed"] as const)(
    "normalizes a real backend capability status %s",
    (status) => {
      expect(normalizeCapabilityStatus(status)).toBe(status);
    },
  );

  it.each([undefined, null, "bogus", 42])(
    "falls back to unknown for %s",
    (raw) => {
      expect(normalizeCapabilityStatus(raw)).toBe("unknown");
    },
  );

  it("surfaces a verified capability alongside healthy infra checks", () => {
    const stats = deriveBackendReadiness({
      backendStatus: "ok",
      backendChecks: {
        database: { status: "ready" },
        migrations: { status: "ready" },
        cache: { status: "ready" },
        models: { status: "ready" },
      },
      backendCapability: { status: "verified", message: "Live pipeline produced a verified 1X2 triple" },
    });
    expect(stats.capability).toBe("verified");
    expect(stats.capabilityMessage).toBe("Live pipeline produced a verified 1X2 triple");
  });

  it("never conflates no-fixtures-to-test with a failure", () => {
    const stats = deriveBackendReadiness({
      backendStatus: "ok",
      backendCapability: { status: "unverified_no_fixtures", message: "No upcoming fixture in the 7-day horizon" },
    });
    expect(stats.capability).toBe("unverified_no_fixtures");
  });

  it("surfaces a failed capability independently of infra readiness", () => {
    const stats = deriveBackendReadiness({
      backendStatus: "ok",
      backendChecks: {
        database: { status: "ready" },
        migrations: { status: "ready" },
        cache: { status: "ready" },
        models: { status: "ready" },
      },
      backendCapability: { status: "failed", message: "prediction_status=UNAVAILABLE identity_verified=false" },
    });
    expect(stats.label).toBe("Core ready");
    expect(stats.capability).toBe("failed");
  });
});

describe("live metric display", () => {
  it("withholds artifact numbers until enough labelled predictions exist", () => {
    expect(liveMetricLabel(false, "51.0%")).toBe("Pending");
    expect(liveMetricLabel(true, "51.0%")).toBe("51.0%");
  });
});
