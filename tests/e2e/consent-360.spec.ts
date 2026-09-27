import { expect, test } from '@playwright/test';

// Directive v11 U14: a first visit at 360 px stacked an 18+ gate and then a
// cookie banner over the market table. Acceptance: one consent step, nothing
// left covering the page afterwards, and a 360 px screenshot as evidence.
// Backend-independent: the consent step renders before any data loads.

// A first visit: none of the consent the config pre-seeds for other specs.
test.use({ storageState: { cookies: [], origins: [] } });

test('first visit at 360 px: one consent step, then nothing covers the page', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 360, height: 640 });
  await page.goto('/');

  const dialog = page.getByRole('dialog');
  await expect(dialog).toHaveCount(1);

  // The step fits the width, and its last action can be scrolled to.
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  const exit = page.getByRole('button', { name: /under 18/i });
  await exit.scrollIntoViewIfNeeded();
  await expect(exit).toBeInViewport();

  const shot = testInfo.outputPath('u14-consent-360.png');
  await page.screenshot({ path: shot });
  await testInfo.attach('u14-consent-360', { path: shot, contentType: 'image/png' });

  await page.getByRole('button', { name: /I am 18\+/ }).first().click();

  await expect(dialog).toHaveCount(0);
  // No second banner: nothing fixed and tall is pinned to the bottom edge,
  // where it would sit over the market table.
  await page.waitForTimeout(500); // the old banner slid in after the gate closed
  const bottomOverlays = await page.evaluate(() =>
    [...document.querySelectorAll('body *')]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        return (
          getComputedStyle(el).position === 'fixed' &&
          box.bottom >= window.innerHeight - 1 &&
          box.height > 100
        );
      })
      .map((el) => el.className.toString().slice(0, 80)),
  );
  expect(bottomOverlays).toEqual([]);
});
