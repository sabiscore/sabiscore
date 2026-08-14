import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BettingIntelligenceDashboard } from "./betting-intelligence-dashboard";

const getUpcomingFixtures = vi.fn();
const getEnginePolicy = vi.fn();
const getFixtureEvidence = vi.fn();
const analyzeFixture = vi.fn();
const refreshFixtureEvidence = vi.fn();
const getProviderOddsCandidates = vi.fn();
const submitManualOddsSnapshot = vi.fn();

vi.mock("@/components/ProviderMeter", () => ({
  ProviderMeter: () => <div data-testid="provider-meter" />,
}));

vi.mock("@/components/ui/ResponsibleGamblingTooltip", () => ({
  ResponsibleGamblingBanner: () => <div data-testid="rg-banner" />,
}));

vi.mock("@/lib/betting-intelligence-api", () => ({
  APIError: class APIError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, body: unknown, message?: string) {
      super(message ?? "API error");
      this.status = status;
      this.body = body;
    }
  },
  getUpcomingFixtures: (...args: unknown[]) => getUpcomingFixtures(...args),
  getEnginePolicy: (...args: unknown[]) => getEnginePolicy(...args),
  getFixtureEvidence: (...args: unknown[]) => getFixtureEvidence(...args),
  analyzeFixture: (...args: unknown[]) => analyzeFixture(...args),
  refreshFixtureEvidence: (...args: unknown[]) => refreshFixtureEvidence(...args),
  getProviderOddsCandidates: (...args: unknown[]) => getProviderOddsCandidates(...args),
  submitManualOddsSnapshot: (...args: unknown[]) => submitManualOddsSnapshot(...args),
}));

const fixture = {
  fixture_id: "fd-1",
  competition: "EPL",
  home_team: "Arsenal",
  away_team: "Chelsea",
  kickoff_utc: "2026-08-21T18:00:00Z",
  status: "scheduled",
  evidence_status: "READY",
  odds_status: "READY",
  venue: null,
};

function setupBaseMocks() {
  getUpcomingFixtures.mockResolvedValue({
    fixtures: [fixture],
    total: 1,
    source: "database",
  });
  getEnginePolicy.mockResolvedValue({
    engine_version: "v1",
    generated_at: new Date().toISOString(),
    policy: {
      min_actionable_edge_pp: 4.2,
      high_conviction_edge_pp: 7.5,
      kelly_fraction: 0.25,
      max_kelly_cap: 0.05,
      speculative_stake_cap: 0.01,
      verdict_precedence: ["HIGH_CONVICTION", "ACTIONABLE", "SPECULATIVE", "HOLD", "PARTIAL", "NO_BET"],
      ucl_coverage: "capped",
      market_freshness_thresholds: { fresh_seconds: 300, recent_seconds: 900, stale_above_seconds: 900 },
      null_rules: {
        missing_quantitative_data: "pass",
        stake_under_partial_hold_no_bet: "pass",
        probabilities_under_partial: "masked",
      },
    },
  });
  refreshFixtureEvidence.mockResolvedValue({ fixture_id: "fd-1", profile: "PREMATCH_STANDARD", provider_results: [], refreshed_at: new Date().toISOString() });
  submitManualOddsSnapshot.mockResolvedValue({
    fixture_id: "fd-1",
    bookmaker: "bet365",
    home_odds: 2.1,
    draw_odds: 3.4,
    away_odds: 3.6,
    observed_at: new Date().toISOString(),
    received_at: new Date().toISOString(),
    executable: true,
    provenance: {},
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  setupBaseMocks();
  getFixtureEvidence.mockResolvedValue({
    fixture,
    model: null,
    market: null,
    freshness: {},
    source_status: {
      model: "VERIFIED",
      market: "VERIFIED",
      team_metrics: "VERIFIED",
      availability: "VERIFIED",
    },
    data_gaps: [],
    retrieval_timeline: [],
    readiness: [],
    source_comparison: [],
  });
  analyzeFixture.mockResolvedValue({
    match_identifier: "fd-1",
    match_id: "fd-1",
    competition: "EPL",
    verdict: "ACTIONABLE",
    stake: "0.03u",
    stake_fraction: 0.03,
    drivers: ["edge positive"],
    risks: [],
    invalidation_conditions: [],
    data_gaps: [],
    explanation: "Actionable at current price.",
    execution_eligible: true,
    confidence: "MEDIUM",
    minimum_acceptable_odds: 2.05,
    edge_percentage_points: 4.2,
    expected_value: 0.04,
    all_market_evaluations: [],
  });
  getProviderOddsCandidates.mockResolvedValue({ fixture_id: "fd-1", candidates: [], warnings: [] });
});

describe("BettingIntelligenceDashboard fail-closed states", () => {
  it("frames every analysis as research with staking disabled", async () => {
    render(<BettingIntelligenceDashboard />);
    expect(screen.getByText(/Research forecast — staking disabled/i)).toBeVisible();
    expect(screen.getByText(/no stake is recommended/i)).toBeVisible();
    await waitFor(() => expect(getUpcomingFixtures).toHaveBeenCalled());
  });

  it("renders source conflict state after evidence retrieval", async () => {
    getFixtureEvidence.mockResolvedValue({
      fixture,
      model: null,
      market: null,
      freshness: {},
      source_status: {
        model: "CONFLICTING",
        market: "VERIFIED",
        team_metrics: "VERIFIED",
        availability: "VERIFIED",
      },
      data_gaps: ["provider_conflict"],
      retrieval_timeline: [],
      readiness: [],
      source_comparison: [],
    });

    render(<BettingIntelligenceDashboard />);
    await waitFor(() => expect(getUpcomingFixtures).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /retrieve evidence/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/Source conflict detected\. The engine will fail closed until the conflict is resolved\./i),
      ).toBeInTheDocument();
    });
  });

  it("renders NO_BET as a pass state after analysis", async () => {
    analyzeFixture.mockResolvedValue({
      match_identifier: "fd-1",
      match_id: "fd-1",
      competition: "EPL",
      verdict: "NO_BET",
      stake: "pass",
      stake_fraction: 0,
      drivers: ["No positive edge"],
      risks: ["Market fairly priced"],
      invalidation_conditions: [],
      data_gaps: [],
      explanation: "No positive expected value.",
      execution_eligible: false,
      confidence: "LOW",
      minimum_acceptable_odds: null,
      edge_percentage_points: null,
      expected_value: null,
      all_market_evaluations: null,
    });

    render(<BettingIntelligenceDashboard />);
    await waitFor(() => expect(getUpcomingFixtures).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /^analyze$/i }));

    await waitFor(() => {
      expect(screen.getByText(/Skip This Match: PASS/i)).toBeInTheDocument();
      expect(screen.getByText(/Not permitted — uncertified generation/i)).toBeInTheDocument();
    });
  });

  it("shows scanner unavailable guidance when provider candidates are empty", async () => {
    render(<BettingIntelligenceDashboard />);
    await waitFor(() => expect(getUpcomingFixtures).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /auto-fill market/i }));

    await waitFor(() => {
      expect(
        screen.getByText(/No backend bookmaker snapshots are available\. Manual entry is required\./i),
      ).toBeInTheDocument();
    });
  });

  it("renders blocking critical gap panel for PARTIAL analyses", async () => {
    analyzeFixture.mockResolvedValue({
      match_identifier: "fd-1",
      match_id: "fd-1",
      competition: "EPL",
      verdict: "PARTIAL",
      stake: "pass",
      stake_fraction: 0,
      drivers: [],
      risks: [],
      invalidation_conditions: ["Resolve fixture identity"],
      data_gaps: ["FIXTURE_IDENTITY_UNVERIFIED"],
      explanation: "Insufficient verified evidence.",
      execution_eligible: false,
      confidence: null,
      minimum_acceptable_odds: null,
      edge_percentage_points: null,
      expected_value: null,
      critical_gaps: ["FIXTURE_IDENTITY_UNVERIFIED"],
      advisory_gaps: [],
      conflicts: [],
      all_market_evaluations: null,
    });

    render(<BettingIntelligenceDashboard />);
    await waitFor(() => expect(getUpcomingFixtures).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /^analyze$/i }));

    await waitFor(() => {
      expect(screen.getByText(/Blocking Gaps — execution paused/i)).toBeInTheDocument();
    });
  });
});
