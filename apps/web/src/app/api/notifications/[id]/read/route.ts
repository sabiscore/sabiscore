import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  return proxyToBackend(
    req,
    `/api/v1/notifications/in-app/${encodeURIComponent(id)}/read`
  );
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const modifiedReq = new NextRequest(req.url, {
    method: "POST",
    headers: req.headers,
  });
  return proxyToBackend(
    modifiedReq,
    `/api/v1/notifications/in-app/${encodeURIComponent(id)}/read`
  );
}
