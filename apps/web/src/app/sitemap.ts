import type { MetadataRoute } from "next";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ??
  (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "https://sabiscore.com");

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

const LEAGUES = [
  "EPL",
  "LA_LIGA",
  "SERIE_A",
  "BUNDESLIGA",
  "LIGUE_1",
  "EREDIVISIE",
  "UCL",
];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();

  const coreEntries: MetadataRoute.Sitemap = CORE_ROUTES.map((path) => ({
    url: `${SITE_URL}${path}`,
    lastModified,
    changeFrequency: path === "/" || path === "/intelligence" ? "hourly" : "daily",
    priority: path === "/" ? 1.0 : path === "/intelligence" || path === "/performance" ? 0.9 : 0.7,
  }));

  const leagueEntries: MetadataRoute.Sitemap = LEAGUES.map((code) => ({
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

  // Example verified fixture routes for programmatic discovery
  const sampleFixtures = [
    "arsenal-vs-chelsea",
    "liverpool-vs-manchester-city",
    "real-madrid-vs-barcelona",
    "bayern-munich-vs-borussia-dortmund",
    "inter-milan-vs-ac-milan",
  ];

  const fixtureEntries: MetadataRoute.Sitemap = sampleFixtures.map((id) => ({
    url: `${SITE_URL}/match/${id}`,
    lastModified,
    changeFrequency: "hourly",
    priority: 0.8,
  }));

  return [...coreEntries, ...leagueEntries, ...teamEntries, ...fixtureEntries];
}
