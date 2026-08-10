import { describe, expect, it } from "vitest";
import {
  classifyAnalysisError,
  describeEvidenceCode,
  fullMatchAnalysisSchema,
  groupEvidenceGaps,
  isRetryableInfrastructureError,
  mapFullAnalysisPresentation,
} from "./full-analysis-contract";

function payload(overrides: Record<string, unknown> = {}) {
  const base = {
    match_id: "Arsenal vs Chelsea",
    verdict: "ACTIONABLE",
    prediction_status: "AVAILABLE",
    prediction_source: "CERTIFIED_MODEL",
    probabilities_available: true,
    is_reduced_evidence_baseline: false,
    top_outcome_probability: 0.5,
    effective_kelly_cap: 0.04,
    stake_permitted: true,
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
      home_win_prob: 0.5,
      draw_prob: 0.28,
      away_win_prob: 0.22,
      prediction: "home_win",
      confidence: 0.5,
      top_outcome_probability: 0.5,
      probabilities_available: true,
      league: "EPL",
      model_version: "v5_phase7",
      calibration_method: "isotonic",
      calibration_applied: true,
      overlay_applied: false,
    },
    uncertainty: {
      epistemic_unc: 0.05,
      aleatoric_unc: 0.1,
      concentration: 0.8,
      credible_interval: [0.42, 0.58],
      confidence_tier: "OK",
    },
    model_drivers: ["elo_difference"],
    causal_drivers: ["elo_difference"],
    rl_recommendation: {
      stake_fraction: 0.015,
      abstain: false,
      reason: "Quarter-Kelly within league cap",
      reward_components: {},
    },
    elo_context: {
      home_elo: 1550,
      away_elo: 1500,
      elo_difference: 50,
      home_elo_trend_5: 2,
      away_elo_trend_5: -1,
      elo_momentum_cross: 0,
    },
    odds_edge: {
      market: "home_win",
      market_odds: 2.4,
      model_prob: 0.5,
      edge: 0.08,
      kelly_stake: 0.015,
    },
    narrative: "[ACTIONABLE] Verified evidence supports a bounded home-win position.",
    partial_intelligence: false,
    data_gaps: [],
    staleness_seconds: 120,
    staleness_available: true,
    freshness_tag: "LIVE",
    feature_freshness_seconds: {},
    feature_source: {},
    actionability: {
      edge_quality_score: 0.7,
      clv_pct: null,
      closing_line_convergence_delta: null,
      suggested_stake_pct: 1.5,
      abstain: false,
      abstain_reason: null,
      top_evidence: ["Elo Difference"],
      caveats: [],
    },
    generated_at: "2026-07-20T12:00:00Z",
    match_importance_score: null,
    competition_stage: null,
    home_team: "Arsenal",
    away_team: "Chelsea",
    league: "EPL",
    kickoff_utc: "2026-07-21T15:00:00Z",
    fixture_verified: true,
    field_availability: {
      fixture: true,
      prediction: true,
      market: true,
      uncertainty: true,
      elo: true,
    },
    unavailable_reasons: {},
  };
  return fullMatchAnalysisSchema.parse({ ...base, ...overrides });
}

function blockedEvidence(kind: "critical" | "conflict") {
  const gap = kind === "critical" ? "MODEL_PREDICTION_UNAVAILABLE" : "CONFLICTING_MARKET_SNAPSHOTS";
  return {
    critical_gaps: kind === "critical" ? [gap] : [],
    advisory_gaps: [],
    conflicts: kind === "conflict" ? [gap] : [],
    all_gaps: [gap],
    critical_gap_count: kind === "critical" ? 1 : 0,
    advisory_gap_count: 0,
    conflict_count: kind === "conflict" ? 1 : 0,
    total_gap_count: 1,
  };
}

describe("full-analysis Zod contract and presentation", () => {
  it("maps certified actionable evidence to one bounded stake decision", () => {
    const view = mapFullAnalysisPresentation(payload(), new Date("2026-07-20T13:00:00Z"));
    expect(view.primaryDecision).toBe("Consider home win");
    expect(view.predictionAvailable).toBe(true);
    expect(view.topOutcomeProbability).toBe(0.5);
    expect(view.stakePermitted).toBe(true);
    expect(view.stakeFraction).toBe(0.015);
    expect(view.effectiveKellyCap).toBe(0.04);
    expect(view.kellyGaugeRatio).toBeCloseTo(0.375);
    expect(view.generatedRelative).toBe("1h ago");
    expect(view.generatedAbsoluteLagos).toContain("2026");
  });

  it("keeps advisory-only evidence available and counts it", () => {
    const evidence = {
      critical_gaps: [],
      advisory_gaps: ["lineup_context"],
      conflicts: [],
      all_gaps: ["lineup_context"],
      critical_gap_count: 0,
      advisory_gap_count: 1,
      conflict_count: 0,
      total_gap_count: 1,
    };
    const view = mapFullAnalysisPresentation(payload({ evidence_quality: evidence, data_gaps: evidence.all_gaps }));
    expect(view.predictionAvailable).toBe(true);
    expect(view.evidenceCounts.advisory).toBe(1);
  });

  it.each(["critical", "conflict"] as const)("forces %s evidence to No bet", (kind) => {
    const evidence = blockedEvidence(kind);
    const view = mapFullAnalysisPresentation(payload({
      verdict: "PARTIAL",
      partial_intelligence: true,
      stake_permitted: false,
      evidence_quality: evidence,
      data_gaps: evidence.all_gaps,
      rl_recommendation: { stake_fraction: 0, abstain: true, reason: "No bet", reward_components: {} },
      odds_edge: { ...payload().odds_edge, kelly_stake: 0 },
      actionability: null,
    }));
    expect(view.primaryDecision).toBe("No bet");
    expect(view.stakeFraction).toBe(0);
    expect(view.kellyGaugeRatio).toBe(0);
  });

  it.each([
    ["REDUCED_EVIDENCE_BASELINE", "DIAGNOSTIC_BASELINE"],
    ["UNAVAILABLE", "NONE"],
  ] as const)("withholds %s probabilities", (status, source) => {
    const evidence = blockedEvidence("critical");
    const ensemble = {
      ...payload().ensemble,
      probabilities_available: false,
      ...(status === "UNAVAILABLE"
        ? { home_win_prob: 0, draw_prob: 0, away_win_prob: 0, confidence: 0, top_outcome_probability: 0 }
        : {}),
    };
    const view = mapFullAnalysisPresentation(payload({
      verdict: "PARTIAL",
      prediction_status: status,
      prediction_source: source,
      probabilities_available: false,
      is_reduced_evidence_baseline: status === "REDUCED_EVIDENCE_BASELINE",
      top_outcome_probability: status === "UNAVAILABLE" ? 0 : 0.5,
      partial_intelligence: true,
      stake_permitted: false,
      evidence_quality: evidence,
      data_gaps: evidence.all_gaps,
      ensemble,
      rl_recommendation: { stake_fraction: 0, abstain: true, reason: "No bet", reward_components: {} },
      odds_edge: { ...payload().odds_edge, kelly_stake: 0 },
      actionability: null,
    }));
    expect(view.primaryDecision).toBe("No bet");
    expect(view.displayedProbabilities).toBeNull();
    expect(view.topOutcomeProbability).toBeNull();
  });

  it("keeps speculative evidence watchlist-only", () => {
    const view = mapFullAnalysisPresentation(payload({
      verdict: "SPECULATIVE",
      stake_permitted: false,
      rl_recommendation: { stake_fraction: 0, abstain: false, reason: "Watch", reward_components: {} },
      odds_edge: { ...payload().odds_edge, kelly_stake: 0 },
      actionability: null,
    }));
    expect(view.primaryDecision).toBe("Watchlist");
    expect(view.stakePermitted).toBe(false);
  });

  it("accepts null phase9 fields from an inactive-phase9 baseline response", () => {
    // Regression: the live backend returns phase9_shadow_only: null (Optional[bool]
    // = None) whenever phase9 is off — the production default. The schema previously
    // typed it .optional() (undefined only), so every real baseline failed to parse
    // and rendered "invalid full-analysis contract". The fixture omits the field, so
    // only an explicit null exercises this path.
    const evidence = blockedEvidence("critical");
    const result = fullMatchAnalysisSchema.safeParse({
      ...payload(),
      verdict: "PARTIAL",
      prediction_status: "REDUCED_EVIDENCE_BASELINE",
      prediction_source: "DIAGNOSTIC_BASELINE",
      probabilities_available: false,
      is_reduced_evidence_baseline: true,
      partial_intelligence: true,
      stake_permitted: false,
      evidence_quality: evidence,
      data_gaps: evidence.all_gaps,
      ensemble: { ...payload().ensemble, probabilities_available: false },
      rl_recommendation: { stake_fraction: 0, abstain: true, reason: "No bet", reward_components: {} },
      odds_edge: null,
      actionability: null,
      phase9_shadow_only: null,
      phase9_candidate_features: null,
    });
    expect(result.success).toBe(true);
  });

  it("rejects a non-simplex available prediction", () => {
    const valid = payload();
    const result = fullMatchAnalysisSchema.safeParse({
      ...valid,
      ensemble: { ...valid.ensemble, home_win_prob: 0.8 },
    });
    expect(result.success).toBe(false);
  });

  it("rejects any positive compatibility stake when the public gate is closed", () => {
    const valid = payload();
    const result = fullMatchAnalysisSchema.safeParse({
      ...valid,
      verdict: "HOLD",
      stake_permitted: false,
      rl_recommendation: { ...valid.rl_recommendation, stake_fraction: 0.01 },
    });
    expect(result.success).toBe(false);
  });
});

describe("analysis error taxonomy", () => {
  it("never classifies HTTP 500 as a cold start", () => {
    expect(classifyAnalysisError({ status: 500 })).toBe("backend_internal_error");
    expect(classifyAnalysisError({ status: 500, body: { error: "warming" } })).toBe("backend_internal_error");
  });

  it("recognizes explicit cold start and retryable infrastructure failures", () => {
    expect(classifyAnalysisError({ status: 503, body: { error: "cold_start" } })).toBe("cold_start");
    expect(classifyAnalysisError({ status: 504 })).toBe("upstream_unavailable");
    expect(isRetryableInfrastructureError("upstream_timeout")).toBe(true);
    expect(isRetryableInfrastructureError("backend_internal_error")).toBe(false);
  });

  it("classifies a 422 as insufficient evidence, not an unexpected error", () => {
    // The backend fails closed with 422 when required evidence is missing (e.g.
    // the off-season break). That is an expected state and must never render the
    // alarming "unexpected error" copy, nor auto-retry.
    expect(classifyAnalysisError({ status: 422 })).toBe("insufficient_evidence");
    expect(
      classifyAnalysisError({ status: 422, code: "INSUFFICIENT_EVIDENCE" }),
    ).toBe("insufficient_evidence");
    expect(isRetryableInfrastructureError("insufficient_evidence")).toBe(false);
  });

  it("recognizes a network failure from the error code as well as the flag", () => {
    // Regression guard: the server component passes {status, code} only. Keying
    // network detection solely on the boolean flag made every genuine connection
    // failure fall through to "unknown".
    expect(classifyAnalysisError({ status: 0, code: "NETWORK_ERROR" })).toBe("network_error");
    expect(classifyAnalysisError({ networkError: true })).toBe("network_error");
  });
});

describe("describeEvidenceCode", () => {
  it("renders every backend critical-gap code as plain language, never raw enum-speak", () => {
    // These are the exact codes appended to critical_gaps in the backend
    // (full_analysis.py / upcoming_match_service.py). A bare replaceAll("_", " ")
    // shouted "FIXTURE IDENTITY UNVERIFIED" on the most-read line of the match page.
    const codes = [
      "FIXTURE_IDENTITY_UNVERIFIED",
      "REQUIRED_MODEL_INPUTS_UNAVAILABLE",
      "MODEL_PREDICTION_UNAVAILABLE",
      "MODEL_PREDICTION_REDUCED_EVIDENCE",
      "STALE_REQUIRED_EVIDENCE",
      // Advisory, not critical — an out-of-date optional enrichment source must
      // never read like a blocking failure, so it needs its own plain-language
      // copy rather than the Title-Case enum fallback.
      "STALE_ENRICHMENT_EVIDENCE",
      "LEAGUE_POLICY_UNAVAILABLE",
    ];
    for (const code of codes) {
      const described = describeEvidenceCode(code);
      expect(described).not.toBe(code.replaceAll("_", " "));
      expect(described).not.toMatch(/[A-Z]{2,}/); // no SHOUTING fragments survive
      expect(described.length).toBeGreaterThan(20); // a sentence, not a relabelled token
    }
  });

  it("falls back to title case for an unmapped code rather than dropping it", () => {
    // A code we have no copy for must stay legible and must never render empty —
    // the reason line is the only explanation the reader gets.
    expect(describeEvidenceCode("SOME_FUTURE_GAP")).toBe("Some Future Gap");
    expect(describeEvidenceCode("")).toBe("");
  });

  it("keeps the reason line human when a critical gap blocks the verdict", () => {
    // The off-season / unsynced-team path users actually hit most often.
    const evidence = {
      critical_gaps: ["FIXTURE_IDENTITY_UNVERIFIED"],
      advisory_gaps: [],
      conflicts: [],
      all_gaps: ["FIXTURE_IDENTITY_UNVERIFIED"],
      critical_gap_count: 1,
      advisory_gap_count: 0,
      conflict_count: 0,
      total_gap_count: 1,
    };
    const view = mapFullAnalysisPresentation(
      payload({
        verdict: "PARTIAL",
        partial_intelligence: true,
        stake_permitted: false,
        evidence_quality: evidence,
        data_gaps: evidence.all_gaps,
        rl_recommendation: { stake_fraction: 0, abstain: true, reason: "No bet", reward_components: {} },
        odds_edge: { ...payload().odds_edge, kelly_stake: 0 },
        actionability: null,
      }),
    );
    expect(view.reason).toContain("could not be tied to a scheduled fixture");
    expect(view.reason).not.toContain("FIXTURE_IDENTITY_UNVERIFIED");
    expect(view.reason).not.toContain("FIXTURE IDENTITY UNVERIFIED");
  });
});

describe("groupEvidenceGaps", () => {
  it("collapses raw canonical feature names into reader-facing families", () => {
    const groups = groupEvidenceGaps([
      "market_prob_home", "market_prob_draw", "log_odds_home", "ev_home",
      "h2h_home_wins", "h2h_draws",
      "elo_difference", "elo_momentum_cross",
      "home_venue_win_rate",
    ]);
    const byLabel = Object.fromEntries(groups.map((g) => [g.label, g.count]));
    expect(byLabel["Market prices"]).toBe(4);
    expect(byLabel["Head-to-head record"]).toBe(2);
    expect(byLabel["Team strength ratings"]).toBe(2);
    expect(byLabel["Home venue record"]).toBe(1);
  });

  it("never surfaces a raw feature name as a family label", () => {
    for (const group of groupEvidenceGaps([
      "away_attack_vs_home_defense", "combined_defense_weakness",
      "shot_quality_diff", "home_weighted_ppg", "match_importance_score",
    ])) {
      expect(group.label).not.toMatch(/_/);
      expect(group.label).not.toMatch(/\b(diff|avg|pct)\b/i);
    }
  });

  it("claims market-interaction fields for Market prices, not h2h/venue", () => {
    const groups = groupEvidenceGaps(["h2h_market_agreement", "venue_market_combo", "form_market_disagreement"]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Market prices");
    expect(groups[0].count).toBe(3);
  });

  it("orders by size and retains every raw code for auditability", () => {
    const gaps = ["h2h_draws", "market_prob_home", "market_prob_away", "elo_difference"];
    const groups = groupEvidenceGaps(gaps);
    expect(groups[0].label).toBe("Market prices");
    expect(groups.flatMap((g) => g.codes).sort()).toEqual([...gaps].sort());
  });

  it("buckets an unrecognised code rather than dropping it", () => {
    const groups = groupEvidenceGaps(["some_brand_new_signal"]);
    expect(groups[0].label).toBe("Other inputs");
    expect(groups[0].codes).toEqual(["some_brand_new_signal"]);
  });
});
