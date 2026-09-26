// Directive v11 U9: a static `import * as Sentry` shipped the whole Sentry browser
// SDK in the chunk every page loads (179 modules, ~273 KB raw, measured
// 2026-09-26) even when no DSN is configured and nothing can ever be sent. The
// DSN is inlined at build time, so without one this block is dead code and the
// SDK is never bundled; with one it loads after first paint.
const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  void import('@sentry/nextjs').then((Sentry) => {
    Sentry.init({
      dsn,
      environment: process.env.NEXT_PUBLIC_VERCEL_ENV ?? process.env.NODE_ENV,
      tracesSampleRate: 0,
      sendDefaultPii: false,
    });
  });
}
