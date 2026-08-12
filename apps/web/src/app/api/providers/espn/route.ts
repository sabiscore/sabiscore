// apps/web/src/app/api/providers/espn/fixtures/route.ts
//
// CORRECT PATTERN — the frontend NEVER calls site.api.espn.com directly.
// It proxies the canonical FastAPI backend, which owns the ESPN provider.
// This route validates its input with Zod, applies a timeout + abort, and
// returns no-store. Contrast with the uploaded doc, which fetched ESPN
// straight from the browser/Next.js — a violation of the canonical shape.

import { NextRequest } from "next/server";
import { z } from "zod";
import { canonicalLeagueId } from "@/lib/league";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const BACKEND_URL = process.env.SABISCORE_BACKEND_URL;

// Mirror of the 7 canonical competitions the backend ESPN provider supports.
const Competition = z.enum([
  "EPL",
  "LA_LIGA",
  "SERIE_A",
  "BUNDESLIGA",
  "LIGUE_1",
  "EREDIVISIE",
  "UCL",
]);

const QuerySchema = z.object({
  competition: Competition,
});

export async function GET(request: NextRequest) {
  if (!BACKEND_URL) {
    return Response.json(
      { error: "Backend not configured" },
      { status: 500, headers: { "Cache-Control": "no-store" } },
    );
  }

  // Normalize before validating: the Zod enum only speaks the canonical
  // vocabulary, so a caller sending the display form ("La Liga") got a 422 for
  // a competition this platform fully supports. canonicalLeagueId() folds both
  // vocabularies; genuinely unknown input still returns null and 422s below.
  const requestedCompetition = request.nextUrl.searchParams.get("competition");
  const parsed = QuerySchema.safeParse({
    competition: requestedCompetition ? canonicalLeagueId(requestedCompetition) : null,
  });

  if (!parsed.success) {
    return Response.json(
      { error: "Invalid competition", details: parsed.error.flatten() },
      { status: 422, headers: { "Cache-Control": "no-store" } },
    );
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);

  try {
    // Proxy the canonical backend. The backend ESPN provider applies the
    // circuit breaker, schema validation, redaction, and trust-tier envelope.
    const upstream = await fetch(
      `${BACKEND_URL}/api/v1/providers/espn/fixtures?competition=${parsed.data.competition}`,
      {
        signal: controller.signal,
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );

    const body = await upstream.json();

    return Response.json(body, {
      status: upstream.status,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    return Response.json(
      { error: aborted ? "Backend timeout" : "Backend unavailable" },
      { status: aborted ? 504 : 502, headers: { "Cache-Control": "no-store" } },
    );
  } finally {
    clearTimeout(timeout);
  }
}
