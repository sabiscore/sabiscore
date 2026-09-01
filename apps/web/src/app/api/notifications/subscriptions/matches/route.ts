import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function POST(req: NextRequest) {
  try {
    const rawBody = await req.json();
    let body = rawBody;
    if (rawBody && rawBody.fixture_id && !rawBody.match_id) {
      body = {
        ...rawBody,
        match_id: rawBody.fixture_id,
      };
    }
    const modifiedReq = new NextRequest(req.url, {
      method: "POST",
      headers: req.headers,
      body: JSON.stringify(body),
    });
    return proxyToBackend(modifiedReq, "/api/v1/notifications/subscriptions/matches");
  } catch {
    return proxyToBackend(req, "/api/v1/notifications/subscriptions/matches");
  }
}

export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/notifications/subscriptions/matches");
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const matchId = searchParams.get("match_id");
  if (matchId) {
    return proxyToBackend(req, `/api/v1/notifications/subscriptions/matches/${encodeURIComponent(matchId)}`);
  }
  return proxyToBackend(req, "/api/v1/notifications/subscriptions/matches");
}
