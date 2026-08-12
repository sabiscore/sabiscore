import { NextRequest, NextResponse } from "next/server";
import { resolveBackendBaseUrl, proxyHeaders, isHtmlBody } from "@/lib/proxy-utils";
import { canonicalLeagueId } from "@/lib/league";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    // Normalize at the boundary like every other league-parameterized proxy:
    // an unrecognised league is dropped rather than forwarded verbatim.
    const requestedLeague = request.nextUrl.searchParams.get("league");
    const league = requestedLeague ? canonicalLeagueId(requestedLeague) : null;
    const nBins = request.nextUrl.searchParams.get("n_bins") ?? "10";
    const url = new URL(`${resolveBackendBaseUrl()}/api/v1/calibration-stats`);
    if (league) url.searchParams.set("league", league);
    url.searchParams.set("n_bins", nBins);

    const res = await fetch(url.toString(), { headers: proxyHeaders() });
    const body = await res.text().catch(() => "");

    if (!res.ok || isHtmlBody(body)) {
      return NextResponse.json({ error: "Backend service unavailable" }, { status: 503 });
    }

    try {
      return NextResponse.json(JSON.parse(body), {
        headers: { "Cache-Control": "public, max-age=600" },
      });
    } catch {
      return NextResponse.json({ error: "Unexpected response from backend" }, { status: 502 });
    }
  } catch (error: unknown) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Unknown" },
      { status: 503 },
    );
  }
}
