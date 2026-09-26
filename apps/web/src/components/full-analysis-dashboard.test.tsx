import type { ReactElement } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  EdgeDeltaBar,
  AnalysisShareAction,
  buildAnalysisEvidenceSummary,
  EloContextCard,
  EnhancedMatchHero,
  EnsembleCard,
  EvidenceStatusCard,
  MarketComparisonTable,
  CounterCase,
  DecisionStateBadge,
  NarrativeBlock,
  OddsEdgeCard,
  RLCard,
  UncertaintyCard,
} from "./full-analysis-dashboard";
import { EvidencePassport } from "./evidence-passport";
import { mapFullAnalysisPresentation, type FullMatchMarket } from "@/lib/full-analysis-contract";

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
  // the standard reduced-evidence path shown live in production. 2026-09-22:
  // that whole explanatory paragraph is gone too — EvidenceStatusCard already
  // gives the one canonical "why" higher up the page, so this card now shows
  // only a per-outcome dash, the same minimal pattern EloContextCard uses.
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
    expect(container.textContent).not.toContain("Diagnostic baseline values are not displayed");
    expect(container.textContent).not.toContain("defaults toward");
    expect(container.textContent).toContain("Home Win unavailable");
    expect(container.textContent).toContain("—");
  });

  // Directive v7.3 P8 (INV-01 zero fabrication): the contract declares
  // calibration_method as a plain (never-null) string — confirmed in
  // full-analysis-contract.ts's z.string() — so this is a defensive
  // fallback for a state the backend should never send. The fallback named
  // a specific method ("isotonic") instead of a generic "calibrated" label;
  // if that field ever did arrive null, the UI would have claimed a
  // specific calibration method was used when none was known. Cast past
  // the type on purpose: this exercises the contract-violation path the
  // type system alone can't.
  it("never names a specific calibration method it was not actually told", () => {
    const { container } = render(
      <EnsembleCard
        data={{
          home_win_prob: 0.5,
          draw_prob: 0.25,
          away_win_prob: 0.25,
          prediction: "home",
          confidence: 0.5,
          top_outcome_probability: 0.5,
          probabilities_available: true,
          league: "EPL",
          model_version: "v5_phase7",
          calibration_method: null as unknown as string,
          calibration_applied: true,
          overlay_applied: false,
          certification_state: "UNVERIFIED",
          coverage: "dedicated",
        }}
      />,
    );
    // The bug lived in the tooltip's `title` attribute, not the visible chip
    // text (which already fell back to the honest "cal") — check the
    // attribute directly, not just textContent, or this test cannot see it.
    const titled = container.querySelector("[title]");
    expect(titled?.getAttribute("title")).not.toContain("isotonic");
    expect(container.textContent).not.toContain("isotonic");
    expect(container.textContent).toContain("cal");
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

  it("adds no counter-case to a WITHHELD fixture; the status card already says why", () => {
    const { container } = render(<CounterCase data={blocked} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders mapped sentence copy without Title-Casing it", () => {
    render(<EvidenceStatusCard data={blocked} />);

    const gap = screen.getByText(/model hasn't passed certification yet/i);
    expect(gap.className).not.toMatch(/\bcapitalize\b/);
    expect(gap).toHaveTextContent("this model hasn't passed certification yet");
  });

  it("never claims a typed matchup was found in the schedule", () => {
    render(<EvidenceStatusCard data={{ ...blocked, match_id: "Arsenal vs Brentford" }} />);
    expect(screen.queryByText(/identified in schedule/i)).not.toBeInTheDocument();
    expect(screen.getByText(/hypothetical matchup, not a scheduled fixture/i)).toBeInTheDocument();
  });

  it("keeps the schedule claim for a real fixture id", () => {
    render(<EvidenceStatusCard data={{ ...blocked, match_id: "fd-564645" }} />);
    expect(screen.getByText(/fixture identified in schedule/i)).toBeInTheDocument();
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

  it("argues against a PLAY forecast, loss probability first (directive v8 §3.5)", () => {
    const { container } = render(<CounterCase data={stakePermittedData} />);
    const items = container.querySelectorAll("li");
    expect(items[0].textContent).toMatch(/loses 45\.0% of the time/);
    expect(container.textContent).toMatch(/uncertainty is unavailable/i);
  });

  it.each(["PLAY", "PASS", "WITHHELD"] as const)(
    "names the %s state in words, not only colour",
    (state) => {
      const { container } = render(<DecisionStateBadge state={state} />);
      expect(container.textContent).toBe({ PLAY: "Play", PASS: "Pass", WITHHELD: "Withheld" }[state]);
    },
  );

  it.each(["PLAY", "PASS", "WITHHELD"] as const)(
    "colours the %s badge only through its state token (directive v10 U8)",
    (state) => {
      const html = render(<DecisionStateBadge state={state} />).container.innerHTML;
      expect(html).toContain(`--state-${state.toLowerCase()}`);
      // No palette hue carries the state; the label text stays neutral.
      expect(html).not.toMatch(/(?:border|bg)-(?:emerald|amber|slate|rose)-\d/);
      expect(html).not.toMatch(/text-(?:emerald|amber|rose)-\d/);
    },
  );

  it("stays visible when EvidenceStatusCard renders nothing (stakePermitted path)", () => {
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

  it("does not attach a never-measured registry status to a resolved market row", () => {
    // /sources/freshness is populated by nothing, so the passport printed
    // "Data unavailable" under "Market Price · Resolved" on every fixture whose
    // odds had just been fetched (live 2026-09-26). The passport now reads only
    // this fixture's own evidence, and fetches nothing.
    const fetchSpy = vi.spyOn(global, "fetch");
    const { container } = renderWithClient(<EvidencePassport data={stakePermittedData} />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/Market Price/);
    expect(text).not.toMatch(/Data unavailable/);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe("result-owned analysis sharing", () => {
  const shareableData = {
    match_id: "fd-share",
    verdict: "NO_BET",
    prediction_status: "AVAILABLE",
    probabilities_available: true,
    is_reduced_evidence_baseline: false,
    partial_intelligence: false,
    stake_permitted: false,
    effective_kelly_cap: 0.04,
    narrative: "No positive value at the current market.",
    generated_at: "2026-09-05T12:00:00Z",
    ensemble: {
      home_win_prob: 0.45,
      draw_prob: 0.3,
      away_win_prob: 0.25,
      prediction: "home_win",
      probabilities_available: true,
      certification_state: "UNVERIFIED",
    },
    rl_recommendation: { abstain: true, stake_fraction: 0, reason: "Risk gate abstained." },
    evidence_quality: {
      critical_gaps: [],
      advisory_gaps: ["market_prob_home"],
      conflicts: [],
      critical_gap_count: 0,
      advisory_gap_count: 1,
      conflict_count: 0,
      total_gap_count: 1,
    },
  } as unknown as Parameters<typeof AnalysisShareAction>[0]["data"];

  it("shares only the parsed result's probabilities, verdict, maturity, and evidence summary", () => {
    render(
      <AnalysisShareAction
        matchId="fd-share"
        league="EPL"
        homeTeam="Arsenal"
        awayTeam="Chelsea"
        data={shareableData}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /share current analysis/i }));

    expect(screen.getByRole("dialog", { name: /share match analysis/i })).toBeInTheDocument();
    expect(screen.getByText("45%")).toBeInTheDocument();
    expect(screen.getByText(/Research mode · Informational only/i)).toBeInTheDocument();
    expect(buildAnalysisEvidenceSummary(shareableData)).toBe(
      "Forecast available; 0 critical gaps, 1 advisory gap, 0 conflicts.",
    );
  });

  it("does not offer analytical sharing when official probabilities are unavailable", () => {
    const unavailable = {
      ...shareableData,
      prediction_status: "REDUCED_EVIDENCE_BASELINE",
      probabilities_available: false,
      is_reduced_evidence_baseline: true,
    } as typeof shareableData;

    const { container } = render(
      <AnalysisShareAction
        matchId="fd-share"
        league="EPL"
        homeTeam="Arsenal"
        awayTeam="Chelsea"
        data={unavailable}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});


describe("a withheld fixture that still carries a forecast (live fd-558881, 2026-09-25)", () => {
  // Uncertified generation: the forecast exists, the stake is withheld, and the
  // model puts the draw 8.3pp above the fair market price.
  const withheldWithForecast = {
    match_id: "fd-558881",
    verdict: "PARTIAL",
    prediction_status: "AVAILABLE",
    prediction_source: "UNCERTIFIED_MODEL",
    probabilities_available: true,
    is_reduced_evidence_baseline: false,
    top_outcome_probability: 0.646,
    ensemble: {
      home_win_prob: 0.646,
      draw_prob: 0.211,
      away_win_prob: 0.143,
      prediction: "home_win",
      probabilities_available: true,
      league: "EREDIVISIE",
      top_outcome_probability: 0.646,
      certification_state: "UNVERIFIED",
    },
    effective_kelly_cap: 0.025,
    stake_permitted: false,
    partial_intelligence: true,
    narrative: "No bet — insufficient verified evidence.",
    freshness_tag: "UNKNOWN",
    generated_at: "2026-09-25T19:09:00Z",
    odds_edge: { market: "draw", market_odds: 7.36, model_prob: 0.211, edge: 0.083, kelly_stake: 0 },
    rl_recommendation: { abstain: true, stake_fraction: 0, reason: null, reward_components: {} },
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

  describe("price movement since SabiScore first saw it (directive v10 U6)", () => {
    const outcome = { implied: 0.5, fair: 0.48, model_prob: 0.5, edge: 0.02, expected_value: null };
    const market = (first_seen: unknown) => ({
      ...withheldWithForecast,
      market: {
        devig_method: "proportional",
        overround: 1.058,
        evaluable: false,
        outcomes: [
          { ...outcome, outcome: "home_win", odds: 1.24 },
          { ...outcome, outcome: "draw", odds: 7.36 },
          { ...outcome, outcome: "away_win", odds: 8.65 },
        ],
        first_seen,
      },
    }) as typeof withheldWithForecast;
    const seen = (home_win: number) => ({
      bookmaker: "pinnacle",
      captured_at: "2026-10-09T13:00:00Z",
      home_win,
      draw: 7.36,
      away_win: 8.65,
    });

    it("states the move for the top outcome, from the same book", () => {
      const text = render(<CounterCase data={market(seen(1.28))} />).container.textContent ?? "";
      expect(text).toMatch(/price for home win moved from 1\.28 to 1\.24 since SabiScore first saw it/);
      // A first sighting is not an opening line: nothing observed the market opening.
      expect(text).not.toMatch(/open/i);
    });

    it("says an unchanged price is unchanged", () => {
      const text = render(<CounterCase data={market(seen(1.24))} />).container.textContent ?? "";
      expect(text).toMatch(/price for home win has not moved \(1\.24\) since SabiScore first saw it/);
    });

    it("says nothing about movement without a captured price", () => {
      for (const data of [market(null), withheldWithForecast]) {
        expect(render(<CounterCase data={data} />).container.textContent).not.toMatch(/first saw it/);
      }
    });
  });

  it("titles the status card for the missing stake, not a missing prediction", () => {
    render(<EvidenceStatusCard data={withheldWithForecast} />);
    expect(screen.getByRole("region", { name: /why no stake/i })).toBeInTheDocument();
    expect(screen.queryByText(/why no prediction/i)).not.toBeInTheDocument();
  });

  it("puts the counter-case beside the positive edge", () => {
    const { container } = render(<CounterCase data={withheldWithForecast} />);
    expect(container.textContent).toMatch(/Why this might fail/);
    expect(container.textContent).toMatch(/loses 35\.4% of the time/);
    expect(container.textContent).toMatch(/draw 8\.3pp above the fair market price.*not evidence of value/);
    // Already listed as a blocking gap in the status card above.
    expect(container.textContent).not.toMatch(/uncertainty is unavailable/i);
  });

  it("says each gap once: no caveat prose restating the banner or the status card", () => {
    // The live PSV page listed its gaps three times with two counts, and put
    // the uncertainty gap back under the status card that already blocks on it.
    const live = {
      ...withheldWithForecast,
      evidence_quality: {
        ...withheldWithForecast.evidence_quality,
        advisory_gaps: ["causal_analysis", "elo_league_adjusted", "home_pressing_intensity"],
        advisory_gap_count: 3,
      },
      actionability: {
        caveats: [
          "Certified ensemble-dispersion uncertainty unavailable",
          "2 live data gap(s): Causal Analysis, Elo League Adjusted",
        ],
      },
    } as typeof withheldWithForecast;
    const { container } = render(<CounterCase data={live} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/ensemble-dispersion uncertainty unavailable/i);
    expect(text).not.toMatch(/live data gap/i);
    expect(text).toMatch(/3 non-blocking inputs are missing/);
    expect(text).not.toMatch(/elo league adjusted|cross-league/i);
  });

  it("labels the market row as an outcome and withholds Kelly it will not size", () => {
    const edge = withheldWithForecast.odds_edge!;
    const withheld = render(<OddsEdgeCard edge={edge} />).container.textContent ?? "";
    expect(withheld).toMatch(/Outcome/);
    expect(withheld).not.toMatch(/Market(?! Edge)/);
    expect(withheld).toMatch(/Kelly.*Withheld/);
    expect(withheld).not.toMatch(/0\.00%/);
    const permitted =
      render(<OddsEdgeCard edge={{ ...edge, kelly_stake: 0.012 }} stakePermitted />).container
        .textContent ?? "";
    expect(permitted).toMatch(/1\.20%/);
  });

  it("shows no freshness pill when nothing was measured", () => {
    const { container } = render(
      <EnhancedMatchHero
        matchId="fd-558881"
        data={{ ...withheldWithForecast, staleness_available: false, staleness_seconds: 0 }}
        presentation={mapFullAnalysisPresentation({
          ...withheldWithForecast,
          staleness_available: false,
          staleness_seconds: 0,
        })}
        league="EREDIVISIE"
        homeTeam="PSV"
        awayTeam="SC Heerenveen"
      />,
    );
    expect(container.textContent).not.toMatch(/unknown/i);
    expect(container.querySelector('[aria-label="Data freshness unknown"]')).toBeNull();
  });

  it("does not colour a gap the backend will not stake on as value", () => {
    const edge = withheldWithForecast.odds_edge!;
    for (const { container } of [
      render(<EdgeDeltaBar oddsEdge={edge} />),
      render(<OddsEdgeCard edge={edge} />),
    ]) {
      expect(container.innerHTML).not.toMatch(/emerald/);
      expect(container.textContent).toContain("+8.3");
    }
    expect(render(<EdgeDeltaBar oddsEdge={edge} stakePermitted />).container.innerHTML).toMatch(/emerald/);
    // The neutral is a named decision state, not an incidental grey (v9 U4).
    expect(render(<EdgeDeltaBar oddsEdge={edge} />).container.innerHTML).toMatch(/--state-withheld/);
  });

  it("names no calibration method when no forecast is published", () => {
    // Live 2026-09-26: the hypothetical Arsenal v Bournemouth page read
    // "Top outcome probability: Unavailable" beside a SIGMOID chip.
    const calibrated = { ...withheldWithForecast.ensemble, calibration_applied: true, calibration_method: "sigmoid" };
    const noForecast = {
      ...withheldWithForecast,
      prediction_status: "REDUCED_EVIDENCE_BASELINE",
      probabilities_available: false,
      is_reduced_evidence_baseline: true,
      ensemble: { ...calibrated, probabilities_available: false },
    } as typeof withheldWithForecast;
    const hero = render(
      <EnhancedMatchHero
        matchId="Arsenal vs Bournemouth"
        data={noForecast}
        presentation={mapFullAnalysisPresentation(noForecast)}
        league="EPL"
      />,
    ).container;
    const card = render(<EnsembleCard data={noForecast.ensemble} />).container;
    for (const container of [hero, card]) expect(container.textContent).not.toMatch(/sigmoid/i);
    // A published forecast still reports the method applied to it.
    expect(render(<EnsembleCard data={calibrated} />).container.textContent).toMatch(/sigmoid/i);
  });
});


describe("MarketComparisonTable (directive v9 U1)", () => {
  const outcomes: FullMatchMarket["outcomes"] = [
    { outcome: "home_win", odds: 1.5, implied: 0.667, fair: 0.64, model_prob: 0.646, edge: 0.006, expected_value: null },
    { outcome: "draw", odds: 7.36, implied: 0.136, fair: 0.128, model_prob: 0.211, edge: 0.083, expected_value: null },
    { outcome: "away_win", odds: 4.2, implied: 0.238, fair: 0.232, model_prob: 0.143, edge: -0.089, expected_value: null },
  ];
  const withheld: FullMatchMarket = { devig_method: "proportional", overround: 1.041, evaluable: false, outcomes };

  it("shows the gap for all three outcomes, neutrally, with no expected return while withheld", () => {
    const { container } = render(<MarketComparisonTable market={withheld} />);
    const text = container.textContent ?? "";
    expect(screen.getAllByRole("row")).toHaveLength(4);
    expect(text).toContain("+8.3pp");
    expect(text).toContain("−8.9pp");
    expect(text).not.toMatch(/Expected return/);
    expect(container.innerHTML).not.toMatch(/emerald/);
    expect(text).toMatch(/not evidence of value/);
  });

  it("draws the dumbbell above the table, which stays the accessible text (directive v10 U5)", () => {
    const { container } = render(<MarketComparisonTable market={withheld} />);
    const chart = container.querySelector("svg[aria-hidden='true']");
    expect(chart?.querySelectorAll("[data-outcome]")).toHaveLength(3);
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("adds expected return only when the fixture is evaluable", () => {
    const evaluable = {
      ...withheld,
      evaluable: true,
      outcomes: outcomes.map((row) => ({ ...row, expected_value: row.outcome === "draw" ? 0.553 : -0.05 })),
    };
    const { container } = render(<MarketComparisonTable market={evaluable} />);
    expect(screen.getByRole("columnheader", { name: /Expected return/ })).toBeInTheDocument();
    expect(container.textContent).toContain("+55.3%");
  });

  it("renders market facts only when there is no measured forecast", () => {
    const marketOnly = {
      ...withheld,
      outcomes: outcomes.map((row) => ({ ...row, model_prob: null, edge: null })),
    };
    const { container } = render(<MarketComparisonTable market={marketOnly} />);
    expect(container.textContent).toMatch(/Market only/);
    expect(container.textContent).not.toMatch(/pp/);
  });
});
