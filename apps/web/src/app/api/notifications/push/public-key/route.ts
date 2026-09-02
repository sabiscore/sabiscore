import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

/**
 * The VAPID application-server key the browser needs for `PushManager.subscribe`.
 *
 * Proxied rather than exposed as a `NEXT_PUBLIC_*` build variable: the key is
 * public by design (RFC 8292 section 2), but serving it from the backend means
 * rotating it is a backend restart instead of a frontend redeploy, and keeps
 * the repo free of another `NEXT_PUBLIC_*` credential-shaped variable.
 */
export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/notifications/push/public-key");
}
