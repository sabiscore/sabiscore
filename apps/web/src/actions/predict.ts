"use server";

/**
 * Next.js 15 server boundary for the match prediction summary.
 *
 * Reads the canonical FastAPI full-analysis endpoint (the single authoritative
 * prediction path: FeatureBridge -> PredictionEngine -> calibration -> decision
 * engine) on the server runtime. It never calls a second inference route, never
 * receives provider credentials, and never fabricates a value: any failure maps
 * to an explicit WITHHELD/UNAVAILABLE result that carries no probabilities.
 */

import { fullMatchAnalysisSchema } from "@/lib/full-analysis-contract";
import { canonicalLeagueId } from "@/lib/league";
import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";
import {
  summarizeAnalysis,
  unavailable,
  type AnalysisFetch,
  type PredictionResult,
} from "@/lib/prediction-truth";

// Same budget as the /api/full-analysis proxy route.
const REQUEST_TIMEOUT_MS = 25_000;

/**
 * The page's single full-analysis request. Its parsed payload feeds both the
 * forecast card (as a summary) and the dashboard (as React Query initialData),
 * so a match page costs one backend inference, not two.
 */
export async function getMatchAnalysis(
  matchId: string,
  options?: { league?: string },
): Promise<AnalysisFetch> {
  const id = matchId.trim();
  const league = canonicalLeagueId(options?.league ?? "EPL");
  if (!id || id.length > 240 || league === null) {
    return unavailable("INVALID_REQUEST", "A valid fixture id and league are required.");
  }

  const url = `${resolveBackendBaseUrl()}/api/v1/matches/upcoming/${encodeURIComponent(id)}/full-analysis?league=${encodeURIComponent(league)}`;

  let res: Response;
  try {
    res = await fetch(url, {
      headers: proxyHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    const timedOut =
      error instanceof Error && (error.name === "AbortError" || error.name === "TimeoutError");
    return timedOut
      ? unavailable("BACKEND_TIMEOUT", "The backend did not respond in time.")
      : unavailable("BACKEND_UNREACHABLE", "The backend could not be reached.");
  }

  const text = await res.text();
  if (isHtmlBody(text)) {
    return unavailable("BACKEND_UNAVAILABLE", "The backend service is unavailable.");
  }
  if (!res.ok) {
    return unavailable(`BACKEND_HTTP_${res.status}`, "The backend declined to provide a forecast.");
  }

  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch {
    return unavailable("SCHEMA_DRIFT", "The backend response was not valid JSON.");
  }

  const parsed = fullMatchAnalysisSchema.safeParse(json);
  if (!parsed.success) {
    return unavailable("SCHEMA_DRIFT", "The backend response did not match the analysis contract.");
  }

  return { status: "OK", analysis: parsed.data };
}

export async function getMatchPrediction(
  matchId: string,
  options?: { league?: string },
): Promise<PredictionResult> {
  const fetched = await getMatchAnalysis(matchId, options);
  return fetched.status === "OK" ? summarizeAnalysis(fetched.analysis) : fetched;
}
