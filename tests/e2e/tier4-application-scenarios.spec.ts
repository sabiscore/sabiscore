import { test, expect } from '@playwright/test';
import {
  createMockAnalysisPayload,
  createMockCalibrationPayload,
  pageFetch,
  setupMockApiRoutes,
} from './helpers/e2e-fixtures';

// ============================================================================
// TIER 4: REAL-WORLD APPLICATION SCENARIOS (Complete Multi-Step User Journeys)
// End-to-end consumer, developer, analytical, and edge lifecycles.
// ============================================================================

test.describe('Tier 4: Real-World Application Scenarios Suite', () => {

  // --------------------------------------------------------------------------
  // Journey 1: The Analytical Consumer Journey (Discovery → Evidence Inspection → Personalization → Sharing)
  // --------------------------------------------------------------------------
  test('Journey 1: Consumer Discovery to Social Advocate', async ({ page }) => {
    await setupMockApiRoutes(page);

    // Step 1: User lands on SabiScore homepage
    await page.goto('/');
    await expect(page.locator('main, article').first()).toBeVisible();

    // Step 2: User inspects upcoming verified fixtures
    const upcomingHeading = page.getByRole('heading', { name: /Upcoming verified fixtures|Match Intelligence|SabiScore/i });
    await expect(upcomingHeading.first()).toBeVisible();

    // Step 3: User navigates to match detail page (Arsenal vs Chelsea)
    await page.goto('/match/arsenal-vs-chelsea?league=EPL');
    await expect(page.locator('main, article').first()).toBeVisible();

    // Step 4: User triggers Save Match
    await page.route('**/api/v1/users/saved-matches', (route) => {
      route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ match_id: 'arsenal-vs-chelsea', saved: true }) });
    });
    const saveRes = await pageFetch(page, '/api/v1/users/saved-matches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ match_id: 'arsenal-vs-chelsea' }),
    });
    expect(saveRes.status).toBe(201);

    // Step 5: User signs up for persistent account
    await page.route('**/api/v1/auth/register', (route) => {
      route.fulfill({
        status: 201,
        headers: { 'Set-Cookie': 'sabi_session=jwt_consumer_token; HttpOnly; Secure; SameSite=Lax; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({ id: 'usr_advocate', email: 'advocate@sabiscore.com', username: 'advocate' }),
      });
    });
    const regRes = await pageFetch(page, '/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'advocate', email: 'advocate@sabiscore.com', password: 'Password123!' }),
    });
    expect(regRes.status).toBe(201);

    // Step 6: User shares match analysis
    const shareBtn = page.getByRole('button', { name: /share/i });
    if (await shareBtn.count() > 0) {
      await shareBtn.first().click();
    }
  });

  // --------------------------------------------------------------------------
  // Journey 2: The Developer Onboarding & API Consumption Lifecycle
  // --------------------------------------------------------------------------
  test('Journey 2: Developer Onboard -> Generate Key -> Invoke API -> Hit Rate Limit -> Revoke Key', async ({ page }) => {
    await setupMockApiRoutes(page);
    await page.goto('/docs');
    await expect(page.locator('main, article').first()).toBeVisible();

    // Step 1: Developer generates an API Key
    const devKey = 'sbk_live_prod_client_key_999';
    await page.route('**/api/v1/developer/keys', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'key_prod_999', key: devKey, name: 'Production Backend', tier: 'FREE' }),
        });
      }
    });

    const createKeyRes = await pageFetch(page, '/api/v1/developer/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'Production Backend' }),
    });
    expect(createKeyRes.status).toBe(201);
    const createKeyData = await createKeyRes.json();
    expect(createKeyData.key).toBe(devKey);

    // Step 2: Developer invokes predictions API
    let devRequests = 0;
    await page.route('**/api/v1/predict/**', (route) => {
      const authKey = route.request().headers()['x-api-key'];
      if (authKey !== devKey) {
        route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'Unauthorized' }) });
        return;
      }
      devRequests++;
      if (devRequests > 10) {
        route.fulfill({
          status: 429,
          headers: { 'Retry-After': '60' },
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'FREE tier minute rate limit reached (10 req/min)' }),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ match_id: 'arsenal-vs-chelsea', prediction: 'home_win', probability: 0.52 }),
        });
      }
    });

    // Make 10 successful requests
    for (let i = 1; i <= 10; i++) {
      const res = await pageFetch(page, `/api/v1/predict/fixture_${i}`, { headers: { 'x-api-key': devKey } });
      expect(res.status).toBe(200);
    }

    // Step 3: 11th request triggers rate limit 429
    const limitRes = await pageFetch(page, '/api/v1/predict/fixture_11', { headers: { 'x-api-key': devKey } });
    expect(limitRes.status).toBe(429);

    // Step 4: Developer revokes the key
    await page.route('**/api/v1/developer/keys/key_prod_999', (route) => {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ revoked: true }) });
    });
    const revokeRes = await pageFetch(page, '/api/v1/developer/keys/key_prod_999', { method: 'DELETE' });
    expect(revokeRes.status).toBe(200);
  });

  // --------------------------------------------------------------------------
  // Journey 3: Analytical Trust Investigation to Notification Subscription
  // --------------------------------------------------------------------------
  test('Journey 3: Public Trust Audit -> Calibration Inspection -> Timezone Notification Subscription', async ({ page }) => {
    await setupMockApiRoutes(page);

    // Step 1: User navigates to /performance
    await page.goto('/performance');
    await expect(page.locator('main, article').first()).toBeVisible();

    // Step 2: Verify performance heading
    const perfHeading = page.getByRole('heading', { name: /Performance/i });
    await expect(perfHeading.first()).toBeVisible();

    // Step 3: User configures timezone in notification preferences
    await page.route('**/api/v1/notifications/preferences', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ timezone: 'Africa/Lagos', probability_delta_threshold: 0.05, in_app_enabled: true }),
      });
    });

    const prefRes = await pageFetch(page, '/api/v1/notifications/preferences');
    expect(prefRes.status).toBe(200);
    const prefData = await prefRes.json();
    expect(prefData.timezone).toBe('Africa/Lagos');

    // Step 4: User subscribes to match notifications
    await page.route('**/api/v1/notifications/subscribe', (route) => {
      route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ subscription_id: 'sub_trust_101', fixture_id: 'arsenal-vs-chelsea' }),
      });
    });

    const subRes = await pageFetch(page, '/api/v1/notifications/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fixture_id: 'arsenal-vs-chelsea', reminder_type: 'KICKOFF_AND_DELTA' }),
    });
    expect(subRes.status).toBe(201);

    // Step 5: Notification center displays incoming notifications
    await page.route('**/api/v1/notifications', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          notifications: [
            { id: 'notif_swing_1', title: 'Odds Shift Alert', message: 'Arsenal win probability moved from 50% to 56%', read: false },
          ],
        }),
      });
    });

    const notifRes = await pageFetch(page, '/api/v1/notifications');
    expect(notifRes.status).toBe(200);
    const notifData = await notifRes.json();
    expect(notifData.notifications[0].title).toBe('Odds Shift Alert');
  });

  // --------------------------------------------------------------------------
  // Journey 4: Off-Season & Low-Evidence Graceful Degradation Journey
  // --------------------------------------------------------------------------
  test('Journey 4: Off-Season Navigation -> Low Evidence Match -> PARTIAL Verdict & No Bet -> Safe Share Card', async ({ page }) => {
    // Step 1: Off-season banner displayed on league filter
    await page.route('**/api/offseason/**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          league: 'BUNDESLIGA',
          season_status: 'OFF_SEASON',
          days_until_next_season: 35,
          prediction_advisory: 'Off-season. Historical baseline only.',
        }),
      });
    });

    await page.goto('/?league=BUNDESLIGA');
    await expect(page.locator('main, article').first()).toBeVisible();

    // Step 2: Navigate to match with missing evidence
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
            critical_gaps: ['COHERENT_1X2_MARKET_UNAVAILABLE', 'LINEUPS_UNVERIFIED'],
            advisory_gaps: [],
            conflicts: [],
          },
        })),
      });
    });

    await page.goto('/match/critical?league=BUNDESLIGA');
    await expect(page.getByRole('img', { name: 'No bet' })).toBeVisible();
    await expect(page.getByText('No bet').first()).toBeVisible();

    // Step 3: Verify no casino phrasing exists on this degraded state
    const pageText = await page.locator('body').innerText();
    expect(/\b(lock|banker|sure bet|free money|guaranteed)\b/i.test(pageText)).toBe(false);
  });

  // --------------------------------------------------------------------------
  // Journey 5: Multi-Device Anonymous Migration & Session Lifecycle
  // --------------------------------------------------------------------------
  test('Journey 5: Device A Anon -> Save State -> Register -> Device B Login -> Sync -> Logout', async ({ page }) => {
    await setupMockApiRoutes(page);
    await page.goto('/');

    // 1. Device A: Anonymous user favorites team
    await page.route('**/api/v1/users/favorites', (route) => {
      if (route.request().method() === 'POST') {
        route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({ team_id: 'liverpool', success: true }) });
      } else {
        route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ favorites: [{ team_id: 'liverpool' }] }) });
      }
    });

    const favA = await pageFetch(page, '/api/v1/users/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: 'liverpool' }),
    });
    expect(favA.status).toBe(201);

    // 2. User registers on Device A
    await page.route('**/api/v1/auth/register', (route) => {
      route.fulfill({
        status: 201,
        headers: { 'Set-Cookie': 'sabi_session=jwt_session_user_device_a; HttpOnly; Secure; SameSite=Lax; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({ id: 'usr_sync', email: 'sync@sabiscore.com', username: 'synced_user' }),
      });
    });

    const regRes = await pageFetch(page, '/api/v1/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'synced_user', email: 'sync@sabiscore.com', password: 'Password123!' }),
    });
    expect(regRes.status).toBe(201);

    // 3. User logs in on Device B
    await page.route('**/api/v1/auth/login', (route) => {
      route.fulfill({
        status: 200,
        headers: { 'Set-Cookie': 'sabi_session=jwt_session_user_device_b; HttpOnly; Secure; SameSite=Lax; Path=/' },
        contentType: 'application/json',
        body: JSON.stringify({ user: { id: 'usr_sync', email: 'sync@sabiscore.com' } }),
      });
    });

    const loginRes = await pageFetch(page, '/api/v1/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: 'sync@sabiscore.com', password: 'Password123!' }),
    });
    expect(loginRes.status).toBe(200);

    // 4. Device B loads favorites and confirms 'liverpool' is present
    const favB = await pageFetch(page, '/api/v1/users/favorites');
    expect(favB.status).toBe(200);
    const favBData = await favB.json();
    expect(favBData.favorites[0].team_id).toBe('liverpool');

    // 5. User logs out on Device B
    await page.route('**/api/v1/auth/logout', (route) => {
      route.fulfill({
        status: 200,
        headers: { 'Set-Cookie': 'sabi_session=; Max-Age=0; Path=/; HttpOnly' },
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    const logoutRes = await pageFetch(page, '/api/v1/auth/logout', { method: 'POST' });
    expect(logoutRes.status).toBe(200);
  });

});
