import type { MetadataRoute } from "next";

import { CANONICAL_LEAGUES } from "@/lib/league";
import { getSitemapFixtures } from "@/lib/sitemap-fixtures-server";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ??
  (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "https://sabiscore.com");

// Fixture listing is a bounded, cheap DB read (no provider calls, no model
// inference) — 1h keeps sitemap traffic off the hot path while staying fresh
// enough for crawlers, matching the TTL convention used by /api/leagues and
// /api/offseason/[league].
export const revalidate = 3600;

const CORE_ROUTES = [
  "/",
  "/intelligence",
  "/match",
  "/performance",
  "/developer",
  "/docs",
  "/dashboard",
];

const TOP_TEAMS = [
  "arsenal",
  "chelsea",
  "liverpool",
  "manchester-city",
  "manchester-united",
  "tottenham",
  "real-madrid",
  "barcelona",
  "bayern-munich",
  "borussia-dortmund",
  "juventus",
  "inter-milan",
  "ac-milan",
  "paris-saint-germain",
  "ajax",
];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const lastModified = new Date();

  const coreEntries: MetadataRoute.Sitemap = CORE_ROUTES.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified,
    changeFrequency: path === "/" || path === "/intelligence" ? "hourly" : "daily",
    priority: path === "/" ? 1.0 : path === "/intelligence" || path === "/performance" ? 0.9 : 0.7,
  }));

  const leagueEntries: MetadataRoute.Sitemap = CANONICAL_LEAGUES.map((code) => ({
    url: `${SITE_URL}/intelligence?league=${encodeURIComponent(code)}`,
    lastModified,
    changeFrequency: "hourly",
    priority: 0.8,
  }));

  const teamEntries: MetadataRoute.Sitemap = TOP_TEAMS.map((slug) => ({
    url: `${SITE_URL}/team/${slug}`,
    lastModified,
    changeFrequency: "daily",
    priority: 0.7,
  }));

  // Live, bounded, fail-closed: real scheduled fixtures from the backend, or
  // nothing at all if it's unreachable — never a fabricated/sample id.
  const fixtures = await getSitemapFixtures();
  const fixtureEntries: MetadataRoute.Sitemap = fixtures.map(({ fixtureId, competition }) => ({
    url: `${SITE_URL}/match/${encodeURIComponent(fixtureId)}?league=${encodeURIComponent(competition)}`,
    lastModified,
    changeFrequency: "hourly",
    priority: 0.8,
  }));

  return [...coreEntries, ...leagueEntries, ...teamEntries, ...fixtureEntries];
}
