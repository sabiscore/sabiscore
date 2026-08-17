"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";
import { FeatureFlag, useFeatureFlag } from "@/lib/feature-flags";
import { ErrorBoundary } from "@/components/error-boundary";

const FullAnalysisDashboard = dynamic(
  () =>
    import("./full-analysis-dashboard").then((m) => ({ default: m.FullAnalysisDashboard })),
  { ssr: false, loading: () => <FullAnalysisSkeleton /> }
);

function FullAnalysisSkeleton() {
  return (
    <div className="space-y-5 animate-pulse" aria-hidden="true">
      <div className="h-14 rounded-2xl bg-slate-800/70" />
      <div className="h-20 rounded-2xl bg-slate-800/50" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        <div className="h-44 rounded-2xl bg-slate-800/40" />
        <div className="h-44 rounded-2xl bg-slate-800/40" />
      </div>
    </div>
  );
}

function FullAnalysisFallback() {
  return (
    <div className="rounded-2xl border border-slate-800/50 bg-slate-900/30 p-6 text-center">
      <p className="text-sm text-slate-300">
        Match Intelligence unavailable for this fixture.
      </p>
    </div>
  );
}

interface FullAnalysisSectionProps {
  matchId: string;
  league?: string;
  /** Only present when matchId is a real canonical ID (routed from a real
   * fixture card) rather than a "Home vs Away" matchup string — lets the
   * hero card display real team names without re-parsing the opaque ID. */
  homeTeam?: string;
  awayTeam?: string;
}

export function FullAnalysisSection({
  matchId,
  league = "EPL",
  homeTeam,
  awayTeam,
}: FullAnalysisSectionProps) {
  const enabled = useFeatureFlag(FeatureFlag.FULL_ANALYSIS_V7);

  if (!enabled) return null;

  return (
    <section aria-label="SabiScore Match Intelligence">
      <div className="flex items-center gap-3 mb-5">
        <div className="h-px flex-1 bg-slate-800/60" />
        <span className="text-[11px] uppercase tracking-[0.35em] text-slate-300 font-semibold">
          Match Intelligence · 6-Layer Analysis
        </span>
        <div className="h-px flex-1 bg-slate-800/60" />
      </div>

      <ErrorBoundary fallback={(_error, _reset) => <FullAnalysisFallback />}>
        <Suspense fallback={<FullAnalysisSkeleton />}>
          <FullAnalysisDashboard
            matchId={matchId}
            league={league}
            homeTeam={homeTeam}
            awayTeam={awayTeam}
          />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}
