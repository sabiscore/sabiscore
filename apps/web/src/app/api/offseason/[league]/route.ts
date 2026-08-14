/**
 * Next.js server-side proxy for the league off-season status endpoint.
 *
 * Route: GET /api/offseason/[league]
 * Proxies to: {BACKEND_URL}/api/v1/leagues/{league}/offseason-status
 *
 * Off-season status changes at most once per day, so we cache the response
 * for 1 hour (s-maxage=3600) to avoid hammering the backend on every page load.
 */
import { NextRequest, NextResponse } from 'next/server';
import { canonicalLeagueId } from '@/lib/league';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const BACKEND_URL =
  process.env.SABISCORE_BACKEND_URL;

/**
 * Complete UNKNOWN-status body for every fallback path. The frontend contract
 * (and e2e shape test) requires data_availability + prediction_advisory on
 * all responses — when the backend is unreachable nothing is available.
 */
function unknownFallback(league: string) {
  return {
    league,
    season_status: 'UNKNOWN',
    next_season_start: null,
    next_season_start_estimated: null,
    days_until_next_season: null,
    data_availability: {
      historical_data: false,
      live_odds: false,
      live_standings: false,
      live_form: false,
      pi_ratings: false,
      berrar_ratings: false,
      market_drift: false,
      match_context: false,
    },
    prediction_advisory:
      'Season status unavailable — backend unreachable. Predictions are not being generated from live data.',
  };
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ league: string }> },
): Promise<NextResponse> {
  const { league: requestedLeague } = await params;
  // Normalize at the boundary rather than relying on the backend's own
  // tolerance and on callers happening to pre-normalize. An unsupported league
  // degrades to the same honest UNKNOWN body every other failure path returns —
  // never a fabricated season status.
  const league = canonicalLeagueId(requestedLeague);

  if (!league) {
    return NextResponse.json(unknownFallback(requestedLeague), { status: 200 });
  }

  if (!BACKEND_URL) {
    return NextResponse.json(
      { error: 'Backend URL not configured', ...unknownFallback(league) },
      { status: 503 },
    );
  }

  const backendUrl = `${BACKEND_URL}/api/v1/leagues/${encodeURIComponent(league)}/offseason-status`;

  try {
    const upstream = await fetch(backendUrl, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      // Node.js fetch: next revalidation handled via Cache-Control on the response
      next: { revalidate: 3600 }, // ISR-style revalidation every hour
    });

    if (!upstream.ok) {
      const text = await upstream.text();
      return NextResponse.json(
        {
          error: `Upstream error ${upstream.status}`,
          detail: text.slice(0, 200),
          ...unknownFallback(league),
        },
        { status: upstream.status },
      );
    }

    const data = await upstream.json();

    return NextResponse.json(data, {
      headers: {
        // Allow CDN/edge caches to cache for 1 hour; clients revalidate after 5 min
        'Cache-Control': 'public, s-maxage=3600, stale-while-revalidate=300',
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    return NextResponse.json(
      {
        error: 'Failed to reach backend',
        detail: message,
        ...unknownFallback(league),
      },
      { status: 502 },
    );
  }
}
