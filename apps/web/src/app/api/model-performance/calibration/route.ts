import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-proxy";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const query = searchParams.toString();
  return proxyToBackend(
    req,
    `/api/v1/model-performance/calibration${query ? `?${query}` : ""}`
  );
}
