import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

/** Register a browser push endpoint against the caller's identity. */
export async function POST(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/notifications/push/devices");
}

/** Deactivate a push endpoint (permission revoked, or the browser unsubscribed). */
export async function DELETE(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/notifications/push/devices");
}
