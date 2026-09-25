import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FullAnalysisDashboard } from "./full-analysis-dashboard";
import { BettingAgentPanel } from "./betting-agent-panel";
import { FeatureFlagProvider } from "@/lib/feature-flags";
import * as api from "@/lib/api";
import type { FullMatchAnalysisResponse } from "@/lib/full-analysis-contract";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getFullAnalysis: vi.fn(),
  };
});

function createMockAnalysis(overrides: Partial<FullMatchAnalysisResponse> = {}): FullMatchAnalysisResponse {
  const base: FullMatchAnalysisResponse = {
    match_id: "Arsenal vs Chelsea",
    verdict: "ACTIONABLE",
    prediction_status: "AVAILABLE",
    prediction_source: "CERTIFIED_MODEL",
    probabilities_available: true,
    is_reduced_evidence_baseline: false,
    top_outcome_probability: 0.52,
    effective_kelly_cap: 0.04,
    stake_permitted: false, // Default research mode: staking disabled
    evidence_quality: {
      critical_gaps: [],
      advisory_gaps: [],
      conflicts: [],
      all_gaps: [],
      critical_gap_count: 0,
      advisory_gap_count: 0,
      conflict_count: 0,
      total_gap_count: 0,
    },
    ensemble: {
      home_win_prob: 0.52,
      draw_prob: 0.26,
      away_win_prob: 0.22,
      prediction: "home_win",
      confidence: 0.52,
      top_outcome_probability: 0.52,
      probabilities_available: true as const,
      league: "EPL",
      model_version: "v5_phase7",
      certification_state: "CERTIFIED",
      calibration_method: "isotonic",
      calibration_applied: true,
      overlay_applied: false as const,
      coverage: "full",
    },
    uncertainty: {
      epistemic_unc: 0.045,
      aleatoric_unc: 0.09,
      concentration: 0.82,
      credible_interval: [0.44, 0.6],
      confidence_tier: "OK",
    },
    model_drivers: ["elo_difference", "rolling_xg_differential"],
    causal_drivers: ["elo_difference"],
    rl_recommendation: {
      stake_fraction: 0,
      abstain: true,
      reason: "Research Mode: Public staking is not permitted.",
      reward_components: {},
    },
    elo_context: {
      home_elo: 1620,
      away_elo: 1540,
      elo_difference: 80,
      home_elo_trend_5: 3.2,
      away_elo_trend_5: -1.4,
      elo_momentum_cross: 0.4,
    },
    odds_edge: {
      market: "home_win",
      market_odds: 2.15,
      model_prob: 0.52,
      edge: 0.055,
      kelly_stake: 0,
    },
    narrative: "[ACTIONABLE] Verified model output indicates statistical edge in research view.",
    partial_intelligence: false,
    data_gaps: [],
    staleness_seconds: 60,
    staleness_available: true,
    freshness_tag: "LIVE",
    feature_freshness_seconds: {},
    feature_source: {},
    actionability: {
      edge_quality_score: 0.68,
      clv_pct: null,
      closing_line_convergence_delta: null,
      suggested_stake_pct: 0,
      abstain: true,
      abstain_reason: "Research Mode active: automated staking disabled.",
      top_evidence: ["Model Edge", "Elo Difference"],
      caveats: ["Research Mode only"],
    },
    match_importance_score: 0.75,
    competition_stage: "Regular Season",
    home_team: "Arsenal",
    away_team: "Chelsea",
    league: "EPL",
    kickoff_utc: "2026-09-23T19:00:00Z",
    fixture_verified: true,
    field_availability: { fixture: true },
    unavailable_reasons: {},
    generated_at: "2026-09-22T10:00:00Z",
  };

  return { ...base, ...overrides };
}

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(
    <FeatureFlagProvider>
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
    </FeatureFlagProvider>,
  );
}

describe("P9 Frontend Betting Safety Audit — Default-Deny Research Mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("FullAnalysisDashboard in Research Mode (stake_permitted = false)", () => {
    it("suppresses all staking controls, inputs, and execute buttons", async () => {
      const mockData = createMockAnalysis({
        stake_permitted: false,
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="EPL" />,
      );

      await waitFor(() => {
        expect(screen.getByRole("region", { name: /full match intelligence dashboard/i })).toBeInTheDocument();
      });

      // 1. Absence of text or number inputs for wagering
      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(container.querySelectorAll("textarea")).toHaveLength(0);

      // 2. Absence of Execute Bet or Place Bet buttons
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();

      // 3. Staking action strips are suppressed
      expect(screen.queryByRole("group", { name: /actionability summary/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: /edge quality and evidence/i })).not.toBeInTheDocument();

      // 4. RLCard displays fallback "No bet" and "NO BET" on gauge
      expect(screen.getByText("NO BET")).toBeInTheDocument();
      expect(screen.getAllByText("No bet").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole("img", { name: /no bet/i })).toBeInTheDocument();
    });

    it("falls back to 'Watchlist' messaging when verdict is SPECULATIVE", async () => {
      const mockData = createMockAnalysis({
        verdict: "SPECULATIVE",
        stake_permitted: false,
        narrative: "[SPECULATIVE] Market signals indicate speculative opportunity.",
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="EPL" />,
      );

      await waitFor(() => {
        expect(screen.getByText(/Watchlist only\. No stake is permitted without stronger evidence\./i)).toBeInTheDocument();
      });

      expect(screen.getAllByText("Speculative").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Watchlist only — no stake")).toBeInTheDocument();
      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    });

    it("falls back to 'No bet' messaging when verdict is NO_BET", async () => {
      const mockData = createMockAnalysis({
        verdict: "NO_BET",
        stake_permitted: false,
        odds_edge: null,
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="EPL" />,
      );

      await waitFor(() => {
        expect(screen.getByText(/Verified data is available, but no market currently offers positive value\./i)).toBeInTheDocument();
      });

      expect(screen.getAllByText("No Bet").length).toBeGreaterThanOrEqual(1);
      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    });

    it("falls back to 'HOLD' messaging when verdict is HOLD", async () => {
      const mockData = createMockAnalysis({
        verdict: "HOLD",
        stake_permitted: false,
        odds_edge: null,
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="EPL" />,
      );

      await waitFor(() => {
        expect(screen.getByText(/Model and market are aligned\. No edge above threshold\./i)).toBeInTheDocument();
      });

      expect(screen.getAllByText("Hold").length).toBeGreaterThanOrEqual(1);
      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    });

    it("falls back to 'PARTIAL' and itemizes blocking gaps when verdict is PARTIAL", async () => {
      const mockData = createMockAnalysis({
        verdict: "PARTIAL",
        partial_intelligence: true,
        stake_permitted: false,
        evidence_quality: {
          critical_gaps: ["ODDS_DATA_UNAVAILABLE"],
          advisory_gaps: [],
          conflicts: [],
          all_gaps: ["ODDS_DATA_UNAVAILABLE"],
          critical_gap_count: 1,
          advisory_gap_count: 0,
          conflict_count: 0,
          total_gap_count: 1,
        },
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="EPL" />,
      );

      await waitFor(() => {
        expect(screen.getByText(/No bet\. Critical evidence gaps or conflicts block action\./i)).toBeInTheDocument();
      });

      expect(screen.getAllByText("Partial").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByRole("region", { name: /why no prediction — evidence status/i })).toBeInTheDocument();
      expect(screen.getAllByText(/odds data unavailable/i).length).toBeGreaterThanOrEqual(1);

      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
    });

    it("enforces UCL Actionable hard-cap with staking suppressed", async () => {
      const mockData = createMockAnalysis({
        league: "UCL",
        verdict: "ACTIONABLE",
        stake_permitted: false,
        ensemble: {
          ...createMockAnalysis().ensemble,
          league: "UCL",
        },
      });
      vi.mocked(api.getFullAnalysis).mockResolvedValue(mockData);

      const { container } = renderWithClient(
        <FullAnalysisDashboard matchId="Arsenal vs Chelsea" league="UCL" />,
      );

      await waitFor(() => {
        expect(screen.getAllByText("Actionable").length).toBeGreaterThanOrEqual(1);
      });

      // UCL capped: no execute or place bet controls, no wager inputs
      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
      expect(screen.getByText("NO BET")).toBeInTheDocument();
    });
  });

  describe("Cross-component safety checks", () => {
    it("BettingAgentPanel exposes no inputs or execute buttons and defaults to Disabled", () => {
      const { container } = render(
        <BettingAgentPanel
          recommendation={{
            stake_fraction: 0.04,
            abstain: false,
            reason: "RL model detected value",
            reward_components: { R_pnl: 0.1 },
          }}
          stakePermitted={false}
          researchMode={true}
        />,
      );

      expect(container.querySelectorAll("input")).toHaveLength(0);
      expect(screen.queryByRole("button", { name: /execute bet/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /place bet/i })).not.toBeInTheDocument();
      expect(screen.getByText("⚠ Staking Disabled")).toBeInTheDocument();
      expect(screen.getAllByText("Disabled").length).toBeGreaterThanOrEqual(1);
    });
  });
});
