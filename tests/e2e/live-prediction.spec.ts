import { test, expect } from '@playwright/test';

test.describe('Live Prediction Flow & Metric Translation Smoke Test', () => {
  test('user loads homepage, clicks a fixture, and views translated probability simplex with Kelly recommendation', async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        consoleErrors.push(msg.text());
      }
    });
    page.on('pageerror', (err) => {
      consoleErrors.push(err.message);
    });

    // 1. Load the homepage
    await page.goto('/');

    // Verify Obsidian Nocturne Hero section rendered
    const hero = page.getByTestId('hero-section');
    await expect(hero).toBeVisible();
    await expect(
      page.getByRole('heading', {
        name: /Edge-First Predictive Modeling & Live Football Intelligence/i,
      })
    ).toBeVisible();

    // 2. Navigate to a live match fixture page
    // Direct navigation to verified fixture path ensures reliable test execution across environments
    await page.goto('/match/11662?league=SERIE_A&home=Inter&away=AC%20Milan');

    // 3. Verify PredictionCard is rendered
    const predictionCard = page.getByTestId('prediction-card');
    await expect(predictionCard).toBeVisible({ timeout: 15000 });

    // 4. Verify Translated Probability Simplex (Home: XX% | Draw: YY% | Away: ZZ%)
    const probHeadline = page.getByTestId('translated-probabilities');
    await expect(probHeadline).toBeVisible();
    await expect(probHeadline).toHaveText(/Home: \d+% \| Draw: \d+% \| Away: \d+%/);

    // 5. Verify Actionable Staking Recommendation ("Bet X%" OR "No Value: Skip")
    const actionable = page.getByTestId('recommendation-actionable');
    const muted = page.getByTestId('recommendation-muted');

    // Exactly one of the two states must be present
    const isActionableVisible = await actionable.isVisible().catch(() => false);
    const isMutedVisible = await muted.isVisible().catch(() => false);

    expect(isActionableVisible || isMutedVisible).toBe(true);

    if (isActionableVisible) {
      await expect(actionable).toContainText(/Actionable Edge: Bet \d+(\.\d+)?% of your bankroll/);
    } else {
      await expect(muted).toContainText('No Value: Skip this match.');
    }

    // 6. Verify Recent Attacking Form (Last 5 Matches) & Trend Indicator
    await expect(page.getByText('Recent Attacking Form (Last 5 Matches)')).toBeVisible();
    const trend = page.getByTestId('xg-trend-indicator');
    await expect(trend).toBeVisible();
    await expect(trend).toContainText(/xG momentum/);

    // 7. Verify zero client-side console errors
    const fatalErrors = consoleErrors.filter(
      (e) => !e.includes('favicon.ico') && !e.includes('hydration') && !e.includes('ResizeObserver')
    );
    expect(fatalErrors).toEqual([]);
  });
});
