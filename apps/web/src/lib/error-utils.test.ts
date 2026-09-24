import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as Sentry from '@sentry/nextjs';
import { logError } from './error-utils';

vi.mock('@sentry/nextjs', () => ({
  captureException: vi.fn(),
}));

describe('logError', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('forwards Error objects to Sentry with structured context', async () => {
    const error = new Error('boom');

    logError(error, {
      component: 'test/component',
      action: 'render',
      metadata: { fixtureId: 'fd-123' },
    });

    const capture = vi.mocked(Sentry.captureException);
    await vi.waitFor(() => expect(capture).toHaveBeenCalledTimes(1));

    const [capturedError, context] = capture.mock.calls[0];
    expect(capturedError).toBe(error);
    expect(context).toMatchObject({
      tags: {
        component: 'test/component',
        action: 'render',
      },
      extra: {
        message: 'boom',
        component: 'test/component',
        action: 'render',
        metadata: { fixtureId: 'fd-123' },
      },
    });
  });

  it('wraps non-Error values before capture', async () => {
    logError('string failure');

    const capture = vi.mocked(Sentry.captureException);
    await vi.waitFor(() => expect(capture).toHaveBeenCalledTimes(1));

    const [capturedError] = capture.mock.calls[0];
    expect(capturedError).toBeInstanceOf(Error);
    expect((capturedError as Error).message).toBe('string failure');
  });

  it('never crashes when telemetry capture fails asynchronously', async () => {
    const capture = vi.mocked(Sentry.captureException);
    capture.mockImplementationOnce(() => {
      throw new Error('telemetry failure');
    });

    expect(() => logError(new Error('safe path'))).not.toThrow();
    await vi.waitFor(() => expect(capture).toHaveBeenCalledTimes(1));
  });

  it('does not statically import the Sentry SDK, keeping it out of the eager bundle', () => {
    // error-utils.ts is imported by app/error.tsx, app/global-error.tsx, and
    // app/match/[id]/error.tsx, which ship in every page's critical bundle.
    // A static top-level `import ... from '@sentry/nextjs'` here pulls the
    // whole client SDK into that eager bundle regardless of whether an error
    // ever occurs or a DSN is configured — logError() must load it lazily.
    const source = readFileSync(join(process.cwd(), 'src', 'lib', 'error-utils.ts'), 'utf8');
    expect(source).not.toMatch(/^\s*import\s.*['"]@sentry\/nextjs['"]/m);
  });
});
