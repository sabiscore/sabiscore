import { NextRequest } from "next/server";
import { proxyFixtureRequest } from "../proxy";
import { canonicalLeagueId } from "@/lib/league";

export async function GET(req: NextRequest) {
  // Same trap as /api/upcoming: `.toUpperCase()` turns "La Liga" into
  // "LA LIGA" (space, not underscore), which missed the canonical allowlist
  // and silently dropped the filter. canonicalLeagueId() folds both
  // vocabularies and validates the 7-competition closed set, so the local
  // Set was redundant. The /intelligence dropdown happens to send canonical
  // ids today, but this is a public route and an exported client helper.
  const requested = req.nextUrl.searchParams.get("competition");
  const competition = requested ? canonicalLeagueId(requested) : null;
  const requestedLimit = Number(req.nextUrl.searchParams.get("limit") ?? 50);
  const params = new URLSearchParams();
  if (competition) {
    params.set("competition", competition);
  }
  params.set(
    "limit",
    String(Number.isInteger(requestedLimit) && requestedLimit >= 1 && requestedLimit <= 200 ? requestedLimit : 50),
  );
  const search = params.toString();
  return proxyFixtureRequest(req, `/api/v1/fixtures/upcoming${search ? `?${search}` : ""}`);
}
