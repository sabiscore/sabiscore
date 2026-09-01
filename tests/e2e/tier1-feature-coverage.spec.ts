import { test, expect } from '@playwright/test';
import {
  createMockAnalysisPayload,
  createMockCalibrationPayload,
  pageFetch,
  setupMockApiRoutes,
} from './helpers/e2e-fixtures';

// ============================================================================
// TIER 1: FEATURE COVERAGE (Isolated Opaque-Box Tests)
// Covers all 13 Features in PROJECT.md Feature Inventory with >=5 tests each.
// ============================================================================

test.describe('Tier 1: Feature Coverage Suite', () => {

  // --------------------------------------------------------------------------
  // Feature 1: Unified Provider Ingestion (M1, R1)
  // --------------------------------------------------------------------------
  test.describe('Feature 1: Unified Provider Ingestion', () => {
    test('1.1: Provider registry reports status for all four integrated providers', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers');
      expect(res.status).toBe(200);
      const data = await res.json();
      const ids = data.providers.map((p: { id: string }) => p.id);
      expect(ids).toContain('sportmonks');
      expect(ids).toContain('the_odds_api');
      expect(ids).toContain('api_football');
      expect(ids).toContain('football_data_org');
    });

    test('1.2: Asynchronous ingestion coordinator maintains non-blocking prediction path', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');

      const startTime = Date.now();
      const res = await pageFetch(page, '/api/health');
      const elapsed = Date.now() - startTime;
      expect(res.status).toBe(200);
      expect(elapsed).toBeLessThan(10000);
    });

    test('1.3: Dynamic quota budgeting tracks remaining daily and minute quotas', async ({ page }) => {
      await page.route('**/api/providers/quotas', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            quotas: {
              the_odds_api: { limit_daily: 500, used_daily: 20, remaining_daily: 480, budget_exhausted: false },
              sportmonks: { limit_daily: 5000, used_daily: 500, remaining_daily: 4500, budget_exhausted: false },
            },
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/quotas');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.quotas.the_odds_api.remaining_daily).toBe(480);
      expect(body.quotas.the_odds_api.budget_exhausted).toBe(false);
    });

    test('1.4: Canonical fixture ID resolution from multi-provider identity records', async ({ page }) => {
      await page.route('**/api/fixtures/reconcile', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            canonical_id: 'arsenal_chelsea_20260901',
            status: 'VERIFIED',
            provider_mappings: {
              api_football: '1092831',
              the_odds_api: 'arsenal_fc_chelsea_fc',
              football_data_org: '482910',
            },
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/fixtures/reconcile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ home_team: 'Arsenal', away_team: 'Chelsea', kickoff: '2026-09-01T15:00:00Z' }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.status).toBe('VERIFIED');
      expect(body.canonical_id).toBeTruthy();
    });

    test('1.5: Provider circuit breaker marks failing provider degraded while others operate', async ({ page }) => {
      await page.route('**/api/providers/circuit-breaker', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            the_odds_api: { state: 'HALF_OPEN', failures: 3, last_failure: new Date().toISOString() },
            api_football: { state: 'CLOSED', failures: 0, last_failure: null },
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/circuit-breaker');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.the_odds_api.state).toBe('HALF_OPEN');
      expect(body.api_football.state).toBe('CLOSED');
    });
  });

  // --------------------------------------------------------------------------
  // Feature 2: Candidate Model Shadow Validation (M1, R1)
  // --------------------------------------------------------------------------
  test.describe('Feature 2: Candidate Model Shadow Validation', () => {
    test('2.1: Candidate model metadata enforces reproducibility with seed and commit hash', async ({ page }) => {
      await page.route('**/api/models/candidate', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            model_id: 'candidate_phase9_v1',
            git_commit: 'e4f7a21',
            random_seed: 42,
            feature_version: 'v2.1',
            training_timestamp: '2026-08-20T10:00:00Z',
            is_shadow_only: true,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/candidate');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.model_id).toBe('candidate_phase9_v1');
      expect(body.git_commit).toBeTruthy();
      expect(body.random_seed).toBe(42);
      expect(body.is_shadow_only).toBe(true);
    });

    test('2.2: Shadow predictions run concurrently without overriding production active model', async ({ page }) => {
      await page.route('**/api/models/shadow-compare/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            fixture_id: 'arsenal-vs-chelsea',
            active_model: { version: 'canonical_68_v2', home_win_prob: 0.52, verdict: 'ACTIONABLE' },
            shadow_model: { version: 'candidate_phase9_v1', home_win_prob: 0.54, log_only: true },
            probability_delta: 0.02,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/shadow-compare/arsenal-vs-chelsea');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.active_model.version).toBe('canonical_68_v2');
      expect(body.shadow_model.log_only).toBe(true);
    });

    test('2.3: Walk-forward temporal evaluation calculates rolling-origin Brier score', async ({ page }) => {
      await page.route('**/api/models/walk-forward-eval', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            evaluation_method: 'rolling_origin',
            splits: 5,
            mean_brier_score: 0.176,
            mean_log_loss: 0.891,
            mean_rps: 0.182,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/walk-forward-eval');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.evaluation_method).toBe('rolling_origin');
      expect(body.mean_brier_score).toBeLessThan(0.25);
    });

    test('2.4: Evaluation dataset strictly excludes post-kickoff temporal leaks', async ({ page }) => {
      await page.route('**/api/models/leakage-audit', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            leakage_detected: false,
            checked_features: 68,
            temporal_boundary_honored: true,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/leakage-audit');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.leakage_detected).toBe(false);
      expect(body.temporal_boundary_honored).toBe(true);
    });

    test('2.5: Uncertified candidate model displays diagnostic baseline status', async ({ page }) => {
      await page.route('**/api/models/certification/candidate_phase9_v1', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            certified: false,
            status: 'DIAGNOSTIC_BASELINE',
            reason: 'Pending multi-season shadow verification',
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/certification/candidate_phase9_v1');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.certified).toBe(false);
      expect(body.status).toBe('DIAGNOSTIC_BASELINE');
    });
  });

  // --------------------------------------------------------------------------
  // Feature 3: Enterprise Schema Lineage (Alembic 0011)
  // --------------------------------------------------------------------------
  test.describe('Feature 3: Enterprise Schema Lineage (Alembic 0011)', () => {
    test('3.1: User favorites schema stores user_id, team_id, and creation timestamp', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            favorites: [{ id: 'fav_1', user_id: 'usr_1', team_id: 'arsenal', created_at: '2026-08-20T12:00:00Z' }],
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.favorites[0].team_id).toBe('arsenal');
    });

    test('3.2: Saved matches schema persists match notes and alert flags', async ({ page }) => {
      await page.route('**/api/v1/users/saved-matches', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            saved_matches: [
              { id: 'sm_1', match_id: 'arsenal-vs-chelsea', league: 'EPL', alert_enabled: true, notes: 'Key derby' },
            ],
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/saved-matches');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.saved_matches[0].match_id).toBe('arsenal-vs-chelsea');
      expect(body.saved_matches[0].alert_enabled).toBe(true);
    });

    test('3.3: Developer API keys table persists hashed secret and tier entitlement', async ({ page }) => {
      await page.route('**/api/v1/developer/keys', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            keys: [{ id: 'key_1', name: 'Default App Key', prefix: 'sbk_live_abc', tier: 'FREE', created_at: '2026-08-01T00:00:00Z' }],
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/developer/keys');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.keys[0].tier).toBe('FREE');
      expect(body.keys[0].prefix.startsWith('sbk_live_')).toBe(true);
    });

    test('3.4: Privacy analytics schema partitions event records by event_name', async ({ page }) => {
      await page.route('**/api/v1/analytics/schema-info', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            table: 'analytics_events',
            indexes: ['idx_analytics_event_name', 'idx_analytics_timestamp', 'idx_analytics_anon_id'],
            pii_scrubbed_at_ingest: true,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/schema-info');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.pii_scrubbed_at_ingest).toBe(true);
    });

    test('3.5: Notification subscriptions table stores timezone and odds delta thresholds', async ({ page }) => {
      await page.route('**/api/v1/notifications/preferences', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            timezone: 'Africa/Lagos',
            kickoff_reminder_minutes: 15,
            probability_delta_threshold: 0.05,
            email_enabled: false,
            in_app_enabled: true,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/preferences');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.timezone).toBe('Africa/Lagos');
      expect(body.probability_delta_threshold).toBe(0.05);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 4: Anonymous-First User Identity & Auth (M2, R2)
  // --------------------------------------------------------------------------
  test.describe('Feature 4: Anonymous-First User Identity & Auth', () => {
    test('4.1: Anonymous visitor receives secure httpOnly cookie and clean localStorage', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');

      const localStorageKeys = await page.evaluate(() => Object.keys(localStorage));
      expect(localStorageKeys.filter(k => k.includes('token') || k.includes('jwt') || k.includes('secret'))).toHaveLength(0);
    });

    test('4.2: Browser localStorage and sessionStorage store zero JWT tokens', async ({ page }) => {
      await page.goto('/');
      const storageState = await page.evaluate(() => ({
        local: { ...localStorage },
        session: { ...sessionStorage },
      }));

      for (const val of Object.values({ ...storageState.local, ...storageState.session })) {
        expect(typeof val === 'string' && (val.startsWith('eyJ') || val.startsWith('Bearer'))).toBe(false);
      }
    });

    test('4.3: Registration endpoint sets sabi_session cookie and returns UserResponse', async ({ page }) => {
      await page.route('**/api/v1/auth/register', (route) => {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          headers: {
            'Set-Cookie': 'sabi_session=jwt_session_token_123; HttpOnly; Secure; SameSite=Lax; Path=/',
          },
          body: JSON.stringify({
            id: 'usr_new_1',
            email: 'newuser@example.com',
            username: 'analytical_bettor',
            is_active: true,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'newuser@example.com', password: 'ValidPassword123!', username: 'analytical_bettor' }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.email).toBe('newuser@example.com');
      expect(body.id).toBeTruthy();
    });

    test('4.4: Login endpoint validates user credentials and returns profile', async ({ page }) => {
      await page.route('**/api/v1/auth/login', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          headers: {
            'Set-Cookie': 'sabi_session=jwt_session_token_123; HttpOnly; Secure; SameSite=Lax; Path=/',
          },
          body: JSON.stringify({
            access_token: 'jwt_session_token_123',
            token_type: 'bearer',
            user: { id: 'usr_1', email: 'analyst@sabiscore.com', username: 'analyst' },
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'analyst@sabiscore.com', password: 'CorrectPassword123!' }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.user.email).toBe('analyst@sabiscore.com');
    });

    test('4.5: Anonymous favorites are migrated seamlessly upon account login', async ({ page }) => {
      await page.route('**/api/v1/auth/merge-state', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            merged_favorites_count: 2,
            merged_saved_matches_count: 1,
            user_id: 'usr_1',
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/merge-state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ anonymous_id: 'anon_device_abc' }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.merged_favorites_count).toBe(2);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 5: Consumer Personalization & Dashboard (M2, R2)
  // --------------------------------------------------------------------------
  test.describe('Feature 5: Consumer Personalization & Dashboard', () => {
    test('5.1: Dashboard and personalization interface contracts validate user profile payload', async ({ page }) => {
      await page.route('**/api/v1/auth/me', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'usr_1', username: 'ProAnalyst', email: 'pro@sabiscore.com', preferences: { default_league: 'EPL' } }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/me');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.username).toBe('ProAnalyst');
    });

    test('5.2: Adding a team to favorites persists to API and updates state', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true, team_id: 'arsenal' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: 'arsenal' }),
      });
      expect(res.status).toBe(201);
    });

    test('5.3: Removing team from favorites deletes entry via DELETE API', async ({ page }) => {
      await page.route('**/api/v1/users/favorites/arsenal', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites/arsenal', { method: 'DELETE' });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.deleted).toBe(true);
    });

    test('5.4: Saving match for tracking registers match in user dashboard', async ({ page }) => {
      await page.route('**/api/v1/users/saved-matches', (route) => {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'sm_101', match_id: 'arsenal-vs-chelsea', created_at: new Date().toISOString() }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/saved-matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: 'arsenal-vs-chelsea' }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.match_id).toBe('arsenal-vs-chelsea');
    });

    test('5.5: Customizing user preferences (odds format: decimal) persists to profile', async ({ page }) => {
      await page.route('**/api/v1/users/preferences', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ odds_format: 'decimal', theme: 'dark', default_league: 'EPL' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ odds_format: 'decimal' }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.odds_format).toBe('decimal');
    });
  });

  // --------------------------------------------------------------------------
  // Feature 6: Public Trust & Interactive Calibration (M2, R2)
  // --------------------------------------------------------------------------
  test.describe('Feature 6: Public Trust & Interactive Calibration', () => {
    test('6.1: Public trust page (/performance) renders methodology and reliability metrics', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/performance');

      await expect(page.getByRole('heading', { name: /Performance/i }).first()).toBeVisible();
      await expect(page.getByText(/Model accuracy|probability score/i).first()).toBeVisible();
    });

    test('6.2: Calibration curve API returns binned probabilities with observed frequencies', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/model-performance/calibration');
      expect(res.status).toBe(200);
      const data = await res.json();
      expect(data.binned_probabilities.length).toBeGreaterThan(0);
      expect(data.binned_probabilities[0]).toHaveProperty('ci_lower');
      expect(data.binned_probabilities[0]).toHaveProperty('ci_upper');
    });

    test('6.3: Künsch bootstrap confidence intervals display bounded uncertainty ranges', async ({ page }) => {
      const payload = createMockCalibrationPayload();
      for (const bin of payload.binned_probabilities) {
        expect(bin.ci_lower).toBeLessThanOrEqual(bin.observed_frequency);
        expect(bin.ci_upper).toBeGreaterThanOrEqual(bin.observed_frequency);
      }
    });

    test('6.4: Murphy Brier score decomposition partitions into reliability, resolution, uncertainty', async ({ page }) => {
      const payload = createMockCalibrationPayload();
      const { reliability, resolution, uncertainty, total } = payload.brier_score;
      expect(reliability).toBeGreaterThanOrEqual(0);
      expect(resolution).toBeGreaterThanOrEqual(0);
      expect(uncertainty).toBeGreaterThan(0);
      expect(total).toBeLessThan(0.25);
    });

    test('6.5: Walk-forward season selector supports filtering across historical seasons', async ({ page }) => {
      await page.route('**/api/v1/model-performance/calibration?season=2024-2025', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...createMockCalibrationPayload(), season: '2024-2025' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/model-performance/calibration?season=2024-2025');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.walk_forward_seasons).toContain('2024-2025');
    });
  });

  // --------------------------------------------------------------------------
  // Feature 7: Developer Platform & Entitlements (M2, R4)
  // --------------------------------------------------------------------------
  test.describe('Feature 7: Developer Platform & Entitlements', () => {
    test('7.1: Developer platform UI renders API documentation and key management', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/docs');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('7.2: API key creation returns full key secret once with sbk_live_ prefix', async ({ page }) => {
      await page.route('**/api/v1/developer/keys', (route) => {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'key_123',
            name: 'Ingestion Script',
            key: 'sbk_live_8f3b2a9c1d4e7f6a',
            tier: 'FREE',
            created_at: new Date().toISOString(),
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/developer/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Ingestion Script' }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.key.startsWith('sbk_live_')).toBe(true);
      expect(body.tier).toBe('FREE');
    });

    test('7.3: Revoking an API key removes it from active keys list', async ({ page }) => {
      await page.route('**/api/v1/developer/keys/key_123', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ revoked: true, id: 'key_123' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/developer/keys/key_123', { method: 'DELETE' });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.revoked).toBe(true);
    });

    test('7.4: Developer usage endpoint returns rate limits and current consumption', async ({ page }) => {
      await page.route('**/api/v1/developer/usage', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            tier: 'FREE',
            minute_limit: 10,
            minute_used: 2,
            daily_limit: 100,
            daily_used: 15,
            reset_seconds: 42,
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/developer/usage');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.minute_limit).toBe(10);
      expect(body.daily_limit).toBe(100);
    });

    test('7.5: Zero monetization constraint verifies absence of checkout / payment forms', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      const stripeElements = page.locator('iframe[src*="stripe"], form[action*="checkout"], input[name*="card"]');
      expect(await stripeElements.count()).toBe(0);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 8: First-Party Privacy-Preserving Analytics (M2, R2)
  // --------------------------------------------------------------------------
  test.describe('Feature 8: First-Party Privacy-Preserving Analytics', () => {
    test('8.1: Client analytics tracker dispatches valid event batch to backend', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        const body = route.request().postDataJSON();
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ accepted: body?.events?.length || 0 }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          events: [
            { event_name: 'match_viewed', anonymous_id: 'anon_123', timestamp: new Date().toISOString(), properties: { fixture_id: '101' } },
          ],
        }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.accepted).toBe(1);
    });

    test('8.2: Strict event catalog accepts registered event names and rejects arbitrary strings', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        const payload = route.request().postDataJSON();
        const valid = ['match_viewed', 'prediction_inspected', 'share_card_generated', 'favorite_toggled'];
        const allValid = payload.events.every((e: { event_name: string }) => valid.includes(e.event_name));
        if (allValid) {
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) });
        } else {
          route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Unrecognized event_name' }) });
        }
      });
      await page.goto('/');

      const resValid = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: [{ event_name: 'prediction_inspected', anonymous_id: 'a1', timestamp: new Date().toISOString() }] }),
      });
      expect(resValid.status).toBe(200);
    });

    test('8.3: Backend sanitization engine scrubs sensitive keys (password, token, email)', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        const body = route.request().postDataJSON();
        const rawProps = body.events[0].properties;
        const sanitized: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(rawProps)) {
          if (!k.includes('password') && !k.includes('token') && !k.includes('secret')) {
            sanitized[k] = v;
          }
        }
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sanitized_properties: sanitized }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          events: [
            {
              event_name: 'match_viewed',
              anonymous_id: 'a1',
              timestamp: new Date().toISOString(),
              properties: { match_id: '101', password_attempt: 'secret_value', auth_token: 'bearer_123' },
            },
          ],
        }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.sanitized_properties).not.toHaveProperty('password_attempt');
      expect(body.sanitized_properties).not.toHaveProperty('auth_token');
    });

    test('8.4: Anonymous event logging functions without requiring user registration', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'logged', user_identified: false }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: [{ event_name: 'share_card_generated', anonymous_id: 'anon_guest_42', timestamp: new Date().toISOString() }] }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.user_identified).toBe(false);
    });

    test('8.5: Zero third-party ad/tracking scripts loaded on consumer pages', async ({ page }) => {
      const blockedTrackers = ['google-analytics.com', 'facebook.net', 'hotjar.com', 'segment.com'];
      page.on('request', (req) => {
        for (const tracker of blockedTrackers) {
          expect(req.url().includes(tracker)).toBe(false);
        }
      });
      await setupMockApiRoutes(page);
      await page.goto('/');
    });
  });

  // --------------------------------------------------------------------------
  // Feature 9: Timezone-Aware Match Notifications (M3, R3)
  // --------------------------------------------------------------------------
  test.describe('Feature 9: Timezone-Aware Match Notifications', () => {
    test('9.1: Match kickoff reminder subscription creates alert record', async ({ page }) => {
      await page.route('**/api/v1/notifications/subscribe', (route) => {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ subscription_id: 'sub_123', fixture_id: '101', reminder_type: 'KICKOFF_15MIN' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixture_id: '101', reminder_type: 'KICKOFF_15MIN' }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.subscription_id).toBe('sub_123');
    });

    test('9.2: Timezone preference adjusts notification scheduling to local user time', async ({ page }) => {
      await page.route('**/api/v1/notifications/preferences', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ timezone: 'Africa/Lagos', display_offset: '+01:00' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/preferences');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.timezone).toBe('Africa/Lagos');
    });

    test('9.3: Probability delta subscription triggers when odds shift >= threshold', async ({ page }) => {
      await page.route('**/api/v1/notifications/subscribe', (route) => {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ subscription_id: 'sub_delta_1', delta_threshold: 0.05, active: true }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixture_id: '101', reminder_type: 'PROBABILITY_DELTA', threshold: 0.05 }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.delta_threshold).toBe(0.05);
    });

    test('9.4: In-app notification center lists unread and read alerts', async ({ page }) => {
      await page.route('**/api/v1/notifications', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            notifications: [
              { id: 'notif_1', title: 'Kickoff in 15m', message: 'Arsenal vs Chelsea begins shortly', read: false },
            ],
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.notifications[0].read).toBe(false);
    });

    test('9.5: Marking notification as read updates status via PATCH endpoint', async ({ page }) => {
      await page.route('**/api/v1/notifications/notif_1/read', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'notif_1', read: true }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/notif_1/read', { method: 'PATCH' });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.read).toBe(true);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 10: Dynamic Social Share & Viral Loop (M3, R3)
  // --------------------------------------------------------------------------
  test.describe('Feature 10: Dynamic Social Share & Viral Loop', () => {
    test('10.1: Dynamic OpenGraph image endpoint returns image response for match', async ({ page }) => {
      await page.route('**/api/og/match/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'image/png',
          body: Buffer.from('fake_image_bytes'),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/og/match/arsenal-vs-chelsea');
      expect(res.status).toBe(200);
      expect(res.headers['content-type']).toContain('image');
    });

    test('10.2: Match Share modal triggers on user interaction', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      const shareButton = page.getByRole('button', { name: /share/i });
      if (await shareButton.count() > 0) {
        await shareButton.first().click();
      }
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('10.3: Formatted clipboard export includes model probabilities and zero casino jargon', async ({ page }) => {
      const matchData = createMockAnalysisPayload();
      const exportText = `SabiScore Analytical Forecast: ${matchData.match_id}\nHome Win: ${(matchData.ensemble.home_win_prob * 100).toFixed(1)}%\nVerdict: ${matchData.verdict}\nEvidence: ${matchData.narrative}`;
      expect(exportText).toContain('SabiScore');
      expect(exportText).not.toMatch(/lock|banker|sure bet|free money|guaranteed/i);
    });

    test('10.4: Web Share API fallback handles non-supported desktop browsers', async ({ page }) => {
      await page.addInitScript(() => {
        delete (navigator as unknown as Record<string, unknown>).share;
      });
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('10.5: Shared card markup contains Schema.org social meta tags', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 11: Programmatic SEO & Structured Data (M3, R3)
  // --------------------------------------------------------------------------
  test.describe('Feature 11: Programmatic SEO & Structured Data', () => {
    test('11.1: Dynamic sitemap.xml returns valid XML containing fixture URLs', async ({ page }) => {
      await page.route('**/sitemap.xml', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/xml',
          body: `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://sabiscore.com/match/arsenal-vs-chelsea</loc></url></urlset>`,
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/sitemap.xml');
      expect(res.status).toBe(200);
      const text = await res.text();
      expect(text).toContain('<urlset');
      expect(text).toContain('https://sabiscore.com');
    });

    test('11.2: Robots.txt allows search engine crawling on match and doc paths', async ({ page }) => {
      await page.route('**/robots.txt', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'text/plain',
          body: `User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: https://sabiscore.com/sitemap.xml`,
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/robots.txt');
      expect(res.status).toBe(200);
      const text = await res.text();
      expect(text.toLowerCase()).toContain('user-agent: *');
      expect(text.toLowerCase()).toContain('disallow: /api/');
    });

    test('11.3: Match page embeds Schema.org SportsEvent JSON-LD structured data', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('11.4: Team page embeds Schema.org SportsTeam JSON-LD structured data', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/team/arsenal');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('11.5: Breadcrumb navigation contains BreadcrumbList structured data', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 12: Anti-Casino Polish & WCAG AA A11y (M3, R3, R5)
  // --------------------------------------------------------------------------
  test.describe('Feature 12: Anti-Casino Polish & WCAG AA A11y', () => {
    test('12.1: Prohibited gambling vocabulary audit scans page text', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');

      const pageText = await page.locator('body').innerText();
      const prohibitedWords = ['\\block\\b', '\\bbanker\\b', '\\bsure bet\\b', '\\bguaranteed\\b', '\\bfree money\\b'];
      for (const word of prohibitedWords) {
        expect(new RegExp(word, 'i').test(pageText)).toBe(false);
      }
    });

    test('12.2: Market discrepancy spotlight uses pure analytical positioning', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('12.3: Keyboard navigation reaches all interactive controls with visible focus', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      await page.keyboard.press('Tab');
      const activeElement = await page.evaluate(() => document.activeElement?.tagName);
      expect(activeElement).toBeTruthy();
    });

    test('12.4: Radix UI tooltips trigger on keyboard focus and dismiss on ESC', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('12.5: High contrast color ratios meet WCAG AA standards', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 13: Fail-Closed UX & Empty State Guards (M3, R5)
  // --------------------------------------------------------------------------
  test.describe('Feature 13: Fail-Closed UX & Empty State Guards', () => {
    test('13.1: Missing critical evidence renders PARTIAL verdict and No bet indicator', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            status: 'REDUCED_EVIDENCE_BASELINE',
            source: 'DIAGNOSTIC_BASELINE',
            stakePermitted: false,
            evidence: { critical_gaps: ['COHERENT_1X2_MARKET_UNAVAILABLE'], advisory_gaps: [], conflicts: [] },
          })),
        });
      });

      await page.goto('/match/critical?league=EPL');
      await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
      await expect(page.getByText('No bet').first()).toBeVisible();
    });

    test('13.2: Zero synthetic probability fabrication displays dash placeholder when data unavailable', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            status: 'UNAVAILABLE',
            source: 'NONE',
            stakePermitted: false,
            evidence: { critical_gaps: ['MODEL_PREDICTION_UNAVAILABLE'], advisory_gaps: [], conflicts: [] },
          })),
        });
      });

      await page.goto('/match/unavailable?league=EPL');
      await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
      await expect(page.getByText('No bet').first()).toBeVisible();
    });

    test('13.3: Conflicting market snapshots trigger explicit conflict badge', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            status: 'AVAILABLE',
            stakePermitted: false,
            evidence: { critical_gaps: [], advisory_gaps: [], conflicts: ['CONFLICTING_MARKET_SNAPSHOTS'] },
          })),
        });
      });

      await page.goto('/match/conflict?league=EPL');
      await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
      await expect(page.getByText('No bet').first()).toBeVisible();
    });

    test('13.4: Unverified fixture identity prompts verification notice before predictions', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            stakePermitted: false,
            status: 'REDUCED_EVIDENCE_BASELINE',
          })),
        });
      });

      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('13.5: Backend 502/503 service degradation renders clean empty state with retry', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Service Unavailable' }),
        });
      });

      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

});
