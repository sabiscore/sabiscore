// SabiScore Strict Betting Intelligence API Types
// Contract version: 1.2.0
// Updated: 2026-07-04

import { z } from "zod";

// --- Enums -------------------------------------------------------------------

export type Verdict =
  | "HIGH_CONVICTION"
  | "ACTIONABLE"
  | "SPECULATIVE"
  | "HOLD"
  | "PARTIAL"
  | "NO_BET";  // NEW: valid data, no positive value

export type Competition =
  | "EPL"
  | "LA_LIGA"
  | "SERIE_A"
  | "BUNDESLIGA"
  | "LIGUE_1"
  | "EREDIVISIE"
  | "UCL";

export type BestMarket = "HOME_ML" | "DRAW_ML" | "AWAY_ML";

export type ConfidenceLabel = "HIGH" | "MEDIUM" | "LOW";

export type EvidenceTier = "OK" | "LOW_EVIDENCE";

export type SourceStatus = "VERIFIED" | "STALE" | "CONFLICTING" | "DATA_GAP";

export type FreshnessStatus = "FRESH" | "RECENT" | "STALE" | "DATA_GAP" | "CONFLICTING" | "UNKNOWN";

export type LineupStatus = "CONFIRMED" | "PROVISIONAL" | "UNKNOWN";

export type SharpSignal = "CONFIRMING" | "NEUTRAL" | "CONFLICTING" | "UNKNOWN";

// --- Strict Engine Input Types ------------------------------------------------

export interface ModelInput {
  home_probability: number;
  draw_probability: number;
  away_probability: number;
  model_version: string;
  calibration_method: string;
  calibration_validated: boolean;
  epistemic_uncertainty: number;
  aleatoric_uncertainty: number;
  confidence_tier: EvidenceTier;
}

export interface MarketInput {
  bookmaker: string;
  market_type: string;
  home_odds: number;
  draw_odds: number;
  away_odds: number;
  opening_home_odds?: number | null;
  opening_draw_odds?: number | null;
  opening_away_odds?: number | null;
  captured_at: string; // ISO-8601 UTC
}

export interface SignalsInput {
  xg_differential?: number | null;
  xga_differential?: number | null;
  opponent_adjusted_form?: number | null;
  club_elo_difference?: number | null;
  schedule_congestion?: number | null;
  travel_load?: number | null;
  confirmed_absences?: string[];
  lineup_status?: LineupStatus;
  sharp_market_signal?: SharpSignal;
}

export interface FreshnessInput {
  model_features_seconds?: number | null;
  market_seconds?: number | null;
  injury_news_seconds?: number | null;
  lineup_seconds?: number | null;
}

export interface SourceStatusInput {
  model?: SourceStatus;
  market?: SourceStatus;
  team_metrics?: SourceStatus;
  availability?: SourceStatus;
}

export interface MatchAnalysisRequest {
  match_id: string;
  home_team: string;
  away_team: string;
  competition: Competition;
  kickoff_utc: string;
  model?: ModelInput | null;
  market?: MarketInput | null;
  signals?: SignalsInput;
  freshness?: FreshnessInput;
  source_status?: SourceStatusInput;
  data_gaps?: string[];
  known_risks?: string[];
}

export interface BatchAnalysisRequest {
  matches: MatchAnalysisRequest[];
  engine_version?: string;
}

// --- Strict Engine Output Types -----------------------------------------------

export interface ProbabilitySet {
  home: number | null;
  draw: number | null;
  away: number | null;
}

export interface DataFreshness {
  status: FreshnessStatus;
  market_captured_at?: string | null;
  oldest_critical_input_seconds?: number | null;
  lineup_status?: LineupStatus;
}

export interface CalculationAudit {
  bookmaker?: string | null;
  market_overround?: number | null;
  raw_implied_home?: number | null;
  raw_implied_draw?: number | null;
  raw_implied_away?: number | null;
  fair_market_home?: number | null;
  fair_market_draw?: number | null;
  fair_market_away?: number | null;
  calibration_method?: string | null;
  model_version?: string | null;
  kelly_fraction: number;
  kelly_cap: number;
  breakeven_odds?: number | null;
  minimum_odds_for_target_ev?: number | null;
  edge_preserving_minimum_odds?: number | null;
}

export interface MarketEvaluation {
  outcome: "home" | "draw" | "away";
  market_label: BestMarket;
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

export interface MatchAnalysisResult {
  contract_version?: string;
  policy_version?: string;
  decision_id?: string | null;
  evaluation_at?: string | null;
  analysis_mode?: "VALUE_ANALYSIS" | "FORECAST_ONLY";
  execution_eligible?: boolean;
  watchlist?: boolean;
  source_summary?: Record<string, unknown>;
  input_hash?: string | null;
  policy_hash?: string | null;
  minimum_acceptable_odds_method?: string | null;
  target_expected_value?: number;
  match_identifier: string;
  match_id: string;
  competition: string;
  kickoff_utc?: string | null;
  verdict: Verdict;
  probabilities?: ProbabilitySet | null;
  best_market?: BestMarket | null;
  market_odds?: number | null;
  raw_market_implied_probability?: number | null;
  fair_market_probability?: number | null;
  edge?: number | null;
  edge_percentage_points?: number | null;
  expected_value?: number | null;
  confidence?: ConfidenceLabel | null;
  confidence_adjusted_value?: number | null;
  stake: string; // "pass" or "{fraction}u"
  stake_fraction: number;
  minimum_acceptable_odds?: number | null;
  drivers: string[];
  risks: string[];
  invalidation_conditions: string[];
  all_market_evaluations?: MarketEvaluation[] | null;
  data_freshness?: DataFreshness | null;
  data_gaps: string[];
  critical_gaps?: string[];
  advisory_gaps?: string[];
  conflicts?: string[];
  calculation_audit?: CalculationAudit | null;
  explanation: string;
}

export interface BatchAnalysisResponse {
  contract_version?: string;
  policy_version?: string;
  engine_version: string;
  generated_at: string;
  top_opportunities: string[];
  batch_watchlist?: string[];
  matches: MatchAnalysisResult[];
}

// --- Engine Policy ------------------------------------------------------------

export interface EnginePolicy {
  contract_version?: string;
  engine_version: string;
  policy_version?: string;
  generated_at: string;
  policy: {
    min_actionable_edge_pp: number;
    high_conviction_edge_pp: number;
    kelly_fraction: number;
    max_kelly_cap: number;
    speculative_stake_cap: number;
    minimum_acceptable_odds_method?: string;
    target_expected_value?: number;
    verdict_precedence: Verdict[];
    ucl_coverage: string;
    market_freshness_thresholds: {
      fresh_seconds: number;
      recent_seconds: number;
      stale_above_seconds: number;
    };
    model_features_fresh_seconds?: number;
    null_rules: {
      missing_quantitative_data: string;
      stake_under_partial_hold_no_bet: string;
      probabilities_under_partial: string;
    };
  };
}

export interface FixtureSummary {
  fixture_id: string;
  competition: string;
  home_team: string;
  away_team: string;
  kickoff_utc: string;
  status: string;
  venue?: string | null;
  evidence_status: string;
  odds_status: string;
}

export interface UpcomingFixturesResponse {
  fixtures: FixtureSummary[];
  total: number;
  source: string;
}

export interface FixtureEvidenceResponse {
  fixture: FixtureSummary;
  model?: Record<string, unknown> | null;
  market?: Record<string, unknown> | null;
  freshness: Record<string, unknown>;
  source_status: Record<string, string>;
  data_gaps: string[];
  retrieval_timeline: Array<Record<string, unknown>>;
  readiness: Array<Record<string, unknown>>;
  source_comparison: Array<Record<string, unknown>>;
}

export interface ManualOddsSnapshotRequest {
  bookmaker: string;
  home_odds: number;
  draw_odds: number;
  away_odds: number;
  observed_at: string;
  opening_home_odds?: number | null;
  opening_draw_odds?: number | null;
  opening_away_odds?: number | null;
  source_label?: string | null;
  source_url?: string | null;
  user_confirmed: boolean;
}

export interface ManualOddsSnapshotResponse {
  fixture_id: string;
  bookmaker: string;
  home_odds: number;
  draw_odds: number;
  away_odds: number;
  observed_at: string;
  received_at: string;
  executable: boolean;
  provenance: Record<string, unknown>;
}

export interface ProviderOddsCandidate {
  bookmaker: string;
  home_odds: number;
  draw_odds: number;
  away_odds: number;
  captured_at: string;
  provider: string;
  executable: boolean;
}

export interface ProviderOddsCandidatesResponse {
  fixture_id: string;
  candidates: ProviderOddsCandidate[];
  warnings: string[];
}

export interface RefreshEvidenceResponse {
  fixture_id: string;
  profile: string;
  provider_results: Array<Record<string, unknown>>;
  refreshed_at: string;
}

export type { FullMatchAnalysisResponse } from "./full-analysis-contract";

// --- API Client Functions -----------------------------------------------------

const SAME_ORIGIN_API = "/api/betting-intelligence";

const verdictSchema = z.enum([
  "HIGH_CONVICTION",
  "ACTIONABLE",
  "SPECULATIVE",
  "HOLD",
  "PARTIAL",
  "NO_BET",
]);

const marketEvaluationSchema = z.object({
  outcome: z.enum(["home", "draw", "away"]),
  market_label: z.enum(["HOME_ML", "DRAW_ML", "AWAY_ML"]),
  model_probability: z.number(),
  market_odds: z.number(),
  raw_implied_probability: z.number(),
  fair_market_probability: z.number(),
  edge: z.number(),
  edge_pct: z.number(),
  expected_value: z.number(),
  stake_fraction: z.number(),
  confidence_adjusted_value: z.number(),
});

const matchAnalysisResultSchema: z.ZodType<MatchAnalysisResult> = z.object({
  match_identifier: z.string(),
  match_id: z.string(),
  competition: z.string(),
  verdict: verdictSchema,
  stake: z.string(),
  stake_fraction: z.number(),
  drivers: z.array(z.string()),
  risks: z.array(z.string()),
  invalidation_conditions: z.array(z.string()),
  data_gaps: z.array(z.string()),
  explanation: z.string(),
  probabilities: z.object({
    home: z.number().nullable(),
    draw: z.number().nullable(),
    away: z.number().nullable(),
  }).nullable().optional(),
  best_market: z.enum(["HOME_ML", "DRAW_ML", "AWAY_ML"]).nullable().optional(),
  market_odds: z.number().nullable().optional(),
  raw_market_implied_probability: z.number().nullable().optional(),
  fair_market_probability: z.number().nullable().optional(),
  edge: z.number().nullable().optional(),
  edge_percentage_points: z.number().nullable().optional(),
  expected_value: z.number().nullable().optional(),
  confidence: z.enum(["HIGH", "MEDIUM", "LOW"]).nullable().optional(),
  confidence_adjusted_value: z.number().nullable().optional(),
  minimum_acceptable_odds: z.number().nullable().optional(),
  all_market_evaluations: z.array(marketEvaluationSchema).nullable().optional(),
  critical_gaps: z.array(z.string()).optional(),
  advisory_gaps: z.array(z.string()).optional(),
  conflicts: z.array(z.string()).optional(),
}).passthrough();

const batchAnalysisResponseSchema: z.ZodType<BatchAnalysisResponse> = z.object({
  engine_version: z.string(),
  generated_at: z.string(),
  top_opportunities: z.array(z.string()),
  matches: z.array(matchAnalysisResultSchema),
  contract_version: z.string().optional(),
  policy_version: z.string().optional(),
  batch_watchlist: z.array(z.string()).optional(),
}).passthrough();

const enginePolicySchema: z.ZodType<EnginePolicy> = z.object({
  engine_version: z.string(),
  generated_at: z.string(),
  policy: z.object({
    min_actionable_edge_pp: z.number(),
    high_conviction_edge_pp: z.number(),
    kelly_fraction: z.number(),
    max_kelly_cap: z.number(),
    speculative_stake_cap: z.number(),
    minimum_acceptable_odds_method: z.string().optional(),
    target_expected_value: z.number().optional(),
    verdict_precedence: z.array(verdictSchema),
    ucl_coverage: z.string(),
    market_freshness_thresholds: z.object({
      fresh_seconds: z.number(),
      recent_seconds: z.number(),
      stale_above_seconds: z.number(),
    }),
    model_features_fresh_seconds: z.number().optional(),
    null_rules: z.object({
      missing_quantitative_data: z.string(),
      stake_under_partial_hold_no_bet: z.string(),
      probabilities_under_partial: z.string(),
    }),
  }).passthrough(),
  contract_version: z.string().optional(),
  policy_version: z.string().optional(),
}).passthrough();

const fixtureSummarySchema: z.ZodType<FixtureSummary> = z.object({
  fixture_id: z.string(),
  competition: z.string(),
  home_team: z.string(),
  away_team: z.string(),
  kickoff_utc: z.string(),
  status: z.string(),
  evidence_status: z.string(),
  odds_status: z.string(),
  venue: z.string().nullable().optional(),
});

const upcomingFixturesResponseSchema: z.ZodType<UpcomingFixturesResponse> = z.object({
  fixtures: z.array(fixtureSummarySchema),
  total: z.number(),
  source: z.string(),
});

const fixtureEvidenceResponseSchema: z.ZodType<FixtureEvidenceResponse> = z.object({
  fixture: fixtureSummarySchema,
  freshness: z.record(z.unknown()),
  source_status: z.record(z.string()),
  data_gaps: z.array(z.string()),
  retrieval_timeline: z.array(z.record(z.unknown())),
  readiness: z.array(z.record(z.unknown())),
  source_comparison: z.array(z.record(z.unknown())),
  model: z.record(z.unknown()).nullable().optional(),
  market: z.record(z.unknown()).nullable().optional(),
});

const manualOddsSnapshotResponseSchema: z.ZodType<ManualOddsSnapshotResponse> = z.object({
  fixture_id: z.string(),
  bookmaker: z.string(),
  home_odds: z.number(),
  draw_odds: z.number(),
  away_odds: z.number(),
  observed_at: z.string(),
  received_at: z.string(),
  executable: z.boolean(),
  provenance: z.record(z.unknown()),
});

const providerOddsCandidateSchema: z.ZodType<ProviderOddsCandidate> = z.object({
  bookmaker: z.string(),
  home_odds: z.number(),
  draw_odds: z.number(),
  away_odds: z.number(),
  captured_at: z.string(),
  provider: z.string(),
  executable: z.boolean(),
});

const providerOddsCandidatesResponseSchema: z.ZodType<ProviderOddsCandidatesResponse> = z.object({
  fixture_id: z.string(),
  candidates: z.array(providerOddsCandidateSchema),
  warnings: z.array(z.string()),
});

const refreshEvidenceResponseSchema: z.ZodType<RefreshEvidenceResponse> = z.object({
  fixture_id: z.string(),
  profile: z.string(),
  provider_results: z.array(z.record(z.unknown())),
  refreshed_at: z.string(),
});

export class APIError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `API error ${status}`);
  }
}

function validateApiResponse<T>(
  schema: z.ZodType<T>,
  payload: unknown,
  path: string,
): T {
  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new APIError(
      502,
      {
        error: "invalid_response",
        path,
        issues: parsed.error.issues.slice(0, 5).map((issue) => ({
          path: issue.path.join("."),
          message: issue.message,
        })),
      },
      `Backend contract error at ${path}`,
    );
  }
  return parsed.data;
}

function messageFromErrorBody(body: unknown): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  const candidate = body as { message?: unknown; detail?: unknown; error?: unknown };
  for (const value of [candidate.message, candidate.detail, candidate.error]) {
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  return undefined;
}

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
  timeoutMs = 10_000,
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
    if (!res.ok) {
      const body = await res.json().catch(() => null);
      throw new APIError(
        res.status,
        body,
        messageFromErrorBody(body) ?? `API error ${res.status}`,
      );
    }
    return (await res.json()) as T;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new APIError(408, null, "Request timed out while waiting for the backend.");
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}

async function apiFetchValidated<T>(
  path: string,
  schema: z.ZodType<T>,
  options?: RequestInit,
  timeoutMs = 10_000,
): Promise<T> {
  const payload = await apiFetch<unknown>(path, options, timeoutMs);
  return validateApiResponse(schema, payload, path);
}

/** Call the strict betting intelligence batch endpoint. */
export async function analyzeBatch(
  request: BatchAnalysisRequest,
): Promise<BatchAnalysisResponse> {
  return apiFetchValidated<BatchAnalysisResponse>(
    `${SAME_ORIGIN_API}/analyze`,
    batchAnalysisResponseSchema,
    { method: "POST", body: JSON.stringify(request) },
  );
}

/** Call the strict betting intelligence single-match endpoint. */
export async function analyzeSingle(
  request: MatchAnalysisRequest,
): Promise<MatchAnalysisResult> {
  return apiFetchValidated<MatchAnalysisResult>(
    `${SAME_ORIGIN_API}/analyze`,
    matchAnalysisResultSchema,
    { method: "POST", body: JSON.stringify(request) },
  );
}

/** Get current engine policy parameters. */
export async function getEnginePolicy(): Promise<EnginePolicy> {
  return apiFetchValidated<EnginePolicy>(
    `${SAME_ORIGIN_API}/policy`,
    enginePolicySchema,
  );
}

export async function getUpcomingFixtures(competition?: string): Promise<UpcomingFixturesResponse> {
  const params = competition ? `?competition=${encodeURIComponent(competition)}` : "";
  return apiFetchValidated<UpcomingFixturesResponse>(
    `/api/fixtures/upcoming${params}`,
    upcomingFixturesResponseSchema,
  );
}

export async function getFixtureEvidence(fixtureId: string): Promise<FixtureEvidenceResponse> {
  return apiFetchValidated<FixtureEvidenceResponse>(
    `/api/fixtures/${encodeURIComponent(fixtureId)}/evidence`,
    fixtureEvidenceResponseSchema,
  );
}

export async function refreshFixtureEvidence(
  fixtureId: string,
  profile = "PREMATCH_STANDARD",
): Promise<RefreshEvidenceResponse> {
  return apiFetchValidated<RefreshEvidenceResponse>(
    `/api/fixtures/${encodeURIComponent(fixtureId)}/refresh`,
    refreshEvidenceResponseSchema,
    { method: "POST", body: JSON.stringify({ profile }) },
  );
}

export async function getProviderOddsCandidates(
  fixtureId: string,
): Promise<ProviderOddsCandidatesResponse> {
  return apiFetchValidated<ProviderOddsCandidatesResponse>(
    `/api/fixtures/${encodeURIComponent(fixtureId)}/odds-snapshots`,
    providerOddsCandidatesResponseSchema,
  );
}

export async function submitManualOddsSnapshot(
  fixtureId: string,
  request: ManualOddsSnapshotRequest,
): Promise<ManualOddsSnapshotResponse> {
  return apiFetchValidated<ManualOddsSnapshotResponse>(
    `/api/fixtures/${encodeURIComponent(fixtureId)}/odds-snapshot`,
    manualOddsSnapshotResponseSchema,
    { method: "POST", body: JSON.stringify(request) },
  );
}

export async function analyzeFixture(fixtureId: string): Promise<MatchAnalysisResult> {
  return apiFetchValidated<MatchAnalysisResult>(
    `/api/fixtures/${encodeURIComponent(fixtureId)}/analyze`,
    matchAnalysisResultSchema,
    { method: "POST" },
  );
}

/** Backward-compatible re-export of the single validated full-analysis client. */
export { getFullAnalysis } from "./api";
