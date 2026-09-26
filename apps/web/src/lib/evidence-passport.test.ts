import { describe, expect, it } from "vitest";
import { buildEvidencePassport, formatEvidenceAge } from "./evidence-passport";

const baseInput = {
  fieldAvailability: {
    fixture: true,
    prediction: true,
    market: false,
    uncertainty: false,
    elo: true,
  },
  unavailableReasons: {
    market: "Coherent single-bookmaker 1X2 snapshot unavailable",
    uncertainty: "Certified ensemble-dispersion uncertainty unavailable",
  },
  advisoryGaps: ["market_prob_home", "elo_league_adjusted", "odds_drift_home"],
};

describe("buildEvidencePassport", () => {
  it("marks a gapped family as gapped and keeps it in the array", () => {
    const rows = buildEvidencePassport(baseInput);
    const market = rows.find((r) => r.key === "market");
    expect(market).toBeDefined();
    expect(market?.resolved).toBe(false);
    expect(market?.statusLabel).toBe("Gapped");
    expect(market?.reason).toBe("Coherent single-bookmaker 1X2 snapshot unavailable");
  });

  it("keeps a resolved family in the array with a resolved status even with zero associated gaps", () => {
    const rows = buildEvidencePassport(baseInput);
    const fixture = rows.find((r) => r.key === "fixture");
    expect(fixture).toBeDefined();
    expect(fixture?.resolved).toBe(true);
    expect(fixture?.statusLabel).toBe("Resolved");
    expect(fixture?.reason).toBeNull();
    expect(fixture?.gapCount).toBe(0);
  });

  it("never omits a family present in field_availability", () => {
    const rows = buildEvidencePassport(baseInput);
    expect(rows.map((r) => r.key).sort()).toEqual(
      ["fixture", "prediction", "market", "uncertainty", "elo"].sort(),
    );
  });

  it("falls back to a neutral, transformed label for an unrecognised family key — never the raw key", () => {
    const rows = buildEvidencePassport({
      ...baseInput,
      fieldAvailability: { ...baseInput.fieldAvailability, mystery_family: false },
      unavailableReasons: { ...baseInput.unavailableReasons, mystery_family: "" },
    });
    const mystery = rows.find((r) => r.key === "mystery_family");
    expect(mystery).toBeDefined();
    expect(mystery?.label).toBe("Mystery Family");
    expect(mystery?.label).not.toBe("mystery_family");
  });

  it("sums gap counts only for families with a matching evidence-family group (market, elo)", () => {
    const rows = buildEvidencePassport(baseInput);
    const market = rows.find((r) => r.key === "market");
    const elo = rows.find((r) => r.key === "elo");
    const prediction = rows.find((r) => r.key === "prediction");
    // "market_prob_home" -> "Market prices", "odds_drift_home" -> "Market movement"
    expect(market?.gapCount).toBe(2);
    // "elo_league_adjusted" -> "Team strength ratings"
    expect(elo?.gapCount).toBe(1);
    // No natural evidence-family group maps to "prediction" — 0 is honest, not fabricated.
    expect(prediction?.gapCount).toBe(0);
  });

  it("says nothing about a family beyond what this fixture measured", () => {
    // The sub-line that used to come from /sources/freshness read "Data
    // unavailable" beside "Resolved" (live 2026-09-26): that registry is never
    // populated, so its status was never a measurement.
    const rows = buildEvidencePassport({
      ...baseInput,
      fieldAvailability: { ...baseInput.fieldAvailability, market: true },
    });
    const market = rows.find((r) => r.key === "market");
    expect(market?.statusLabel).toBe("Resolved");
    expect(market?.reason).toBeNull();
    expect(JSON.stringify(market)).not.toMatch(/unavailable/i);
  });

  it("never leaks a raw backend token through gap or freshness labels", () => {
    const rows = buildEvidencePassport(baseInput);
    const serialised = JSON.stringify(rows);
    expect(serialised).not.toContain("DATA_GAP");
    expect(serialised).not.toContain("fixtures_results");
  });

  it("does not crash on an empty passport", () => {
    const rows = buildEvidencePassport({
      fieldAvailability: {},
      unavailableReasons: {},
      advisoryGaps: [],
    });
    expect(rows).toEqual([]);
  });
});

describe("formatEvidenceAge", () => {
  it("formats valid ages without exposing raw seconds", () => {
    expect(formatEvidenceAge(30)).toBe("Less than a minute ago");
    expect(formatEvidenceAge(90)).toBe("1m ago");
    expect(formatEvidenceAge(3_660)).toBe("1h ago");
    expect(formatEvidenceAge(172_800)).toBe("2d ago");
  });

  it("fails closed for missing or invalid ages", () => {
    expect(formatEvidenceAge(null)).toBe("Unknown");
    expect(formatEvidenceAge(-1)).toBe("Unknown");
    expect(formatEvidenceAge(Number.NaN)).toBe("Unknown");
  });
});
