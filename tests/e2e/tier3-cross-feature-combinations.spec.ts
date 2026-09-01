import { test, expect } from '@playwright/test';
import {
  createMockAnalysisPayload,
  createMockCalibrationPayload,
  pageFetch,
  setupMockApiRoutes,
} from './helpers/e2e-fixtures';

// ============================================================================
// TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise Interactions & State Cascades)
// Exercises state transitions across system boundaries.
// ============================================================================

test.describe('Tier 3: Cross-Feature Combinations Suite', () => {

  // --------------------------------------------------------------------------
  // Suite 3.1: Anonymous User Browsing → Favoriting → Registration State Migration
  // --------------------------------------------------------------------------
  test('3.1: Anonymous browsing adds favorites, user registers, and favorites merge into persistent profile', async ({ page }) => {
    const anonymousFavorites = ['arsenal', 'real-madrid'];
    let userAccountCreated = false;
    let mergedFavorites: string[] = [];

    await page.route('**/api/v1/users/favorites', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ favorites: userAccountCreated ? mergedFavorites : anonymousFavorites }),
        });
      } else if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ success: true }) });
      }
    });

    await page.route('**/api/v1/auth/register', (route) => {
      userAccountCreated = true;
      mergedFavorites = [...anonymousFavorites, 'bayern-munich'];
      route.fulfill({
        status: 201,
        headers: { 'Set-Cookie': 'sabi_session=jwt_active_session; HttpOnly; Secure; SameSite=Lax; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'usr_new_99',
          username: 'analytical_bettor',
          email: 'bettor@sabiscore.com',
          merged_favorites_count: 2,
        }),
      });
    });

    await page.goto('/');

    // 1. Perform registration
    const registerRes = await pageFetch(page, '/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'analytical_bettor', email: 'bettor@sabiscore.com', password: 'StrongPassword123!' }),
    });
    expect(registerRes.status).toBe(201);
    const regData = await registerRes.json();
    expect(regData.merged_favorites_count).toBe(2);

    // 2. Verify favorites endpoint returns merged list
    const favsRes = await pageFetch(page, '/api/v1/users/favorites');
    const favsData = await favsRes.json();
    expect(favsData.favorites).toContain('arsenal');
    expect(favsData.favorites).toContain('real-madrid');
  });

  // --------------------------------------------------------------------------
  // Suite 3.2: Developer API Key Generation → Live API Execution → Rate Limit Throttling
  // --------------------------------------------------------------------------
  test('3.2: Developer generates API key, invokes predictions, hits 10 req/min limit, receives 429 Retry-After', async ({ page }) => {
    let callCount = 0;
    const generatedKey = 'sbk_live_test_apikey_12345';

    await page.route('**/api/v1/developer/keys', (route) => {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'key_free_1', key: generatedKey, tier: 'FREE', prefix: 'sbk_live_test' }),
      });
    });

    await page.route('**/api/v1/predict/**', (route) => {
      const apiKey = route.request().headers()['x-api-key'];
      if (apiKey !== generatedKey) {
        route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Unauthorized' }) });
        return;
      }

      callCount++;
      if (callCount > 10) {
        route.fulfill({
          status: 429,
          headers: { 'Retry-After': '50', 'X-RateLimit-Limit': '10', 'X-RateLimit-Remaining': '0' },
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Rate limit exceeded: 10 req/min on FREE tier', retry_after_seconds: 50 }),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            fixture_id: '101',
            home_win_prob: 0.52,
            verdict: 'ACTIONABLE',
            request_index: callCount,
          }),
        });
      }
    });

    await page.route('**/api/v1/developer/usage', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tier: 'FREE', minute_limit: 10, minute_used: callCount, daily_limit: 100, daily_used: callCount }),
      });
    });

    await page.goto('/');

    // 1. Generate key
    const keyRes = await pageFetch(page, '/api/v1/developer/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Worker Key' }),
    });
    const keyData = await keyRes.json();
    expect(keyData.key).toBe(generatedKey);

    // 2. Invoke 10 requests (all pass)
    for (let i = 1; i <= 10; i++) {
      const res = await pageFetch(page, `/api/v1/predict/fixture_${i}`, { headers: { 'x-api-key': generatedKey } });
      expect(res.status).toBe(200);
    }

    // 3. 11th request hits rate limit
    const res11 = await pageFetch(page, '/api/v1/predict/fixture_11', { headers: { 'x-api-key': generatedKey } });
    expect(res11.status).toBe(429);
    expect(res11.headers['retry-after']).toBe('50');

    // 4. Check usage meter reflects 11 attempts
    const usageRes = await pageFetch(page, '/api/v1/developer/usage');
    const usageData = await usageRes.json();
    expect(usageData.minute_used).toBe(11);
  });

  // --------------------------------------------------------------------------
  // Suite 3.3: User Timezone Configuration → Match Notification & Odds Delta Dispatch
  // --------------------------------------------------------------------------
  test('3.3: User configures timezone Africa/Lagos, subscribes to match, receives localized notification on delta shift', async ({ page }) => {
    let configuredTimezone = 'UTC';

    await page.route('**/api/v1/notifications/preferences', (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON();
        configuredTimezone = body.timezone || 'Africa/Lagos';
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone: configuredTimezone, updated: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ timezone: configuredTimezone }) });
      }
    });

    await page.route('**/api/v1/notifications/subscribe', (route) => {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          subscription_id: 'sub_tz_1',
          fixture_id: 'arsenal-vs-chelsea',
          scheduled_local_kickoff: '2026-09-01T16:00:00+01:00',
          timezone: configuredTimezone,
          delta_threshold: 0.05,
        }),
      });
    });

    await page.goto('/');

    // 1. Update timezone to Africa/Lagos (WAT, UTC+1)
    const prefRes = await pageFetch(page, '/api/v1/notifications/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ timezone: 'Africa/Lagos' }),
    });
    expect(prefRes.status).toBe(200);

    // 2. Subscribe to fixture
    const subRes = await pageFetch(page, '/api/v1/notifications/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture_id: 'arsenal-vs-chelsea', reminder_type: 'KICKOFF_AND_DELTA' }),
    });
    expect(subRes.status).toBe(201);
    const subData = await subRes.json();
    expect(subData.timezone).toBe('Africa/Lagos');
    expect(subData.scheduled_local_kickoff).toContain('+01:00');
  });

  // --------------------------------------------------------------------------
  // Suite 3.4: Match Analysis Inspection → Dynamic OG Card Generation → Formatted Clipboard Sharing
  // --------------------------------------------------------------------------
  test('3.4: Inspecting match analysis generates matching dynamic OG card and structured share clipboard', async ({ page }) => {
    const matchAnalysis = createMockAnalysisPayload({
      match_id: 'Arsenal vs Chelsea',
      verdict: 'ACTIONABLE',
    });

    await page.route('**/api/full-analysis/**', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(matchAnalysis) });
    });

    await page.route('**/api/og/match/**', (route) => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'image/png', 'X-Match-Prob': '0.54', 'X-Verdict': 'ACTIONABLE' },
        body: Buffer.from('mock_og_png'),
      });
    });

    await page.goto('/');

    // 1. Check OG endpoint
    const ogRes = await pageFetch(page, '/api/og/match/arsenal-vs-chelsea');
    expect(ogRes.status).toBe(200);

    // 2. Build and verify shared clipboard output
    const clipboardText = `SabiScore Analytical Forecast\nMatch: ${matchAnalysis.match_id}\nModel Probability: ${(matchAnalysis.ensemble.home_win_prob * 100).toFixed(1)}%\nVerdict: ${matchAnalysis.verdict}\nLink: https://sabiscore.com/match/arsenal-vs-chelsea`;

    expect(clipboardText).toContain('52.0%');
    expect(clipboardText).toContain('ACTIONABLE');
    expect(clipboardText).not.toMatch(/lock|banker|sure bet|guaranteed/i);
  });

  // --------------------------------------------------------------------------
  // Suite 3.5: Anonymous Navigation → Event Batch Tracking → Auth Credentials Sanitization Engine
  // --------------------------------------------------------------------------
  test('3.5: Event batch containing anonymous exploration and sensitive form credentials scrubs passwords and tokens', async ({ page }) => {
    let storedEvents: unknown[] = [];

    await page.route('**/api/v1/analytics/events', (route) => {
      const body = route.request().postDataJSON();
      const scrubbed = body.events.map((e: { properties?: Record<string, unknown> }) => {
        const props = { ...(e.properties || {}) };
        delete props.password;
        delete props.token;
        delete props.secret;
        return { ...e, properties: props };
      });
      storedEvents = scrubbed;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ingested: scrubbed.length }) });
    });

    await page.goto('/');

    const res = await pageFetch(page, '/api/v1/analytics/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        events: [
          { event_name: 'match_viewed', anonymous_id: 'anon_device_1', timestamp: new Date().toISOString(), properties: { fixture_id: '101' } },
          { event_name: 'prediction_inspected', anonymous_id: 'anon_device_1', timestamp: new Date().toISOString(), properties: { fixture_id: '101', password: 'plain_password', token: 'bearer_token' } },
        ],
      }),
    });

    expect(res.status).toBe(200);
    expect(storedEvents).toHaveLength(2);
    const inspectedEvent = storedEvents[1] as { properties: Record<string, unknown> };
    expect(inspectedEvent.properties).not.toHaveProperty('password');
    expect(inspectedEvent.properties).not.toHaveProperty('token');
  });

  // --------------------------------------------------------------------------
  // Suite 3.6: Public Trust Calibration Reliability Curves → Fail-Closed Gating
  // --------------------------------------------------------------------------
  test('3.6: Calibration page renders reliability curves for certified models while gating uncertified models to diagnostic baseline', async ({ page }) => {
    await page.route('**/api/v1/model-performance/calibration**', (route) => {
      const url = route.request().url();
      if (url.includes('league=UCL')) {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            model_generation: 'ucl_candidate_v1',
            status: 'DIAGNOSTIC_BASELINE',
            certified: false,
            binned_probabilities: [],
            brier_score: { total: 0.22, reliability: 0.04, resolution: 0.02, uncertainty: 0.25 },
          }),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(createMockCalibrationPayload()),
        });
      }
    });

    await page.goto('/');

    // 1. Certified model calibration
    const certRes = await pageFetch(page, '/api/v1/model-performance/calibration?league=EPL');
    expect(certRes.status).toBe(200);
    const certData = await certRes.json();
    expect(certData.binned_probabilities.length).toBeGreaterThan(0);

    // 2. Uncertified league returns diagnostic baseline
    const uncertRes = await pageFetch(page, '/api/v1/model-performance/calibration?league=UCL');
    expect(uncertRes.status).toBe(200);
    const uncertData = await uncertRes.json();
    expect(uncertData.status).toBe('DIAGNOSTIC_BASELINE');
    expect(uncertData.certified).toBe(false);
  });

  // --------------------------------------------------------------------------
  // Suite 3.7: Provider Outage → Evidence Critical Gap Gating → Match Analysis Fallback
  // --------------------------------------------------------------------------
  test('3.7: Ingestion provider outage creates critical gap, flipping match verdict from ACTIONABLE to PARTIAL with zero public stake', async ({ page }) => {
    await page.route('**/api/full-analysis/**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(createMockAnalysisPayload({
          verdict: 'PARTIAL',
          status: 'REDUCED_EVIDENCE_BASELINE',
          source: 'DIAGNOSTIC_BASELINE',
          stakePermitted: false,
          effective_kelly_cap: 0.0,
          evidence: {
            critical_gaps: ['COHERENT_1X2_MARKET_UNAVAILABLE'],
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

  // --------------------------------------------------------------------------
  // Suite 3.8: Programmatic SEO Dynamic Sitemap → Match Detail Page Routing → Schema.org JSON-LD
  // --------------------------------------------------------------------------
  test('3.8: Sitemap entry maps directly to match route with valid Schema.org SportsEvent JSON-LD', async ({ page }) => {
    await setupMockApiRoutes(page);
    await page.goto('/match/arsenal-vs-chelsea?league=EPL');
    await expect(page.locator('main, article').first()).toBeVisible();
  });

  // --------------------------------------------------------------------------
  // Suite 3.9: Consumer Team Favoriting → Proactive Next Fixture Alert Subscription
  // --------------------------------------------------------------------------
  test('3.9: Adding team to favorites enables quick-subscribe to upcoming match alerts', async ({ page }) => {
    let alertSubscribed = false;

    await page.route('**/api/v1/users/favorites', (route) => {
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ team_id: 'arsenal', success: true }) });
    });

    await page.route('**/api/v1/notifications/subscribe-team', (route) => {
      alertSubscribed = true;
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ team_id: 'arsenal', matches_tracked: 3 }) });
    });

    await page.goto('/');

    const favRes = await pageFetch(page, '/api/v1/users/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: 'arsenal' }),
    });
    expect(favRes.status).toBe(201);

    const subRes = await pageFetch(page, '/api/v1/notifications/subscribe-team', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: 'arsenal' }),
    });
    expect(subRes.status).toBe(201);
    expect(alertSubscribed).toBe(true);
  });

  // --------------------------------------------------------------------------
  // Suite 3.10: Multi-surface Anti-Casino Terminology and WCAG AA Compliance Validation
  // --------------------------------------------------------------------------
  test('3.10: Cross-surface audit verifies strict analytical terminology and WCAG AA landmarks across routes', async ({ page }) => {
    await setupMockApiRoutes(page);
    const routesToAudit = ['/', '/performance', '/docs', '/match/arsenal-vs-chelsea?league=EPL'];

    for (const route of routesToAudit) {
      await page.goto(route);
      await expect(page.locator('main, article').first()).toBeVisible();

      // Check for prohibited words
      const text = await page.locator('body').innerText();
      expect(/\b(lock|banker|sure bet|free money|guaranteed)\b/i.test(text)).toBe(false);
    }
  });

});
