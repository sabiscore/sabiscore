"use server";

/**
 * Next.js 15 Server Action for Live Match Prediction.
 *
 * Securely calls FastAPI `POST /api/v1/predict/match` on the server runtime.
 * Never leaks backend infrastructure URLs or provider keys to the browser.
 */

import { resolveBackendBaseUrl, isHtmlBody } from "@/lib/proxy-utils";
import type { PredictionResponse, PredictMatchOptions } from "@/types/prediction";

export async function getMatchPrediction(
  matchId: string,
  options?: PredictMatchOptions
): Promise<PredictionResponse | null> {
  const baseUrl = resolveBackendBaseUrl();
  const url = `${baseUrl}/api/v1/predict/match`;

  // Parse home / away names if matchId has format "Home vs Away"
  let homeTeam = options?.home_team;
  let awayTeam = options?.away_team;
  if (!homeTeam || !awayTeam) {
    if (matchId.includes(" vs ")) {
      const parts = matchId.split(" vs ");
      homeTeam = homeTeam || parts[0]?.trim();
      awayTeam = awayTeam || parts[1]?.trim();
    } else {
      homeTeam = homeTeam || "Home Team";
      awayTeam = awayTeam || "Away Team";
    }
  }

  const payload = {
    match_id: matchId,
    home_team: homeTeam,
    away_team: awayTeam,
    competition: options?.competition || "SERIE_A",
    home_odds: options?.home_odds ?? null,
    draw_odds: options?.draw_odds ?? null,
    away_odds: options?.away_odds ?? null,
  };

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10000), // 10s timeout
    });

    if (!res.ok) {
      console.warn(`[getMatchPrediction] Backend returned status ${res.status}`);
      return null;
    }

    const text = await res.text();
    if (isHtmlBody(text)) {
      console.error("[getMatchPrediction] Backend returned HTML instead of JSON");
      return null;
    }

    const data: PredictionResponse = JSON.parse(text);

    // Validate probability simplex
    const sum = data.probabilities.home + data.probabilities.draw + data.probabilities.away;
    if (Math.abs(sum - 1.0) > 1e-4) {
      console.error(`[getMatchPrediction] Probability simplex invariant violated (sum=${sum})`);
      return null;
    }

    return data;
  } catch (error) {
    console.error("[getMatchPrediction] Failed to fetch match prediction:", error);
    return null;
  }
}
