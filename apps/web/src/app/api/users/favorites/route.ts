import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/users/favorites");
}

export async function POST(req: NextRequest) {
  try {
    const rawBody = await req.json();
    let body = rawBody;
    // Adapt team_id shorthand to backend FavoriteCreate schema if needed
    if (rawBody && rawBody.team_id && !rawBody.entity_id) {
      body = {
        entity_type: "team",
        entity_id: rawBody.team_id,
      };
    }
    const modifiedReq = new NextRequest(req.url, {
      method: "POST",
      headers: req.headers,
      body: JSON.stringify(body),
    });
    return proxyToBackend(modifiedReq, "/api/v1/users/favorites");
  } catch {
    return proxyToBackend(req, "/api/v1/users/favorites");
  }
}

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const query = searchParams.toString();
  return proxyToBackend(req, `/api/v1/users/favorites${query ? `?${query}` : ""}`);
}
