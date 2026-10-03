import { test, expect } from '@playwright/test';

test.describe('Match forecast truth-state smoke test', () => {
  test('match page renders either a backend-computed forecast or an explicit withheld state, never fabricated values', async ({
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

    await page.goto('/');
    const hero = page.getByTestId('hero-section');
    await expect(hero).toBeVisible();

    await page.goto('/match/11662?league=SERIE_A&home=Inter&away=AC%20Milan');

    const card = page.getByTestId('prediction-card');
    await expect(card).toBeVisible({ timeout: 15000 });

    // A truth-state badge is always present.
    await expect(page.getByTestId('truth-state-badge')).toBeVisible();

    const probabilities = page.getByTestId('translated-probabilities');
    const withheld = page.getByTestId('withheld-message');
    const hasProbabilities = await probabilities.isVisible().catch(() => false);
    const hasWithheld = await withheld.isVisible().catch(() => false);

    // Exactly one: a forecast OR an explicit withheld message. Never both, never neither.
    expect(hasProbabilities !== hasWithheld).toBe(true);

    if (hasProbabilities) {
      await expect(probabilities).toHaveText(/Home: \d+% \| Draw: \d+% \| Away: \d+%/);
    } else {
      // Withheld states must not leak any probability, odds or stake figures.
      await expect(card).not.toContainText(/Home: \d+%/);
      await expect(card).toContainText(/Reason code:/);
    }

    const fatalErrors = consoleErrors.filter(
      (e) => !e.includes('favicon.ico') && !e.includes('hydration') && !e.includes('ResizeObserver'),
    );
    expect(fatalErrors).toEqual([]);
  });
});
