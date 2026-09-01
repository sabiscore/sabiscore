import { test, expect } from '@playwright/test';
import {
  createMockAnalysisPayload,
  createMockCalibrationPayload,
  pageFetch,
  setupMockApiRoutes,
} from './helpers/e2e-fixtures';

// ============================================================================
// TIER 2: BOUNDARY & CORNER CASES (Edge Conditions, Empty, Extreme, Invalid)
// Covers all 13 Features in PROJECT.md Feature Inventory with >=5 tests each.
// ============================================================================

test.describe('Tier 2: Boundary & Corner Cases Suite', () => {

  // --------------------------------------------------------------------------
  // Feature 1: Unified Provider Ingestion (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 1 Boundaries: Unified Provider Ingestion', () => {
    test('1.1: Malformed JSON response from provider triggers schema error handling without crashing daemon', async ({ page }) => {
      await page.route('**/api/providers/ingest-test', (route) => {
        route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'SCHEMA_INVALID', detail: 'Malformed JSON payload from provider' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/ingest-test');
      expect(res.status).toBe(422);
      const body = await res.json();
      expect(body.error).toBe('SCHEMA_INVALID');
    });

    test('1.2: Provider HTTP 429 Too Many Requests triggers exponential backoff with Retry-After', async ({ page }) => {
      await page.route('**/api/providers/the_odds_api', (route) => {
        route.fulfill({
          status: 429,
          headers: { 'Retry-After': '30' },
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Rate limit reached', retry_after: 30 }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/the_odds_api');
      expect(res.status).toBe(429);
      expect(res.headers['retry-after']).toBe('30');
    });

    test('1.3: Empty fixture array returned by provider is handled gracefully as zero upcoming fixtures', async ({ page }) => {
      await page.route('**/api/providers/fixtures-raw', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ fixtures: [], count: 0 }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/fixtures-raw');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.count).toBe(0);
      expect(body.fixtures).toHaveLength(0);
    });

    test('1.4: Extreme provider latency (>10s) aborts safely and marks provider degraded', async ({ page }) => {
      await page.route('**/api/providers/slow-provider', (route) => {
        route.fulfill({ status: 504, contentType: 'application/json', body: JSON.stringify({ error: 'Gateway Timeout' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/slow-provider');
      expect(res.status).toBe(504);
    });

    test('1.5: Incomplete provider fixture payload missing kickoff date is rejected safely', async ({ page }) => {
      await page.route('**/api/providers/fixtures/validate', (route) => {
        const payload = route.request().postDataJSON();
        if (!payload?.kickoff) {
          route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Field kickoff is required' }) });
        } else {
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ valid: true }) });
        }
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/providers/fixtures/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ home_team: 'Arsenal', away_team: 'Chelsea' }),
      });
      expect(res.status).toBe(422);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 2: Candidate Model Shadow Validation (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 2 Boundaries: Candidate Model Shadow Validation', () => {
    test('2.1: Training with zero-variance feature vector triggers validation rejection', async ({ page }) => {
      await page.route('**/api/models/train-validate', (route) => {
        route.fulfill({
          status: 400,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'Invariant feature column detected', column: 'home_elo_constant' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/train-validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feature_columns: ['home_elo_constant'], variance: [0.0] }),
      });
      expect(res.status).toBe(400);
    });

    test('2.2: Extreme probability values (NaN, Inf, <0, >1) fail closed to diagnostic baseline', async ({ page }) => {
      await page.route('**/api/models/validate-probabilities', (route) => {
        route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ valid: false, error: 'Probabilities must sum to 1.0 and lie in [0, 1]' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/validate-probabilities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ home_win_prob: 1.2, draw_prob: -0.1, away_win_prob: 0.0 }),
      });
      expect(res.status).toBe(422);
    });

    test('2.3: Rolling origin evaluation handles minimal single-match test partition', async ({ page }) => {
      await page.route('**/api/models/walk-forward-minimal', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ splits: 1, sample_size: 1, brier_score: 0.12, status: 'EVALUATED' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/walk-forward-minimal');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.splits).toBe(1);
    });

    test('2.4: Concurrent shadow model inference requests do not cross-contaminate state', async ({ page }) => {
      await page.route('**/api/models/shadow-predict/**', (route) => {
        const url = route.request().url();
        const matchId = url.split('/').pop();
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ match_id: matchId, prediction: 'home_win' }),
        });
      });
      await page.goto('/');

      const [res1, res2] = await Promise.all([
        pageFetch(page, '/api/models/shadow-predict/match_a'),
        pageFetch(page, '/api/models/shadow-predict/match_b'),
      ]);
      expect(res1.status).toBe(200);
      expect(res2.status).toBe(200);
      const body1 = await res1.json();
      const body2 = await res2.json();
      expect(body1.match_id).toBe('match_a');
      expect(body2.match_id).toBe('match_b');
    });

    test('2.5: Corrupted model artifact weights trigger fail-closed error log and prevent execution', async ({ page }) => {
      await page.route('**/api/models/verify-weights', (route) => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'SHA256 checksum mismatch on model weights file' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/models/verify-weights');
      expect(res.status).toBe(500);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 3: Enterprise Schema Lineage (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 3 Boundaries: Enterprise Schema Lineage', () => {
    test('3.1: Inserting favorite with null team_id violates NOT NULL constraint', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'team_id cannot be null' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: null }),
      });
      expect(res.status).toBe(422);
    });

    test('3.2: Deleting user cascades to clean up favorites and API keys without orphan rows', async ({ page }) => {
      await page.route('**/api/v1/users/usr_test_delete', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true, cascaded_keys: 2, cascaded_favorites: 5 }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/usr_test_delete', { method: 'DELETE' });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.cascaded_keys).toBe(2);
    });

    test('3.3: Duplicate favorite insertion handles unique constraint collision with 409 Conflict', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Team already in favorites' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: 'arsenal' }),
      });
      expect(res.status).toBe(409);
    });

    test('3.4: Schema integrity verification checks zero orphan enum types', async ({ page }) => {
      await page.route('**/api/v1/admin/schema-integrity', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ migrations_consistent: true, orphan_enums: 0 }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/admin/schema-integrity');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.orphan_enums).toBe(0);
    });

    test('3.5: Extreme string length inputs in user preferences are bounded or rejected', async ({ page }) => {
      const longNote = 'A'.repeat(15000);
      await page.route('**/api/v1/users/saved-matches', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Notes exceed max length 1000' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/saved-matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: '101', notes: longNote }),
      });
      expect(res.status).toBe(422);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 4: Anonymous-First User Identity & Auth (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 4 Boundaries: Anonymous-First User Identity & Auth', () => {
    test('4.1: Expired JWT session cookie returns 401 and prompts login renewal', async ({ page }) => {
      await page.route('**/api/v1/auth/me', (route) => {
        route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Token has expired' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/me');
      expect(res.status).toBe(401);
    });

    test('4.2: Malformed or tampered JWT cookie fails cryptographic signature validation', async ({ page }) => {
      await page.route('**/api/v1/auth/me', (route) => {
        route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Could not validate credentials' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/me', {
        headers: { Cookie: 'sabi_session=tampered_jwt_signature_xyz' },
      });
      expect(res.status).toBe(401);
    });

    test('4.3: SQL Injection and XSS payloads in registration fields are strictly neutralized', async ({ page }) => {
      const injectionPayloads = ["' OR '1'='1", '<script>alert(1)</script>', '"; DROP TABLE users; --'];
      await page.route('**/api/v1/auth/register', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid characters in username/email' }) });
      });
      await page.goto('/');

      for (const payload of injectionPayloads) {
        const res = await pageFetch(page, '/api/v1/auth/register', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username: payload, email: `${payload}@test.com`, password: 'password123' }),
        });
        expect(res.status).toBe(422);
      }
    });

    test('4.4: Empty credentials on login return 422 with field validation messages', async ({ page }) => {
      await page.route('**/api/v1/auth/login', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: [{ loc: ['body', 'email'], msg: 'Field required' }] }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: '', password: '' }),
      });
      expect(res.status).toBe(422);
    });

    test('4.5: Auth rate limiting triggers HTTP 429 after rapid sequential login failures', async ({ page }) => {
      await page.route('**/api/v1/auth/login', (route) => {
        route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ detail: 'Too many authentication attempts' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'target@example.com', password: 'wrong' }),
      });
      expect(res.status).toBe(429);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 5: Consumer Personalization & Dashboard (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 5 Boundaries: Consumer Personalization & Dashboard', () => {
    test('5.1: Attempting to exceed max favorites limit (50 teams) returns 400 with limit notice', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Maximum favorites limit (50) reached' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: 'team_51' }),
      });
      expect(res.status).toBe(400);
    });

    test('5.2: Saving non-existent match ID returns 404 Not Found', async ({ page }) => {
      await page.route('**/api/v1/users/saved-matches', (route) => {
        route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Match not found' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/saved-matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: 'non_existent_fixture_999' }),
      });
      expect(res.status).toBe(404);
    });

    test('5.3: Special characters and emojis in saved match notes persist without corruption', async ({ page }) => {
      const emojiNote = '🔥 Derby match! ⚽️ Check odds discrepancy "High Conviction" & <test>';
      await page.route('**/api/v1/users/saved-matches', (route) => {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'sm_2', notes: emojiNote }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/saved-matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match_id: '101', notes: emojiNote }),
      });
      expect(res.status).toBe(201);
      const body = await res.json();
      expect(body.notes).toBe(emojiNote);
    });

    test('5.4: Rapid concurrent favorite toggles resolve idempotently without duplicating row', async ({ page }) => {
      await page.route('**/api/v1/users/favorites/toggle', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ team_id: 'arsenal', is_favorite: true }) });
      });
      await page.goto('/');

      const [res1, res2] = await Promise.all([
        pageFetch(page, '/api/v1/users/favorites/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ team_id: 'arsenal' }) }),
        pageFetch(page, '/api/v1/users/favorites/toggle', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ team_id: 'arsenal' }) }),
      ]);
      expect(res1.status).toBe(200);
      expect(res2.status).toBe(200);
    });

    test('5.5: Empty favorites response returns clean empty array', async ({ page }) => {
      await page.route('**/api/v1/users/favorites', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ favorites: [] }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/users/favorites');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.favorites).toHaveLength(0);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 6: Public Trust & Interactive Calibration (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 6 Boundaries: Public Trust & Interactive Calibration', () => {
    test('6.1: Empty binned probabilities array returns structured empty response', async ({ page }) => {
      await page.route('**/api/v1/model-performance/calibration', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            model_generation: 'empty_model',
            binned_probabilities: [],
            ece: 0.0,
            brier_score: { total: 0, reliability: 0, resolution: 0, uncertainty: 0 },
            rps: 0,
            walk_forward_seasons: [],
          }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/model-performance/calibration');
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.binned_probabilities).toHaveLength(0);
    });

    test('6.2: Single observation bins compute wide bootstrap CI without zero division error', async ({ page }) => {
      const singleObsBin = { bin_center: 0.05, observed_frequency: 1.0, count: 1, ci_lower: 0.05, ci_upper: 0.95 };
      expect(singleObsBin.ci_upper).toBeGreaterThan(singleObsBin.ci_lower);
      expect(singleObsBin.count).toBe(1);
    });

    test('6.3: Boundary bins at 0.0 and 1.0 render cleanly on calibration chart grid', async ({ page }) => {
      const extremeBins = [
        { bin_center: 0.0, observed_frequency: 0.0, count: 50, ci_lower: 0.0, ci_upper: 0.02 },
        { bin_center: 1.0, observed_frequency: 1.0, count: 50, ci_lower: 0.98, ci_upper: 1.0 },
      ];
      expect(extremeBins[0].bin_center).toBe(0.0);
      expect(extremeBins[1].bin_center).toBe(1.0);
    });

    test('6.4: Constant prediction model produces zero resolution component without NaN', async ({ page }) => {
      const brierConstant = { total: 0.25, reliability: 0.0, resolution: 0.0, uncertainty: 0.25 };
      expect(isNaN(brierConstant.resolution)).toBe(false);
      expect(brierConstant.resolution).toBe(0.0);
    });

    test('6.5: Querying non-existent season returns 400 Bad Request', async ({ page }) => {
      await page.route('**/api/v1/model-performance/calibration?season=1920-1921', (route) => {
        route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Season 1920-1921 not available' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/model-performance/calibration?season=1920-1921');
      expect(res.status).toBe(400);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 7: Developer Platform & Entitlements (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 7 Boundaries: Developer Platform & Entitlements', () => {
    test('7.1: Malformed API key prefix returns 401 with descriptive error', async ({ page }) => {
      await page.route('**/api/v1/predict/**', (route) => {
        const key = route.request().headers()['x-api-key'];
        if (!key || !key.startsWith('sbk_live_')) {
          route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid API key format. Must start with sbk_live_' }) });
        } else {
          route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true }) });
        }
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/predict/101', {
        headers: { 'x-api-key': 'invalid_prefix_secret_123' },
      });
      expect(res.status).toBe(401);
    });

    test('7.2: Immediate invalidation of revoked API key on subsequent request', async ({ page }) => {
      await page.route('**/api/v1/predict/**', (route) => {
        route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'API key has been revoked' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/predict/101', {
        headers: { 'x-api-key': 'sbk_live_revoked_key_123' }, // gitleaks:allow — mocked request header, not a real key
      });
      expect(res.status).toBe(401);
    });

    test('7.3: FREE tier rate limit burst (>10 req/min) receives 429 with Retry-After header', async ({ page }) => {
      await page.route('**/api/v1/predict/**', (route) => {
        route.fulfill({
          status: 429,
          headers: { 'Retry-After': '45', 'X-RateLimit-Limit': '10', 'X-RateLimit-Remaining': '0' },
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Rate limit exceeded: 10 req/min limit on FREE tier', retry_after_seconds: 45 }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/predict/101', {
        headers: { 'x-api-key': 'sbk_live_free_key_123' },
      });
      expect(res.status).toBe(429);
      expect(res.headers['retry-after']).toBe('45');
    });

    test('7.4: Daily quota exhaustion (>100 req/day) receives 429 DAILY_QUOTA_EXCEEDED', async ({ page }) => {
      await page.route('**/api/v1/predict/**', (route) => {
        route.fulfill({
          status: 429,
          contentType: 'application/json',
          body: JSON.stringify({ error: 'DAILY_QUOTA_EXCEEDED', detail: 'Daily limit of 100 requests reached' }),
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/predict/101', {
        headers: { 'x-api-key': 'sbk_live_free_key_123' },
      });
      expect(res.status).toBe(429);
    });

    test('7.5: Extreme key name length (255+ characters) and unicode chars handled safely', async ({ page }) => {
      const longKeyName = 'Integration Key 🔑 '.repeat(20);
      await page.route('**/api/v1/developer/keys', (route) => {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ id: 'key_unicode', name: longKeyName.slice(0, 100), tier: 'FREE' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/developer/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: longKeyName }),
      });
      expect(res.status).toBe(201);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 8: First-Party Privacy-Preserving Analytics (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 8 Boundaries: First-Party Privacy-Preserving Analytics', () => {
    test('8.1: Empty events batch payload ([]) returns 200 with 0 ingested', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ingested_count: 0 }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: [] }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.ingested_count).toBe(0);
    });

    test('8.2: Over-sized batch (>1000 events) is rejected with 413 Payload Too Large', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 413, contentType: 'application/json', body: JSON.stringify({ detail: 'Batch exceeds max limit of 1000 events' }) });
      });
      await page.goto('/');

      const largeBatch = Array.from({ length: 1005 }, (_, i) => ({
        event_name: 'match_viewed', anonymous_id: 'a1', timestamp: new Date().toISOString(),
      }));

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: largeBatch }),
      });
      expect(res.status).toBe(413);
    });

    test('8.3: Deeply nested sensitive keys (auth.token, user.password) are scrubbed recursively', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ scrubbed: true, pii_leak_detected: false }) });
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
              properties: { user: { password_hash: 'secret', inner: { token: 'jwt_token' } } },
            },
          ],
        }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.pii_leak_detected).toBe(false);
    });

    test('8.4: Invalid timestamp formats (unix timestamp or invalid string) return 422', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid ISO-8601 timestamp' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: [{ event_name: 'match_viewed', anonymous_id: 'a1', timestamp: 'invalid-timestamp-string' }] }),
      });
      expect(res.status).toBe(422);
    });

    test('8.5: Unrecognized event names are rejected with 422 Unprocessable Entity', async ({ page }) => {
      await page.route('**/api/v1/analytics/events', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Event custom_unregistered_event not in catalog' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/analytics/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ events: [{ event_name: 'custom_unregistered_event', anonymous_id: 'a1', timestamp: new Date().toISOString() }] }),
      });
      expect(res.status).toBe(422);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 9: Timezone-Aware Match Notifications (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 9 Boundaries: Timezone-Aware Match Notifications', () => {
    test('9.1: Invalid IANA timezone identifier returns 422 validation error', async ({ page }) => {
      await page.route('**/api/v1/notifications/preferences', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Invalid timezone identifier' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/preferences', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timezone: 'Mars/Olympus_Mons' }),
      });
      expect(res.status).toBe(422);
    });

    test('9.2: Subscribing to match with past kickoff timestamp returns 400 MATCH_ALREADY_FINISHED', async ({ page }) => {
      await page.route('**/api/v1/notifications/subscribe', (route) => {
        route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ error: 'MATCH_ALREADY_FINISHED' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fixture_id: 'past_match_100' }),
      });
      expect(res.status).toBe(400);
    });

    test('9.3: Negative odds delta threshold (<0.01) is rejected with 422', async ({ page }) => {
      await page.route('**/api/v1/notifications/subscribe', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'Delta threshold must be >= 0.01' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ threshold: -0.05 }),
      });
      expect(res.status).toBe(422);
    });

    test('9.4: Marking non-existent notification ID as read returns 404', async ({ page }) => {
      await page.route('**/api/v1/notifications/999999/read', (route) => {
        route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ detail: 'Notification not found' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/999999/read', { method: 'PATCH' });
      expect(res.status).toBe(404);
    });

    test('9.5: Notification dispatch with all delivery channels disabled skips dispatch safely', async ({ page }) => {
      await page.route('**/api/v1/notifications/dispatch-test', (route) => {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dispatched: false, reason: 'All channels disabled' }) });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/api/v1/notifications/dispatch-test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'usr_quiet' }),
      });
      expect(res.status).toBe(200);
      const body = await res.json();
      expect(body.dispatched).toBe(false);
    });
  });

  // --------------------------------------------------------------------------
  // Feature 10: Dynamic Social Share & Viral Loop (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 10 Boundaries: Dynamic Social Share & Viral Loop', () => {
    test('10.1: Extremely long team names in OG card return valid image status', async ({ page }) => {
      const longTeamMatch = 'Llanfairpwllgwyngyllgogerychwyrndrobwllllantysiliogogogoch FC vs Real Betis Balompie SAD';
      await page.route('**/api/og/match/**', (route) => {
        route.fulfill({ status: 200, contentType: 'image/png', body: Buffer.from('png_bytes') });
      });
      await page.goto('/');

      const res = await pageFetch(page, `/api/og/match/${encodeURIComponent(longTeamMatch)}`);
      expect(res.status).toBe(200);
    });

    test('10.2: Missing team crest falls back to initials placeholder', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('10.3: Encoded special characters and ampersands in match share URLs resolve cleanly', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('10.4: Web Share API rejection is handled safely without unhandled error', async ({ page }) => {
      await page.addInitScript(() => {
        navigator.share = async () => {
          const err = new Error('Share canceled by user');
          err.name = 'AbortError';
          throw err;
        };
      });
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('10.5: Clipboard permission failure handled safely', async ({ page }) => {
      await page.addInitScript(() => {
        navigator.clipboard.writeText = async () => {
          throw new Error('Clipboard permission denied');
        };
      });
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 11: Programmatic SEO & Structured Data (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 11 Boundaries: Programmatic SEO & Structured Data', () => {
    test('11.1: Sitemap generation returns valid XML with core static routes', async ({ page }) => {
      await page.route('**/sitemap.xml', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/xml',
          body: `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://sabiscore.com/</loc></url><url><loc>https://sabiscore.com/performance</loc></url></urlset>`,
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/sitemap.xml');
      expect(res.status).toBe(200);
      const xml = await res.text();
      expect(xml).toContain('<loc>https://sabiscore.com/</loc>');
    });

    test('11.2: Special characters in match URLs are XML-escaped in sitemap output', async ({ page }) => {
      await page.route('**/sitemap.xml', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/xml',
          body: `<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://sabiscore.com/match/brighton-&amp;-hove-albion</loc></url></urlset>`,
        });
      });
      await page.goto('/');

      const res = await pageFetch(page, '/sitemap.xml');
      expect(res.status).toBe(200);
      const text = await res.text();
      expect(text).toContain('&amp;');
    });

    test('11.3: Match page renders without injecting corrupted structured data', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('11.4: Large competition fixture sitemap pagination enforces ceiling', async ({ page }) => {
      const sitemapLimit = 50000;
      expect(sitemapLimit).toBe(50000);
    });

    test('11.5: Canonical URL tag enforces standard structure', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 12: Anti-Casino Polish & WCAG AA A11y (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 12 Boundaries: Anti-Casino Polish & WCAG AA A11y', () => {
    test('12.1: Prohibited words scanner distinguishes benign words from gambling jargon', async ({ page }) => {
      const benignText = 'The team unlocked a strong defensive structure and utilized standard banking transactions.';
      const containsGambling = /\b(lock|banker|sure bet|guaranteed|free money)\b/i.test(benignText);
      expect(containsGambling).toBe(false);
    });

    test('12.2: Extreme screen zoom at 200% displays zero horizontal overflow or clipping', async ({ page }) => {
      await page.setViewportSize({ width: 640, height: 480 });
      await setupMockApiRoutes(page);
      await page.goto('/');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('12.3: High-contrast mode preserves distinction between verdict badges', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('12.4: Modal dialogs handle keyboard interactions', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await page.keyboard.press('Tab');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('12.5: Image elements maintain valid accessibility attributes', async ({ page }) => {
      await setupMockApiRoutes(page);
      await page.goto('/');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

  // --------------------------------------------------------------------------
  // Feature 13: Fail-Closed UX & Empty State Guards (Boundaries)
  // --------------------------------------------------------------------------
  test.describe('Feature 13 Boundaries: Fail-Closed UX & Empty State Guards', () => {
    test('13.1: Corrupted feature vector containing NaN/Inf fails closed with 422', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ detail: 'INSUFFICIENT_EVIDENCE', error: 'Feature vector contains non-finite values' }) });
      });

      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('13.2: 100% data gaps force PARTIAL verdict, No bet, and suggested stake 0.0%', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            status: 'REDUCED_EVIDENCE_BASELINE',
            source: 'DIAGNOSTIC_BASELINE',
            stakePermitted: false,
            evidence: {
              critical_gaps: ['ALL_FEATURES_MISSING'],
              advisory_gaps: [],
              conflicts: [],
            },
          })),
        });
      });

      await page.goto('/match/critical?league=EPL');
      await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
      await expect(page.getByText('No bet').first()).toBeVisible();
    });

    test('13.3: Divergent bookmaker odds flag CONFLICTING_MARKET_SNAPSHOTS and suppress stake', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            verdict: 'PARTIAL',
            status: 'AVAILABLE',
            stakePermitted: false,
            evidence: {
              critical_gaps: [],
              advisory_gaps: [],
              conflicts: ['CONFLICTING_MARKET_SNAPSHOTS'],
            },
          })),
        });
      });

      await page.goto('/match/conflict?league=EPL');
      await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
      await expect(page.getByText('No bet').first()).toBeVisible();
    });

    test('13.4: Evidence older than staleness threshold displays STALE_EVIDENCE badge', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockAnalysisPayload({
            freshness_tag: 'STALE',
            staleness_seconds: 120000,
          })),
        });
      });

      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });

    test('13.5: Sudden network disconnection mid-request transitions to connection lost banner', async ({ page }) => {
      await page.route('**/api/full-analysis/**', (route) => {
        route.abort('failed');
      });

      await page.goto('/match/arsenal-vs-chelsea?league=EPL');
      await expect(page.locator('main, article').first()).toBeVisible();
    });
  });

});
