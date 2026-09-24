import { NextRequest, NextResponse } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function GET(req: NextRequest) {
  // The backend authenticates only a bearer token or the sabi_session cookie.
  // Without either the answer is always 401, which every anonymous page
  // load logged as a console error and paid a backend round-trip for.
  // `null` is what auth-context already treats as "signed out".
  if (!req.headers.get("authorization") && !req.cookies.get("sabi_session")) {
    return NextResponse.json(null, { headers: { "Cache-Control": "no-store" } });
  }
  return proxyToBackend(req, "/api/v1/auth/me");
}
