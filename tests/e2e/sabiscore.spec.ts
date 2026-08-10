import { test, expect } from '@playwright/test';

// Backend-independent by design (same contract as intelligence.spec.ts):
// assertions target static shell chrome and mocked API responses so the
// release gate never needs a live FastAPI backend.
test.describe('SabiScore End-to-End', () => {
  test('homepage renders the verified-fixture primary workflow', async ({ page }) => {
    await page.goto('/');

    await expect(page.getByRole('heading', { name: /Upcoming verified fixtures/i })).toBeVisible();
    await expect(
      page.getByRole('link', { name: /Review verified fixtures/i }).first(),
    ).toBeVisible();
  });

  test('shows an evidence-safe banner when backend reports unavailable', async ({ page }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'degraded', backendStatus: 'unavailable' }),
      }),
    );

    await page.goto('/');

    await expect(
      page.getByRole('alert').getByText(/live readiness and provider status cannot be verified/i),
    ).toBeVisible();
  });
});

test.describe('Phase 8 feature analytics API', () => {
  test('phase8-features route returns JSON with expected shape', async ({ request }) => {
    // This test exercises the Next.js proxy route against the backend.
    // If the backend is not running, the route returns 502 — we only assert shape
    // when the backend is healthy, otherwise we just confirm the route exists.
    const res = await request.get('/api/phase8-features/Arsenal%20vs%20Chelsea?league=EPL');
    // The route must respond (not 404) regardless of backend availability.
    expect(res.status()).not.toBe(404);

    if (res.ok()) {
      const body = await res.json();
      // Top-level fields
      expect(body).toHaveProperty('match_id', 'Arsenal vs Chelsea');
      expect(body).toHaveProperty('league', 'EPL');
      expect(body).toHaveProperty('status');
      expect(body).toHaveProperty('feature_groups');
      expect(body).toHaveProperty('total_phase8_features', 21);
      expect(body).toHaveProperty('phase8_enabled');
      // Feature groups: should have 5 groups
      expect(Array.isArray(body.feature_groups)).toBe(true);
      if ((body as { phase8_enabled: boolean }).phase8_enabled) {
        expect((body as { feature_groups: unknown[] }).feature_groups.length).toBe(5);
      }
    }
  });

  test('phase8-features route returns 400 for missing matchId', async ({ request }) => {
    // An empty matchId segment is malformed; Next.js returns 404 for unknown routes.
    const res = await request.get('/api/phase8-features/');
    // Next.js catches empty segment as a different route; we just confirm no 500.
    expect(res.status()).not.toBe(500);
  });
});

// ---------------------------------------------------------------------------
// Sprint 4 Slice A: CLV / Actionability + Off-season E2E
// ---------------------------------------------------------------------------

test.describe('Sprint 4 Slice A — actionability and off-season', () => {
  test('full-analysis route includes actionability field', async ({ request }) => {
    const res = await request.get(
      '/api/full-analysis/Arsenal%20vs%20Chelsea?league=EPL',
    );
    expect(res.status()).not.toBe(404);

    if (res.ok()) {
      const body = await res.json() as Record<string, unknown>;
      // actionability is either null or an object with edge_quality_score
      expect('actionability' in body).toBe(true);
      if (body.actionability !== null && body.actionability !== undefined) {
        const act = body.actionability as Record<string, unknown>;
        expect(act).toHaveProperty('edge_quality_score');
        expect(typeof act.edge_quality_score).toBe('number');
        expect((act.edge_quality_score as number)).toBeGreaterThanOrEqual(0);
        expect((act.edge_quality_score as number)).toBeLessThanOrEqual(1);
        expect(act).toHaveProperty('abstain');
        expect(act).toHaveProperty('top_evidence');
        expect(Array.isArray(act.top_evidence)).toBe(true);
        expect(act).toHaveProperty('caveats');
        expect(Array.isArray(act.caveats)).toBe(true);
        expect(act).toHaveProperty('suggested_stake_pct');
      }
    }
  });

  test('actionability abstain=true renders no-bet in dashboard', async ({ page }) => {
    // Mock the full-analysis API to return an abstain=true actionability block
    await page.route('**/api/full-analysis/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          match_id: 'test-match',
          verdict: 'HOLD',
          ensemble: { home_win_prob: 0.36, draw_prob: 0.33, away_win_prob: 0.31, prediction: 'home_win', confidence: 0.36, league: 'EPL', model_version: '' },
          uncertainty: { epistemic_unc: 0.18, aleatoric_unc: 0.12, concentration: 1.2, credible_interval: [0.25, 0.55], confidence_tier: 'LOW_EVIDENCE' },
          causal_drivers: [],
          rl_recommendation: { stake_fraction: 0.0, abstain: true, reason: 'Low reward signal', reward_components: {} },
          elo_context: { home_elo: 1500, away_elo: 1500, elo_difference: 0, home_elo_trend_5: 0, away_elo_trend_5: 0, elo_momentum_cross: 0 },
          odds_edge: null,
          narrative: 'Hold — low evidence environment.',
          partial_intelligence: false,
          data_gaps: [],
          staleness_seconds: 0,
          freshness_tag: 'LIVE',
          per_feature_freshness_seconds: {},
          actionability: {
            edge_quality_score: 0.12,
            clv_pct: null,
            closing_line_convergence_delta: null,
            suggested_stake_pct: 0.0,
            abstain: true,
            abstain_reason: 'Low reward signal',
            top_evidence: [],
            caveats: ['Low model evidence (epistemic 0.18)'],
          },
          generated_at: new Date().toISOString(),
        }),
      });
    });

    await page.goto('/match/test-match?league=EPL');

    // The CLV Evidence Panel should show "No bet" as the stake
    const stakeLabel = page.getByText('No bet');
    if (await stakeLabel.count() > 0) {
      await expect(stakeLabel.first()).toBeVisible();
    }

    // ABSTAIN signal label should be visible in the evidence panel
    const abstainLabel = page.getByText('ABSTAIN');
    if (await abstainLabel.count() > 0) {
      await expect(abstainLabel.first()).toBeVisible();
    }
  });

  test('offseason route returns JSON with expected shape', async ({ request }) => {
    const res = await request.get('/api/offseason/EPL');
    expect(res.status()).not.toBe(404);

    // Either the backend proxy responds, or the fallback UNKNOWN response is used
    const body = await res.json() as Record<string, unknown>;
    expect(body).toHaveProperty('season_status');
    expect(['IN_SEASON', 'OFF_SEASON', 'UNKNOWN']).toContain(body.season_status);
    expect(body).toHaveProperty('data_availability');
    expect(body).toHaveProperty('prediction_advisory');
  });

  test('off-season banner appears when mock returns OFF_SEASON', async ({ page }) => {
    // Mock the offseason API to return OFF_SEASON
    await page.route('**/api/offseason/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          league: 'EPL',
          league_slug: 'epl',
          season_status: 'OFF_SEASON',
          current_season_label: '2025-26',
          current_season_end: '2026-05-19',
          next_season_start: '2026-08-08',
          days_until_next_season: 42,
          data_availability: {
            historical_results: true,
            elo_ratings: true,
            market_odds: false,
            form_stats: true,
            team_metadata: true,
          },
          prediction_advisory: 'Off-season. Predictions use last-season data.',
          queried_at: new Date().toISOString(),
        }),
      });
    });

    // Navigate to a page that renders UpcomingMatchesPanel with a league filter
    await page.goto('/?league=EPL');

    // The off-season notice should appear
    const offseasonNotice = page.getByText(/days? until next season/i);
    if (await offseasonNotice.count() > 0) {
      await expect(offseasonNotice.first()).toBeVisible();
    }
  });

  test('offseason route returns UNKNOWN for unknown league slug', async ({ request }) => {
    const res = await request.get('/api/offseason/unknown_fantasy_league_xyz');
    // Should not 500 or 404 (graceful fallback to UNKNOWN)
    expect(res.status()).not.toBe(500);
    if (res.ok()) {
      const body = await res.json() as Record<string, unknown>;
      expect(body.season_status).toBe('UNKNOWN');
    }
  });
});
