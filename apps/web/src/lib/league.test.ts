import { describe, expect, it } from "vitest";
import { canonicalLeagueId, CANONICAL_LEAGUES, leagueDisplayName } from "./league";

describe("canonicalLeagueId", () => {
  // The live defect: the match selector pushed ?league=La Liga and the proxy's
  // enum only accepted LA_LIGA, so every non-EPL match page 400'd. EPL masked it
  // because both vocabularies spell it identically.
  it("normalizes the display vocabulary the selector emits", () => {
    expect(canonicalLeagueId("La Liga")).toBe("LA_LIGA");
    expect(canonicalLeagueId("Serie A")).toBe("SERIE_A");
    expect(canonicalLeagueId("Ligue 1")).toBe("LIGUE_1");
    expect(canonicalLeagueId("Bundesliga")).toBe("BUNDESLIGA");
    expect(canonicalLeagueId("Eredivisie")).toBe("EREDIVISIE");
    expect(canonicalLeagueId("Champions League")).toBe("UCL");
    expect(canonicalLeagueId("Premier League")).toBe("EPL");
  });

  it("passes canonical ids through unchanged", () => {
    for (const league of CANONICAL_LEAGUES) {
      expect(canonicalLeagueId(league)).toBe(league);
    }
  });

  it("tolerates casing, spacing, and hyphen variants", () => {
    expect(canonicalLeagueId("la liga")).toBe("LA_LIGA");
    expect(canonicalLeagueId("LaLiga")).toBe("LA_LIGA");
    expect(canonicalLeagueId("ligue-1")).toBe("LIGUE_1");
    expect(canonicalLeagueId("  Serie A  ")).toBe("SERIE_A");
  });

  it("returns null for unsupported or empty input rather than guessing", () => {
    // Fail closed: the 7-competition set is closed, matching the backend.
    expect(canonicalLeagueId("Primeira Liga")).toBeNull();
    expect(canonicalLeagueId("")).toBeNull();
    expect(canonicalLeagueId(null)).toBeNull();
    expect(canonicalLeagueId(undefined)).toBeNull();
  });
});

describe("leagueDisplayName", () => {
  it.each([
    ["EPL", "Premier League"],
    ["LA_LIGA", "La Liga"],
    ["BUNDESLIGA", "Bundesliga"],
    ["SERIE_A", "Serie A"],
    ["LIGUE_1", "Ligue 1"],
    ["EREDIVISIE", "Eredivisie"],
    ["UCL", "UEFA Champions League"],
  ])("maps %s to %s", (input, expected) => {
    expect(leagueDisplayName(input)).toBe(expected);
  });
});
