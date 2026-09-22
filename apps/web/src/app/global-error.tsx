'use client';

import { useEffect } from 'react';
import { logError, safeErrorMessage } from '@/lib/error-utils';

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  useEffect(() => {
    logError(error, {
      component: 'app/global-error',
      action: 'render',
      metadata: {
        digest: error.digest,
      },
    });
  }, [error]);

  const errorMessage = safeErrorMessage(error);

  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-900 text-slate-50 font-sans">
        <div className="flex min-h-screen items-center justify-center px-4">
          <div className="w-full max-w-xl text-center space-y-4">
            <h1 className="text-2xl font-bold">Something went wrong</h1>
            <p className="text-slate-300">{errorMessage}</p>
            <button
              onClick={reset}
              className="inline-flex items-center justify-center rounded-lg bg-indigo-600 px-6 py-3 text-base font-semibold text-white shadow-lg shadow-indigo-900/40 transition hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            >
              Try again
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
