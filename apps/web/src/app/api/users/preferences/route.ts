import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/users/preferences");
}

export async function PUT(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/users/preferences");
}
