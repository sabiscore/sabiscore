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

  it('forwards Error objects to Sentry with structured context', () => {
    const error = new Error('boom');

    logError(error, {
      component: 'test/component',
      action: 'render',
      metadata: { fixtureId: 'fd-123' },
    });

    const capture = vi.mocked(Sentry.captureException);
    expect(capture).toHaveBeenCalledTimes(1);

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

  it('wraps non-Error values before capture', () => {
    logError('string failure');

    const capture = vi.mocked(Sentry.captureException);
    expect(capture).toHaveBeenCalledTimes(1);

    const [capturedError] = capture.mock.calls[0];
    expect(capturedError).toBeInstanceOf(Error);
    expect((capturedError as Error).message).toBe('string failure');
  });

  it('never throws when telemetry capture fails', () => {
    const capture = vi.mocked(Sentry.captureException);
    capture.mockImplementationOnce(() => {
      throw new Error('telemetry failure');
    });

    expect(() => logError(new Error('safe path'))).not.toThrow();
  });
});
