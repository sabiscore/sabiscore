import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function GET(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/users/saved-matches");
}

export async function POST(req: NextRequest) {
  return proxyToBackend(req, "/api/v1/users/saved-matches");
}
