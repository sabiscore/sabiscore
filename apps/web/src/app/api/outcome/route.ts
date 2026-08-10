/** Public outcome mutation is retired. Settlement is backend-owned. */

import { NextResponse } from "next/server";

export const runtime = "edge";
export const dynamic = "force-dynamic";

function retiredResponse() {
  return NextResponse.json(
    {
      error: "outcome_mutation_retired",
      message: "Outcomes are settled by the authoritative backend and cannot be mutated publicly",
      settlementSource: "backend",
    },
    { status: 410, headers: { "Cache-Control": "no-store" } },
  );
}

export async function POST() {
  return retiredResponse();
}

export async function PUT() {
  return retiredResponse();
}
