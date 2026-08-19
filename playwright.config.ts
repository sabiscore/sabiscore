import { defineConfig, devices } from '@playwright/test';

// GitHub's hosted Ubuntu runner already ships Google Chrome. In CI, use the
// branded system channel so the release gate does not depend on downloading a
// second ~300 MB Chromium/Headless-Shell toolchain from Playwright's CDN.
// Local development keeps Playwright's normal bundled Chromium semantics.
const ciChromeChannel = process.env.CI ? { channel: 'chrome' as const } : {};

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 60_000,
  expect: {
    timeout: 15_000,
  },
  use: {
    baseURL: 'http://localhost:3000',
    trace: 'on-first-retry',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Release gate names this "Playwright desktop smoke" / "Playwright mobile
  // smoke" — both projects run every spec in testDir, including
  // intelligence.spec.ts, against the build started by webServer below.
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium', ...ciChromeChannel },
    },
    {
      name: 'mobile-chrome',
      use: { ...devices['Pixel 5'], ...ciChromeChannel },
    },
  ],
  webServer: {
    command: 'pnpm --filter @sabiscore/web start',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
