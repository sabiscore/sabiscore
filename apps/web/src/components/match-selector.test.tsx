import { describe, expect, it } from "vitest";
import type { UpcomingMatch } from "@/lib/api";
import { describeMatchSelectionState, excludeSelectedTeam } from "./match-selector";
import {
  buildMatchInsightsHref,
  getTopEdgeFixtureId,
  selectorLeagueId,
  type SelectedFixture,
} from "@/lib/match-selection";
import { describeEdgeQualityPill, describeValueBadge } from "@/lib/edge-quality";

describe("excludeSelectedTeam", () => {
  const teams = ["Arsenal", "Aston Villa", "Brighton"];

  it("removes the selected team from the option list", () => {
    expect(excludeSelectedTeam(teams, "Arsenal")).toEqual(["Aston Villa", "Brighton"]);
  });

  it("is case- and whitespace-insensitive", () => {
    expect(excludeSelectedTeam(teams, "  arsenal  ")).toEqual(["Aston Villa", "Brighton"]);
  });

  it("returns the full list when no valid selection exists", () => {
    expect(excludeSelectedTeam(teams, "")).toEqual(teams);
    expect(excludeSelectedTeam(teams, "Chelsea")).toEqual(teams);
  });
});

describe("match selection summary", () => {
  it("describes a verified fixture selection", () => {
    const summary = describeMatchSelectionState({
      homeTeam: "Arsenal",
      awayTeam: "Bournemouth",
      league: "EPL",
      selectedFixture: {
        matchId: "fixture-123",
        homeTeam: "Arsenal",
        awayTeam: "Bournemouth",
        league: "EPL",
      },
    });

    expect(summary.badge).toBe("Verified fixture");
    expect(summary.title).toBe("Arsenal vs Bournemouth");
    expect(summary.description).toContain("canonical fixture identity");
  });

  it("describes an explicit manual matchup as hypothetical", () => {
    const summary = describeMatchSelectionState({
      homeTeam: "Arsenal",
      awayTeam: "Chelsea",
      league: "EPL",
      selectedFixture: null,
    });

    expect(summary.badge).toBe("Manual matchup");
    expect(summary.title).toBe("Arsenal vs Chelsea");
    expect(summary.description).toContain("hypothetical Premier League matchup");
  });

  it("gives a league-aware prompt when no teams are selected yet", () => {
    const summary = describeMatchSelectionState({
      homeTeam: "",
      awayTeam: "",
      league: "LA_LIGA",
      selectedFixture: null,
    });

    expect(summary.badge).toBe("Selection pending");
    expect(summary.title).toBe("Start with La Liga");
    expect(summary.description).toContain("Verified selections stay authoritative");
  });
});


describe("selector league normalization", () => {
  it("maps canonical API vocabulary to the selector vocabulary", () => {
    expect(selectorLeagueId("LA_LIGA")).toBe("La Liga");
    expect(selectorLeagueId("SERIE_A")).toBe("Serie A");
    expect(selectorLeagueId("LIGUE_1")).toBe("Ligue 1");
  });

  it("fails closed for an unsupported competition", () => {
    expect(selectorLeagueId("SCOTTISH_PREMIERSHIP")).toBeNull();
  });
});

describe("canonical fixture navigation", () => {
  const selectedFixture: SelectedFixture = {
    matchId: "fixture-123",
    homeTeam: "Arsenal",
    awayTeam: "Bournemouth",
    league: "EPL",
  };

  it("preserves the real fixture id when the selection is unchanged", () => {
    expect(
      buildMatchInsightsHref({
        selectedFixture,
        homeTeam: "Arsenal",
        awayTeam: "Bournemouth",
        league: "EPL",
      }),
    ).toBe("/match/fixture-123?league=EPL&home=Arsenal&away=Bournemouth");
  });

  // The id is opaque: the Phase-7 insights call takes a matchup string with no
  // id variant, and the hero card parses team names off the route segment.
  // Without these params both fall back to rendering the raw id.
  it("carries team names alongside the canonical id", () => {
    const href = buildMatchInsightsHref({
      selectedFixture,
      homeTeam: "Arsenal",
      awayTeam: "Bournemouth",
      league: "EPL",
    });
    const params = new URL(href, "https://example.test").searchParams;
    expect(params.get("home")).toBe("Arsenal");
    expect(params.get("away")).toBe("Bournemouth");
  });

  it("falls back to the explicit matchup path after a manual edit", () => {
    expect(
      buildMatchInsightsHref({
        selectedFixture,
        homeTeam: "Arsenal",
        awayTeam: "Chelsea",
        league: "EPL",
      }),
    ).toBe("/match/Arsenal%20vs%20Chelsea?league=EPL");
  });
});

describe("top-edge labelling", () => {
  const base = {
    home_team: "A",
    away_team: "B",
    league: "EPL",
    match_date: "2026-08-08T12:00:00Z",
    venue: null,
    status: "scheduled",
    value_bets: [],
    has_value: false,
    best_value_bet: null,
    data_gaps: [],
    staleness_seconds: 0,
    source: "test",
    clv_pct: null,
  } satisfies Omit<UpcomingMatch, "match_id" | "predictions" | "edge_quality_score">;

  it("does not fabricate a top edge from null or zero scores", () => {
    const fixtures: UpcomingMatch[] = [
      { ...base, match_id: "a", predictions: null, edge_quality_score: null },
      { ...base, match_id: "b", predictions: null, edge_quality_score: 0 },
    ];
    expect(getTopEdgeFixtureId(fixtures)).toBeNull();
  });

  it("selects the highest positive scored fixture with a prediction", () => {
    const prediction = {
      home_win: 0.5,
      draw: 0.25,
      away_win: 0.25,
      confidence: 0.5,
      model_version: "test",
    };
    const fixtures: UpcomingMatch[] = [
      { ...base, match_id: "a", predictions: prediction, edge_quality_score: 0.2 },
      { ...base, match_id: "b", predictions: prediction, edge_quality_score: 0.6 },
    ];
    expect(getTopEdgeFixtureId(fixtures)).toBe("b");
  });
});

describe("edge-quality pill (BigMatchesCarousel homepage badge)", () => {
  // Regression: edge_quality_score is a 0.40*confidence + 0.30*market_edge +
  // 0.20*freshness + 0.10*completeness composite (backend
  // upcoming_matches.py:_compute_edge_quality_score) — a quality signal, not a
  // market edge. It was previously rendered as "{score*100}% edge" on the live
  // homepage, and — compounded by a separate backend bug (staleness_seconds
  // silently defaulting to 0, pinning the freshness term at its max) — produced
  // an identical badge across every fixture. The pill must never claim to be an
  // edge percentage; the real market edge is the separate Value badge.
  it("never renders anything containing the substring '% edge'", () => {
    for (const score of [0, 0.1, 0.32, 0.33, 0.5, 0.66, 0.67, 0.9, 1]) {
      const pill = describeEdgeQualityPill(score);
      expect(pill?.label).not.toMatch(/%\s*edge/i);
      expect(pill?.title).not.toMatch(/%\s*edge/i);
    }
  });

  it("returns null instead of a placeholder pill when no score exists", () => {
    expect(describeEdgeQualityPill(null)).toBeNull();
    expect(describeEdgeQualityPill(undefined)).toBeNull();
  });

  it("labels High/Medium/Low at the same 0.67/0.33 thresholds as EdgeQualityBar", () => {
    expect(describeEdgeQualityPill(0.67)?.label).toBe("High quality");
    expect(describeEdgeQualityPill(0.66)?.label).toBe("Medium quality");
    expect(describeEdgeQualityPill(0.33)?.label).toBe("Medium quality");
    expect(describeEdgeQualityPill(0.32)?.label).toBe("Low quality");
  });

  it("shows the real market edge only when a value bet genuinely exists", () => {
    expect(describeValueBadge(true, 6.2)).toBe("Value 6.2%");
    expect(describeValueBadge(false, 6.2)).toBeNull(); // has_value=false must win
    expect(describeValueBadge(true, null)).toBeNull(); // no edge to show
    expect(describeValueBadge(true, undefined)).toBeNull();
  });
});
