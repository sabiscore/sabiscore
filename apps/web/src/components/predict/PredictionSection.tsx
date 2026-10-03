import React, { Suspense } from "react";
import { getMatchAnalysis } from "@/actions/predict";
import { FullAnalysisSection } from "@/components/full-analysis-section";
import { summarizeAnalysis } from "@/lib/prediction-truth";
import { PredictionCard } from "./PredictionCard";
import { PredictionCardSkeleton } from "./PredictionCardSkeleton";

interface MatchAnalysisPanelsProps {
  matchId: string;
  league: string;
  homeTeam?: string;
  awayTeam?: string;
}

/**
 * Fetches the full analysis once and renders both the forecast card and the
 * dashboard from that payload. The dashboard only fetches for itself when this
 * request produced no data, so its own retry and error states still apply.
 */
export async function MatchAnalysisContent({
  matchId,
  league,
  homeTeam,
  awayTeam,
}: MatchAnalysisPanelsProps) {
  // The server action never throws and never fabricates: failures arrive as an
  // explicit UNAVAILABLE result and render without any numbers.
  const fetched = await getMatchAnalysis(matchId, { league });
  const analysis = fetched.status === "OK" ? fetched.analysis : undefined;
  const result = fetched.status === "OK" ? summarizeAnalysis(fetched.analysis) : fetched;
  return (
    <>
      <section className="my-4 w-full" aria-label="Match forecast summary">
        <PredictionCard result={result} />
      </section>
      <FullAnalysisSection
        matchId={matchId}
        league={league}
        homeTeam={homeTeam}
        awayTeam={awayTeam}
        initialData={analysis}
      />
    </>
  );
}

export function MatchAnalysisPanels(props: MatchAnalysisPanelsProps) {
  return (
    <Suspense fallback={<PredictionCardSkeleton />}>
      <MatchAnalysisContent {...props} />
    </Suspense>
  );
}
