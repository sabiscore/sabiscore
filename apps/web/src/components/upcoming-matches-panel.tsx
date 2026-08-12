"use client";

import { memo, useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { LEAGUE_COLORS } from "@/lib/league-colors";
import { getUpcomingMatches } from "@/lib/api";
import { LeagueOffseasonNotice } from "@/components/LeagueOffseasonNotice";
import { UCLStageBadge } from "@/components/UCLStageBadge";
import { EdgeQualityBar } from "@/components/edge-quality-bar";

// ─── League types (from /api/v1/leagues) ─────────────────────────────────────

interface LeagueListItem {
  id: string;
  name: string;
  coverage: "FULL" | "SOFT" | "EXPERIMENTAL";
  low_evidence_allowed: boolean;
  caveat_text: string | null;
}

// Compact fallback while API loads — keeps filter bar snappy
const LEAGUE_FALLBACK: LeagueListItem[] = [
  { id: "EPL", name: "Premier League", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "La Liga", name: "La Liga", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "Bundesliga", name: "Bundesliga", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "Serie A", name: "Serie A", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "Ligue 1", name: "Ligue 1", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "Eredivisie", name: "Eredivisie", coverage: "FULL", low_evidence_allowed: false, caveat_text: null },
  { id: "UCL", name: "UCL", coverage: "SOFT", low_evidence_allowed: true, caveat_text: "Soft coverage — higher epistemic uncertainty" },
];

async function fetchLeagues(): Promise<LeagueListItem[]> {
  try {
    const res = await fetch("/api/leagues", { cache: "no-store" });
    if (!res.ok) return LEAGUE_FALLBACK;
    const data: unknown = await res.json();
    return Array.isArray(data) && data.length > 0 ? (data as LeagueListItem[]) : LEAGUE_FALLBACK;
  } catch {
    return LEAGUE_FALLBACK;
  }
}

// ─── League filter bar ────────────────────────────────────────────────────────

function LeagueFilterBar({
  selected,
  onChange,
}: {
  selected: string | null;
  onChange: (id: string | null) => void;
}) {
  const { data: leagues } = useQuery({
    queryKey: ["leagues-list"],
    queryFn: fetchLeagues,
    staleTime: 3600_000,
    placeholderData: LEAGUE_FALLBACK,
  });

  const items = leagues ?? LEAGUE_FALLBACK;

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      role="group"
      aria-label="Filter by league"
    >
      <button
        onClick={() => onChange(null)}
        aria-pressed={selected === null}
        className={cn(
          "rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors",
          selected === null
            ? "border-slate-400/40 bg-slate-700 text-white"
            : "border-slate-700/50 text-slate-500 hover:text-slate-300",
        )}
      >
        All
      </button>
      {items.map((l) => (
        <button
          key={l.id}
          onClick={() => onChange(selected === l.id ? null : l.id)}
          aria-pressed={selected === l.id}
          title={l.caveat_text ?? l.name}
          className={cn(
            "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-wider transition-colors",
            selected === l.id
              ? LEAGUE_COLORS[l.id] ?? "border-slate-400/40 bg-slate-700 text-white"
              : "border-slate-700/50 text-slate-500 hover:text-slate-300",
          )}
        >
          {l.id}
          {l.coverage === "SOFT" && (
            <span className="text-[8px] font-normal normal-case tracking-normal opacity-70">~</span>
          )}
        </button>
      ))}
    </div>
  );
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface UpcomingMatch {
  match_id: string;
  home_team: string;
  away_team: string;
  league: string;
  match_date: string;
  status: string;
  has_value: boolean;
  staleness_seconds?: number;
  data_gaps?: string[];
  best_value_bet?: {
    edge_pct: number;
    confidence: number;
    outcome: string;
  } | null;
  data_quality?: {
    historical_data_ratio: number;
    defaults_used_count: number;
    is_synthetic: boolean;
  } | null;
  predictions?: {
    home_win?: number;
    draw_prob?: number;
    draw?: number;
    away_win_prob?: number;
    away_win?: number;
    prediction?: string;
    confidence?: number;
  } | null;
  /** Composite edge quality score 0–1. Null when neither predictions nor value bets are present. */
  edge_quality_score?: number | null;
  /** Closing-line value %. Always null pre-kick-off. */
  clv_pct?: number | null;
  /** UCL knockout/group stage slug: "group" | "r16" | "qf" | "sf" | "final". Null for domestic leagues. */
  competition_stage?: string | null;
  /** Advisory portfolio-exposure annotation (ADR-0005). Null on non-value fixtures. */
  portfolio?: {
    raw_kelly_stake_pct: number;
    correlation_group_size: number;
    correlation_haircut_multiplier: number;
    adjusted_kelly_stake_pct: number;
    exceeds_aggregate_cap: boolean;
  } | null;
}

interface UpcomingMatchesResponse {
  upcoming_matches: UpcomingMatch[];
  total: number;
  matches_with_value: number;
  avg_edge_pct: number;
  source: string;
  offseason?: boolean;
  next_season_start?: string | null;
  /** True when the backend failed to build the list, as opposed to genuinely
   *  having no fixtures. Must stay distinguishable from an empty in-season
   *  window: reporting a backend failure as "no fixtures" hid a total outage
   *  behind a plausible empty state. */
  data_gap?: boolean;
  /** Batch-level advisory exposure summary (ADR-0005). Null when predictions weren't requested. */
  portfolio_exposure?: {
    aggregate_recommended_pct: number;
    aggregate_cap_pct: number;
    exceeds_aggregate_cap: boolean;
    drawdown: { status: string; realized_drawdown_pct: number | null; paused: boolean };
  } | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
// EdgeQualityBar (+ edgeQualityLabel/edgeQualityColor) now live in
// @/components/edge-quality-bar and @/lib/edge-quality — shared with
// match-selector.tsx's BigMatchesCarousel, same precedent as LEAGUE_COLORS.

// ─── CLVBadge ─────────────────────────────────────────────────────────────────

function CLVBadge({ clvPct }: { clvPct: number }) {
  const isPositive = clvPct >= 0;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tabular-nums",
        isPositive
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : "border-rose-500/30 bg-rose-500/10 text-rose-300"
      )}
      title="Closing-line value (CLV)"
      aria-label={`CLV ${clvPct >= 0 ? "+" : ""}${clvPct.toFixed(1)}%`}
    >
      CLV {clvPct >= 0 ? "+" : ""}{clvPct.toFixed(1)}%
    </span>
  );
}

function leagueChip(league: string) {
  return cn(
    "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
    LEAGUE_COLORS[league] ?? "border-slate-700/50 text-slate-400 bg-slate-800/50"
  );
}

function formatMatchDate(dateStr: string) {
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
}

function freshnessLabel(stalenessSeconds?: number) {
  const age = stalenessSeconds ?? 0;
  if (age <= 0) {
    return { label: "Live", className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" };
  }
  if (age < 86400) {
    return { label: "Recent", className: "border-amber-500/30 bg-amber-500/10 text-amber-300" };
  }
  return { label: "Stale", className: "border-rose-500/30 bg-rose-500/10 text-rose-300" };
}

/**
 * Discovery window, in days. MUST stay aligned with the backend's
 * `fixture_sync_service.SYNC_HORIZON_DAYS` — fixtures outside the sync
 * horizon are never seeded, so asking for more returns nothing.
 *
 * Single source of truth for BOTH the query and the empty-state copy. These
 * were two independent literals and drifted: the query asked for 7 days while
 * the backend synced 14, and the copy quoted its own third number.
 */
const VISIBLE_WINDOW_DAYS = 14;
/** Fixtures rendered in the panel. */
const VISIBLE_MATCH_LIMIT = 12;
/** Fetched from the backend — a margin above what's rendered so the
 *  "showing N of M" count is meaningful. Cheap: this call always sets
 *  include_predictions=false, so it is a bounded DB read with no model work. */
const FETCH_MATCH_LIMIT = 24;

async function fetchUpcoming(league?: string): Promise<UpcomingMatchesResponse> {
  return getUpcomingMatches({
    league,
    limit: FETCH_MATCH_LIMIT,
    days_ahead: VISIBLE_WINDOW_DAYS,
  }) as Promise<UpcomingMatchesResponse>;
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function PanelSkeleton() {
  return (
    <div className="space-y-3 animate-pulse" aria-busy="true" aria-label="Loading upcoming matches">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="h-16 rounded-xl bg-slate-800/50" />
      ))}
    </div>
  );
}

// ─── Match row ────────────────────────────────────────────────────────────────

function MatchRow({ match }: { match: UpcomingMatch }) {
  // Route by the real canonical match_id when the API supplied one, so the
  // backend can verify fixture identity instead of falling back to the
  // unverified "Home vs Away" matchup path. home/away/league travel as query
  // params for the legacy Phase-7 insights call and the page title, which
  // still need team-name strings.
  const href = match.match_id
    ? `/match/${encodeURIComponent(match.match_id)}?league=${encodeURIComponent(match.league)}&home=${encodeURIComponent(match.home_team)}&away=${encodeURIComponent(match.away_team)}`
    : `/match/${encodeURIComponent(`${match.home_team} vs ${match.away_team}`)}?league=${encodeURIComponent(match.league)}`;
  const conf = match.predictions?.confidence ?? null;
  const edge = match.best_value_bet?.edge_pct ?? null;
  const freshness = freshnessLabel(match.staleness_seconds);
  const hasDataGaps = Boolean(match.data_gaps && match.data_gaps.length > 0);
  const eqs = match.edge_quality_score ?? null;
  const clv = match.clv_pct ?? null;
  const stage = match.competition_stage ?? null;

  const confLabel = conf !== null ? ` · ${(conf * 100).toFixed(0)}% confidence` : "";
  const valueLabelPart = match.has_value ? " · value bet" : "";
  const freshnessAria = ` · ${freshness.label.toLowerCase()} data`;
  const partialAria = hasDataGaps ? " · partial intelligence" : "";
  const ariaLabel = `${match.home_team} vs ${match.away_team} · ${match.league} · ${formatMatchDate(match.match_date)}${valueLabelPart}${confLabel}${freshnessAria}${partialAria}`;

  return (
    <Link
      href={href}
      aria-label={ariaLabel}
      className="group flex items-center justify-between gap-4 rounded-xl border border-slate-800/60 bg-slate-900/50 px-4 py-3 transition hover:border-indigo-500/30 hover:bg-slate-900/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-950"
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="truncate text-sm font-medium text-slate-200 group-hover:text-white transition-colors">
          {match.home_team}
          <span className="mx-1.5 text-slate-600">vs</span>
          {match.away_team}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <span className={leagueChip(match.league)}>{match.league}</span>
          <span className="text-[10px] text-slate-600">
            {formatMatchDate(match.match_date)}
            {" · "}
            {new Date(match.match_date).toLocaleTimeString("en-NG", {
              hour: "2-digit", minute: "2-digit",
              timeZone: "Africa/Lagos", hour12: false,
            })}
          </span>
          <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider", freshness.className)}>
            {freshness.label}
          </span>
          {stage && <UCLStageBadge stage={stage} compact />}
          {hasDataGaps && (
            <span className="inline-flex items-center rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-fuchsia-300">
              Partial
            </span>
          )}
          {match.portfolio?.exceeds_aggregate_cap && (
            <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
              Exceeds portfolio cap
            </span>
          )}
          {clv !== null && <CLVBadge clvPct={clv} />}
        </div>
      </div>

      <div className="flex flex-shrink-0 items-center gap-3">
        {eqs !== null && (
          <div className="hidden sm:block">
            <EdgeQualityBar score={eqs} />
          </div>
        )}
        {match.has_value && (
          <span className="hidden sm:inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
            Value {edge !== null ? `${edge.toFixed(1)}%` : ""}
          </span>
        )}
        {conf !== null && (
          <div className="hidden min-w-[4.5rem] sm:block text-right">
            <p className="text-xs font-bold text-slate-300">{(conf * 100).toFixed(0)}%</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-600">confidence</p>
          </div>
        )}
        <svg
          className="h-3.5 w-3.5 flex-shrink-0 text-slate-700 group-hover:text-indigo-400 transition-colors"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          aria-hidden
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
      </div>
    </Link>
  );
}

// ─── Panel ────────────────────────────────────────────────────────────────────

interface UpcomingMatchesPanelProps {
  /** Fixed league filter — when provided the internal filter bar is hidden. */
  league?: string;
  title?: string;
}

function UpcomingMatchesPanelInner({ league: leagueProp, title = "Upcoming Fixtures" }: UpcomingMatchesPanelProps) {
  // Internal league filter — overridden by the `league` prop when provided
  const [selectedLeague, setSelectedLeague] = useState<string | null>(null);
  const activeLeague = leagueProp ?? selectedLeague ?? undefined;

  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ["upcomingMatches", activeLeague ?? "all"],
    queryFn: () => fetchUpcoming(activeLeague),
    staleTime: 5 * 60_000,
  });

  // Derive off-season state from the matches response — avoids a redundant /api/offseason fetch.
  const isOffseason = Boolean(data?.offseason);
  const nextSeasonStart = data?.next_season_start ?? null;
  const daysUntilNextSeason = useMemo(() => {
    if (!nextSeasonStart) return null;
    try {
      const diff = new Date(nextSeasonStart).getTime() - Date.now();
      return Math.max(0, Math.ceil(diff / 86_400_000));
    } catch {
      return null;
    }
  }, [nextSeasonStart]);

  const dismissKey = `offseason-dismissed:${activeLeague ?? "none"}`;
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    try {
      setDismissed(sessionStorage.getItem(dismissKey) === "1");
    } catch {
      // sessionStorage blocked (e.g. incognito strict mode)
    }
  }, [dismissKey]);

  const handleDismiss = () => {
    setDismissed(true);
    try { sessionStorage.setItem(dismissKey, "1"); } catch { /* ignore */ }
  };

  // Show the pre-list notice only when fixtures are present but the season is ending soon,
  // or when the list has matches but offseason=true (transition edge case).
  const showOffseasonBanner = isOffseason && !dismissed && data && data.upcoming_matches.length > 0;

  return (
    <section aria-label="Upcoming matches" className="space-y-4">
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-200">{title}</h2>
            {isFetching && !isLoading && (
              <span className="text-[10px] font-medium text-slate-600 animate-pulse" aria-live="polite">
                Refreshing…
              </span>
            )}
          </div>
          {data && data.matches_with_value > 0 && (
            <span className="text-xs text-slate-500">
              {data.matches_with_value} with value · avg edge {data.avg_edge_pct.toFixed(1)}%
              {data.portfolio_exposure?.exceeds_aggregate_cap && (
                <span className="ml-2 text-amber-400">
                  · {data.portfolio_exposure.aggregate_recommended_pct.toFixed(1)}% recommended exceeds {data.portfolio_exposure.aggregate_cap_pct.toFixed(1)}% portfolio cap
                </span>
              )}
            </span>
          )}
        </div>
        {/* Show league filter bar only when no fixed league prop is passed */}
        {!leagueProp && (
          <LeagueFilterBar selected={selectedLeague} onChange={setSelectedLeague} />
        )}
      </div>

      {/* Off-season banner — shown when fixture list is non-empty but season is flagged closed */}
      {showOffseasonBanner && (
        <div
          className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/5 px-4 py-3"
          role="status"
          aria-label="Off-season notice"
        >
          <svg className="mt-0.5 h-4 w-4 flex-shrink-0 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-amber-300">
              {daysUntilNextSeason != null
                ? `${daysUntilNextSeason} day${daysUntilNextSeason === 1 ? "" : "s"} until next season · Limited predictions available`
                : "Off-season · Limited predictions available"}
            </p>
            {nextSeasonStart && (
              <p className="mt-0.5 text-[11px] text-slate-500">
                Next season starts{" "}
                <time dateTime={nextSeasonStart}>
                  {new Date(nextSeasonStart).toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" })}
                </time>
              </p>
            )}
          </div>
          <button
            onClick={handleDismiss}
            className="flex-shrink-0 text-slate-600 hover:text-slate-400 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-500 rounded"
            aria-label="Dismiss off-season notice"
          >
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {isLoading && <PanelSkeleton />}

      {error && !data && (
        <p className="rounded-xl border border-slate-800/50 bg-slate-900/30 px-4 py-8 text-center text-xs text-slate-500">
          Fixtures unavailable — backend offline or warming up.
        </p>
      )}

      {data && data.upcoming_matches.length === 0 && !isLoading && (
        data.offseason ? (
          <LeagueOffseasonNotice
            leagueName={activeLeague ?? "This league"}
            nextSeasonStart={data.next_season_start ?? null}
          />
        ) : (
          // data_gap means the backend failed rather than genuinely having no
          // fixtures — saying "no fixtures" there would report an outage as a
          // quiet, believable empty state.
          <p className="rounded-xl border border-slate-800/50 bg-slate-900/30 px-4 py-8 text-center text-xs text-slate-500">
            {data.data_gap
              ? "Fixture list unavailable right now. Please try again shortly."
              : `No upcoming fixtures in the next ${VISIBLE_WINDOW_DAYS} days.`}
          </p>
        )
      )}

      {data && data.upcoming_matches.length > 0 && (
        <>
          {/* Two columns from xl up: the panel spans the full content width, so a
              single column left most of the row empty and pushed all but a
              handful of fixtures below the fold. */}
          <div className="grid gap-2 xl:grid-cols-2">
            {data.upcoming_matches.slice(0, VISIBLE_MATCH_LIMIT).map((m) => (
              <MatchRow key={m.match_id} match={m} />
            ))}
          </div>
          {data.upcoming_matches.length > VISIBLE_MATCH_LIMIT && (
            <p className="pt-1 text-center text-[11px] text-slate-600">
              Showing {VISIBLE_MATCH_LIMIT} of {data.upcoming_matches.length} fixtures
              {!selectedLeague && " · filter by league to narrow the list"}
            </p>
          )}
        </>
      )}
    </section>
  );
}

export const UpcomingMatchesPanel = memo(UpcomingMatchesPanelInner);
