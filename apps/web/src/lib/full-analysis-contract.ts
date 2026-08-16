import { z } from "zod";

const verdictSchema = z.enum([
  "HIGH_CONVICTION",
  "ACTIONABLE",
  "SPECULATIVE",
  "HOLD",
  "NO_BET",
  "PARTIAL",
]);

const predictionStatusSchema = z.enum([
  "AVAILABLE",
  "REDUCED_EVIDENCE_BASELINE",
  "UNAVAILABLE",
]);

const predictionSourceSchema = z.enum([
  "CERTIFIED_MODEL",
  "UNCERTIFIED_MODEL",
  "DIAGNOSTIC_BASELINE",
  "NONE",
]);

const ensembleSchema = z
  .object({
    home_win_prob: z.number().min(0).max(1),
    draw_prob: z.number().min(0).max(1),
    away_win_prob: z.number().min(0).max(1),
    prediction: z.string(),
    confidence: z.number().min(0).max(1),
    top_outcome_probability: z.number().min(0).max(1),
    probabilities_available: z.boolean(),
    league: z.string(),
    model_version: z.string(),
    generation: z.string().nullable().optional(),
    feature_schema_version: z.string().nullable().optional(),
    manifest_sha256: z.string().nullable().optional(),
    certification_state: z.string().default("UNVERIFIED"),
    artifact_sha256: z.string().nullable().optional(),
    coverage: z.string().default("dedicated"),
    calibration_method: z.string(),
    calibration_applied: z.boolean(),
    overlay_applied: z.boolean(),
  })
  .superRefine((value, ctx) => {
    const top = Math.max(value.home_win_prob, value.draw_prob, value.away_win_prob);
    if (Math.abs(top - value.top_outcome_probability) > 0.0001) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["top_outcome_probability"],
        message: "must equal the largest outcome probability",
      });
    }
    if (Math.abs(value.confidence - value.top_outcome_probability) > 0.0001) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["confidence"],
        message: "deprecated confidence alias must equal top_outcome_probability",
      });
    }
    const total = value.home_win_prob + value.draw_prob + value.away_win_prob;
    if (value.probabilities_available && Math.abs(total - 1) > 0.0001) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["home_win_prob"],
        message: "available probabilities must sum to one",
      });
    }
  });

const actionabilitySchema = z.object({
  edge_quality_score: z.number().min(0).max(1),
  clv_pct: z.number().nullable(),
  closing_line_convergence_delta: z.number().nullable(),
  suggested_stake_pct: z.number().min(0),
  abstain: z.boolean(),
  abstain_reason: z.string().nullable(),
  top_evidence: z.array(z.string()),
  caveats: z.array(z.string()),
});

const evidenceQualitySchema = z.object({
  critical_gaps: z.array(z.string()),
  advisory_gaps: z.array(z.string()),
  conflicts: z.array(z.string()),
  all_gaps: z.array(z.string()),
  critical_gap_count: z.number().int().min(0),
  advisory_gap_count: z.number().int().min(0),
  conflict_count: z.number().int().min(0),
  total_gap_count: z.number().int().min(0),
});

const phase9CandidateSchema = z.object({
  hybrid_xg: z.record(z.number()).optional(),
  market_efficiency: z.object({
    bookmaker_margin: z.number().optional(),
    market_complete: z.boolean().optional(),
    market_sharpness: z.enum(["sharp", "standard", "unknown"]).optional(),
    has_value: z.boolean().optional(),
    value_bets: z.array(z.object({
      outcome: z.string(),
      ev: z.number(),
      edge: z.number(),
      kelly_fraction: z.number().optional(),
    })).optional(),
    recommended_kelly_fraction: z.number().optional(),
    clv_available: z.boolean().optional(),
  }).passthrough().optional(),
}).passthrough();

export const fullMatchAnalysisSchema = z
  .object({
    match_id: z.string(),
    verdict: verdictSchema,
    prediction_status: predictionStatusSchema,
    prediction_source: predictionSourceSchema,
    probabilities_available: z.boolean(),
    is_reduced_evidence_baseline: z.boolean(),
    top_outcome_probability: z.number().min(0).max(1),
    effective_kelly_cap: z.number().min(0).max(0.05),
    stake_permitted: z.boolean(),
    evidence_quality: evidenceQualitySchema,
    ensemble: ensembleSchema,
    uncertainty: z.object({
      epistemic_unc: z.number(),
      aleatoric_unc: z.number(),
      concentration: z.number(),
      credible_interval: z.tuple([z.number(), z.number()]),
      confidence_tier: z.string(),
    }).nullable(),
    model_drivers: z.array(z.string()),
    causal_drivers: z.array(z.string()),
    rl_recommendation: z.object({
      stake_fraction: z.number().min(0),
      abstain: z.boolean(),
      reason: z.string().nullable(),
      reward_components: z.record(z.number()),
    }),
    elo_context: z.object({
      home_elo: z.number(),
      away_elo: z.number(),
      elo_difference: z.number(),
      home_elo_trend_5: z.number(),
      away_elo_trend_5: z.number(),
      elo_momentum_cross: z.number(),
    }).nullable(),
    odds_edge: z
      .object({
        market: z.string(),
        market_odds: z.number(),
        model_prob: z.number(),
        edge: z.number(),
        kelly_stake: z.number().min(0),
      })
      .nullable(),
    narrative: z.string().max(280),
    partial_intelligence: z.boolean(),
    data_gaps: z.array(z.string()),
    staleness_seconds: z.number().int().min(0),
    staleness_available: z.boolean(),
    freshness_tag: z.enum(["LIVE", "RECENT", "STALE", "UNKNOWN"]),
    feature_freshness_seconds: z.record(z.number().int().min(0).nullable()),
    feature_source: z.record(z.string()),
    actionability: actionabilitySchema.nullable(),
    match_importance_score: z.number().nullable().optional(),
    competition_stage: z.string().nullable().optional(),
    home_team: z.string().nullable().optional(),
    away_team: z.string().nullable().optional(),
    league: z.string().nullable().optional(),
    kickoff_utc: z.string().datetime({ offset: true }).nullable().optional(),
    fixture_verified: z.boolean().nullable().optional(),
    field_availability: z.record(z.boolean()).default({}),
    unavailable_reasons: z.record(z.string()).default({}),
    generated_at: z.string().datetime({ offset: true }),
    phase9_candidate_features: phase9CandidateSchema.nullable().optional(),
    // Backend declares Optional[bool] = None (schemas/full_analysis.py): null when
    // phase9 is inactive, which is the production default. Must mirror the sibling
    // phase9_candidate_features nullability — .optional() alone rejects null and
    // fails the whole parse ("invalid full-analysis contract" on every baseline).
    phase9_shadow_only: z.boolean().nullable().optional(),
  })
  .superRefine((value, ctx) => {
    if (JSON.stringify(value.data_gaps) !== JSON.stringify(value.evidence_quality.all_gaps)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["data_gaps"],
        message: "must remain an alias of evidence_quality.all_gaps",
      });
    }
    const available = value.prediction_status === "AVAILABLE";
    if (
      value.probabilities_available !== available ||
      value.ensemble.probabilities_available !== available
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["probabilities_available"],
        message: "must agree with prediction_status",
      });
    }
    const expectedSource = {
      AVAILABLE: value.ensemble.certification_state === "CERTIFIED"
        ? "CERTIFIED_MODEL"
        : "UNCERTIFIED_MODEL",
      REDUCED_EVIDENCE_BASELINE: "DIAGNOSTIC_BASELINE",
      UNAVAILABLE: "NONE",
    }[value.prediction_status];
    if (value.prediction_source !== expectedSource) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["prediction_source"],
        message: "must agree with prediction_status",
      });
    }
    if (
      value.is_reduced_evidence_baseline !==
      (value.prediction_status === "REDUCED_EVIDENCE_BASELINE")
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["is_reduced_evidence_baseline"],
        message: "must agree with prediction_status",
      });
    }
    const normalizedGaps = [
      ...new Set([
        ...value.evidence_quality.critical_gaps,
        ...value.evidence_quality.advisory_gaps,
        ...value.evidence_quality.conflicts,
      ]),
    ];
    const evidenceCountsMatch =
      value.evidence_quality.critical_gap_count === value.evidence_quality.critical_gaps.length &&
      value.evidence_quality.advisory_gap_count === value.evidence_quality.advisory_gaps.length &&
      value.evidence_quality.conflict_count === value.evidence_quality.conflicts.length &&
      value.evidence_quality.total_gap_count === value.evidence_quality.all_gaps.length;
    if (
      JSON.stringify(normalizedGaps) !== JSON.stringify(value.evidence_quality.all_gaps) ||
      !evidenceCountsMatch
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["evidence_quality"],
        message: "must contain deduplicated category lists, their normalized union, and exact counts",
      });
    }
    if (Math.abs(value.top_outcome_probability - value.ensemble.top_outcome_probability) > 0.0001) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["top_outcome_probability"],
        message: "must agree with the ensemble top outcome probability",
      });
    }
    const expectedPartial =
      value.evidence_quality.critical_gap_count > 0 ||
      value.evidence_quality.conflict_count > 0;
    if (value.partial_intelligence !== expectedPartial) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["partial_intelligence"],
        message: "must derive only from critical gaps or conflicts",
      });
    }
    const blocked =
      value.partial_intelligence ||
      value.evidence_quality.critical_gap_count > 0 ||
      value.evidence_quality.conflict_count > 0 ||
      !available;
    if (
      value.stake_permitted &&
      (blocked ||
        !["ACTIONABLE", "HIGH_CONVICTION"].includes(value.verdict) ||
        value.rl_recommendation.abstain ||
        value.rl_recommendation.stake_fraction <= 0 ||
        value.uncertainty === null ||
        value.fixture_verified !== true)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["stake_permitted"],
        message: "is inconsistent with the evidence and verdict gates",
      });
    }
    if (!value.stake_permitted) {
      if (value.rl_recommendation.stake_fraction > 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["rl_recommendation", "stake_fraction"],
          message: "must be zero when public staking is not permitted",
        });
      }
      if (value.odds_edge && value.odds_edge.kelly_stake > 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["odds_edge", "kelly_stake"],
          message: "must be zero when public staking is not permitted",
        });
      }
      if (value.actionability && value.actionability.suggested_stake_pct > 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["actionability", "suggested_stake_pct"],
          message: "must be zero when public staking is not permitted",
        });
      }
    }
  });

export type FullMatchAnalysisResponse = z.infer<typeof fullMatchAnalysisSchema>;
export type FullMatchEnsemble = FullMatchAnalysisResponse["ensemble"];
export type FullMatchUncertainty = FullMatchAnalysisResponse["uncertainty"];
export type FullMatchRLRecommendation = FullMatchAnalysisResponse["rl_recommendation"];
export type FullMatchEloContext = FullMatchAnalysisResponse["elo_context"];
export type FullMatchOddsEdge = NonNullable<FullMatchAnalysisResponse["odds_edge"]>;
export type MatchActionability = NonNullable<FullMatchAnalysisResponse["actionability"]>;

export type AnalysisErrorCategory =
  | "cold_start"
  | "upstream_timeout"
  | "upstream_unavailable"
  | "backend_internal_error"
  | "invalid_response"
  | "insufficient_evidence"
  | "network_error"
  | "unknown";

export function classifyAnalysisError(input: {
  status?: number;
  code?: string;
  body?: unknown;
  networkError?: boolean;
}): AnalysisErrorCategory {
  const code = input.code?.toLowerCase();
  const body = input.body && typeof input.body === "object"
    ? (input.body as { error?: unknown; code?: unknown })
    : undefined;
  const marker = `${String(body?.error ?? "")} ${String(body?.code ?? "")} ${code ?? ""}`.toLowerCase();
  if (input.status === 500) return "backend_internal_error";
  if (marker.includes("cold_start") || marker.includes("warming")) return "cold_start";
  if (input.status === 408 || code === "timeout" || code === "full_analysis_timeout") {
    return "upstream_timeout";
  }
  if (code === "invalid_response") return "invalid_response";
  // 422 is the backend's fail-closed answer when verified evidence is missing —
  // an expected state (e.g. the off-season break), not a fault.
  if (input.status === 422 || marker.includes("insufficient_evidence")) {
    return "insufficient_evidence";
  }
  if (input.status === 502 || input.status === 503 || input.status === 504) {
    return "upstream_unavailable";
  }
  if (input.networkError || code === "network_error") return "network_error";
  return "unknown";
}

export function isRetryableInfrastructureError(category: AnalysisErrorCategory): boolean {
  return [
    "cold_start",
    "upstream_timeout",
    "upstream_unavailable",
    "network_error",
  ].includes(category);
}

function relativeTime(iso: string, now: Date): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export function formatLagosTimestamp(iso: string): string {
  return new Intl.DateTimeFormat("en-NG", {
    timeZone: "Africa/Lagos",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

/**
 * Plain-language readings of the backend's evidence codes.
 *
 * The backend emits SCREAMING_SNAKE codes (`FIXTURE_IDENTITY_UNVERIFIED`); a bare
 * `replaceAll("_", " ")` shouts raw enum-speak at the reader on the single most-read
 * line of the match page. Each entry states what is actually missing and why that
 * blocks a stake — never softened, since these are the fail-closed reasons.
 *
 * Unknown codes fall back to title case rather than being dropped: a code we have
 * not written copy for must still be legible, and must never render as an empty
 * reason. Keep in sync with the `critical_gaps.append(...)` sites in
 * `backend/src/api/endpoints/full_analysis.py` and `upcoming_match_service.py`.
 */
const EVIDENCE_CODE_COPY: Record<string, string> = {
  FIXTURE_IDENTITY_UNVERIFIED:
    "this matchup could not be tied to a scheduled fixture, so team history cannot be verified",
  REQUIRED_MODEL_INPUTS_UNAVAILABLE:
    "the inputs the model requires — recent form, head-to-head, and a coherent market — are not available",
  MODEL_PREDICTION_UNAVAILABLE: "the certified model could not produce a prediction",
  MODEL_GENERATION_UNCERTIFIED: "this model hasn't passed certification yet",
  MODEL_UNCERTAINTY_UNAVAILABLE: "confidence range not available for this fixture",
  MODEL_PREDICTION_REDUCED_EVIDENCE:
    "only a diagnostic baseline was produced, not a certified prediction",
  STALE_REQUIRED_EVIDENCE: "the required evidence is too old to rely on",
  STALE_ENRICHMENT_EVIDENCE:
    "an optional enrichment source is out of date, so a little supporting detail is missing",
  LEAGUE_POLICY_UNAVAILABLE: "this competition has no calibrated staking policy yet",
  COHERENT_1X2_MARKET_UNAVAILABLE:
    "no stable market price to compare against yet",
};

/** Title-case a backend code so an unmapped value still reads as words, not an enum. */
function titleCaseCode(code: string): string {
  return code
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Render one evidence code for a human. Returns the mapped sentence fragment when we
 * have copy for it, otherwise a title-cased fallback.
 */
export function describeEvidenceCode(code: string): string {
  return EVIDENCE_CODE_COPY[code] ?? titleCaseCode(code);
}

export function isNarrativeRedundant(
  narrative: string | null | undefined,
  reason: string | null | undefined,
): boolean {
  if (!narrative?.trim()) return true;
  if (!reason?.trim()) return false;
  const normalize = (value: string) =>
    value
      .toLowerCase()
      .replace(/\(s\)/g, "")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  const normalizedNarrative = normalize(narrative);
  const normalizedReason = normalize(reason);
  return (
    normalizedNarrative === normalizedReason ||
    normalizedNarrative.includes(normalizedReason) ||
    normalizedReason.includes(normalizedNarrative)
  );
}

export function mapFullAnalysisPresentation(
  data: FullMatchAnalysisResponse,
  now = new Date(),
) {
  const hasCriticalEvidenceIssue =
    data.partial_intelligence ||
    data.evidence_quality.critical_gap_count > 0 ||
    data.evidence_quality.conflict_count > 0;
  const predictionAvailable =
    data.prediction_status === "AVAILABLE" && data.probabilities_available;
  const blocked = !predictionAvailable || hasCriticalEvidenceIssue;
  const watchlistOnly = !blocked && data.verdict === "SPECULATIVE";
  const actionableVerdict = ["ACTIONABLE", "HIGH_CONVICTION"].includes(data.verdict);
  const stakePermitted = Boolean(
    !blocked &&
      actionableVerdict &&
      data.stake_permitted &&
      !data.rl_recommendation.abstain &&
      data.rl_recommendation.stake_fraction > 0,
  );

  let primaryDecision = "No bet";
  if (watchlistOnly) primaryDecision = "Watchlist";
  if (stakePermitted && data.odds_edge) {
    primaryDecision = `Consider ${data.odds_edge.market.replaceAll("_", " ")}`;
  }

  const reason = data.evidence_quality.conflicts[0]
    ? `Sources disagree — ${describeEvidenceCode(data.evidence_quality.conflicts[0])}.`
    : data.evidence_quality.critical_gaps[0]
      ? `Not enough verified data — ${describeEvidenceCode(data.evidence_quality.critical_gaps[0])}.`
      : !predictionAvailable
        ? data.is_reduced_evidence_baseline
          ? "Official probabilities are unavailable because only a diagnostic baseline was produced."
          : data.narrative || "Official probabilities are unavailable because verified evidence is insufficient."
        : watchlistOnly
          ? "The signal is speculative and remains watchlist-only."
          : data.rl_recommendation.abstain
            ? data.rl_recommendation.reason ?? "The risk gate requires abstention."
            : data.narrative;

  const effectiveStake = stakePermitted
    ? Math.min(data.rl_recommendation.stake_fraction, data.effective_kelly_cap)
    : 0;

  return {
    primaryDecision,
    reason,
    predictionAvailable,
    isReducedEvidenceBaseline: data.is_reduced_evidence_baseline,
    displayedProbabilities: predictionAvailable
      ? {
          home: data.ensemble.home_win_prob,
          draw: data.ensemble.draw_prob,
          away: data.ensemble.away_win_prob,
        }
      : null,
    topOutcome: predictionAvailable ? data.ensemble.prediction : null,
    topOutcomeProbability: predictionAvailable
      ? data.top_outcome_probability
      : null,
    stakePermitted,
    stakeFraction: effectiveStake,
    effectiveKellyCap: data.effective_kelly_cap,
    kellyGaugeRatio:
      stakePermitted && data.effective_kelly_cap > 0
        ? Math.min(1, effectiveStake / data.effective_kelly_cap)
        : 0,
    evidenceCounts: {
      critical: data.evidence_quality.critical_gap_count,
      advisory: data.evidence_quality.advisory_gap_count,
      conflicts: data.evidence_quality.conflict_count,
      total: data.evidence_quality.total_gap_count,
    },
    freshness: data.freshness_tag,
    generatedRelative: relativeTime(data.generated_at, now),
    generatedAbsoluteLagos: formatLagosTimestamp(data.generated_at),
  } as const;
}

// ─── Evidence gap grouping ────────────────────────────────────────────────────

/**
 * Missing-evidence codes are canonical *feature names* — `away_attack_vs_home_defense`,
 * `h2h_dominance`, `elo_momentum_cross`. A reduced-evidence fixture produces
 * ~50 of them, and listing each one title-cased put raw model internals in front
 * of ordinary users while telling them nothing they could act on.
 *
 * Each family below answers "what kind of evidence is missing", which is the
 * only part a reader can do anything with (mostly: come back closer to kickoff).
 * Order is deliberate — first match wins, so narrower patterns precede broader
 * ones (the market-interaction fields must be claimed before the plain h2h/venue
 * families would take them).
 */
const EVIDENCE_FAMILIES: ReadonlyArray<{ label: string; match: (code: string) => boolean }> = [
  { label: "Market prices", match: (c) =>
      c.startsWith("market_") || c.startsWith("log_odds") || c.startsWith("ev_") ||
      c === "odds_ratio" || c === "draw_probability" ||
      c.startsWith("form_market_") || c === "venue_market_combo" || c === "h2h_market_agreement" },
  { label: "Market movement", match: (c) => c.startsWith("odds_drift") || c === "sharp_money_direction" || c === "max_abs_odds_drift" },
  { label: "Head-to-head record", match: (c) => c.startsWith("h2h_") },
  { label: "Team strength ratings", match: (c) => c.startsWith("elo_") },
  { label: "Rating systems", match: (c) => c.includes("_pi_") || c.startsWith("pi_") || c.includes("berrar") },
  { label: "Home venue record", match: (c) => c.startsWith("home_venue_") || c === "home_advantage_strength" },
  { label: "Tactical metrics", match: (c) =>
      c.includes("pressing") || c.includes("carry") || c.includes("shot_quality") ||
      c.includes("key_passes") || c.includes("set_piece") },
  { label: "Weighted form", match: (c) => c.includes("weighted_") },
  { label: "Match context", match: (c) => c === "match_importance_score" },
  { label: "League baselines", match: (c) => c.startsWith("league_") },
  { label: "Combined strength", match: (c) =>
      c.startsWith("combined_") || c === "total_goals_expected" || c.includes("_vs_") },
  { label: "Recent form", match: (c) => c.includes("form_last5") || c.includes("last5") || c.includes("gd_recent") || c.includes("goals_") },
  { label: "Schedule", match: (c) => ["day_of_week", "is_weekend", "month", "season_phase"].includes(c) },
];

export interface EvidenceGapGroup {
  label: string;
  count: number;
  /** Raw codes, retained so the audit trail stays reachable. */
  codes: string[];
}

/** Group raw gap codes into reader-facing families, largest first. */
export function groupEvidenceGaps(gaps: readonly string[]): EvidenceGapGroup[] {
  const buckets = new Map<string, string[]>();
  for (const code of gaps) {
    const family = EVIDENCE_FAMILIES.find((f) => f.match(code))?.label ?? "Other inputs";
    const existing = buckets.get(family);
    if (existing) existing.push(code);
    else buckets.set(family, [code]);
  }
  return [...buckets.entries()]
    .map(([label, codes]) => ({ label, count: codes.length, codes }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}
