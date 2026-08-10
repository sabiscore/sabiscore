/**
 * Upcoming Matches API Route
 *
 * Proxies upcoming matches + predictions + value bets from FastAPI backend.
 * GET /api/upcoming  (this file is app/api/upcoming/route.ts → served at /api/upcoming)
 * Backend target: GET /api/v1/upcoming/matches
 */

import { NextRequest, NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 15;

const PROXY_TIMEOUT_MS = 8_000;

function boundedInteger(value: string | null, fallback: number, min: number, max: number): number | null {
  if (value == null) return fallback;
  if (!/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : null;
}

function booleanQuery(value: string | null, fallback: boolean): boolean | null {
  if (value == null) return fallback;
  if (value === 'true') return true;
  if (value === 'false') return false;
  return null;
}

function unavailablePayload(reason: string, source: string) {
  return {
    upcoming_matches: [],
    total: 0,
    matches_with_value: 0,
    avg_edge_pct: 0,
    cache_hit: false,
    ttl_seconds: 0,
    source,
    data_gap: true,
    unavailable_reasons: [reason],
    offseason: false,
    next_season_start: null,
    generated_at: new Date().toISOString(),
  };
}

/**
 * GET /api/upcoming
 * Query parameters:
 *   - league: Optional league filter (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie)
 *   - days_ahead: Number of days ahead (1-30, default 7)
 *   - limit: Max matches (1-50, default 20)
 *   - include_predictions: Include ML predictions (default true)
 *   - include_value_bets: Include value bets (default true)
 */
export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;

    const league = searchParams.get('league') || undefined;
    const daysAhead = boundedInteger(searchParams.get('days_ahead'), 7, 1, 30);
    const limit = boundedInteger(searchParams.get('limit'), 20, 1, 50);
    const includePredictions = booleanQuery(searchParams.get('include_predictions'), false);
    const includeValueBets = booleanQuery(searchParams.get('include_value_bets'), false);

    if (
      daysAhead === null ||
      limit === null ||
      includePredictions === null ||
      includeValueBets === null ||
      (league !== undefined && !/^[A-Za-z0-9 _-]{1,40}$/.test(league))
    ) {
      return NextResponse.json(
        { ...unavailablePayload('INVALID_UPCOMING_QUERY', 'validation'), error: 'Invalid query parameters' },
        { status: 400, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    // Build backend URL with query params
    const backendBaseUrl = resolveBackendBaseUrl();
    const url = new URL(`${backendBaseUrl}/api/v1/upcoming/matches`);

    // Add query parameters
    if (league) url.searchParams.set('league', league);
    url.searchParams.set('days_ahead', String(daysAhead));
    url.searchParams.set('limit', String(limit));
    url.searchParams.set('include_predictions', String(includePredictions));
    url.searchParams.set('include_value_bets', String(includeValueBets));

    const response = await fetch(url.toString(), {
      headers: proxyHeaders(),
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      cache: 'no-store',
    });
    const body = await response.text().catch(() => '');

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          ...unavailablePayload('UPCOMING_BACKEND_UNAVAILABLE', 'backend_error'),
          error: 'Backend service unavailable',
        },
        { status: response.status >= 400 && response.status < 500 ? response.status : 503, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(body);
    } catch {
      return NextResponse.json(
        { ...unavailablePayload('UPCOMING_BACKEND_INVALID_RESPONSE', 'backend_error'), error: 'Unexpected response from backend' },
        { status: 502, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 'no-store',
        'Content-Type': 'application/json',
      },
    });
  } catch (error: unknown) {
    const timedOut = error instanceof Error && ['AbortError', 'TimeoutError'].includes(error.name);

    return NextResponse.json(
      {
        ...unavailablePayload(
          timedOut ? 'UPCOMING_PROXY_TIMEOUT' : 'UPCOMING_PROXY_UNAVAILABLE',
          timedOut ? 'timeout' : 'proxy_error',
        ),
        error: timedOut ? 'Upcoming fixtures timed out' : 'Upcoming fixtures unavailable',
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
