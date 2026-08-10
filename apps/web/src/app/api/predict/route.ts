/**
 * Strict prediction compatibility proxy.
 *
 * Only a fixture persisted by the backend may be analysed. The backend response
 * is returned unchanged after validating its probability simplex; this route
 * never invents fixture context, fills missing probabilities, or records local
 * outcomes/performance.
 */

import { NextRequest, NextResponse } from "next/server";
import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 15;

type PredictionPayload = {
  probabilities?: { home?: unknown; draw?: unknown; away?: unknown } | null;
};

function validFixtureId(value: unknown): value is string {
  return typeof value === "string" && value.length >= 1 && value.length <= 128 &&
    /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(value);
}

function hasValidProbabilitySimplex(payload: PredictionPayload): boolean {
  const values = [
    payload.probabilities?.home,
    payload.probabilities?.draw,
    payload.probabilities?.away,
  ];
  if (!values.every((value) => typeof value === "number" && Number.isFinite(value))) {
    return false;
  }
  const probabilities = values as number[];
  return probabilities.every((value) => value >= 0 && value <= 1) &&
    Math.abs(probabilities.reduce((sum, value) => sum + value, 0) - 1) <= 1e-6;
}

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "invalid_request", message: "A JSON body is required" },
      { status: 400, headers: { "Cache-Control": "no-store" } },
    );
  }

  const matchId = (body as { match_id?: unknown })?.match_id;
  if (!validFixtureId(matchId)) {
    return NextResponse.json(
      {
        error: "verified_fixture_required",
        message: "match_id must identify a persisted backend fixture",
      },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const backendResponse = await fetch(
      `${resolveBackendBaseUrl()}/api/v1/fixtures/${encodeURIComponent(matchId)}/analyze`,
      {
        method: "POST",
        headers: proxyHeaders(),
        cache: "no-store",
        signal: AbortSignal.timeout(8000),
      },
    );
    const responseBody = await backendResponse.text().catch(() => "");
    if (isHtmlBody(responseBody)) {
      return NextResponse.json(
        { error: "backend_unavailable", message: "Backend service unavailable" },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }

    let parsed: PredictionPayload;
    try {
      parsed = JSON.parse(responseBody) as PredictionPayload;
    } catch {
      return NextResponse.json(
        { error: "invalid_backend_response", message: "Backend returned invalid JSON" },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }

    if (backendResponse.ok && !hasValidProbabilitySimplex(parsed)) {
      return NextResponse.json(
        {
          error: "invalid_probability_simplex",
          message: "Backend prediction probabilities are missing or invalid",
        },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }

    return NextResponse.json(parsed, {
      status: backendResponse.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error: unknown) {
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    return NextResponse.json(
      {
        error: timedOut ? "backend_timeout" : "backend_unavailable",
        message: timedOut ? "Prediction request timed out" : "Backend service unavailable",
      },
      { status: timedOut ? 504 : 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export async function GET() {
  return NextResponse.json(
    {
      status: "ready",
      mode: "verified_fixture_proxy",
      outcomeMutation: "retired",
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
