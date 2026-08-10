import { expect, test } from "@playwright/test";

type Evidence = {
  critical_gaps: string[];
  advisory_gaps: string[];
  conflicts: string[];
};

function evidenceQuality({ critical_gaps, advisory_gaps, conflicts }: Evidence) {
  const all_gaps = [...new Set([...critical_gaps, ...advisory_gaps, ...conflicts])];
  return {
    critical_gaps,
    advisory_gaps,
    conflicts,
    all_gaps,
    critical_gap_count: critical_gaps.length,
    advisory_gap_count: advisory_gaps.length,
    conflict_count: conflicts.length,
    total_gap_count: all_gaps.length,
  };
}

function analysisPayload(options: {
  verdict?: "ACTIONABLE" | "PARTIAL";
  status?: "AVAILABLE" | "REDUCED_EVIDENCE_BASELINE" | "UNAVAILABLE";
  source?: "CERTIFIED_MODEL" | "DIAGNOSTIC_BASELINE" | "NONE";
  evidence?: Evidence;
  stakePermitted?: boolean;
}) {
  const status = options.status ?? "AVAILABLE";
  const evidence = evidenceQuality(options.evidence ?? {
    critical_gaps: [],
    advisory_gaps: [],
    conflicts: [],
  });
  const available = status === "AVAILABLE";
  const stakePermitted = options.stakePermitted ?? true;
  const probabilities = status === "UNAVAILABLE"
    ? { home_win_prob: 0, draw_prob: 0, away_win_prob: 0, top: 0 }
    : { home_win_prob: 0.5, draw_prob: 0.28, away_win_prob: 0.22, top: 0.5 };

  return {
    match_id: "Arsenal vs Chelsea",
    verdict: options.verdict ?? "ACTIONABLE",
    prediction_status: status,
    prediction_source: options.source ?? "CERTIFIED_MODEL",
    probabilities_available: available,
    is_reduced_evidence_baseline: status === "REDUCED_EVIDENCE_BASELINE",
    top_outcome_probability: probabilities.top,
    effective_kelly_cap: 0.04,
    stake_permitted: stakePermitted,
    fixture_verified: true,
    evidence_quality: evidence,
    ensemble: {
      home_win_prob: probabilities.home_win_prob,
      draw_prob: probabilities.draw_prob,
      away_win_prob: probabilities.away_win_prob,
      prediction: "home_win",
      confidence: probabilities.top,
      top_outcome_probability: probabilities.top,
      probabilities_available: available,
      league: "EPL",
      model_version: status === "AVAILABLE" ? "v5_phase7" : "diagnostic",
      calibration_method: status === "AVAILABLE" ? "isotonic" : "raw",
      calibration_applied: status === "AVAILABLE",
      overlay_applied: false,
    },
    uncertainty: {
      epistemic_unc: 0.05,
      aleatoric_unc: 0.1,
      concentration: 0.8,
      credible_interval: [0.42, 0.58],
      confidence_tier: "OK",
    },
    model_drivers: stakePermitted ? ["elo_difference"] : [],
    causal_drivers: stakePermitted ? ["elo_difference"] : [],
    rl_recommendation: {
      stake_fraction: stakePermitted ? 0.015 : 0,
      abstain: !stakePermitted,
      reason: stakePermitted ? "Quarter-Kelly within league cap" : "No public stake",
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
    odds_edge: stakePermitted
      ? { market: "home_win", market_odds: 2.4, model_prob: 0.5, edge: 0.08, kelly_stake: 0.015 }
      : null,
    narrative: stakePermitted
      ? "Verified evidence supports a bounded home-win position."
      : "No bet — insufficient verified evidence.",
    partial_intelligence: evidence.critical_gap_count > 0 || evidence.conflict_count > 0,
    data_gaps: evidence.all_gaps,
    staleness_seconds: 120,
    staleness_available: available,
    freshness_tag: available ? "LIVE" : "UNKNOWN",
    feature_freshness_seconds: {},
    feature_source: {},
    actionability: null,
    match_importance_score: null,
    competition_stage: null,
    generated_at: "2026-07-20T12:00:00Z",
  };
}

test.describe("match-analysis decision integrity", () => {
  test("renders real, advisory, baseline, unavailable, critical, and conflicting evidence", async ({ page }) => {
    const scenarios = [
      {
        id: "real",
        payload: analysisPayload({}),
        decision: "Consider home win",
        coverage: "0 critical / 0 advisory / 0 conflicts",
      },
      {
        id: "advisory",
        payload: analysisPayload({
          evidence: { critical_gaps: [], advisory_gaps: ["lineup_context"], conflicts: [] },
        }),
        decision: "Consider home win",
        coverage: "0 critical / 1 advisory / 0 conflicts",
      },
      {
        id: "baseline",
        payload: analysisPayload({
          verdict: "PARTIAL",
          status: "REDUCED_EVIDENCE_BASELINE",
          source: "DIAGNOSTIC_BASELINE",
          stakePermitted: false,
          evidence: { critical_gaps: ["MODEL_PREDICTION_REDUCED_EVIDENCE"], advisory_gaps: [], conflicts: [] },
        }),
        decision: "No bet",
        coverage: "1 critical / 0 advisory / 0 conflicts",
      },
      {
        id: "unavailable",
        payload: analysisPayload({
          verdict: "PARTIAL",
          status: "UNAVAILABLE",
          source: "NONE",
          stakePermitted: false,
          evidence: { critical_gaps: ["MODEL_PREDICTION_UNAVAILABLE"], advisory_gaps: [], conflicts: [] },
        }),
        decision: "No bet",
        coverage: "1 critical / 0 advisory / 0 conflicts",
      },
      {
        id: "critical",
        payload: analysisPayload({
          verdict: "PARTIAL",
          stakePermitted: false,
          evidence: { critical_gaps: ["COHERENT_1X2_MARKET_UNAVAILABLE"], advisory_gaps: [], conflicts: [] },
        }),
        decision: "No bet",
        coverage: "1 critical / 0 advisory / 0 conflicts",
      },
      {
        id: "conflict",
        payload: analysisPayload({
          verdict: "PARTIAL",
          stakePermitted: false,
          evidence: { critical_gaps: [], advisory_gaps: [], conflicts: ["CONFLICTING_MARKET_SNAPSHOTS"] },
        }),
        decision: "No bet",
        coverage: "0 critical / 0 advisory / 1 conflicts",
      },
    ];

    let activePayload = scenarios[0].payload;
    await page.route("**/api/full-analysis/**", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(activePayload),
    }));

    for (const scenario of scenarios) {
      activePayload = scenario.payload;
      await page.goto(`/match/${scenario.id}?league=EPL`);
      const summary = page.getByLabel("Actionability summary");
      await expect(summary.getByText(scenario.decision, { exact: true })).toBeVisible();
      await expect(summary.getByText(scenario.coverage, { exact: true })).toBeVisible();
      if (scenario.decision === "No bet") {
        await expect(page.getByText("Top outcome probability").first()).toBeVisible();
        await expect(page.getByRole("img", { name: "No bet" })).toBeVisible();
      }
    }
  });
});
