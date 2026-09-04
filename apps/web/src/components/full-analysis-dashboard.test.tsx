import type { ReactElement } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  EdgeDeltaBar,
  EloContextCard,
  EnsembleCard,
  EvidenceStatusCard,
  NarrativeBlock,
  OddsEdgeCard,
  RLCard,
  UncertaintyCard,
} from "./full-analysis-dashboard";
import { EvidencePassport } from "./evidence-passport";

describe("NarrativeBlock accessibility", () => {
  it("supports keyboard-operable disclosure with a valid controlled region", () => {
    const text = "Evidence detail. ".repeat(30);
    render(<NarrativeBlock text={text} />);
    const button = screen.getByRole("button", { name: /show more/i });
    const narrative = document.getElementById("narrative-text");
    expect(button).toHaveAttribute("aria-controls", "narrative-text");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(narrative).not.toHaveTextContent(text);
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(narrative).toHaveTextContent(text.trim());
  });
});

describe("reduced-evidence display honesty", () => {
  // The backend fills absent ratings with a neutral 1500 and still emits a
  // placeholder credible interval. Rendering either as a measurement presents
  // a default as data — the same class of defect as the vΩ.23 backend fix.
  const neutralElo = {
    home_elo: 1500,
    away_elo: 1500,
    elo_difference: 0,
    home_elo_trend_5: 0,
    away_elo_trend_5: 0,
    elo_momentum_cross: 0,
  };

  it("hides neutral-default Elo ratings on a reduced-evidence baseline", () => {
    const { container } = render(<EloContextCard elo={null} />);
    expect(container.textContent).not.toContain("1500");
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Home Elo unavailable")).toHaveClass("sr-only");
    expect(container.querySelector('[aria-label="Home Elo unavailable"]')).toBeNull();
  });

  it("shows Elo ratings when the analysis is evidence-backed", () => {
    const { container } = render(
      <EloContextCard elo={{ ...neutralElo, home_elo: 1712, away_elo: 1588 }} />,
    );
    expect(container.textContent).toContain("1712");
    expect(container.textContent).toContain("1588");
  });

  // Live off-season payload sends reward_components {R_pnl:0, R_ic:0, R_cal:0,
  // R_risk:0, R_abs:0.05} with abstain:true. Rendering four 0.000 tiles states a
  // reward decomposition for a stake that was never sized — and slice(0,4) drops
  // R_abs, the only non-zero term. Same defect class as the Elo/CI fixes above.
  it("hides the RL reward decomposition when the policy abstained", () => {
    const { container } = render(
      <RLCard
        rec={{
          stake_fraction: 0,
          abstain: true,
          reason: "Abstained: insufficient verified evidence",
          reward_components: { R_pnl: 0, R_ic: 0, R_cal: 0, R_risk: 0, R_abs: 0.05 },
        }}
        effectiveKellyCap={0.04}
        stakePermitted={false}
      />,
    );
    expect(container.textContent).not.toContain("0.000");
    expect(container.textContent).toContain("No bet");
  });

  it("shows the RL reward decomposition when a stake was actually sized", () => {
    const { container } = render(
      <RLCard
        rec={{
          stake_fraction: 0.03,
          abstain: false,
          reason: null,
          reward_components: { R_pnl: 0.125, R_ic: 0.4, R_cal: 0.2, R_risk: 0.1 },
        }}
        effectiveKellyCap={0.04}
        stakePermitted
      />,
    );
    expect(container.textContent).toContain("0.125");
  });

  it("hides the credible interval when no prediction was produced", () => {
    const unc = {
      epistemic_unc: 1,
      aleatoric_unc: 0,
      concentration: 1.0001,
      credible_interval: [0, 0.002] as [number, number],
      confidence_tier: "LOW_EVIDENCE" as const,
    };
    const { container } = render(<UncertaintyCard unc={unc} available={false} />);
    expect(container.textContent).not.toContain("0.2%");
    expect(container.textContent).toContain("—");
  });

  // The card used to pair "Diagnostic baseline values are not displayed"
  // with a second line describing that same suppressed value's shape
  // ("defaults toward even") — contradicting its own non-display claim on
  // the standard reduced-evidence path shown live in production.
  it("does not describe a suppressed baseline's shape when probabilities are unavailable", () => {
    const { container } = render(
      <EnsembleCard
        data={{
          home_win_prob: 0.34,
          draw_prob: 0.33,
          away_win_prob: 0.33,
          prediction: "draw",
          confidence: 0.34,
          top_outcome_probability: 0.34,
          probabilities_available: false,
          league: "EPL",
          model_version: "v5_phase7",
          calibration_method: "isotonic",
          calibration_applied: false,
          overlay_applied: false,
          // Added with the manifest-authority provenance fields (model-status.ts /
          // prediction.py's _ArtifactBundle) — this fixture predates them and was
          // the one non-null-safety typecheck break the patch introduced elsewhere.
          certification_state: "UNVERIFIED",
          coverage: "dedicated",
        }}
      />,
    );
    expect(container.textContent).toContain("Diagnostic baseline values are not displayed");
    expect(container.textContent).not.toContain("defaults toward");
  });
});

describe("beginner-friendly jargon explainers (vΩ.28)", () => {
  // Kelly, Edge, Epistemic, Aleatoric, and CI carried no explanation on this
  // page — the Kelly/Edge tooltips already existed but were only wired into
  // ValueBetCard, a different widget on the same route. These pin that the
  // explainer triggers are reachable by keyboard/focus (not just mouse hover)
  // in both a PARTIAL/abstain-style state and an ACTIONABLE/stake-permitted
  // state, per the vΩ.28 DoD.
  const abstainRec = {
    stake_fraction: 0,
    abstain: true,
    reason: "Insufficient verified evidence.",
    reward_components: {},
  };
  const activeRec = {
    stake_fraction: 0.03,
    abstain: false,
    reason: null,
    reward_components: { r_pnl: 0.12 },
  };
  const edge = {
    market: "home_win",
    market_odds: 2.1,
    model_prob: 0.55,
    edge: 0.08,
    kelly_stake: 0.02,
  };

  it("exposes the RLCard Kelly-cap explainer via focus when abstaining (PARTIAL-like)", () => {
    render(<RLCard rec={abstainRec} effectiveKellyCap={0.04} stakePermitted={false} />);
    const trigger = screen.getByRole("button");
    fireEvent.focus(trigger);
    expect(screen.getByText(/Kelly Criterion suggests optimal bet sizing/i)).toBeInTheDocument();
  });

  it("exposes the RLCard Kelly-cap explainer via focus when a stake is permitted (HIGH_CONVICTION-like)", () => {
    render(<RLCard rec={activeRec} effectiveKellyCap={0.04} stakePermitted />);
    const trigger = screen.getByRole("button");
    fireEvent.focus(trigger);
    expect(screen.getByText(/Kelly Criterion suggests optimal bet sizing/i)).toBeInTheDocument();
  });

  it("exposes the OddsEdgeCard Edge and Kelly explainers via focus", () => {
    render(<OddsEdgeCard edge={edge} />);
    const triggers = screen.getAllByRole("button");
    expect(triggers).toHaveLength(2);

    fireEvent.focus(triggers[0]);
    expect(screen.getByText(/bookmaker's fair probability/i)).toBeInTheDocument();
    fireEvent.blur(triggers[0]);

    fireEvent.focus(triggers[1]);
    expect(screen.getByText(/Kelly Criterion suggests optimal bet sizing/i)).toBeInTheDocument();
  });

  it("exposes the UncertaintyCard BNN/Epistemic/Aleatoric/CI explainers via focus", () => {
    const unc = {
      epistemic_unc: 0.12,
      aleatoric_unc: 0.2,
      concentration: 4,
      credible_interval: [0.4, 0.6] as [number, number],
      confidence_tier: "OK",
    };
    render(<UncertaintyCard unc={unc} available />);
    const triggers = screen.getAllByRole("button");
    const expectedText = [
      /Bayesian Neural Network/i,
      /Unknown-unknowns/i,
      /Irreducible randomness/i,
      /95% credible interval/i,
    ];
    expect(triggers).toHaveLength(expectedText.length);
    triggers.forEach((trigger, i) => {
      fireEvent.focus(trigger);
      expect(screen.getByText(expectedText[i])).toBeInTheDocument();
      fireEvent.blur(trigger);
    });
  });
});

describe("EvidenceStatusCard blocking-gap copy", () => {
  // `describeEvidenceCode` returns a lowercase sentence fragment because it is
  // also interpolated mid-sentence. A `capitalize` class here Title-Cased that
  // real copy into "This Model Hasn't Passed Certification Yet", which is
  // indistinguishable from the raw-enum `titleCaseCode` fallback the map exists
  // to replace — and that is exactly what the live /match page rendered.
  const blocked = {
    partial_intelligence: true,
    prediction_status: "REDUCED_EVIDENCE_BASELINE",
    probabilities_available: false,
    is_reduced_evidence_baseline: true,
    verdict: "NO_BET",
    stake_permitted: false,
    effective_kelly_cap: 0.025,
    narrative: "No bet — insufficient verified evidence.",
    freshness_tag: "UNKNOWN",
    generated_at: "2026-08-30T02:36:00Z",
    odds_edge: null,
    rl_recommendation: { abstain: true, stake_fraction: 0, reason: null },
    evidence_quality: {
      critical_gaps: ["MODEL_GENERATION_UNCERTIFIED", "MODEL_UNCERTAINTY_UNAVAILABLE"],
      advisory_gaps: [],
      conflicts: [],
      critical_gap_count: 2,
      advisory_gap_count: 0,
      conflict_count: 0,
      total_gap_count: 2,
    },
  } as unknown as Parameters<typeof EvidenceStatusCard>[0]["data"];

  it("renders mapped sentence copy without Title-Casing it", () => {
    render(<EvidenceStatusCard data={blocked} />);

    const gap = screen.getByText(/model hasn't passed certification yet/i);
    expect(gap.className).not.toMatch(/\bcapitalize\b/);
    expect(gap).toHaveTextContent("this model hasn't passed certification yet");
  });
});

describe("EdgeDeltaBar uses the backend's de-vigged edge", () => {
  // Backend contract (`_odds_edge_from_features`): the book is de-vigged
  // (`fair = (1/odds) / overround`) and `edge = model_prob - fair`. Here the
  // book carries a 6% overround, so the vigged price and the fair price are
  // 1.7pp apart — enough that recomputing `1 / market_odds` in the browser
  // produces a visibly different card from the backend's own number.
  const oddsEdge = {
    market: "home_win",
    market_odds: 3.3, // raw implied 30.303%
    model_prob: 0.393,
    edge: 0.10712, // 0.393 − 0.28588 fair
    kelly_stake: 0.02,
  };

  it("shows the fair market probability, not the vigged 1/odds price", () => {
    const { container } = render(<EdgeDeltaBar oddsEdge={oddsEdge} />);
    expect(container.textContent).toContain("Fair market 28.6%");
    // 1 / 3.3 = 30.3% — the bookmaker's margin still in it.
    expect(container.textContent).not.toContain("30.3%");
  });

  it("reports the backend edge in percentage points, never as EV", () => {
    const { container } = render(<EdgeDeltaBar oddsEdge={oddsEdge} />);
    expect(container.textContent).toContain("+10.7pp");
    expect(container.textContent).toContain("Model above fair market");
    // A probability-point gap is not expected value; the backend computes EV
    // separately (`model_prob * odds − 1`) and does not publish it here.
    expect(container.textContent).not.toContain("EV advantage");
  });

  it("agrees with the OddsEdgeCard rendered directly beneath it", () => {
    const delta = render(<EdgeDeltaBar oddsEdge={oddsEdge} />).container.textContent ?? "";
    const card = render(<OddsEdgeCard edge={oddsEdge} />).container.textContent ?? "";
    expect(delta).toContain("10.7");
    expect(card).toContain("10.7");
  });
});

describe("EvidencePassport (Phase 5 §5)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  function renderWithClient(ui: ReactElement) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
  }

  // Same shape EvidenceStatusCard suppresses on (presentation.stakePermitted
  // === true, via mapFullAnalysisPresentation) — the passport must stay
  // visible on exactly the path where the "why no bet" card renders nothing.
  const stakePermittedData = {
    match_id: "test-fixture",
    verdict: "ACTIONABLE",
    prediction_status: "AVAILABLE",
    prediction_source: "CERTIFIED_MODEL",
    probabilities_available: true,
    is_reduced_evidence_baseline: false,
    top_outcome_probability: 0.55,
    // probabilities_available: true makes mapFullAnalysisPresentation
    // dereference data.ensemble.* (full-analysis-contract.ts:527) — the
    // sibling `blocked` fixture above omits it only because its
    // probabilities_available: false short-circuits that branch.
    ensemble: {
      home_win_prob: 0.55,
      draw_prob: 0.25,
      away_win_prob: 0.2,
      prediction: "home_win",
      probabilities_available: true,
      league: "EPL",
      top_outcome_probability: 0.55,
      certification_state: "CERTIFIED",
    },
    effective_kelly_cap: 0.04,
    stake_permitted: true,
    partial_intelligence: false,
    narrative: "Model and market evidence are aligned.",
    freshness_tag: "LIVE",
    generated_at: "2026-09-04T12:00:00Z",
    odds_edge: { market: "home_win", market_odds: 2.1, model_prob: 0.55, edge: 0.05, kelly_stake: 0.02 },
    rl_recommendation: { abstain: false, stake_fraction: 0.02, reason: null, reward_components: {} },
    evidence_quality: {
      critical_gaps: [],
      advisory_gaps: ["market_prob_home"],
      conflicts: [],
      critical_gap_count: 0,
      advisory_gap_count: 1,
      conflict_count: 0,
      total_gap_count: 1,
    },
    field_availability: {
      fixture: true,
      prediction: true,
      market: true,
      uncertainty: true,
      elo: true,
    },
    unavailable_reasons: {},
  } as unknown as Parameters<typeof EvidenceStatusCard>[0]["data"];

  it("stays visible when EvidenceStatusCard renders nothing (stakePermitted path)", () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ status: "AVAILABLE", sources: [] }),
    } as unknown as Response);

    const statusCard = render(<EvidenceStatusCard data={stakePermittedData} />);
    expect(statusCard.container).toBeEmptyDOMElement();

    const passport = renderWithClient(<EvidencePassport data={stakePermittedData} />);
    expect(passport.container).not.toBeEmptyDOMElement();
    expect(screen.getByText("Fixture Identity")).toBeInTheDocument();
    expect(screen.getByText("Model Prediction")).toBeInTheDocument();
    expect(screen.getByText("Team Strength (Elo)")).toBeInTheDocument();
    // A resolved family can still carry advisory gaps — the market row's chip
    // reads "Resolved · 1" from this fixture's one advisory gap, which is
    // the honest rendering, so match the status prefix rather than exact text.
    expect(screen.getAllByText(/^Resolved/).length).toBe(5);
    expect(screen.queryByText(/^Gapped/)).toBeNull();
  });

  // Regression guard for the three raw-enum leaks the old DataFreshnessSection
  // rendered directly in JSX: {data.status} (route envelope), {src.freshness_status}
  // (title attr, keys a color map), and {src.category}. The mocked API response
  // below deliberately carries all five prohibited raw tokens somewhere in its
  // payload; none may reach the rendered DOM text.
  const gappedData = {
    ...stakePermittedData,
    field_availability: {
      fixture: true,
      prediction: true,
      market: false,
      uncertainty: false,
      elo: true,
    },
    unavailable_reasons: {
      market: "Coherent single-bookmaker 1X2 snapshot unavailable",
      uncertainty: "Certified ensemble-dispersion uncertainty unavailable",
    },
  } as unknown as Parameters<typeof EvidenceStatusCard>[0]["data"];

  it("never renders a raw backend token from the sources/freshness response", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "FETCH_FAILED",
        sources: [
          { name: "odds-market-features", category: "betting_market", freshness_status: "DATA_GAP", enabled: true },
          { name: "football-data.org", category: "fixtures_results", freshness_status: "STALE", enabled: true },
        ],
      }),
    } as unknown as Response);

    const { container } = renderWithClient(<EvidencePassport data={gappedData} />);

    // Wait for the sources/freshness query to resolve and the market row's
    // provenance sub-line (the one family with an honest category mapping) to render.
    await waitFor(() => {
      expect(container.textContent ?? "").toContain("Betting Market");
    });

    await waitFor(() => {
      const text = container.textContent ?? "";
      for (const raw of ["DATA_GAP", "fixtures_results", "UNAVAILABLE", "FETCH_FAILED", "UNKNOWN"]) {
        expect(text).not.toContain(raw);
      }
    });
  });
});
