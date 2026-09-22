import { describe, expect, it } from 'vitest';
import { buildCspPolicy, getSentryIngestOrigin } from './middleware';

describe('getSentryIngestOrigin', () => {
  it('returns null when DSN is missing', () => {
    expect(getSentryIngestOrigin(undefined)).toBeNull();
  });

  it('returns null when DSN is invalid', () => {
    expect(getSentryIngestOrigin('not-a-valid-url')).toBeNull();
  });

  it('extracts origin from a valid DSN', () => {
    const dsn = 'https://public@example.ingest.sentry.io/123456';
    expect(getSentryIngestOrigin(dsn)).toBe('https://example.ingest.sentry.io');
  });
});

describe('buildCspPolicy', () => {
  it('includes backend and sentry origins in connect-src when DSN exists', () => {
    const csp = buildCspPolicy({
      nonce: 'nonce-123',
      backendUrl: 'https://api.sabiscore.dev',
      sentryDsn: 'https://public@example.ingest.sentry.io/123456',
    });

    expect(csp).toContain("script-src 'self' 'nonce-nonce-123' 'strict-dynamic'");
    expect(csp).toContain("connect-src 'self' https://api.sabiscore.dev https://example.ingest.sentry.io");
  });

  it('does not append sentry origin when DSN is missing', () => {
    const csp = buildCspPolicy({
      nonce: 'nonce-abc',
      backendUrl: 'https://api.sabiscore.dev',
    });

    expect(csp).toContain("connect-src 'self' https://api.sabiscore.dev");
    expect(csp).not.toContain('ingest.sentry.io');
  });
});
