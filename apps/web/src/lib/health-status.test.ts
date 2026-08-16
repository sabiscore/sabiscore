import { describe, expect, it } from "vitest";
import {
  backendHealthIssues,
  deriveBackendReadiness,
  deriveProviderActivation,
  derivePlatformHealth,
  isHealthyBackendStatus,
  liveMetricLabel,
  normalizeCapabilityStatus,
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

describe("platform provider health", () => {
  it("keeps configured, enabled, and live provider counts distinct", () => {
    const health = derivePlatformHealth({
      backendStatus: "ok",
      backendChecks: { models: { status: "ready" } },
      providers: [
        { configured: true, enabled: true, status: "VERIFIED" },
        { configured: true, enabled: true, status: "CONFIGURED_UNVERIFIED" },
        { configured: false, enabled: false, status: "UNCONFIGURED" },
      ],
    });
    expect(health.configured).toBe(2);
    expect(health.enabled).toBe(2);
    expect(health.live).toBe(1);
    expect(health.degraded).toBe(0);
    expect(health.modelsReady).toBe(true);
    expect(health.providerActivation.label).toBe("Ready");
  });

  it("reports a partial provider state until every configured provider is enabled", () => {
    expect(deriveProviderActivation([
      { configured: true, enabled: true, status: "CONFIGURED_UNVERIFIED" },
      { configured: true, enabled: false, status: "UNAVAILABLE" },
    ])).toMatchObject({
      total: 2,
      configured: 2,
      enabled: 1,
      live: 0,
      degraded: 0,
      label: "Partial",
    });
  });

  it("treats intentional configured-unverified status as neutral but real negative evidence as degraded", () => {
    expect(deriveProviderActivation([
      { configured: true, enabled: true, status: "CONFIGURED_UNVERIFIED" },
      { configured: true, enabled: true, status: "RATE_LIMITED" },
    ])).toMatchObject({
      configured: 2,
      enabled: 2,
      live: 0,
      degraded: 1,
      label: "Partial",
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
