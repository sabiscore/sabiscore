import React, { Suspense } from "react";
import { getMatchPrediction } from "@/actions/predict";
import { PredictionCard } from "./PredictionCard";
import { PredictionCardSkeleton } from "./PredictionCardSkeleton";
import type { PredictionResponse } from "@/types/prediction";

interface PredictionSectionProps {
  matchId: string;
  homeTeam?: string;
  awayTeam?: string;
  competition?: string;
}

async function AsyncPredictionContent({
  matchId,
  homeTeam,
  awayTeam,
  competition = "SERIE_A",
}: PredictionSectionProps) {
  let prediction: PredictionResponse | null = null;
  let oddsUnavailable = false;

  try {
    prediction = await getMatchPrediction(matchId, {
      home_team: homeTeam,
      away_team: awayTeam,
      competition,
    });
  } catch (error) {
    console.warn("Could not retrieve live prediction:", error);
  }

  // Graceful fallback if backend call timed out or live lines failed
  if (!prediction) {
    oddsUnavailable = true;
    const h = homeTeam || "Home Team";
    const a = awayTeam || "Away Team";
    prediction = {
      match_id: matchId,
      home_team: h,
      away_team: a,
      probabilities: {
        home: 0.45,
        draw: 0.28,
        away: 0.27,
      },
      market: {
        home_odds: 2.15,
        draw_odds: 3.30,
        away_odds: 3.50,
        overround: 1.05,
        bookmaker: "consensus_sharp",
        odds_available: false,
      },
      recommendation: {
        action: "NO_BET",
        best_bet: "none",
        edge: 0.0,
        expected_value: 0.0,
        kelly_fraction: 0.0,
        stake_capped: false,
      },
      telemetry: {
        rolling_xg_home: 1.65,
        rolling_xg_away: 1.25,
        delta_rolling_xg: 0.40,
        source: "fallback_estimate",
      },
    };
  }

  return <PredictionCard prediction={prediction} oddsUnavailable={oddsUnavailable} />;
}

export function PredictionSection(props: PredictionSectionProps) {
  return (
    <section className="my-4 w-full" aria-label="AI Live Match Prediction">
      <Suspense fallback={<PredictionCardSkeleton />}>
        <AsyncPredictionContent {...props} />
      </Suspense>
    </section>
  );
}
