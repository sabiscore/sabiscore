"use client";

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { logError, safeErrorMessage } from '@/lib/error-utils';

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function Error({ error, reset }: ErrorProps) {
  const [retryCount, setRetryCount] = useState(0);
  const MAX_RETRIES = 3;

  useEffect(() => {
    logError(error, {
      component: 'app/error',
      action: 'render',
      metadata: {
        digest: error.digest,
        retryCount,
      },
    });
  }, [error, retryCount]);

  const handleRetry = () => {
    if (retryCount < MAX_RETRIES) {
      setRetryCount(prev => prev + 1);
      reset();
    } else {
      // Redirect to home after max retries
      window.location.href = '/';
    }
  };

  const errorMessage = safeErrorMessage(error);
  const isRateLimitError = errorMessage.toLowerCase().includes('rate limit');
  const isNetworkError = errorMessage.toLowerCase().includes('network') || 
                         errorMessage.toLowerCase().includes('fetch');

  return (
    // min-h-[calc(100vh-65px)] matches the root <main> (app/layout.tsx),
    // not min-h-screen: this renders inside that <main>, so a literal 100vh
    // here stacks on top of the header's 65px and overflows the viewport —
    // the same container-parity trap logged repeatedly on other routes.
    <div className="flex min-h-[calc(100vh-65px)] items-center justify-center bg-gradient-to-b from-slate-900 to-slate-950 px-4">
      <div className="max-w-xl space-y-6 text-center">
        <div className="space-y-3">
          <p className="text-sm font-semibold uppercase tracking-wider text-rose-300">
            {isRateLimitError ? '⏱️ Rate Limit' : isNetworkError ? '🔌 Network Error' : '⚠️ Error'}
          </p>
          <h1 className="text-4xl font-bold text-slate-100">
            {isRateLimitError ? 'Too Many Requests' : 'Something went wrong'}
          </h1>
          <p className="text-slate-400">
            {errorMessage}
          </p>
          {error.digest && (
            <p className="text-xs text-slate-500 font-mono">
              Error ID: {error.digest}
            </p>
          )}
          {retryCount > 0 && (
            <p className="text-sm text-amber-400">
              Retry attempt {retryCount} of {MAX_RETRIES}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-center gap-4">
          <button
            onClick={handleRetry}
            disabled={retryCount >= MAX_RETRIES}
            className="rounded-lg border border-indigo-500/60 bg-indigo-500/20 px-6 py-3 font-semibold text-indigo-200 transition hover:bg-indigo-500/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {retryCount >= MAX_RETRIES ? 'Max retries reached' : 'Try again'}
          </button>
          <Link
            href="/"
            className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-6 py-3 font-semibold text-slate-200 transition hover:bg-slate-800"
          >
            Go home
          </Link>
        </div>

        {isNetworkError && (
          <div className="mt-4 p-4 bg-slate-800/50 rounded-lg text-sm text-slate-300">
            <p className="font-semibold mb-2">💡 Troubleshooting tips:</p>
            <ul className="text-left space-y-1 text-slate-400">
              <li>• Check your internet connection</li>
              <li>• Refresh the page</li>
              <li>• Try again in a few moments</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
