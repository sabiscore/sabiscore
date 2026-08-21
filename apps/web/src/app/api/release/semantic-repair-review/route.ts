import { NextResponse } from "next/server";
import {
  ERROR_CACHE_HEADERS,
  isHtmlBody,
  proxyHeaders,
  resolveBackendBaseUrl,
  sanitizeBackendError,
} from "@/lib/proxy-utils";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const response = await fetch(
      `${resolveBackendBaseUrl()}/api/v1/release/semantic-repair-review`,
      {
        headers: proxyHeaders(),
        cache: "no-store",
      },
    );
    const body = await response.text().catch(() => "");

    if (!response.ok || isHtmlBody(body)) {
      return NextResponse.json(
        {
          status: "UNAVAILABLE",
          detail: sanitizeBackendError(body, response.status),
        },
        {
          status: response.ok ? 502 : response.status,
          headers: ERROR_CACHE_HEADERS,
        },
      );
    }

    try {
      return NextResponse.json(JSON.parse(body), {
        status: response.status,
        headers: ERROR_CACHE_HEADERS,
      });
    } catch {
      return NextResponse.json(
        {
          status: "UNAVAILABLE",
          detail: "Backend returned invalid JSON",
        },
        { status: 502, headers: ERROR_CACHE_HEADERS },
      );
    }
  } catch {
    return NextResponse.json(
      {
        status: "UNAVAILABLE",
        detail: "Backend service unavailable",
      },
      { status: 503, headers: ERROR_CACHE_HEADERS },
    );
  }
}
