import { describe, expect, it } from "vitest";
import { statusBadge } from "./ProviderMeter";

/**
 * The live /intelligence panel rendered "? Football-Data.org LIVE_VERIFIED" and
 * "? API-Football UNKNOWN": both states exist in `health-status.ts` but were
 * missing from this component's switch, so every row fell through to a `default`
 * branch that printed `row.status` verbatim and styled it "not configured".
 */
describe("statusBadge", () => {
  it("treats LIVE_VERIFIED as live-validated, like VERIFIED", () => {
    expect(statusBadge({ enabled: true, state: "LIVE_VERIFIED" })).toEqual(
      statusBadge({ enabled: true, status: "VERIFIED" }),
    );
    expect(statusBadge({ enabled: true, state: "LIVE_VERIFIED" }).label).toBe("Live-validated");
  });

  it("reads `state` in preference to `status`, as the evidence merge intends", () => {
    // mergeProviderEvidence layers a live reading over the registry row; reading
    // `status` alone showed a stale registry value for an evidence-bearing row.
    const badge = statusBadge({ enabled: true, status: "CONFIGURED_UNVERIFIED", state: "VERIFIED" });
    expect(badge.label).toBe("Live-validated");
  });

  it("never renders a raw backend token, however new", () => {
    for (const token of ["UNKNOWN", "SOME_FUTURE_STATE", "LIVE_VERIFIED_V2"]) {
      const badge = statusBadge({ enabled: true, state: token });
      expect(badge.label).not.toContain("_");
      expect(badge.label).not.toBe(token);
      expect(badge.icon).not.toBe("?");
    }
  });

  it("falls closed to neutral copy rather than an outage for an unknown state", () => {
    const badge = statusBadge({ enabled: true, state: "SOME_FUTURE_STATE" });
    expect(badge.label).toBe("Status unavailable");
    expect(badge.className).toBe("pm-unverified");
  });

  it("still reports a disabled provider as not configured", () => {
    expect(statusBadge({ enabled: false, state: "VERIFIED" }).label).toBe("Not configured");
  });

  // Directive v10 U7. ESPN read an amber "Stale" (live 2026-09-26): its one
  // observation was six days old because it runs only when a person asks for
  // evidence. The age of an on-demand call measures traffic, not health.
  it("shows an on-demand provider's age, never Stale", () => {
    const badge = statusBadge({
      enabled: true, state: "STALE", cadence: "on_demand", observations: 1, age_seconds: 559_595,
    });
    expect(badge.label).toBe("Last checked 6d ago");
    expect(badge.className).toBe("pm-unverified");
    expect(
      statusBadge({ enabled: true, state: "UNKNOWN", cadence: "on_demand", observations: 0 }).label,
    ).toBe("Not yet used");
  });

  it("still calls a scheduled provider Stale once it misses its schedule", () => {
    const badge = statusBadge({ enabled: true, state: "STALE", cadence: "scheduled", age_seconds: 90_000 });
    expect(badge.label).toBe("Stale");
    expect(badge.className).toBe("pm-stale");
  });
});
