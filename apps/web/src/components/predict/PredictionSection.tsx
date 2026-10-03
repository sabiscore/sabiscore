import React, { Suspense } from "react";
import { getMatchPrediction } from "@/actions/predict";
import { PredictionCard } from "./PredictionCard";
import { PredictionCardSkeleton } from "./PredictionCardSkeleton";

interface PredictionSectionProps {
  matchId: string;
  competition?: string;
}

async function AsyncPredictionContent({ matchId, competition }: PredictionSectionProps) {
  // The server action never throws and never fabricates: failures arrive as an
  // explicit WITHHELD/UNAVAILABLE result and render without any numbers.
  const result = await getMatchPrediction(matchId, { league: competition });
  return <PredictionCard result={result} />;
}

export function PredictionSection(props: PredictionSectionProps) {
  return (
    <section className="my-4 w-full" aria-label="Match forecast summary">
      <Suspense fallback={<PredictionCardSkeleton />}>
        <AsyncPredictionContent {...props} />
      </Suspense>
    </section>
  );
}
