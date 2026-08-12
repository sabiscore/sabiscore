import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The two-league-vocabulary trap has now shipped four times (vΩ.26 ×3 proxies,
 * then /api/upcoming and /api/fixtures/upcoming). Every instance looked
 * identical: normalize a league param with `.toUpperCase()`, compare against a
 * set of canonical ids, and silently drop the filter when they disagree.
 *
 * `"La Liga".toUpperCase()` is `"LA LIGA"` — space, not underscore — so it
 * never matches `"LA_LIGA"`. `"EPL"` is spelled identically in both
 * vocabularies, so any check exercised only with EPL passes under every broken
 * implementation. That is precisely why this kept recurring.
 *
 * `canonicalLeagueId()` (`src/lib/league.ts`) folds both vocabularies and
 * validates the seven-competition closed set. It is the only correct
 * normalizer, so this contract asserts that every route reading a league or
 * competition parameter actually reaches for it.
 */

const API_ROOT = join(process.cwd(), "src", "app", "api");

/**
 * Reads a league/competition value off the query string or route params.
 *
 * The destructured form matters as much as the dotted one: dynamic routes are
 * conventionally written `const { league } = await params`, which an earlier
 * version of this pattern missed — it would have skipped
 * `app/api/offseason/[league]/route.ts`, the very file most at risk.
 */
const READS_LEAGUE_PARAM = new RegExp(
  [
    // ?league= / ?competition=
    /searchParams\.get\(\s*['"](?:league|competition)['"]\s*\)/.source,
    // params.league / params.competition
    /params\.(?:league|competition)\b/.source,
    // const { league } = await params
    /\{\s*league\b[^}]*\}\s*=\s*(?:await\s+)?params/.source,
    // { params }: { params: Promise<{ league: string }> }
    /params:\s*Promise<\{\s*(?:league|competition)\b/.source,
  ].join("|"),
);

/** The broken idiom: upper-casing a league instead of canonicalizing it. */
const UPPERCASES_LEAGUE =
  /(?:league|competition)\w*\s*(?:\?\.|\.)\s*toUpperCase\s*\(\)/i;

function routeFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return routeFiles(path);
    if (entry.name.includes(".test.") || entry.name.includes(".spec.")) return [];
    return entry.name === "route.ts" ? [path] : [];
  });
}

function relative(path: string): string {
  return path.slice(join(process.cwd(), "src").length + 1).replace(/\\/g, "/");
}

describe("league normalization contract", () => {
  it("every API route reading a league param normalizes with canonicalLeagueId", () => {
    const offenders = routeFiles(API_ROOT)
      .filter((path) => {
        const source = readFileSync(path, "utf8");
        return READS_LEAGUE_PARAM.test(source) && !source.includes("canonicalLeagueId");
      })
      .map(relative);

    expect(offenders).toEqual([]);
  });

  it("no API route upper-cases a league instead of canonicalizing it", () => {
    const offenders = routeFiles(API_ROOT)
      .filter((path) => UPPERCASES_LEAGUE.test(readFileSync(path, "utf8")))
      .map(relative);

    expect(offenders).toEqual([]);
  });
});
