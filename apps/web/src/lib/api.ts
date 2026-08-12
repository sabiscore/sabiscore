// Edge-optimized API client for Sabiscore
// Supports Cloudflare KV → Upstash Redis → PostgreSQL cache hierarchy


// Performance optimization: Enable connection reuse
const ENABLE_KEEPALIVE = true;

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy";
  database: boolean;
  models: boolean;
  cache: boolean;
  cache_metrics: Record<string, unknown>;
  latency_ms: number;
}

export interface PredictionSummary {
  home_win_prob: number;
  draw_prob: number;
  away_win_prob: number;
  prediction: string;
  confidence: number;
}

export interface XGAnalysis {
  home_xg: number;
  away_xg: number;
  total_xg: number;
  xg_difference: number;
}

export interface ValueBetQuality {
  quality_score: number;
  tier: string;
  recommendation: string;
  ev_contribution: number;
  confidence_contribution: number;
  liquidity_contribution: number;
}

export interface ValueBet {
  bet_type: string;
  market_odds: number;
  model_prob: number;
  market_prob: number;
  expected_value: number;
  value_pct: number;
  kelly_stake: number;
  confidence_interval: number[];
  edge: number;
  recommendation: string;
  quality: ValueBetQuality;
}

export interface MonteCarloData {
  simulations: number;
  distribution: Record<string, number>;
  confidence_intervals: Record<string, number[]>;
}

export interface Scenario {
  name: string;
  probability: number;
  home_score: number;
  away_score: number;
  result: string;
}

export interface RiskAssessment {
  risk_level: string;
  confidence_score: number;
  value_available: boolean;
  best_bet?: ValueBet | null;
  distribution: Record<string, number>;
  recommendation: string;
}

// ── Phase 6 types ────────────────────────────────────────────────────────────

export interface CredibleInterval {
  lower: number;
  upper: number;
}

export interface UncertaintyBreakdown {
  epistemic_unc: number;
  aleatoric_unc: number;
  concentration: number;
  credible_interval: CredibleInterval;
  /** "LOW_EVIDENCE" when epistemic > threshold; "OK" otherwise. C12 */
  confidence_tier?: "LOW_EVIDENCE" | "OK";
}

export interface CausalSummary {
  top_drivers: string[];
  collider_warnings: string[];
  source?: string | null;
  status: string;
}

export interface RLRecommendation {
  stake_fraction: number;
  abstain: boolean;
  reward_components: Record<string, number>;
  reason?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────

export interface Metadata {
  matchup: string;
  league: string;
  home_team: string;
  away_team: string;
}

export interface TransformationStep {
  step: string;
  function: string;
  timestamp: string;
}

export interface DataProvenance {
  source: Record<string, unknown>;
  computed_from: string[];
  transformations: TransformationStep[];
  real_time_adjusted: boolean;
  drift_detected?: Record<string, unknown> | null;
  validation_status: string;
}

export interface InsightsResponse {
  matchup: string;
  league: string;
  metadata: Metadata;
  predictions: PredictionSummary;
  xg_analysis: XGAnalysis;
  value_analysis: {
    bets: ValueBet[];
    edges: Record<string, number>;
    best_bet?: ValueBet | null;
    summary: string;
  };
  monte_carlo: MonteCarloData;
  scenarios: Scenario[];
  explanation: Record<string, unknown>;
  risk_assessment: RiskAssessment;
  narrative: string;
  generated_at: string;
  confidence_level: number;
  provenance?: DataProvenance | null;
  uncertainty?: UncertaintyBreakdown | null;
  causal_summary?: CausalSummary | null;
  rl_recommendation?: RLRecommendation | null;
}

class APIError extends Error {
  constructor(
    message: string,
    public status?: number,
    public code?: string
  ) {
    super(message);
    this.name = "APIError";
  }

  // Ensure proper serialization for logging
  toJSON() {
    return {
      name: this.name,
      message: this.message,
      status: this.status,
      code: this.code,
    };
  }

  // Proper string representation
  toString() {
    return `${this.name}: ${this.message}${this.status ? ` (${this.status})` : ''}${this.code ? ` [${this.code}]` : ''}`;
  }
}

export interface ApiFetchOptions extends RequestInit {
  timeoutMs?: number;
  retries?: number;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  if (!path.startsWith("/")) {
    throw new APIError("Browser API calls must use same-origin backend proxy paths", 400, "INVALID_API_PATH");
  }

  const { timeoutMs = 8_000, retries = 2, ...requestOptions } = options;
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const headers = new Headers(requestOptions.headers);
      headers.set("Accept", "application/json");
      if (requestOptions.body && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
      }

      const response = await fetch(path, {
        ...requestOptions,
        headers,
        signal: controller.signal,
        cache: requestOptions.cache ?? "no-store",
      });

      if (!response.ok) {
        let message = `HTTP ${response.status}`;
        try {
          const body = (await response.json()) as { detail?: string; error?: string; message?: string };
          message = body.detail ?? body.error ?? body.message ?? message;
        } catch {
          // Keep the HTTP fallback.
        }

        const apiError = new APIError(message, response.status, "BACKEND_ERROR");
        if (response.status >= 400 && response.status < 500) {
          throw apiError;
        }
        lastError = apiError;
      } else {
        return (await response.json()) as T;
      }
    } catch (error) {
      if (error instanceof APIError && error.status && error.status >= 400 && error.status < 500) {
        throw error;
      }
      if (error instanceof Error && error.name === "AbortError") {
        lastError = new APIError("Backend request timed out", 408, "TIMEOUT");
      } else {
        lastError = error;
      }
    } finally {
      clearTimeout(timeout);
    }

    if (attempt < retries) {
      await new Promise((resolve) => setTimeout(resolve, 350 * 2 ** attempt));
    }
  }

  if (lastError instanceof APIError) throw lastError;
  if (lastError instanceof Error) throw new APIError(lastError.message, 503, "NETWORK_ERROR");
  throw new APIError("Backend request failed", 503, "NETWORK_ERROR");
}

export interface ReadyCheckResponse {
  status: "ok" | "not_ready" | string;
  checks: Record<string, unknown>;
  models_loaded: boolean;
  leagues_loaded: string[];
  required_leagues: string[];
  model_error?: string | null;
  timestamp: string;
}

export interface CertifiedPredictionRequest {
  match_id: string;
  home_team: string;
  away_team: string;
  competition: string;
  kickoff_utc: string;
  model: {
    home_probability: number;
    draw_probability: number;
    away_probability: number;
    model_version?: string;
    calibration_method?: string;
    calibration_validated?: boolean;
    epistemic_uncertainty?: number;
    aleatoric_uncertainty?: number;
    confidence_tier?: "OK" | "LOW_EVIDENCE";
  };
  market?: {
    bookmaker: string;
    market_type?: "1X2";
    home_odds: number;
    draw_odds: number;
    away_odds: number;
    opening_home_odds?: number;
    opening_draw_odds?: number;
    opening_away_odds?: number;
    captured_at: string;
  } | null;
  signals?: Record<string, unknown>;
  freshness?: Record<string, number | null>;
  source_status?: Record<string, string>;
  data_gaps?: string[];
  known_risks?: string[];
}

export interface CertifiedMarketEvaluation {
  outcome: string;
  market_label: "HOME_ML" | "DRAW_ML" | "AWAY_ML";
  model_probability: number;
  market_odds: number;
  raw_implied_probability: number;
  fair_market_probability: number;
  edge: number;
  edge_pct: number;
  expected_value: number;
  stake_fraction: number;
  confidence_adjusted_value: number;
}

export interface CertifiedMatchAnalysis {
  decision_id?: string | null;
  evaluation_at?: string | null;
  analysis_mode: "VALUE_ANALYSIS" | "FORECAST_ONLY";
  execution_eligible: boolean;
  watchlist: boolean;
  match_identifier: string;
  match_id: string;
  competition: string;
  verdict: "HIGH_CONVICTION" | "ACTIONABLE" | "SPECULATIVE" | "HOLD" | "PARTIAL" | "NO_BET";
  probabilities?: { home?: number | null; draw?: number | null; away?: number | null } | null;
  best_market?: "HOME_ML" | "DRAW_ML" | "AWAY_ML" | null;
  market_odds?: number | null;
  fair_market_probability?: number | null;
  edge_percentage_points?: number | null;
  expected_value?: number | null;
  confidence?: "HIGH" | "MEDIUM" | "LOW" | null;
  confidence_adjusted_value?: number | null;
  stake: string;
  stake_fraction: number;
  minimum_acceptable_odds?: number | null;
  drivers: string[];
  risks: string[];
  invalidation_conditions: string[];
  critical_gaps?: string[];
  advisory_gaps?: string[];
  conflicts?: string[];
  all_market_evaluations?: CertifiedMarketEvaluation[] | null;
  data_gaps: string[];
  data_freshness?: {
    status: string;
    market_captured_at?: string | null;
    oldest_critical_input_seconds?: number | null;
    lineup_status: string;
  } | null;
  calculation_audit?: {
    bookmaker?: string | null;
    market_overround?: number | null;
    breakeven_odds?: number | null;
    minimum_odds_for_target_ev?: number | null;
    edge_preserving_minimum_odds?: number | null;
    kelly_fraction: number;
    kelly_cap: number;
  } | null;
  explanation: string;
}

export async function getBackendReadiness(): Promise<ReadyCheckResponse> {
  return apiFetch<ReadyCheckResponse>("/api/health/ready", {
    timeoutMs: 5_000,
    retries: 1,
  });
}

export async function analyzeCertifiedPrediction(
  request: CertifiedPredictionRequest,
): Promise<CertifiedMatchAnalysis> {
  return apiFetch<CertifiedMatchAnalysis>("/api/v1/predictions/analyze", {
    method: "POST",
    body: JSON.stringify(request),
    timeoutMs: 10_000,
    retries: 1,
  });
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit = {},
  timeout = 10000
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      // Enable keep-alive for connection reuse
      keepalive: ENABLE_KEEPALIVE,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new APIError("The prediction engine is warming up. Please try again in 30 seconds.", 408, "TIMEOUT");
    }
    // Handle network errors gracefully
    if (error instanceof TypeError && error.message.includes('fetch')) {
      throw new APIError("Network error - please check your connection", 0, "NETWORK_ERROR");
    }
    throw error;
  }
}

async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  timeout = 10000,
  maxRetries = 2
): Promise<Response> {
  let lastError: Error | undefined;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fetchWithTimeout(url, options, timeout);
    } catch (error) {
      lastError = error as Error;
      
      // Don't retry on client errors (4xx)
      if (error instanceof APIError && error.status && error.status >= 400 && error.status < 500) {
        throw error;
      }
      
      // Exponential backoff: 1s, 2s, 4s
      if (attempt < maxRetries) {
        await new Promise(resolve => setTimeout(resolve, Math.pow(2, attempt) * 1000));
      }
    }
  }
  
  throw lastError || new APIError("Max retries exceeded", 503, "MAX_RETRIES_EXCEEDED");
}

export async function healthCheck(): Promise<HealthResponse> {
  try {
    // Use the Next.js proxy route to avoid cross-origin requests from the browser.
    // The /api/health route is same-origin from the client's perspective and proxies
    // to the Render backend server-side.
    const response = await fetchWithRetry('/api/health', {
      next: { revalidate: 60 }, // Cache for 60 seconds
    }, 5000, 1); // 5s timeout, 1 retry

    if (!response.ok) {
      throw new APIError(
        "Health check failed",
        response.status,
        "HEALTH_CHECK_FAILED"
      );
    }

    return await response.json();
  } catch (error) {
    console.error("Health check error:", error);
    throw error;
  }
}

// getMatchInsights lives in `lib/insights-server.ts`: it is server-only and must
// call the backend directly. A relative fetch from a server component throws
// `Failed to parse URL`, which is what silently broke the /match insights panel.

// Client-side API client for use in React components
export const apiClient = {
  healthCheck,
  
  async generateInsights(matchup: string, league: string = "EPL"): Promise<InsightsResponse> {
    const response = await fetch("/api/insights", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ matchup, league }),
    });

    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const errorData = await response.json();
        errorMessage = errorData.detail || errorData.message || errorMessage;
      } catch {
        // Ignore
      }
      throw new APIError(errorMessage, response.status, "INSIGHTS_ERROR");
    }

    return (await response.json()) as InsightsResponse;
  },
};

// ---------------------------------------------------------------------------
// Phase 7-D: FullMatchAnalysisResponse types and client
// ---------------------------------------------------------------------------

export type {
  FullMatchAnalysisResponse,
  FullMatchEloContext,
  FullMatchEnsemble,
  FullMatchOddsEdge,
  FullMatchRLRecommendation,
  FullMatchUncertainty,
  MatchActionability,
} from "./full-analysis-contract";

import {
  classifyAnalysisError,
  fullMatchAnalysisSchema,
  isRetryableInfrastructureError,
  type FullMatchAnalysisResponse,
} from "./full-analysis-contract";

export async function getFullAnalysis(
  matchId: string,
  league: string = "EPL",
): Promise<FullMatchAnalysisResponse> {
  const url = `/api/full-analysis/${encodeURIComponent(matchId)}?league=${encodeURIComponent(league)}`;
  const deadline = Date.now() + 28_000;
  let lastError: APIError | null = null;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    const controller = new AbortController();
    const timeoutId = setTimeout(
      () => controller.abort(),
      Math.max(1, deadline - Date.now()),
    );
    try {
      const response = await fetch(url, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal,
      });
      const body = await response.json().catch(() => null) as unknown;

      if (!response.ok) {
        const category = classifyAnalysisError({
          status: response.status,
          body,
        });
        const detail = body && typeof body === "object"
          ? String(
              (body as { detail?: unknown; error?: unknown }).detail ??
                (body as { error?: unknown }).error ??
                `HTTP ${response.status}`,
            )
          : `HTTP ${response.status}`;
        const failure = new APIError(detail, response.status, category.toUpperCase());
        if (attempt === 0 && isRetryableInfrastructureError(category) && Date.now() < deadline) {
          lastError = failure;
          continue;
        }
        throw failure;
      }

      const parsed = fullMatchAnalysisSchema.safeParse(body);
      if (!parsed.success) {
        throw new APIError(
          "The backend returned an invalid full-analysis contract.",
          502,
          "INVALID_RESPONSE",
        );
      }
      return parsed.data;
    } catch (error) {
      const failure = error instanceof APIError
        ? error
        : error instanceof Error && error.name === "AbortError"
          ? new APIError("Full analysis timed out after 28 seconds.", 408, "UPSTREAM_TIMEOUT")
          : new APIError(
              error instanceof Error ? error.message : "Network request failed.",
              0,
              "NETWORK_ERROR",
            );
      const category = classifyAnalysisError({
        status: failure.status,
        code: failure.code,
        networkError: failure.code === "NETWORK_ERROR",
      });
      if (attempt === 0 && isRetryableInfrastructureError(category) && Date.now() < deadline) {
        lastError = failure;
        continue;
      }
      throw failure;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  throw lastError ?? new APIError("Full analysis unavailable.", 503, "UPSTREAM_UNAVAILABLE");
}

// ---------------------------------------------------------------------------
// Phase 8 Sprint 2: Phase8FeaturesResponse types and client
// ---------------------------------------------------------------------------

export interface Phase8FeatureValue {
  name: string;
  value: number;
  is_data_gap: boolean;
  /**
   * Seconds since this feature's live data source was last updated.
   * null = DATA_GAP (not computable). 0 = fresh. >0 = staleness in seconds.
   */
  freshness_seconds: number | null;
  source: string | null;
}

export interface Phase8FeatureGroup {
  group_id: string;
  label: string;
  description: string;
  reference: string;
  features: Phase8FeatureValue[];
  all_available: boolean;
  /** Max staleness across the group's live features (seconds). 0 if all are DATA_GAP. */
  group_freshness_seconds: number;
}

export interface Phase8FeaturesResponse {
  match_id: string;
  league: string;
  /** "ok" | "partial" | "disabled" */
  status: string;
  data_gaps: string[];
  feature_groups: Phase8FeatureGroup[];
  /**
   * Per-feature staleness map for Phase 8 features.
   * null = DATA_GAP. 0 = fresh. >0 = staleness in seconds.
   */
  feature_freshness_seconds: Record<string, number | null>;
  total_phase8_features: number;
  available_features: number;
  phase8_enabled: boolean;
  source: string;
}

/**
 * Fetch Phase 8 enriched feature values for a match from the backend proxy.
 * The backend route is: GET /matches/upcoming/{match_id}/phase8-features
 * Proxied via Next.js API at: /api/phase8-features/{matchId}
 */
export async function getPhase8Features(
  matchId: string,
  league: string = "EPL",
): Promise<Phase8FeaturesResponse> {
  const url = `/api/phase8-features/${encodeURIComponent(matchId)}?league=${encodeURIComponent(league)}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate: 60 },
      signal: controller.signal,
    } as RequestInit);

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        if (err.error === "cold_start") {
          throw new APIError(
            err.detail || "The prediction engine is warming up.",
            503,
            "COLD_START",
          );
        }
        detail = err.detail || err.error || detail;
      } catch (parseErr) {
        if (parseErr instanceof APIError) throw parseErr;
      }
      throw new APIError(detail, response.status, "PHASE8_FEATURES_ERROR");
    }

    return (await response.json()) as Phase8FeaturesResponse;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new APIError("Phase 8 features timed out (8s)", 408, "PHASE8_FEATURES_TIMEOUT");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Sprint 4 Slice A: Off-season status endpoint
// ---------------------------------------------------------------------------

export interface OffseasonDataAvailability {
  historical_data: boolean;
  live_odds: boolean;
  live_standings: boolean;
  live_form: boolean;
  pi_ratings: boolean;
  berrar_ratings: boolean;
  market_drift: boolean;
  match_context: boolean;
}

export interface OffseasonStatusResponse {
  league: string;
  league_slug: string;
  season_status: "IN_SEASON" | "OFF_SEASON" | "UNKNOWN";
  current_season_label: string;
  current_season_end: string;
  next_season_start: string;
  days_until_next_season: number | null;
  data_availability: OffseasonDataAvailability;
  prediction_advisory: string;
  queried_at: string;
}

/**
 * Fetch off-season status for a league.
 * Proxied via Next.js API at: /api/offseason/{league}
 * Cached 1 hour at edge (s-maxage=3600).
 */
export async function getOffseasonStatus(
  league: string,
): Promise<OffseasonStatusResponse> {
  const url = `/api/offseason/${encodeURIComponent(league)}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5_000);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate: 3600 },
      signal: controller.signal,
    } as RequestInit);

    if (!response.ok) {
      // Graceful degradation: return UNKNOWN status rather than throwing
      return {
        league,
        league_slug: league.toLowerCase(),
        season_status: "UNKNOWN",
        current_season_label: "",
        current_season_end: "",
        next_season_start: "",
        days_until_next_season: null,
        data_availability: {
          historical_data: false,
          live_odds: false,
          live_standings: false,
          live_form: false,
          pi_ratings: false,
          berrar_ratings: false,
          market_drift: false,
          match_context: false,
        },
        prediction_advisory: "Season status unavailable.",
        queried_at: new Date().toISOString(),
      };
    }

    return (await response.json()) as OffseasonStatusResponse;
  } catch {
    // Network error — degrade gracefully, don't block fixture rendering
    return {
      league,
      league_slug: league.toLowerCase(),
      season_status: "UNKNOWN",
      current_season_label: "",
      current_season_end: "",
      next_season_start: "",
      days_until_next_season: null,
      data_availability: {
        historical_data: false,
        live_odds: false,
        live_standings: false,
        live_form: false,
        pi_ratings: false,
        berrar_ratings: false,
        market_drift: false,
        match_context: false,
      },
      prediction_advisory: "Season status unavailable.",
      queried_at: new Date().toISOString(),
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Sprint 4: Upcoming matches with edge_quality_score and offseason contract
// ---------------------------------------------------------------------------

export interface UpcomingMatchPrediction {
  home_win: number;
  draw: number;
  away_win: number;
  confidence: number;
  model_version: string;
}

export interface UpcomingMatchValueBet {
  outcome: string;
  edge_pct: number;
  kelly_stake_pct: number;
  clv_cents: number;
  recommended_stake_ngn: number;
  confidence: number;
}

export interface UpcomingMatch {
  match_id: string;
  home_team: string;
  away_team: string;
  league: string;
  match_date: string;
  venue: string | null;
  status: string;
  predictions: UpcomingMatchPrediction | null;
  value_bets: UpcomingMatchValueBet[];
  has_value: boolean;
  best_value_bet: UpcomingMatchValueBet | null;
  data_gaps: string[];
  staleness_seconds: number;
  source: string;
  /** Composite 0–1 edge quality: 0.40×confidence + 0.30×market_edge + 0.20×freshness + 0.10×completeness. */
  edge_quality_score: number | null;
  /** Closing-line value %. Always null pre-kick-off. */
  clv_pct: number | null;
  /** Feature completeness provenance — present when the projector ran. */
  data_quality?: {
    historical_data_ratio: number;
    defaults_used_count: number;
    is_synthetic: boolean;
  } | null;
  /** UCL knockout/group stage slug: "group" | "r16" | "qf" | "sf" | "final". Null for domestic leagues. */
  competition_stage?: string | null;
  /** Advisory portfolio-exposure annotation (ADR-0005). Null on non-value fixtures. */
  portfolio?: {
    raw_kelly_stake_pct: number;
    correlation_group_size: number;
    correlation_haircut_multiplier: number;
    adjusted_kelly_stake_pct: number;
    exceeds_aggregate_cap: boolean;
  } | null;
}

export interface UpcomingMatchesResponse {
  upcoming_matches: UpcomingMatch[];
  total: number;
  matches_with_value: number;
  avg_edge_pct: number;
  cache_hit: boolean;
  ttl_seconds: number;
  source: string;
  /** True when the fixture list is genuinely empty and the league is in an inter-season break. */
  offseason: boolean;
  /** ISO 8601 date of the next season kick-off. Null when not offseason. */
  next_season_start: string | null;
  data_gap: boolean;
  unavailable_reasons: string[];
  generated_at: string;
  /** Batch-level advisory exposure summary (ADR-0005). Null when predictions weren't requested. */
  portfolio_exposure?: {
    aggregate_recommended_pct: number;
    aggregate_cap_pct: number;
    exceeds_aggregate_cap: boolean;
    drawdown: { status: string; realized_drawdown_pct: number | null; paused: boolean };
  } | null;
}

/** Fetch the synchronized fixture-discovery list without bulk model/provider work. */
export async function getUpcomingMatches(
  params: { league?: string; days_ahead?: number; limit?: number } = {},
): Promise<UpcomingMatchesResponse> {
  const qs = new URLSearchParams();
  if (params.league) qs.set("league", params.league);
  if (params.days_ahead !== undefined) qs.set("days_ahead", String(params.days_ahead));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  qs.set("include_predictions", "false");
  qs.set("include_value_bets", "false");
  const url = `/api/upcoming${qs.size ? `?${qs}` : ""}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail || err.error || detail;
      } catch { /* ignore */ }
      throw new APIError(detail, response.status, "UPCOMING_MATCHES_ERROR");
    }

    return (await response.json()) as UpcomingMatchesResponse;
  } catch (err) {
    if (err instanceof Error && ["AbortError", "TimeoutError"].includes(err.name)) {
      throw new APIError("Upcoming matches request timed out (8s)", 408, "UPCOMING_MATCHES_TIMEOUT");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

// ---------------------------------------------------------------------------
// Sprint 4: Team intelligence endpoint
// ---------------------------------------------------------------------------

export type TeamFormVerdict = "IMPROVING" | "STABLE" | "DECLINING" | "VOLATILE";

export interface TeamFormResult {
  match_date: string;
  opponent: string;
  home_or_away: "home" | "away";
  goals_for: number | null;
  goals_against: number | null;
  result: "W" | "D" | "L";
  points: number;
}

export interface TeamH2HEntry {
  opponent: string;
  played: number;
  wins: number;
  draws: number;
  losses: number;
  goals_for: number;
  goals_against: number;
}

export interface TeamUpcomingFixture {
  match_id: string;
  home_team: string;
  away_team: string;
  match_date: string;
  league: string;
  edge_quality_score: number | null;
  has_prediction: boolean;
}

export interface TeamIntelligenceResponse {
  team_slug: string;
  team_name: string;
  league: string | null;
  form_verdict: TeamFormVerdict;
  ppg_last5: number | null;
  ppg_last10: number | null;
  recent_form: TeamFormResult[];
  h2h_summary: TeamH2HEntry[];
  upcoming_fixtures: TeamUpcomingFixture[];
  queried_at: string;
}

/** Fetch rolling form, H2H, and upcoming fixtures for a team by slug. */
export async function getTeamIntelligence(
  slug: string,
  options: { history_matches?: number; upcoming_days?: number } = {},
): Promise<TeamIntelligenceResponse> {
  const qs = new URLSearchParams();
  if (options.history_matches !== undefined) qs.set("history_matches", String(options.history_matches));
  if (options.upcoming_days !== undefined) qs.set("upcoming_days", String(options.upcoming_days));
  const url = `/api/teams/${encodeURIComponent(slug)}/intelligence${qs.size ? `?${qs}` : ""}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8_000);

  try {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate: 300 },
      signal: controller.signal,
    } as RequestInit);

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const err = await response.json();
        detail = err.detail || err.error || detail;
      } catch { /* ignore */ }
      throw new APIError(detail, response.status, "TEAM_INTELLIGENCE_ERROR");
    }

    return (await response.json()) as TeamIntelligenceResponse;
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") {
      throw new APIError("Team intelligence request timed out (8s)", 408, "TEAM_INTELLIGENCE_TIMEOUT");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
}

export function parseApiError(error: unknown): { message: string; code?: string } {
  if (error instanceof APIError) {
    return { message: error.message, code: error.code };
  }

  if (error instanceof Error) {
    return { message: error.message };
  }

  return { message: "An unexpected error occurred" };
}

export { APIError };
