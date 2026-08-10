/** Drift cannot be asserted until authoritative settled samples are sufficient. */

import { NextResponse } from "next/server";

export const runtime = "edge";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(
    {
      status: "PENDING",
      driftDetected: null,
      severity: "unavailable",
      source: "backend_settlement",
      recommendation: "Await a certified settled-prediction evaluation window",
      timestamp: new Date().toISOString(),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
