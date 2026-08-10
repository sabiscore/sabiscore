import { NextRequest, NextResponse } from 'next/server';
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from '@/lib/proxy-utils';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export const maxDuration = 10;

const PROXY_TIMEOUT_MS = 5_000;

export async function GET(request: NextRequest) {
  try {
    const rawDays = request.nextUrl.searchParams.get('days') || '7';
    if (!/^\d+$/.test(rawDays) || Number(rawDays) < 1 || Number(rawDays) > 14) {
      return NextResponse.json(
        { fixtures: [], total: 0, days: 7, data_gap: true, reason: 'INVALID_SCAN_WINDOW', source: 'validation' },
        { status: 400, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    const days = Number(rawDays);
    const backendBaseUrl = resolveBackendBaseUrl();
    const url = new URL(`${backendBaseUrl}/api/v1/value-bet-scan`);
    url.searchParams.set('days', String(days));

    const response = await fetch(url.toString(), {
      headers: proxyHeaders(),
      signal: AbortSignal.timeout(PROXY_TIMEOUT_MS),
      cache: 'no-store',
    });
    const body = await response.text().catch(() => '');

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          fixtures: [],
          total: 0,
          days,
          data_gap: true,
          reason: 'VALUE_SCAN_BACKEND_UNAVAILABLE',
          source: 'backend_error',
          error: 'Backend service unavailable',
        },
        { status: 503, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    let raw: Record<string, unknown> | unknown[];
    try {
      raw = JSON.parse(body) as Record<string, unknown> | unknown[];
    } catch {
      return NextResponse.json(
        { fixtures: [], total: 0, days, data_gap: true, reason: 'VALUE_SCAN_INVALID_RESPONSE', source: 'backend_error' },
        { status: 502, headers: { 'Cache-Control': 'no-store' } },
      );
    }
    // Backend (v5) returns { items, total, data_gap }; normalise to { fixtures, total, data_gap, days, source }
    const normalised = Array.isArray(raw)
      ? { fixtures: raw, total: raw.length, data_gap: false, days, source: "api" }
      : {
          fixtures: raw.items ?? raw.fixtures ?? [],
          total: raw.total ?? 0,
          data_gap: raw.data_gap ?? false,
          reason: raw.reason ?? null,
          generated_at: raw.generated_at ?? null,
          days,
          source: raw.source ?? "api",
        };
    return NextResponse.json(normalised, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error: unknown) {
    const timedOut = error instanceof Error && ['AbortError', 'TimeoutError'].includes(error.name);
    return NextResponse.json(
      {
        fixtures: [],
        total: 0,
        data_gap: true,
        days: 7,
        reason: timedOut ? 'VALUE_SCAN_PROXY_TIMEOUT' : 'VALUE_SCAN_PROXY_UNAVAILABLE',
        source: timedOut ? 'timeout' : 'proxy_error',
        error: timedOut ? 'Value scan timed out' : 'Value scan unavailable',
      },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
