"use client";

import { memo } from "react";
import { cn } from "@/lib/utils";
import { EdgeSignal } from "@/components/brand/edge-signal";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface FixturePrediction {
  home_win: number;
  draw: number;
  away_win: number;
  confidence?: number;
  model_version?: string;
}

export interface MatchIntelligenceFixture {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  kickoffUtc: string;
  league: string;
  homeLogoUrl?: string;
  awayLogoUrl?: string;
  predictionAvailable: boolean;
  unavailableReason?: string | null;
  edge_pct?: number | null;
  matchImportance?: string | null;
  matchRound?: string | null;
  prediction?: FixturePrediction | null;
}

// ─── League chip ─────────────────────────────────────────────────────────────

const LEAGUE_COLORS: Record<string, string> = {
  EPL: "border-purple-500/30 text-purple-300 bg-purple-500/10",
  "La Liga": "border-amber-500/30 text-amber-300 bg-amber-500/10",
  Bundesliga: "border-red-500/30 text-red-300 bg-red-500/10",
  "Serie A": "border-blue-500/30 text-blue-300 bg-blue-500/10",
  "Ligue 1": "border-cyan-500/30 text-cyan-300 bg-cyan-500/10",
  Eredivisie: "border-orange-500/30 text-orange-300 bg-orange-500/10",
  UCL: "border-indigo-500/30 text-indigo-300 bg-indigo-500/10",
};

function leagueChipClass(league: string) {
  return cn(
    "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
    LEAGUE_COLORS[league] ??
      "border-slate-700/50 text-slate-400 bg-slate-800/50",
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatKickoff(utcStr: string): string {
  try {
    const d = new Date(utcStr);
    return d.toLocaleString([], {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return utcStr;
  }
}

function ProbabilityBar({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: number;
  colorClass: string;
}) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex flex-col gap-0.5" role="group" aria-label={`${label}: ${pct}%`}>
      <div className="flex justify-between text-[10px] text-slate-400">
        <span>{label}</span>
        <span className="font-semibold text-slate-200">{pct}%</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-slate-700/60">
        <div
          className={cn("h-full rounded-full transition-all duration-500", colorClass)}
          style={{ width: `${pct}%` }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}

// ─── Card ─────────────────────────────────────────────────────────────────────

export const MatchIntelligenceCard = memo(function MatchIntelligenceCard({
  fixture,
  className,
}: {
  fixture: MatchIntelligenceFixture;
  className?: string;
}) {
  const hasEdge =
    fixture.edge_pct !== null && fixture.edge_pct !== undefined && fixture.edge_pct > 0;
  const isValueBet = hasEdge && (fixture.edge_pct ?? 0) >= 4.2;

  return (
    <article
      data-testid="match-intelligence-card"
      data-match-id={fixture.matchId}
      className={cn(
        "relative overflow-hidden rounded-2xl border border-white/[0.07] bg-slate-900/70 p-4 shadow-lg backdrop-blur-sm transition-colors hover:border-white/[0.12]",
        isValueBet && "ring-1 ring-emerald-500/30",
        className,
      )}
    >
      {/* Value badge */}
      {isValueBet && (
        <div
          aria-label="Value bet identified"
          className="absolute right-3 top-3 flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300"
        >
          <EdgeSignal className="h-3.5 w-3.5 text-emerald-300" />
          +{(fixture.edge_pct ?? 0).toFixed(1)}% edge
        </div>
      )}

      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-2 pr-16">
        <div className="space-y-1">
          {/* Teams */}
          <p className="text-sm font-semibold leading-tight text-white">
            <span data-testid="home-team">{fixture.homeTeam}</span>
            <span className="mx-2 text-slate-500" aria-hidden="true">vs</span>
            <span data-testid="away-team">{fixture.awayTeam}</span>
          </p>
          {/* Meta */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className={leagueChipClass(fixture.league)} aria-label={`League: ${fixture.league}`}>
              {fixture.league}
            </span>
            {fixture.matchRound && (
              <span className="text-[10px] text-slate-500">{fixture.matchRound}</span>
            )}
            <time
              dateTime={fixture.kickoffUtc}
              className="text-[10px] text-slate-500"
            >
              {formatKickoff(fixture.kickoffUtc)}
            </time>
          </div>
        </div>
      </div>

      {/* Prediction bars */}
      {fixture.predictionAvailable && fixture.prediction ? (
        <div className="space-y-2" aria-label="Match outcome probabilities">
          <ProbabilityBar label="Home" value={fixture.prediction.home_win} colorClass="bg-emerald-500" />
          <ProbabilityBar label="Draw" value={fixture.prediction.draw} colorClass="bg-amber-500" />
          <ProbabilityBar label="Away" value={fixture.prediction.away_win} colorClass="bg-sky-500" />
          {fixture.prediction.confidence !== undefined && (
            <p className="mt-1.5 text-right text-[10px] text-slate-500">
              Model confidence:{" "}
              <span className="font-semibold text-slate-300">
                {Math.round(fixture.prediction.confidence * 100)}%
              </span>
            </p>
          )}
        </div>
      ) : (
        <p className="mt-2 text-xs text-slate-500 italic">
          {fixture.unavailableReason ?? "Prediction not yet available"}
        </p>
      )}
    </article>
  );
});

// ─── Skeleton ────────────────────────────────────────────────────────────────

export function MatchIntelligenceCardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-2xl border border-white/[0.05] bg-slate-900/50 p-4"
          aria-hidden="true"
        >
          <div className="mb-3 space-y-2">
            <div className="h-4 w-3/4 rounded bg-slate-800" />
            <div className="flex gap-2">
              <div className="h-3 w-14 rounded-full bg-slate-800" />
              <div className="h-3 w-24 rounded bg-slate-800" />
            </div>
          </div>
          <div className="space-y-2">
            <div className="h-2.5 w-full rounded bg-slate-800" />
            <div className="h-2.5 w-full rounded bg-slate-800" />
            <div className="h-2.5 w-full rounded bg-slate-800" />
          </div>
        </div>
      ))}
    </>
  );
}
