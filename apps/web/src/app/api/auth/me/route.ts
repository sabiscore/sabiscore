import { NextRequest, NextResponse } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

const SESSION_COOKIE = "sabi_session";

function signedOut(): NextResponse {
  return NextResponse.json(null, { headers: { "Cache-Control": "no-store" } });
}

export async function GET(req: NextRequest) {
  const bearer = req.headers.get("authorization");
  // The backend authenticates only a bearer token or the sabi_session cookie.
  // Without either the answer is always 401, which every anonymous page
  // load logged as a console error and paid a backend round-trip for.
  // `null` is what auth-context already treats as "signed out".
  if (!bearer && !req.cookies.get(SESSION_COOKIE)) return signedOut();

  const res = await proxyToBackend(req, "/api/v1/auth/me");
  // A session cookie the backend rejects (expired token, rotated key, deleted
  // user) is still sent on every page load, so each one logged a 401 until the
  // cookie aged out. Clear it and answer "signed out" instead. A rejected
  // bearer token stays a 401: that caller chose the credential.
  if (res.status === 401 && !bearer) {
    const out = signedOut();
    out.cookies.delete(SESSION_COOKIE);
    return out;
  }
  return res;
}
