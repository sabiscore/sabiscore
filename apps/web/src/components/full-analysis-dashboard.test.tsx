import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  EloContextCard,
  EnsembleCard,
  EvidenceStatusCard,
  NarrativeBlock,
  OddsEdgeCard,
  RLCard,
  UncertaintyCard,
} from "./full-analysis-dashboard";

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
    expect(screen.getByText(/difference between our model's probability/i)).toBeInTheDocument();
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
