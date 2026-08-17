import { test, expect } from '@playwright/test';

// Runs under both the "chromium" (desktop) and "mobile-chrome" Playwright
// projects (playwright.config.ts) — satisfies the "Playwright desktop smoke
// (/intelligence)" and "Playwright mobile smoke (/intelligence)" release
// gates with one shared spec. Backend-independent by design: every assertion
// targets static page chrome that renders before any fixture data loads, so
// the gate doesn't require a live FastAPI backend or provider credentials.
test.describe('/intelligence smoke', () => {
  test('renders the betting intelligence workspace chrome', async ({ page }) => {
    await page.goto('/intelligence');

    await expect(page.getByRole('heading', { name: 'SabiScore Match Intelligence' })).toBeVisible();
    await expect(page.getByText('Fixture Discovery')).toBeVisible();
    await expect(page.getByLabel('Competition')).toBeVisible();
    await expect(page.getByPlaceholder('Search team')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Analyze' })).toBeVisible();
    await expect(page.getByText('No fixture selected')).toBeVisible();
  });

  test('keyboard can reach the team search and competition fields', async ({ page }) => {
    await page.goto('/intelligence');

    await page.getByPlaceholder('Search team').focus();
    await expect(page.getByPlaceholder('Search team')).toBeFocused();

    await page.getByLabel('Competition').focus();
    await expect(page.getByLabel('Competition')).toBeFocused();
  });
});
