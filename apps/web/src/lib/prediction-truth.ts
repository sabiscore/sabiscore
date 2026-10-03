/**
 * Consumer-truth mapping for the match prediction summary.
 *
 * This module only *re-labels* values the FastAPI backend already computed
 * (probabilities, verdict, stake permission, evidence gaps). It never derives
 * de-vig, EV, Kelly or stakes, and it never substitutes a value when the
 * backend is unavailable: every failure becomes an explicit WITHHELD /
 * UNAVAILABLE state that carries no probabilities.
 */

import type { FullMatchAnalysisResponse } from "@/lib/full-analysis-contract";

export type TruthState =
  | "RESEARCH_MODE"
  | "INSUFFICIENT_VERIFIED_DATA"
  | "NO_VERIFIED_EDGE"
  | "POTENTIAL_VALUE"
  | "WITHHELD";

export const TRUTH_STATE_LABEL: Record<TruthState, string> = {
  RESEARCH_MODE: "Research Mode",
  INSUFFICIENT_VERIFIED_DATA: "Insufficient Verified Data",
  NO_VERIFIED_EDGE: "No Verified Edge",
  POTENTIAL_VALUE: "Potential Value",
  WITHHELD: "Withheld",
};

export type MarketHealth = "VERIFIED_EVALUABLE" | "AVAILABLE_NOT_EVALUABLE" | "UNAVAILABLE";

export interface PredictionSummary {
  match_id: string;
  home_team: string | null;
  away_team: string | null;
  truth_state: Exclude<TruthState, "WITHHELD" | "INSUFFICIENT_VERIFIED_DATA">;
  probabilities: { home: number; draw: number; away: number };
  model: {
    version: string;
    generation: string | null;
    certification_state: string;
    prediction_source: string;
    calibration_method: string;
    calibration_applied: boolean;
  };
  evidence: { critical: number; advisory: number; conflicts: number };
  market: {
    health: MarketHealth;
    bookmaker: string | null;
    captured_at: string | null;
  };
  freshness: { tag: string; staleness_seconds: number | null };
  verdict: string;
  stake_permitted: boolean;
  /** Backend-computed value; null unless the backend permits public staking. */
  suggested_stake_pct: number | null;
  counter_case: string[];
  generated_at: string;
}

export interface PredictionWithheld {
  status: "WITHHELD";
  truth_state: "WITHHELD" | "INSUFFICIENT_VERIFIED_DATA";
  reason_code: string;
  message: string;
  data_gaps: string[];
}

export interface PredictionUnavailable {
  status: "UNAVAILABLE";
  truth_state: "WITHHELD";
  reason_code: string;
  message: string;
}

export interface PredictionOk {
  status: "OK";
  truth_state: Exclude<TruthState, "WITHHELD" | "INSUFFICIENT_VERIFIED_DATA">;
  summary: PredictionSummary;
}

export type PredictionResult = PredictionOk | PredictionWithheld | PredictionUnavailable;

export function unavailable(reason_code: string, message: string): PredictionUnavailable {
  return { status: "UNAVAILABLE", truth_state: "WITHHELD", reason_code, message };
}

function marketHealth(analysis: FullMatchAnalysisResponse): MarketHealth {
  if (!analysis.market) return "UNAVAILABLE";
  return analysis.market.evaluable ? "VERIFIED_EVALUABLE" : "AVAILABLE_NOT_EVALUABLE";
}

/** Map a schema-validated canonical analysis to a consumer-truth result. */
export function summarizeAnalysis(analysis: FullMatchAnalysisResponse): PredictionResult {
  const gaps = analysis.evidence_quality.all_gaps.slice(0, 5);

  if (analysis.prediction_status === "REDUCED_EVIDENCE_BASELINE") {
    return {
      status: "WITHHELD",
      truth_state: "INSUFFICIENT_VERIFIED_DATA",
      reason_code: "REDUCED_EVIDENCE_BASELINE",
      message:
        "Only a diagnostic baseline exists for this fixture. It is not presented as a forecast.",
      data_gaps: gaps,
    };
  }

  if (analysis.prediction_status === "UNAVAILABLE" || !analysis.probabilities_available) {
    return {
      status: "WITHHELD",
      truth_state: "WITHHELD",
      reason_code: "MODEL_OR_EVIDENCE_UNAVAILABLE",
      message:
        "The model or required evidence is unavailable, so no forecast is shown for this fixture.",
      data_gaps: gaps,
    };
  }

  const certified = analysis.ensemble.certification_state === "CERTIFIED";
  const market = marketHealth(analysis);
  const actionableVerdict =
    analysis.verdict === "ACTIONABLE" || analysis.verdict === "HIGH_CONVICTION";

  let truth: PredictionSummary["truth_state"];
  if (!certified) {
    truth = "RESEARCH_MODE";
  } else if (market === "VERIFIED_EVALUABLE" && actionableVerdict && analysis.stake_permitted) {
    truth = "POTENTIAL_VALUE";
  } else {
    truth = "NO_VERIFIED_EDGE";
  }

  const stakePct =
    analysis.stake_permitted && analysis.actionability
      ? analysis.actionability.suggested_stake_pct
      : null;

  return {
    status: "OK",
    truth_state: truth,
    summary: {
      match_id: analysis.match_id,
      home_team: analysis.home_team ?? null,
      away_team: analysis.away_team ?? null,
      truth_state: truth,
      probabilities: {
        home: analysis.ensemble.home_win_prob,
        draw: analysis.ensemble.draw_prob,
        away: analysis.ensemble.away_win_prob,
      },
      model: {
        version: analysis.ensemble.model_version,
        generation: analysis.ensemble.generation ?? null,
        certification_state: analysis.ensemble.certification_state,
        prediction_source: analysis.prediction_source,
        calibration_method: analysis.ensemble.calibration_method,
        calibration_applied: analysis.ensemble.calibration_applied,
      },
      evidence: {
        critical: analysis.evidence_quality.critical_gap_count,
        advisory: analysis.evidence_quality.advisory_gap_count,
        conflicts: analysis.evidence_quality.conflict_count,
      },
      market: {
        health: market,
        bookmaker: analysis.market?.bookmaker ?? null,
        captured_at: analysis.market?.captured_at ?? null,
      },
      freshness: {
        tag: analysis.freshness_tag,
        staleness_seconds: analysis.staleness_available ? analysis.staleness_seconds : null,
      },
      verdict: analysis.verdict,
      stake_permitted: analysis.stake_permitted,
      suggested_stake_pct: stakePct,
      counter_case: gaps,
      generated_at: analysis.generated_at,
    },
  };
}
