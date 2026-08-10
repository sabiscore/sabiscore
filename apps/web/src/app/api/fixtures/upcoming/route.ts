import { NextRequest } from "next/server";
import { proxyFixtureRequest } from "../proxy";

const ALLOWED_COMPETITIONS = new Set([
  "EPL", "LA_LIGA", "SERIE_A", "BUNDESLIGA", "LIGUE_1", "EREDIVISIE", "UCL",
]);

export async function GET(req: NextRequest) {
  const competition = req.nextUrl.searchParams.get("competition")?.toUpperCase();
  const requestedLimit = Number(req.nextUrl.searchParams.get("limit") ?? 50);
  const params = new URLSearchParams();
  if (competition && ALLOWED_COMPETITIONS.has(competition)) {
    params.set("competition", competition);
  }
  params.set(
    "limit",
    String(Number.isInteger(requestedLimit) && requestedLimit >= 1 && requestedLimit <= 200 ? requestedLimit : 50),
  );
  const search = params.toString();
  return proxyFixtureRequest(req, `/api/v1/fixtures/upcoming${search ? `?${search}` : ""}`);
}
