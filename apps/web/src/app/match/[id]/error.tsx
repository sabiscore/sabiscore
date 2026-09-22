'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { RefreshCw, Home, AlertCircle } from 'lucide-react';
import { logError } from '@/lib/error-utils';

interface MatchErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function MatchInsightsError({ error, reset }: MatchErrorProps) {
  const [isRetrying, setIsRetrying] = useState(false);

  useEffect(() => {
    // API/backend errors are caught inline in page.tsx; this boundary only fires
    // for genuine unexpected crashes (rendering errors, unhandled component throws).
    logError(error, {
      component: 'app/match/[id]/error',
      action: 'render',
      metadata: {
        digest: error.digest,
      },
    });
  }, [error]);

  return (
    <div className="mx-auto flex max-w-3xl flex-col items-center gap-6 text-center py-16 px-4">
      <div className="flex h-20 w-20 items-center justify-center rounded-full border bg-slate-800/50 border-rose-500/30">
        <AlertCircle className="h-10 w-10 text-rose-400" />
      </div>

      <div className="space-y-3">
        <p className="text-sm font-semibold uppercase tracking-wider text-rose-300">
          Unexpected Error
        </p>
        <h1 className="text-3xl font-bold text-slate-100">We hit a snag</h1>
        <p className="text-slate-400 max-w-md mx-auto">
          Something unexpected happened. Please try again — if the issue persists,
          try picking a different matchup.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => {
            setIsRetrying(true);
            reset();
          }}
          disabled={isRetrying}
          className="inline-flex items-center gap-2 rounded-xl border border-indigo-500/60 bg-indigo-500/20 px-6 py-3 font-semibold text-indigo-200 transition hover:bg-indigo-500/30 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isRetrying ? 'animate-spin' : ''}`} />
          {isRetrying ? 'Retrying…' : 'Retry now'}
        </button>
        <Link
          href="/match"
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700/60 bg-slate-800/40 px-6 py-3 font-semibold text-slate-200 transition hover:bg-slate-800"
        >
          <Home className="h-4 w-4" />
          Pick another matchup
        </Link>
      </div>

      {error.digest && (
        <p className="mt-2 text-xs text-slate-600 font-mono">ref: {error.digest}</p>
      )}
    </div>
  );
}
