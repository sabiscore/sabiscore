/**
 * Upcoming Matches API Route
 *
 * Proxies upcoming matches + predictions + value bets from FastAPI backend.
 * GET /api/upcoming  (this file is app/api/upcoming/route.ts → served at /api/upcoming)
 * Backend target: GET /api/v1/upcoming/matches
 */

import { NextRequest, NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody, isLocalhostFallback } from '@/lib/proxy-utils';
import { canonicalLeagueId } from '@/lib/league';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 30;
const BACKEND_DEADLINE_MS = 8_000;

function boundedInteger(value: string | null, fallback: number, minimum: number, maximum: number) {
  const parsed = Number(value ?? fallback);
  return Number.isInteger(parsed) && parsed >= minimum && parsed <= maximum ? parsed : fallback;
}

function booleanQuery(value: string | null, fallback: boolean) {
  return value === null ? fallback : value === 'true';
}

/**
 * GET /api/upcoming
 * Query parameters:
 *   - league: Optional league filter (EPL, La Liga, Bundesliga, Serie A, Ligue 1, Eredivisie)
 *   - days_ahead: Number of days ahead (1-30, default 7)
 *   - limit: Max matches (1-50, default 20)
 *   - include_predictions: Include ML predictions (default false)
 *   - include_value_bets: Include value bets (default false)
 */
export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;

    // Extract query parameters — canonicalLeagueId() validates against the
    // 7-competition closed set and returns null for unknown/display-form inputs.
    // ponytail: replaces .toUpperCase()+Set check; "La Liga"→"LA_LIGA" now works
    const requestedLeague = searchParams.get('league');
    const league = requestedLeague ? (canonicalLeagueId(requestedLeague) ?? undefined) : undefined;
    const daysAhead = boundedInteger(searchParams.get('days_ahead'), 7, 1, 30);
    const limit = boundedInteger(searchParams.get('limit'), 20, 1, 50);
    // Discovery-first default: callers must explicitly opt into bounded
    // enrichment to avoid accidental heavy-mode requests from omitted params.
    const includePredictions = booleanQuery(searchParams.get('include_predictions'), false);
    const includeValueBets = booleanQuery(searchParams.get('include_value_bets'), false);

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
      cache: 'no-store',
      signal: AbortSignal.timeout(BACKEND_DEADLINE_MS),
    });
    const body = await response.text().catch(() => '');

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          upcoming_matches: [],
          total: 0,
          matches_with_value: 0,
          avg_edge_pct: 0.0,
          cache_hit: false,
          ttl_seconds: 0,
          source: 'error',
          status: 'UNAVAILABLE',
          data_gap: true,
          reason: 'backend_service_unavailable',
          retryable: true,
          freshness: null,
          provenance: [],
          generated_at: new Date().toISOString(),
          deadline_ms: BACKEND_DEADLINE_MS,
          offseason: false,
          next_season_start: null,
        },
        { status: 503, headers: { 'Cache-Control': 'no-store' } }
      );
    }

    let data: Record<string, unknown>;
    try {
      data = JSON.parse(body);
    } catch {
      return NextResponse.json(
        {
          upcoming_matches: [],
          total: 0,
          matches_with_value: 0,
          avg_edge_pct: 0.0,
          cache_hit: false,
          ttl_seconds: 0,
          source: 'error',
          status: 'UNAVAILABLE',
          data_gap: true,
          reason: 'backend_invalid_response',
          retryable: true,
          freshness: null,
          provenance: [],
          generated_at: new Date().toISOString(),
          deadline_ms: BACKEND_DEADLINE_MS,
          offseason: false,
          next_season_start: null,
          error: 'Unexpected response from backend',
        },
        { status: 502, headers: { 'Cache-Control': 'no-store' } }
      );
    }

    return NextResponse.json(data, {
      headers: {
        'Cache-Control': 'no-store',
        'Content-Type': 'application/json',
      },
    });
  } catch {
    console.error('[Upcoming Matches] backend request failed');

    return NextResponse.json(
      {
        upcoming_matches: [],
        total: 0,
        matches_with_value: 0,
        avg_edge_pct: 0.0,
        cache_hit: false,
        ttl_seconds: 0,
        source: 'error',
        status: 'UNAVAILABLE',
        data_gap: true,
        reason: isLocalhostFallback() ? 'backend_url_not_configured' : 'backend_deadline_or_network_failure',
        retryable: true,
        freshness: null,
        provenance: [],
        generated_at: new Date().toISOString(),
        deadline_ms: BACKEND_DEADLINE_MS,
        offseason: false,
        next_season_start: null,
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}
