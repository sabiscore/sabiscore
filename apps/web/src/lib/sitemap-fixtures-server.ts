/**
 * Server-side fixture fetch for `sitemap.ts`.
 *
 * Same reason as `team-intelligence-server.ts`: `sitemap.ts` runs server-only
 * and cannot fetch a relative URL (undici throws on `/api/...`), so this calls
 * the backend directly via `SABISCORE_BACKEND_URL`. Fails closed to an empty
 * list on any error, timeout, or malformed response — a broken backend must
 * never crash sitemap generation, and a fixture id must pass the same shape
 * check the fixture-proxy route enforces before it's trusted enough to publish.
 */

import { isHtmlBody, proxyHeaders, resolveBackendBaseUrl } from "@/lib/proxy-utils";

const FIXTURE_ID_PATTERN = /^[a-zA-Z0-9_-]{1,64}$/;

export interface SitemapFixture {
  fixtureId: string;
  competition: string;
}

interface FixtureSummary {
  fixture_id?: unknown;
  competition?: unknown;
}

interface UpcomingFixturesResponse {
  fixtures?: FixtureSummary[];
}

export async function getSitemapFixtures(limit = 200): Promise<SitemapFixture[]> {
  const url = `${resolveBackendBaseUrl()}/api/v1/fixtures/upcoming?limit=${limit}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: proxyHeaders(),
      // Cached, NOT no-store: this is a bounded fixture *listing*, not an
      // evidence/decision endpoint, so the no-store rule doesn't apply here.
      // A no-store fetch would opt the whole sitemap route into dynamic
      // rendering and silently defeat its `export const revalidate = 3600`,
      // turning "one cheap DB read per hour" into one per crawler request.
      next: { revalidate: 3600 },
      signal: AbortSignal.timeout(8_000),
    });
  } catch {
    return [];
  }

  const bodyText = await response.text().catch(() => "");
  if (!response.ok || isHtmlBody(bodyText)) return [];

  let parsed: UpcomingFixturesResponse;
  try {
    parsed = JSON.parse(bodyText) as UpcomingFixturesResponse;
  } catch {
    return [];
  }

  if (!Array.isArray(parsed.fixtures)) return [];

  const result: SitemapFixture[] = [];
  for (const fixture of parsed.fixtures) {
    const fixtureId = fixture.fixture_id;
    const competition = fixture.competition;
    if (typeof fixtureId !== "string" || typeof competition !== "string") continue;
    if (!FIXTURE_ID_PATTERN.test(fixtureId)) continue;
    result.push({ fixtureId, competition });
  }
  return result;
}
