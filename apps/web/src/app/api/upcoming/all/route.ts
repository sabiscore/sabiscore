/**
 * GET /api/upcoming/all
 *
 * Proxies merged all-leagues upcoming fixtures from backend.
 */

import { NextRequest, NextResponse } from "next/server";
import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 10;

export async function GET(request: NextRequest) {
  try {
    const searchParams = request.nextUrl.searchParams;
    const days = searchParams.get("days") || "7";
    const limit = searchParams.get("limit") || "200";
    if (!/^\d+$/.test(days) || Number(days) < 1 || Number(days) > 14 ||
        !/^\d+$/.test(limit) || Number(limit) < 1 || Number(limit) > 200) {
      return NextResponse.json(
        { fixtures: [], total: 0, days: 7, source: "validation", cache_ttl_seconds: 0, data_gap: true, reason: "INVALID_UPCOMING_QUERY" },
        { status: 400, headers: { "Cache-Control": "no-store" } },
      );
    }

    const backendBaseUrl = resolveBackendBaseUrl();
    const url = new URL(`${backendBaseUrl}/api/v1/upcoming/all`);
    url.searchParams.set("days", days);
    url.searchParams.set("limit", limit);

    const response = await fetch(url.toString(), {
      method: "GET",
      headers: proxyHeaders(),
      signal: AbortSignal.timeout(5_000),
      cache: "no-store",
    });

    const body = await response.text().catch(() => "");
    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          fixtures: [],
          total: 0,
          days: Number(days),
          source: "error",
          cache_ttl_seconds: 300,
          data_gap: true,
          reason: "UPCOMING_BACKEND_UNAVAILABLE",
          error: "Backend service unavailable",
        },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }

    try {
      const data = JSON.parse(body) as Record<string, unknown>;
      return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
    } catch {
      return NextResponse.json(
        { fixtures: [], total: 0, days: Number(days), source: "backend_error", cache_ttl_seconds: 0, data_gap: true, reason: "UPCOMING_BACKEND_INVALID_RESPONSE" },
        { status: 502, headers: { "Cache-Control": "no-store" } },
      );
    }
  } catch (error: unknown) {
    const timedOut = error instanceof Error && ["AbortError", "TimeoutError"].includes(error.name);
    return NextResponse.json(
      {
        fixtures: [],
        total: 0,
        days: 7,
        source: timedOut ? "timeout" : "proxy_error",
        cache_ttl_seconds: 0,
        data_gap: true,
        reason: timedOut ? "UPCOMING_PROXY_TIMEOUT" : "UPCOMING_PROXY_UNAVAILABLE",
        error: timedOut ? "Upcoming fixtures timed out" : "Upcoming fixtures unavailable",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
