import { NextRequest, NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';
import { canonicalLeagueId } from '@/lib/league';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** See the sibling summary route: the backend's own 503 body distinguishes
 *  "no settled predictions yet" from a real outage, so it is forwarded intact
 *  rather than overwritten with a fabricated empty series. */
function infrastructureError(
  message: string,
  status: number,
  league: string | null,
  window: number,
) {
  return NextResponse.json(
    {
      status: 'METRICS_UNAVAILABLE',
      reason: 'backend_unreachable',
      league,
      window,
      series: [],
      error: message,
    },
    { status },
  );
}

export async function GET(request: NextRequest) {
  // Normalized at the boundary like every other league-parameterized proxy;
  // `league` is echoed back in the error bodies below, so it must be the same
  // canonical value that was actually forwarded, not the raw client string.
  const requestedLeague = request.nextUrl.searchParams.get('league');
  const league = requestedLeague ? canonicalLeagueId(requestedLeague) : null;
  const windowParam = request.nextUrl.searchParams.get('window') || '30';
  const window = Number(windowParam);

  try {
    const url = new URL(`${resolveBackendBaseUrl()}/api/v1/model-performance`);
    if (league) url.searchParams.set('league', league);
    url.searchParams.set('window', windowParam);

    const response = await fetch(url.toString(), { headers: proxyHeaders() });
    const body = await response.text().catch(() => '');

    if (isHtmlBody(body)) {
      return infrastructureError('Backend service unavailable', 503, league, window);
    }

    try {
      return NextResponse.json(JSON.parse(body), { status: response.status });
    } catch {
      return infrastructureError('Unexpected response from backend', 502, league, window);
    }
  } catch (error: unknown) {
    return infrastructureError(
      error instanceof Error ? error.message : 'Unknown error',
      503,
      league,
      window,
    );
  }
}
