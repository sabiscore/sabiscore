import { Page, Route } from '@playwright/test';

export interface ProviderStatus {
  id: string;
  name: string;
  status: 'HEALTHY' | 'DEGRADED' | 'RATE_LIMITED' | 'UNAVAILABLE' | 'CIRCUIT_OPEN';
  quota_remaining_daily: number;
  quota_remaining_minute: number;
  latency_ms: number;
}

export interface CalibrationBin {
  bin_center: number;
  observed_frequency: number;
  count: number;
  ci_lower: number;
  ci_upper: number;
}

export interface CalibrationResponse {
  model_generation: string;
  binned_probabilities: CalibrationBin[];
  ece: number;
  brier_score: {
    total: number;
    reliability: number;
    resolution: number;
    uncertainty: number;
  };
  rps: number;
  walk_forward_seasons: string[];
}

export interface EvidenceQuality {
  critical_gaps: string[];
  advisory_gaps: string[];
  conflicts: string[];
  all_gaps: string[];
  critical_gap_count: number;
  advisory_gap_count: number;
  conflict_count: number;
  total_gap_count: number;
}

export interface MatchAnalysisPayload {
  match_id: string;
  verdict: 'HIGH_CONVICTION' | 'ACTIONABLE' | 'SPECULATIVE' | 'HOLD' | 'PARTIAL' | 'NO_BET';
  prediction_status: 'AVAILABLE' | 'REDUCED_EVIDENCE_BASELINE' | 'UNAVAILABLE';
  prediction_source: 'CERTIFIED_MODEL' | 'UNCERTIFIED_MODEL' | 'DIAGNOSTIC_BASELINE' | 'NONE';
  probabilities_available: boolean;
  is_reduced_evidence_baseline: boolean;
  top_outcome_probability: number;
  effective_kelly_cap: number;
  stake_permitted: boolean;
  fixture_verified: boolean;
  evidence_quality: EvidenceQuality;
  ensemble: {
    home_win_prob: number;
    draw_prob: number;
    away_win_prob: number;
    prediction: string;
    confidence: number;
    top_outcome_probability: number;
    probabilities_available: boolean;
    league: string;
    model_version: string;
    certification_state: string;
    coverage: string;
    calibration_method: string;
    calibration_applied: boolean;
    overlay_applied: boolean;
  };
  uncertainty: {
    epistemic_unc: number;
    aleatoric_unc: number;
    concentration: number;
    credible_interval: [number, number];
    confidence_tier: 'OK' | 'LOW_EVIDENCE' | 'UNCERTIFIED';
  };
  model_drivers: string[];
  causal_drivers: string[];
  rl_recommendation: {
    stake_fraction: number;
    abstain: boolean;
    reason: string;
    reward_components: Record<string, number>;
  };
  elo_context: {
    home_elo: number;
    away_elo: number;
    elo_difference: number;
    home_elo_trend_5: number;
    away_elo_trend_5: number;
    elo_momentum_cross: number;
  };
  odds_edge: {
    market: string;
    market_odds: number;
    model_prob: number;
    edge: number;
    kelly_stake: number;
  } | null;
  narrative: string;
  partial_intelligence: boolean;
  data_gaps: string[];
  staleness_seconds: number;
  staleness_available: boolean;
  freshness_tag: 'LIVE' | 'STALE' | 'UNKNOWN';
  feature_freshness_seconds: Record<string, number>;
  feature_source: Record<string, string>;
  actionability: null;
  match_importance_score: null;
  competition_stage: null;
  generated_at: string;
}

export function createMockAnalysisPayload(options: {
  match_id?: string;
  verdict?: 'HIGH_CONVICTION' | 'ACTIONABLE' | 'SPECULATIVE' | 'HOLD' | 'PARTIAL' | 'NO_BET';
  status?: 'AVAILABLE' | 'REDUCED_EVIDENCE_BASELINE' | 'UNAVAILABLE';
  source?: 'CERTIFIED_MODEL' | 'UNCERTIFIED_MODEL' | 'DIAGNOSTIC_BASELINE' | 'NONE';
  evidence?: { critical_gaps?: string[]; advisory_gaps?: string[]; conflicts?: string[] };
  stakePermitted?: boolean;
  freshness_tag?: 'LIVE' | 'STALE' | 'UNKNOWN';
  staleness_seconds?: number;
} = {}): MatchAnalysisPayload {
  const status = options.status ?? 'AVAILABLE';
  const crit = options.evidence?.critical_gaps ?? [];
  const adv = options.evidence?.advisory_gaps ?? [];
  const conf = options.evidence?.conflicts ?? [];
  const all_gaps = [...new Set([...crit, ...adv, ...conf])];

  const evidence: EvidenceQuality = {
    critical_gaps: crit,
    advisory_gaps: adv,
    conflicts: conf,
    all_gaps,
    critical_gap_count: crit.length,
    advisory_gap_count: adv.length,
    conflict_count: conf.length,
    total_gap_count: all_gaps.length,
  };

  const available = status === 'AVAILABLE';
  const isBaseline = status === 'REDUCED_EVIDENCE_BASELINE';
  const isUnavailable = status === 'UNAVAILABLE';

  const defaultSource = available
    ? 'CERTIFIED_MODEL'
    : isBaseline
    ? 'DIAGNOSTIC_BASELINE'
    : 'NONE';

  const source = options.source ?? defaultSource;
  const certificationState = source === 'CERTIFIED_MODEL' ? 'CERTIFIED' : 'UNVERIFIED';

  const stakePermitted = options.stakePermitted ?? (options.verdict === 'ACTIONABLE' || options.verdict === 'HIGH_CONVICTION' || (!options.verdict && available));
  const probabilities = isUnavailable
    ? { home_win_prob: 0, draw_prob: 0, away_win_prob: 0, top: 0 }
    : { home_win_prob: 0.5, draw_prob: 0.28, away_win_prob: 0.22, top: 0.5 };

  return {
    match_id: options.match_id ?? 'Arsenal vs Chelsea',
    verdict: options.verdict ?? (stakePermitted ? 'ACTIONABLE' : 'PARTIAL'),
    prediction_status: status,
    prediction_source: source,
    probabilities_available: available,
    is_reduced_evidence_baseline: isBaseline,
    top_outcome_probability: probabilities.top,
    effective_kelly_cap: 0.04,
    stake_permitted: stakePermitted,
    fixture_verified: true,
    evidence_quality: evidence,
    ensemble: {
      home_win_prob: probabilities.home_win_prob,
      draw_prob: probabilities.draw_prob,
      away_win_prob: probabilities.away_win_prob,
      prediction: 'home_win',
      confidence: probabilities.top,
      top_outcome_probability: probabilities.top,
      probabilities_available: available,
      league: 'EPL',
      model_version: available ? 'v5_phase7' : 'diagnostic',
      certification_state: certificationState,
      coverage: 'dedicated',
      calibration_method: available ? 'isotonic' : 'raw',
      calibration_applied: available,
      overlay_applied: false,
    },
    uncertainty: {
      epistemic_unc: 0.05,
      aleatoric_unc: 0.1,
      concentration: 0.8,
      credible_interval: [0.42, 0.58],
      confidence_tier: 'OK',
    },
    model_drivers: stakePermitted ? ['elo_difference'] : [],
    causal_drivers: stakePermitted ? ['elo_difference'] : [],
    rl_recommendation: {
      stake_fraction: stakePermitted ? 0.015 : 0,
      abstain: !stakePermitted,
      reason: stakePermitted ? 'Quarter-Kelly within league cap' : 'No public stake',
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
      ? { market: 'home_win', market_odds: 2.4, model_prob: 0.5, edge: 0.08, kelly_stake: 0.015 }
      : null,
    narrative: stakePermitted
      ? 'Verified evidence supports a bounded home-win position.'
      : 'No bet — insufficient verified evidence.',
    partial_intelligence: evidence.critical_gap_count > 0 || evidence.conflict_count > 0,
    data_gaps: evidence.all_gaps,
    staleness_seconds: options.staleness_seconds ?? 120,
    staleness_available: available,
    freshness_tag: options.freshness_tag ?? (available ? 'LIVE' : 'UNKNOWN'),
    feature_freshness_seconds: {},
    feature_source: {},
    actionability: null,
    match_importance_score: null,
    competition_stage: null,
    generated_at: '2026-07-20T12:00:00Z',
  };
}

export function createMockCalibrationPayload(): CalibrationResponse {
  return {
    model_generation: 'canonical_68_v2',
    binned_probabilities: [
      { bin_center: 0.1, observed_frequency: 0.095, count: 240, ci_lower: 0.072, ci_upper: 0.118 },
      { bin_center: 0.2, observed_frequency: 0.205, count: 310, ci_lower: 0.181, ci_upper: 0.229 },
      { bin_center: 0.3, observed_frequency: 0.292, count: 450, ci_lower: 0.268, ci_upper: 0.316 },
      { bin_center: 0.4, observed_frequency: 0.408, count: 520, ci_lower: 0.384, ci_upper: 0.432 },
      { bin_center: 0.5, observed_frequency: 0.495, count: 610, ci_lower: 0.471, ci_upper: 0.519 },
      { bin_center: 0.6, observed_frequency: 0.612, count: 480, ci_lower: 0.588, ci_upper: 0.636 },
      { bin_center: 0.7, observed_frequency: 0.689, count: 360, ci_lower: 0.665, ci_upper: 0.713 },
      { bin_center: 0.8, observed_frequency: 0.804, count: 220, ci_lower: 0.780, ci_upper: 0.828 },
      { bin_center: 0.9, observed_frequency: 0.891, count: 140, ci_lower: 0.867, ci_upper: 0.915 },
    ],
    ece: 0.018,
    brier_score: {
      total: 0.178,
      reliability: 0.006,
      resolution: 0.078,
      uncertainty: 0.250,
    },
    rps: 0.184,
    walk_forward_seasons: ['2023-2024', '2024-2025'],
  };
}

export async function pageFetch(
  page: Page,
  url: string,
  options?: { method?: string; headers?: Record<string, string>; body?: string }
): Promise<{ status: number; ok: boolean; headers: Record<string, string>; json: () => Promise<any>; text: () => Promise<string> }> {
  const result = await page.evaluate(
    async ({ url, options }) => {
      try {
        const res = await fetch(url, options);
        const text = await res.text();
        let jsonBody = null;
        try {
          jsonBody = JSON.parse(text);
        } catch {}
        const headers: Record<string, string> = {};
        res.headers.forEach((v, k) => {
          headers[k.toLowerCase()] = v;
        });
        return {
          status: res.status,
          ok: res.ok,
          headers,
          bodyText: text,
          bodyJson: jsonBody,
        };
      } catch (err: any) {
        return {
          status: 0,
          ok: false,
          headers: {},
          bodyText: err?.message || 'Fetch error',
          bodyJson: null,
        };
      }
    },
    { url, options }
  );

  return {
    status: result.status,
    ok: result.ok,
    headers: result.headers,
    text: async () => result.bodyText,
    json: async () => result.bodyJson,
  };
}

export async function setupMockApiRoutes(page: Page) {
  // Mock Health API. `providers` mirrors the real /api/health shape — an array
  // of ProviderHealthRow (see apps/web/src/lib/health-status.ts) — not a status
  // map. `deriveProviderActivation`, called from the root layout on every page,
  // calls `.filter()` on this field directly.
  await page.route('**/api/health', (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'healthy',
        backendStatus: 'healthy',
        sha: 'abc1234',
        database: 'connected',
        redis: 'connected',
        backendChecks: {
          database: { status: 'ready' },
          migrations: { status: 'ready' },
          cache: { status: 'ready' },
          models: { status: 'ready' },
        },
        providers: [
          { provider: 'sportmonks', configured: true, enabled: true, state: 'VERIFIED' },
          { provider: 'the_odds_api', configured: true, enabled: true, state: 'VERIFIED' },
          { provider: 'api_football', configured: true, enabled: true, state: 'VERIFIED' },
          { provider: 'football_data_org', configured: true, enabled: true, state: 'VERIFIED' },
        ],
      }),
    });
  });

  // Mock Providers API
  await page.route('**/api/providers**', (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        providers: [
          { id: 'sportmonks', name: 'Sportmonks API', status: 'HEALTHY', quota_remaining_daily: 4500, quota_remaining_minute: 120, latency_ms: 85 },
          { id: 'the_odds_api', name: 'The Odds API', status: 'HEALTHY', quota_remaining_daily: 480, quota_remaining_minute: 25, latency_ms: 110 },
          { id: 'api_football', name: 'API-Football', status: 'HEALTHY', quota_remaining_daily: 8200, quota_remaining_minute: 280, latency_ms: 95 },
          { id: 'football_data_org', name: 'Football-Data.org', status: 'HEALTHY', quota_remaining_daily: 920, quota_remaining_minute: 10, latency_ms: 130 },
        ],
      }),
    });
  });

  // Mock Calibration Performance API
  await page.route('**/api/v1/model-performance/calibration**', (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(createMockCalibrationPayload()),
    });
  });

  // Mock Upcoming Fixtures API. Field is `upcoming_matches`, not `fixtures` — see
  // UpcomingMatchesResponse in apps/web/src/lib/api.ts. upcoming-matches-panel.tsx
  // and match-selector.tsx both read `data.upcoming_matches.length` unguarded.
  await page.route('**/api/upcoming**', (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        upcoming_matches: [
          {
            match_id: 'Arsenal vs Chelsea',
            home_team: 'Arsenal',
            away_team: 'Chelsea',
            league: 'EPL',
            match_date: new Date(Date.now() + 86400000).toISOString(),
            venue: null,
            status: 'PREMATCH',
            predictions: null,
            value_bets: [],
            has_value: false,
            best_value_bet: null,
            data_gaps: [],
            staleness_seconds: 120,
            staleness_available: true,
            source: 'mock',
            edge_quality_score: null,
            clv_pct: null,
          },
        ],
        total: 1,
        matches_with_value: 0,
        avg_edge_pct: 0,
        cache_hit: false,
        ttl_seconds: 300,
        source: 'mock',
        offseason: false,
        next_season_start: null,
        next_season_start_estimated: null,
        data_gap: false,
        unavailable_reasons: [],
        generated_at: new Date().toISOString(),
      }),
    });
  });

  // Mock Full Analysis API
  await page.route('**/api/full-analysis/**', (route: Route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(createMockAnalysisPayload()),
    });
  });
}
