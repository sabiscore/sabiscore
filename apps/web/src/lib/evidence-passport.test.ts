import { describe, expect, it } from "vitest";
import { buildEvidencePassport } from "./evidence-passport";

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
  sources: [
    { name: "odds-market-features", category: "betting_market", freshness_status: "DATA_GAP", enabled: true },
    { name: "football-data.org", category: "fixtures_results", freshness_status: "LIVE", enabled: true },
  ],
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

  it("falls back to a neutral freshness label for an unrecognised source status — never the raw token", () => {
    const rows = buildEvidencePassport({
      ...baseInput,
      sources: [
        { name: "odds-market-features", category: "betting_market", freshness_status: "WEIRD_TOKEN", enabled: true },
      ],
    });
    const market = rows.find((r) => r.key === "market");
    expect(market?.provenance?.freshnessLabel).toBe("Status unavailable");
    expect(market?.provenance?.freshnessLabel).not.toBe("WEIRD_TOKEN");
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

  it("attaches provenance only for the family with an honest source-category mapping (market)", () => {
    const rows = buildEvidencePassport(baseInput);
    const market = rows.find((r) => r.key === "market");
    const fixture = rows.find((r) => r.key === "fixture");
    expect(market?.provenance).toEqual({
      sourceName: "odds-market-features",
      category: "Betting Market",
      freshnessLabel: "Data unavailable",
      freshnessTone: "neutral",
    });
    // No registered source category maps to "fixture" — never fabricated.
    expect(fixture?.provenance).toBeNull();
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
      sources: [],
    });
    expect(rows).toEqual([]);
  });
});
