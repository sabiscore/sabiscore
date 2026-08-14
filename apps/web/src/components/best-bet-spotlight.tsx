"use client";

import { memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, TrendingUp, AlertCircle, Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { LEAGUE_COLORS } from "@/lib/league-colors";
import { ResponsibleGamblingBanner } from "@/components/ui/ResponsibleGamblingTooltip";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ValueBetFixture {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  league: string;
  kickoffUtc: string;
  outcome: string;
  edge_pct: number;
  confidence: number;
  kelly_stake_pct?: number;
}

interface ValueBetScanResponse {
  fixtures: ValueBetFixture[];
  total: number;
  data_gap: boolean;
  days: number;
  source: string;
}

// ─── League chip colors ───────────────────────────────────────────────────────

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatKickoff(utcStr: string): string {
  try {
    const d = new Date(utcStr);
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return utcStr;
  }
}

function confidenceTier(c: number): { label: string; cls: string } {
  if (c >= 0.8) return { label: "High confidence", cls: "text-emerald-400" };
  if (c >= 0.65) return { label: "Medium confidence", cls: "text-amber-400" };
  return { label: "Low confidence", cls: "text-rose-400" };
}

async function fetchScan(): Promise<ValueBetScanResponse> {
  const res = await fetch("/api/value-bet-scan?days=7", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ValueBetScanResponse>;
}

// ─── Empty / data-gap states ──────────────────────────────────────────────────

function DataGapState() {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center" role="status">
      <Database className="h-7 w-7 text-slate-400" aria-hidden="true" />
      <p className="text-sm font-medium text-slate-300">No certified opportunities right now</p>
      {/* No fixed refresh cadence exists to promise — predictions are written as
          fixtures are analyzed, and none are during the close season. */}
      <p className="text-xs text-slate-300">
        Predictions appear here once fixtures are analyzed.
      </p>
    </div>
  );
}

function NoEdgeState() {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center" role="status">
      <TrendingUp className="h-7 w-7 text-slate-400" aria-hidden="true" />
      <p className="text-sm font-medium text-slate-300">No research candidates this week</p>
      <p className="text-xs text-slate-300">No model-market comparisons cleared the evidence filter.</p>
    </div>
  );
}

// ─── Spotlight card ───────────────────────────────────────────────────────────

function SpotlightCard({ bet }: { bet: ValueBetFixture }) {
  const leagueChipCls =
    LEAGUE_COLORS[bet.league] ?? "border-slate-700/50 text-slate-400 bg-slate-800/50";
  const tier = confidenceTier(bet.confidence);

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            leagueChipCls,
          )}
        >
          {bet.league}
        </span>
        <span className="text-[10px] uppercase tracking-widest text-slate-300">
          Largest research gap this week
        </span>
      </div>

      {/* Match */}
      <div>
        <p className="text-xl font-bold text-white">
          {bet.homeTeam}
          <span className="mx-2 text-slate-300 font-normal">vs</span>
          {bet.awayTeam}
        </p>
        <time dateTime={bet.kickoffUtc} className="text-[11px] text-slate-300">
          {formatKickoff(bet.kickoffUtc)}
        </time>
      </div>

      {/* Metrics row */}
      <div className="flex flex-wrap items-end gap-6">
        {/* Edge */}
        <div>
          <p className="text-[10px] uppercase tracking-[0.3em] text-slate-300">Edge</p>
          <p className="flex items-center gap-1 text-3xl font-black text-emerald-400 tabular-nums leading-none">
            <ArrowUpRight className="h-5 w-5" aria-hidden="true" />
            {bet.edge_pct.toFixed(1)}%
          </p>
        </div>

        {/* Confidence */}
        <div>
          <p className="text-[10px] uppercase tracking-[0.3em] text-slate-300">Confidence</p>
          <p className={cn("text-lg font-bold leading-none", tier.cls)}>
            {(bet.confidence * 100).toFixed(0)}%
          </p>
          <p className={cn("text-[10px] mt-0.5", tier.cls)}>{tier.label}</p>
        </div>

        {/* Bet type */}
        <div>
          <p className="text-[10px] uppercase tracking-[0.3em] text-slate-300">Outcome</p>
          <p className="text-base font-semibold capitalize text-slate-200 leading-none">
            {bet.outcome}
          </p>
        </div>

        <div>
          <p className="text-[10px] uppercase tracking-[0.3em] text-slate-300">Stake</p>
          <p className="text-base font-semibold text-slate-300 leading-none">Disabled</p>
          <p className="mt-0.5 text-[10px] text-slate-300">uncertified generation</p>
        </div>
      </div>

      {/* Responsible gambling notice — required below every stake surface */}
      <div className="pt-1">
        <ResponsibleGamblingBanner compact />
      </div>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function SpotlightSkeleton() {
  return (
    <div className="space-y-4 animate-pulse" aria-busy="true" role="status">
      <span className="sr-only">Loading best bet</span>
      <div className="h-3 w-32 rounded bg-slate-800/60" />
      <div className="space-y-2">
        <div className="h-6 w-64 rounded bg-slate-800/60" />
        <div className="h-3 w-20 rounded bg-slate-800/40" />
      </div>
      <div className="flex gap-6">
        <div className="h-10 w-16 rounded bg-slate-800/60" />
        <div className="h-10 w-16 rounded bg-slate-800/60" />
        <div className="h-10 w-16 rounded bg-slate-800/60" />
      </div>
    </div>
  );
}

// ─── Public component ─────────────────────────────────────────────────────────

export const BestBetSpotlight = memo(function BestBetSpotlight({
  className,
}: {
  className?: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["best-bet-spotlight"],
    queryFn: fetchScan,
    staleTime: 5 * 60_000,
  });

  const topBet =
    data?.fixtures && data.fixtures.length > 0
      ? [...data.fixtures].sort((a, b) => b.edge_pct - a.edge_pct)[0]
      : null;

  return (
    <section
      aria-label="Research market comparison"
      className={cn(
        "rounded-[24px] border border-white/[0.07] bg-slate-950/80 p-6 shadow-lg",
        className,
      )}
    >
      <p className="mb-4 flex items-center gap-2 text-xs uppercase tracking-[0.3em] text-slate-300">
        <TrendingUp className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
        Research market comparison
      </p>

      {isLoading ? (
        <SpotlightSkeleton />
      ) : isError ? (
        <div className="flex items-center gap-2 py-6 text-rose-400" role="alert">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <span className="text-sm">Scanner unavailable</span>
        </div>
      ) : data?.data_gap ? (
        <DataGapState />
      ) : !topBet ? (
        <NoEdgeState />
      ) : (
        <SpotlightCard bet={topBet} />
      )}
    </section>
  );
});
