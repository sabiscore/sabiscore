import { NextRequest, NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const BACKEND_DEADLINE_MS = 6_000;

export async function GET(request: NextRequest) {
  try {
    const requestedDays = Number(request.nextUrl.searchParams.get('days') ?? 7);
    const days = Number.isInteger(requestedDays) && requestedDays >= 1 && requestedDays <= 14
      ? requestedDays
      : 7;
    const backendBaseUrl = resolveBackendBaseUrl();
    const url = new URL(`${backendBaseUrl}/api/v1/value-bet-scan`);
    url.searchParams.set('days', String(days));

    const response = await fetch(url.toString(), {
      headers: proxyHeaders(),
      cache: 'no-store',
      signal: AbortSignal.timeout(BACKEND_DEADLINE_MS),
    });
    const body = await response.text().catch(() => '');

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          fixtures: [], total: 0, days, status: 'UNAVAILABLE', data_gap: true,
          reason: 'backend_service_unavailable', retryable: true, freshness: null,
          provenance: [], generated_at: new Date().toISOString(), deadline_ms: BACKEND_DEADLINE_MS,
        },
        { status: 503, headers: { 'Cache-Control': 'no-store' } }
      );
    }

    const raw = JSON.parse(body);
    // Backend (v5) returns { items, total, data_gap }; normalise to { fixtures, total, data_gap, days, source }
    const normalised = Array.isArray(raw)
      ? { fixtures: raw, total: raw.length, data_gap: false, days, source: "api" }
      : {
          fixtures: raw.items ?? raw.fixtures ?? [],
          total: raw.total ?? 0,
          data_gap: raw.data_gap ?? false,
          days,
          source: raw.source ?? "api",
          status: raw.status ?? "AVAILABLE",
          reason: raw.reason ?? null,
          retryable: raw.retryable ?? false,
          freshness: raw.freshness ?? null,
          provenance: raw.provenance ?? [],
          generated_at: raw.generated_at ?? null,
          deadline_ms: raw.deadline_ms ?? BACKEND_DEADLINE_MS,
        };
    return NextResponse.json(normalised, { headers: { 'Cache-Control': 'no-store' } });
  } catch {
    return NextResponse.json(
      {
        fixtures: [],
        total: 0,
        status: 'UNAVAILABLE',
        data_gap: true,
        days: 7,
        reason: 'backend_deadline_or_network_failure',
        retryable: true,
        freshness: null,
        provenance: [],
        generated_at: new Date().toISOString(),
        deadline_ms: BACKEND_DEADLINE_MS,
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } }
    );
  }
}
