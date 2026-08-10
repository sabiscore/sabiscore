/** Local prediction-history export is retired with client-owned outcomes. */

import { NextResponse } from "next/server";

export const runtime = "edge";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(
    {
      error: "local_monitoring_retired",
      message: "Performance exports require authoritative backend settlement data",
      source: "backend_settlement",
    },
    { status: 410, headers: { "Cache-Control": "no-store" } },
  );
}
