/* eslint-disable jsx-a11y/aria-proptypes */
"use client";

import { useMemo, useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { toast } from "react-hot-toast";
import { useQuery } from "@tanstack/react-query";

import { TeamAutocomplete } from "./team-autocomplete";
import { LeagueOffseasonNotice } from "./LeagueOffseasonNotice";
import { getTeamsForLeague, LeagueId } from "../lib/team-data";
import { getOffseasonStatus, getUpcomingMatches, type UpcomingMatch } from "@/lib/api";
import { safeErrorMessage } from "@/lib/error-utils";
import {
  PLATFORM_HEALTH_QUERY_KEY,
  fetchPlatformHealth,
  derivePlatformHealth,
} from "@/lib/health-status";
import { LEAGUE_CONFIG, TeamVsDisplay } from "./team-display";
import {
  buildMatchInsightsHref,
  getTopEdgeFixtureId,
  selectorLeagueId,
  type SelectedFixture,
} from "@/lib/match-selection";
// Only rendered once a matchup is submitted, and it carries framer-motion's
// drag/gesture machinery — keep it out of the /match first-load bundle.
const MatchLoadingExperience = dynamic(
  () =>
    import("@/components/loading/match-loading-experience").then(
      (m) => m.MatchLoadingExperience,
    ),
  { ssr: false },
);
import { FeatureFlag, useFeatureFlag } from "@/lib/feature-flags";
import { hashMatchup } from "@/lib/interstitial-storage";
import { canonicalLeagueId } from "@/lib/league";
import { describeEdgeQualityPill, describeValueBadge } from "@/lib/edge-quality";
import { cn } from "@/lib/utils";
import { CountryFlag } from "@/components/ui/cached-logo";

// Keeps a team already chosen on one side out of the other side's dropdown,
// rather than only rejecting the combination after submit.
export function excludeSelectedTeam(teams: readonly string[], selected: string): string[] {
  const target = selected.trim().toLowerCase();
  if (!target) return [...teams];
  return teams.filter((team) => team.trim().toLowerCase() !== target);
}

export interface MatchSelectionSummary {
  badge: string;
  title: string;
  description: string;
}

export function describeMatchSelectionState({
  homeTeam,
  awayTeam,
  league,
  selectedFixture,
}: {
  homeTeam: string;
  awayTeam: string;
  league: LeagueId;
  selectedFixture: SelectedFixture | null;
}): MatchSelectionSummary {
  const leagueKey = canonicalLeagueId(league);
  const leagueLabel = LEAGUES.find((item) => canonicalLeagueId(item.id) === leagueKey)?.name ?? league;
  const matchupLabel = homeTeam.trim() && awayTeam.trim()
    ? `${homeTeam.trim()} vs ${awayTeam.trim()}`
    : `Pick two teams in ${leagueLabel}`;

  if (selectedFixture) {
    return {
      badge: "Verified fixture",
      title: matchupLabel,
      description:
        "This selection preserves the canonical fixture identity from the carousel and keeps the analysis on a verified path.",
    };
  }

  if (homeTeam.trim() && awayTeam.trim()) {
    return {
      badge: "Manual matchup",
      title: matchupLabel,
      description:
        `This will be treated as a hypothetical ${leagueLabel} matchup until a verified fixture is chosen.`,
    };
  }

  return {
    badge: "Selection pending",
    title: `Start with ${leagueLabel}`,
    description:
      "Pick a verified fixture from the carousel or enter a matchup below. Verified selections stay authoritative; manual entries remain explicit hypotheticals.",
  };
}

const LEAGUES = [
  { id: "EPL", name: "Premier League" },
  { id: "La Liga", name: "La Liga" },
  { id: "Serie A", name: "Serie A" },
  { id: "Bundesliga", name: "Bundesliga" },
  { id: "Ligue 1", name: "Ligue 1" },
  { id: "Eredivisie", name: "Eredivisie" },
  { id: "UCL", name: "Champions League" },
] as const satisfies ReadonlyArray<{ id: LeagueId; name: string }>;

// ─── Big Matches Carousel (E.5) ───────────────────────────────────────────────

interface BigMatchesCarouselProps {
  onSelectFixture: (fixture: SelectedFixture) => void;
}

function BigMatchesCarousel({ onSelectFixture }: BigMatchesCarouselProps) {
  const [activeLeague, setActiveLeague] = useState<LeagueId | "ALL">("ALL");

  const { data, isLoading } = useQuery({
    queryKey: ["big-matches-carousel"],
    queryFn: () => getUpcomingMatches({ days_ahead: 7, limit: 20 }),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  const fixtures = useMemo<UpcomingMatch[]>(() => {
    if (!data?.upcoming_matches) return [];
    const list = activeLeague === "ALL"
      ? data.upcoming_matches
      : data.upcoming_matches.filter(
          (m) => canonicalLeagueId(m.league) === canonicalLeagueId(activeLeague),
        );
    return [...list]
      .sort((a, b) => (b.edge_quality_score ?? 0) - (a.edge_quality_score ?? 0))
      .slice(0, 6);
  }, [data, activeLeague]);

  const topEdgeId = getTopEdgeFixtureId(fixtures);

  // Don't render during offseason or when data is empty after load
  if (!isLoading && (data?.offseason || fixtures.length === 0)) return null;

  return (
    <div className="space-y-3 mb-6">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-[0.3em] text-slate-500 font-semibold">
          Upcoming Fixtures
        </p>
        {/* League filter chips */}
        <div className="flex gap-1.5 overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          <button
            type="button"
            onClick={() => setActiveLeague("ALL")}
            aria-pressed={activeLeague === "ALL"}
            className={cn(
              "flex-shrink-0 min-h-[24px] rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-400",
              activeLeague === "ALL"
                ? "border-slate-400/30 bg-slate-700/50 text-slate-200"
                : "border-slate-700/40 text-slate-500 hover:text-slate-300",
            )}
          >
            All
          </button>
          {LEAGUES.slice(0, 5).map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => setActiveLeague(l.id)}
              aria-pressed={activeLeague === l.id}
              className={cn(
                "flex-shrink-0 min-h-[24px] rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-400",
                activeLeague === l.id
                  ? "border-indigo-400/30 bg-indigo-500/10 text-indigo-300"
                  : "border-slate-700/40 text-slate-500 hover:text-slate-300",
              )}
            >
              {l.id}
            </button>
          ))}
        </div>
      </div>

      {/* Cards */}
      <div className="flex gap-3 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {isLoading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="flex-shrink-0 w-[180px] h-[100px] rounded-xl border border-slate-800/60 bg-slate-900/40 animate-pulse"
              />
            ))
          : fixtures.map((match) => {
              const selectorLeague = selectorLeagueId(match.league);
              const isTopEdge = match.match_id === topEdgeId;
              const prediction = match.predictions;
              const qualityPill = describeEdgeQualityPill(match.edge_quality_score);
              const valueBadge = describeValueBadge(match.has_value, match.best_value_bet?.edge_pct);
              const clvPositive = match.clv_pct != null && match.clv_pct > 0;
              const topOutcome = prediction
                ? (
                    prediction.home_win >= prediction.draw && prediction.home_win >= prediction.away_win
                      ? "Home Win"
                      : prediction.away_win >= prediction.draw
                      ? "Away Win"
                      : "Draw"
                  )
                : null;

              return (
                <button
                  key={match.match_id}
                  type="button"
                  onClick={() => {
                    if (!selectorLeague) return;
                    onSelectFixture({
                      matchId: match.match_id,
                      homeTeam: match.home_team,
                      awayTeam: match.away_team,
                      league: selectorLeague,
                    });
                  }}
                  disabled={!selectorLeague}
                  aria-label={`${match.home_team} vs ${match.away_team}${isTopEdge ? " — Top Edge Today" : ""}`}
                  className={cn(
                    "flex-shrink-0 w-[180px] rounded-xl border p-3 text-left transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400 hover:border-slate-600/60 min-h-[44px] disabled:cursor-not-allowed disabled:opacity-50",
                    isTopEdge
                      ? "border-emerald-500/30 bg-emerald-500/5"
                      : "border-slate-800/60 bg-slate-900/40 hover:bg-slate-900/70",
                  )}
                >
                  {isTopEdge && (
                    <p className="text-[9px] font-bold uppercase tracking-widest text-emerald-400 mb-1">
                      🔥 Top Edge Today
                    </p>
                  )}
                  <p className="text-[11px] font-semibold text-slate-100 truncate">{match.home_team}</p>
                  <p className="text-[10px] text-slate-500">vs {match.away_team}</p>
                  {match.match_date && (
                    <p className="text-[9px] text-slate-600 mt-0.5">
                      {new Date(match.match_date).toLocaleString("en-NG", {
                        weekday: "short", day: "numeric", month: "short",
                        hour: "2-digit", minute: "2-digit",
                        timeZone: "Africa/Lagos", hour12: false,
                      })} WAT
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap items-center gap-1">
                    {/* edge_quality_score is a confidence/freshness/completeness
                        blend, not a market edge — never render it as "% edge"
                        (see @/lib/edge-quality). Real market edge, when one
                        exists, is the separate Value pill below. */}
                    {qualityPill && (
                      <span
                        className={cn(
                          "rounded-full border px-1.5 py-0.5 text-[9px] font-semibold",
                          qualityPill.className,
                        )}
                        title={qualityPill.title}
                      >
                        {qualityPill.label}
                      </span>
                    )}
                    {valueBadge && (
                      <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-300">
                        {valueBadge}
                      </span>
                    )}
                    {clvPositive && (
                      <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-1.5 py-0.5 text-[9px] font-semibold text-cyan-300">
                        +{match.clv_pct!.toFixed(1)}% CLV
                      </span>
                    )}
                    {topOutcome && (
                      <span className="text-[9px] text-slate-500">{topOutcome}</span>
                    )}
                  </div>
                </button>
              );
            })}
      </div>
    </div>
  );
}

export function MatchSelector() {
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [league, setLeague] = useState<LeagueId>("EPL");
  const [loading, setLoading] = useState(false);
  const [showInterstitial, setShowInterstitial] = useState(false);
  const [selectedFixture, setSelectedFixture] = useState<SelectedFixture | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const router = useRouter();
  const interstitialV2Enabled = useFeatureFlag(FeatureFlag.PREDICTION_INTERSTITIAL_V2);
  const premiumVisualsEnabled = useFeatureFlag(FeatureFlag.PREMIUM_VISUAL_HIERARCHY);
  const [pendingMatchup, setPendingMatchup] = useState<{
    home: string;
    away: string;
    league: LeagueId;
    key: string;
  } | null>(null);

  const STORAGE_KEY = "sabiscore.matchSelector.v1";

  // Restore persisted selector state on mount
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed?.league) setLeague(parsed.league as LeagueId);
      if (parsed?.homeTeam) setHomeTeam(parsed.homeTeam);
      if (parsed?.awayTeam) setAwayTeam(parsed.awayTeam);
    } catch {
      // ignore parse errors
      // console.warn("Failed to restore match selector state", err);
    }
  }, []);

  // Persist selection when values change
  useEffect(() => {
    try {
      const payload = { league, homeTeam, awayTeam };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // ignore storage errors
    }
  }, [league, homeTeam, awayTeam]);

  const leagueTeams = useMemo(() => getTeamsForLeague(league), [league]);

  // Same normalization handleSubmit already uses for its equality guard —
  // keeps a team already picked on one side out of the other side's list,
  // instead of only rejecting the combination after submit.
  const homeTeamOptions = useMemo(
    () => excludeSelectedTeam(leagueTeams, awayTeam),
    [leagueTeams, awayTeam],
  );
  const awayTeamOptions = useMemo(
    () => excludeSelectedTeam(leagueTeams, homeTeam),
    [leagueTeams, homeTeam],
  );

  const handleLeagueSelect = (nextLeague: LeagueId) => {
    if (nextLeague === league) {
      return;
    }

    setLeague(nextLeague);
    setHomeTeam("");
    setAwayTeam("");
    setSelectedFixture(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!homeTeam.trim() || !awayTeam.trim()) {
      toast.error("Please enter both teams");
      return;
    }

    if (homeTeam.trim().toLowerCase() === awayTeam.trim().toLowerCase()) {
      toast.error("Please select different teams");
      return;
    }

    const normalizedHome = homeTeam.trim();
    const normalizedAway = awayTeam.trim();
    setLoading(true);
    if (interstitialV2Enabled) {
      const matchupKey = hashMatchup(normalizedHome, normalizedAway);
      setPendingMatchup({ home: normalizedHome, away: normalizedAway, league, key: matchupKey });
      setShowInterstitial(true);
    }

    try {
      // Preserve the canonical fixture ID when the selection came from the
      // real-fixture carousel. Manual edits intentionally clear that identity
      // and remain an explicitly unverified matchup path.
      router.push(
        buildMatchInsightsHref({
          selectedFixture,
          homeTeam: normalizedHome,
          awayTeam: normalizedAway,
          league,
        }),
      );
      
      // Clear persisted state after successful navigation to avoid stale team selections
      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch {
        // ignore storage errors
      }
    } catch (error) {
      setShowInterstitial(false);
      setPendingMatchup(null);
      const message = safeErrorMessage(error);
      toast.error(message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!showInterstitial) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => dialogRef.current?.focus());
    const handleDialogKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setShowInterstitial(false);
        setPendingMatchup(null);
        setLoading(false);
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      );
      if (focusable.length === 0) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleDialogKeyDown);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", handleDialogKeyDown);
      previousFocusRef.current?.focus();
    };
  }, [showInterstitial]);

  const hasTeamsSelected = Boolean(homeTeam.trim() && awayTeam.trim());

  const handleCarouselSelect = (fixture: SelectedFixture) => {
    setSelectedFixture(fixture);
    setLeague(fixture.league);
    setHomeTeam(fixture.homeTeam);
    setAwayTeam(fixture.awayTeam);
  };

  const handleHomeTeamChange = (value: string) => {
    setHomeTeam(value);
    if (value.trim().toLowerCase() !== selectedFixture?.homeTeam.trim().toLowerCase()) {
      setSelectedFixture(null);
    }
  };

  const handleAwayTeamChange = (value: string) => {
    setAwayTeam(value);
    if (value.trim().toLowerCase() !== selectedFixture?.awayTeam.trim().toLowerCase()) {
      setSelectedFixture(null);
    }
  };

  // Off-season signal for the currently selected league, so the user sees it
  // before submitting a hypothetical matchup rather than after. Uses the
  // purpose-built season endpoint (edge-cached 1h, no prediction work) rather
  // than piggybacking the fixtures list; staleTime mirrors that edge cache.
  // `getOffseasonStatus` never throws — it degrades to UNKNOWN, which renders
  // nothing.
  const { data: offseasonData } = useQuery({
    queryKey: ["match-selector-offseason", league],
    queryFn: () => getOffseasonStatus(canonicalLeagueId(league) ?? league),
    staleTime: 60 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
  });

  // Same query key as PlatformHealthPills, so this dedupes against its
  // fetch rather than issuing a second request — the footer below must not
  // assert a "live" claim beyond what that pill actually verifies.
  const { data: platformHealthData } = useQuery({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 30_000,
  });
  const platformHealth = platformHealthData ? derivePlatformHealth(platformHealthData) : null;
  const selectionSummary = describeMatchSelectionState({
    homeTeam,
    awayTeam,
    league,
    selectedFixture,
  });
  const submitLabel = loading
    ? "Generating insights..."
    : selectedFixture
    ? "Open verified analysis"
    : "Generate manual insights";

  return (
    <>
      <div
        className={cn(
          "glass-card relative overflow-hidden p-5 sm:p-8",
          premiumVisualsEnabled &&
            "border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
        )}
      >
        {premiumVisualsEnabled && (
          <div
            className="pointer-events-none absolute inset-0 opacity-60 bg-[radial-gradient(circle_at_top,rgba(0,212,255,0.25),transparent_55%),radial-gradient(circle_at_20%_80%,rgba(123,47,247,0.15),transparent_45%)]"
            aria-hidden="true"
          />
        )}
        <div className="relative space-y-6">
          {/* Big Matches Carousel (E.5) */}
          <BigMatchesCarousel onSelectFixture={handleCarouselSelect} />

          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-3">
              <h2 className="text-xl font-bold text-slate-100 sm:text-2xl">Generate Match Insights</h2>
              {premiumVisualsEnabled && (
                <span className="hidden rounded-full border border-white/10 bg-slate-900/60 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-slate-300 sm:inline-flex">
                  Premium visual mode
                </span>
              )}
            </div>
            <p className="text-sm text-slate-400 sm:text-base">Choose a verified fixture or enter a hypothetical matchup.</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-950/50 p-4 sm:p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn(
                "rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.24em]",
                selectedFixture
                  ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-300"
                  : homeTeam.trim() && awayTeam.trim()
                  ? "border-amber-400/30 bg-amber-400/10 text-amber-300"
                  : "border-slate-700/60 bg-slate-900/70 text-slate-400",
              )}>
                {selectionSummary.badge}
              </span>
              <h3 className="text-sm font-semibold text-slate-100 sm:text-base">
                {selectionSummary.title}
              </h3>
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              {selectionSummary.description}
            </p>
            {selectedFixture && (
              <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
                  Canonical fixture ID preserved
                </span>
                <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1">
                  {league}
                </span>
              </div>
            )}
          </div>

        {premiumVisualsEnabled && hasTeamsSelected && (
          <div className="hidden rounded-2xl border border-white/10 bg-slate-900/60 p-4 sm:block">
            <>
                <TeamVsDisplay
                  homeTeam={homeTeam}
                  awayTeam={awayTeam}
                  league={league}
                  size="lg"
                  showCountryFlags={true}
                  className="justify-between"
                />
                <div className="mt-4 hidden flex-wrap gap-3 text-[11px] text-slate-300 sm:flex">
                  <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-3 py-1">
                    Evidence availability checked
                  </span>
                  <span className="rounded-full border border-amber-300/30 bg-amber-300/10 px-3 py-1">
                    Model status reported by backend
                  </span>
                  <span className="rounded-full border border-purple-300/30 bg-purple-300/10 px-3 py-1">
                    Zero stake when gates close
                  </span>
                </div>
              </>
          </div>
        )}

        {hasTeamsSelected && (
          <div className="rounded-xl border border-white/10 bg-slate-900/50 px-3 py-2 text-sm sm:hidden">
            <div className="flex items-center justify-between gap-2">
              <span className="truncate font-medium text-slate-200">{homeTeam || "Home team"}</span>
              <span className="text-xs uppercase text-slate-500">vs</span>
              <span className="truncate text-right font-medium text-slate-200">{awayTeam || "Away team"}</span>
            </div>
            <p className="mt-1 text-[11px] text-slate-500">
              {selectedFixture ? "Verified fixture selected" : "Manual matchup selected"}
            </p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4 sm:space-y-6">
          {/* League Selector */}
          <div className="space-y-2">
            <label className="text-sm font-medium text-slate-300">League</label>
            <div className="flex gap-2 overflow-x-auto pb-1 md:grid md:grid-cols-5 md:overflow-visible">
              {LEAGUES.map((l) => (
                <button
                  key={l.id}
                  type="button"
                  onClick={() => handleLeagueSelect(l.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      handleLeagueSelect(l.id);
                    }
                  }}
                  data-selected={league === l.id}
                  aria-label={`Select ${l.name}${league === l.id ? ' (selected)' : ''}`}
                  className={cn(
                    "min-w-[116px] flex-shrink-0 rounded-xl border-2 p-3 transition-all md:min-w-0",
                    premiumVisualsEnabled
                      ? league === l.id
                        ? "border-transparent bg-gradient-to-br from-cyan-400/30 to-indigo-500/30 text-white shadow-[0_10px_25px_rgba(15,23,42,0.55)]"
                        : "border-white/10 bg-slate-900/60 text-slate-300 hover:border-cyan-400/30"
                      : league === l.id
                      ? "border-indigo-500 bg-indigo-500/10 text-slate-100"
                      : "border-slate-700 bg-slate-800/50 text-slate-400 hover:border-slate-600"
                  )}
                >
                  <div className="mb-1 flex justify-center">
                    {LEAGUE_CONFIG[l.id]?.countryCode ? (
                      <CountryFlag 
                        countryCode={LEAGUE_CONFIG[l.id].countryCode} 
                        size={32}
                        className="rounded-sm"
                      />
                    ) : (
                      <span className="text-2xl">⚽</span>
                    )}
                  </div>
                  <div className="text-xs font-medium">{l.name}</div>
                  {premiumVisualsEnabled && LEAGUE_CONFIG[l.id]?.country && (
                    <p className="text-[10px] text-slate-500">{LEAGUE_CONFIG[l.id]?.country}</p>
                  )}
                </button>
              ))}
            </div>
          </div>

          {offseasonData?.season_status === "OFF_SEASON" && (
            <LeagueOffseasonNotice
              leagueName={
                offseasonData.league || LEAGUES.find((l) => l.id === league)?.name || league
              }
              nextSeasonStart={offseasonData.next_season_start || null}
            />
          )}

          {/* Team Inputs */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <TeamAutocomplete
              label="Home Team"
              value={homeTeam}
              onChange={handleHomeTeamChange}
              options={homeTeamOptions}
              league={league}
              placeholder="Search or type a team"
              disabled={loading}
            />

            <TeamAutocomplete
              label="Away Team"
              value={awayTeam}
              onChange={handleAwayTeamChange}
              options={awayTeamOptions}
              league={league}
              placeholder="Search or type a team"
              disabled={loading}
            />
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-4 font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all duration-200 hover:scale-[1.02] hover:bg-indigo-500 hover:shadow-indigo-500/40 disabled:cursor-not-allowed disabled:scale-100 disabled:bg-slate-700 disabled:shadow-none"
          >
            {loading ? (
              <>
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/30 border-t-white"></div>
                Generating insights...
              </>
            ) : (
              <>
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
                {submitLabel}
              </>
            )}
          </button>

          <div className="mt-2 text-center">
            <button
              type="button"
              onClick={() => {
                setHomeTeam("");
                setAwayTeam("");
                setLeague("EPL");
                setSelectedFixture(null);
                try {
                  localStorage.removeItem(STORAGE_KEY);
                } catch {}
                toast.success("Selector reset");
              }}
              className="min-h-11 rounded-lg px-3 text-sm text-slate-400 transition-colors hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              Reset selection
            </button>
          </div>
        </form>

        <div className="pt-4 border-t border-slate-800/50">
          <p className="text-xs text-center text-slate-500">
            Analysis, evidence checks, and verdicts remain server-authoritative
          </p>
          <div className="mt-2 flex items-center justify-center gap-2 text-[10px] text-slate-600">
            <span className="inline-flex items-center gap-1">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  platformHealth && platformHealth.enabled === platformHealth.configured
                    ? "animate-pulse bg-green-500/60"
                    : "bg-amber-500/60",
                )}
              />
              {platformHealth
                ? `${platformHealth.enabled} of ${platformHealth.configured} providers enabled`
                : "Checking providers"}
            </span>
            <span>•</span>
            <span>Evidence timestamps appear in each analysis</span>
          </div>
        </div>
        </div>
      </div>

      {interstitialV2Enabled && showInterstitial && pendingMatchup && (
        // py-[max(…)] keeps the card clear of a notch. The previous
        // `py-safe-area-inset-top` is not a Tailwind utility and compiled to
        // nothing, so this overlay had no vertical padding at all.
        <div
          ref={dialogRef}
          tabIndex={-1}
          className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden bg-slate-950/90 px-4 py-[max(1rem,env(safe-area-inset-top))] backdrop-blur"
          role="dialog"
          aria-modal="true"
          aria-labelledby="match-loading-title"
          aria-describedby="match-loading-desc"
        >
          <h2 id="match-loading-title" className="sr-only">Preparing match analysis</h2>
          <p id="match-loading-desc" className="sr-only">
            SabiScore is acquiring evidence and will navigate to the authoritative analysis.
          </p>
          <div className="absolute inset-0" aria-hidden="true" />
          {/* max-w-6xl matches the interstitial's own container; a narrower clamp
              here would collapse its two-column layout back to a single strip.
              py-4 replaces the padding the interstitial dropped for route parity —
              this overlay has no <main> ancestor supplying it. */}
          <div className="relative w-full max-w-6xl max-h-[calc(100vh-2rem)] overflow-y-auto py-4">
            <MatchLoadingExperience
              homeTeam={pendingMatchup.home}
              awayTeam={pendingMatchup.away}
              league={pendingMatchup.league}
              matchupId={pendingMatchup.key}
            />
          </div>
        </div>
      )}
    </>
  );
}
