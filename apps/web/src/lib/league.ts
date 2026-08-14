/**
 * Canonical league identifiers.
 *
 * Two vocabularies exist in this app and both are load-bearing:
 *   - Display form ("La Liga", "Serie A", "Ligue 1") keys team lists, logos,
 *     and colour maps (`team-data.ts`, `logo-resolver.ts`, `league-colors.ts`).
 *   - Canonical form ("LA_LIGA", "SERIE_A", "LIGUE_1") is what the API layer
 *     and the sidebar use.
 *
 * Mixing them produced a 400 on every non-EPL match page: the selector pushed
 * `?league=La Liga` and the proxy's enum only accepted `LA_LIGA`. EPL hid the
 * bug because both vocabularies spell it the same way.
 *
 * This mirrors `canonical_league_id` in backend/src/core/league_policy.py
 * exactly — lowercase, fold separators to `_`, alias-lookup, else upper-case —
 * so the two sides cannot drift.
 */

const ALIASES: Record<string, string> = {
  premier_league: "EPL",
  epl: "EPL",
  la_liga: "LA_LIGA",
  laliga: "LA_LIGA",
  bundesliga: "BUNDESLIGA",
  serie_a: "SERIE_A",
  ligue_1: "LIGUE_1",
  eredivisie: "EREDIVISIE",
  ucl: "UCL",
  champions_league: "UCL",
  uefa_champions_league: "UCL",
};

export const CANONICAL_LEAGUES = [
  "EPL",
  "LA_LIGA",
  "BUNDESLIGA",
  "SERIE_A",
  "LIGUE_1",
  "EREDIVISIE",
  "UCL",
] as const;

export type CanonicalLeague = (typeof CANONICAL_LEAGUES)[number];

const LEAGUE_DISPLAY_NAMES: Record<CanonicalLeague, string> = {
  EPL: "Premier League",
  LA_LIGA: "La Liga",
  BUNDESLIGA: "Bundesliga",
  SERIE_A: "Serie A",
  LIGUE_1: "Ligue 1",
  EREDIVISIE: "Eredivisie",
  UCL: "UEFA Champions League",
};

/** Normalize any accepted spelling to its canonical id, or null if unsupported. */
export function canonicalLeagueId(input: string | null | undefined): CanonicalLeague | null {
  const key = (input ?? "").trim();
  if (!key) return null;
  const normalized = key.toLowerCase().replace(/[-\s]+/g, "_");
  const resolved = ALIASES[normalized] ?? key.toUpperCase();
  return (CANONICAL_LEAGUES as readonly string[]).includes(resolved)
    ? (resolved as CanonicalLeague)
    : null;
}

/** Resolve a supported spelling to its user-facing league name. */
export function leagueDisplayName(input: string | null | undefined): string {
  const canonical = canonicalLeagueId(input);
  return canonical ? LEAGUE_DISPLAY_NAMES[canonical] : (input?.trim() || "This league");
}
