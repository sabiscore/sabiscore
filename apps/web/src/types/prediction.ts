/**
 * Next.js 15 TypeScript Interfaces for Stacked ML Live Inference.
 * Strictly mirrors the backend Pydantic v2 LivePredictionResponse model.
 */

export interface ProbabilitySimplex {
  home: number;
  draw: number;
  away: number;
}

export interface MarketOddsPayload {
  home_odds: number;
  draw_odds: number;
  away_odds: number;
  overround: number;
  bookmaker: string;
  odds_available?: boolean;
}

export interface KellyRecommendation {
  action: "ACTIONABLE" | "LEAN" | "NO_BET" | "HOLD";
  best_bet: "home" | "draw" | "away" | "none";
  edge: number;
  expected_value: number;
  kelly_fraction: number;
  stake_capped: boolean;
}

export interface TelemetrySummary {
  rolling_xg_home: number;
  rolling_xg_away: number;
  delta_rolling_xg: number;
  source: string;
}

export interface PredictionResponse {
  match_id: string;
  home_team: string;
  away_team: string;
  probabilities: ProbabilitySimplex;
  market: MarketOddsPayload;
  recommendation: KellyRecommendation;
  telemetry: TelemetrySummary;
}

export interface PredictMatchOptions {
  home_team?: string;
  away_team?: string;
  competition?: string;
  home_odds?: number;
  draw_odds?: number;
  away_odds?: number;
}
