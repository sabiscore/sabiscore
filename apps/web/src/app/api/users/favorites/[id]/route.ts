import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  return proxyToBackend(req, `/api/v1/users/favorites/${encodeURIComponent(id)}`);
}
