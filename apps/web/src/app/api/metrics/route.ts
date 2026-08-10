/** Compatibility metrics route backed only by authoritative settlement data. */

import { NextResponse } from "next/server";
import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(`${resolveBackendBaseUrl()}/api/v1/model-performance/summary`, {
      headers: proxyHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    const body = await response.text().catch(() => "");
    if (isHtmlBody(body)) {
      throw new Error("backend_unavailable");
    }
    const summary = JSON.parse(body) as Record<string, unknown>;
    return NextResponse.json(
      {
        status: summary.status === "OK" ? "MEASURED" : "PENDING",
        source: "backend_settlement",
        summary,
      },
      { status: response.status, headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      {
        status: "PENDING",
        source: "backend_settlement",
        reason: "backend_unavailable",
      },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
