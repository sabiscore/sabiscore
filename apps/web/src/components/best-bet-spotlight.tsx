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
    <div className="flex flex-col items-center gap-1.5 py-2 text-center" role="status">
      <Database className="h-4 w-4 text-slate-400" aria-hidden="true" />
      <p className="text-xs font-semibold text-slate-300">No certified opportunities right now</p>
      <p className="text-[11px] text-slate-400">
        Predictions appear here once fixtures are analyzed.
      </p>
    </div>
  );
}

function NoEdgeState() {
  return (
    <div className="flex flex-col items-center gap-1.5 py-2 text-center" role="status">
      <TrendingUp className="h-4 w-4 text-slate-400" aria-hidden="true" />
      <p className="text-xs font-semibold text-slate-300">No research candidates this week</p>
      <p className="text-[11px] text-slate-400">No model-market comparisons cleared the evidence filter.</p>
    </div>
  );
}

// ─── Spotlight card ───────────────────────────────────────────────────────────

function SpotlightCard({ bet }: { bet: ValueBetFixture }) {
  const leagueChipCls =
    LEAGUE_COLORS[bet.league] ?? "border-slate-700/50 text-slate-400 bg-slate-800/50";
  const tier = confidenceTier(bet.confidence);

  return (
    <div className="space-y-2">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            leagueChipCls,
          )}
        >
          {bet.league}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-slate-300">
          Largest research gap this week
        </span>
      </div>

      {/* Match */}
      <div>
        <p className="text-base font-bold text-white sm:text-lg">
          {bet.homeTeam}
          <span className="mx-1.5 text-slate-300 font-normal">vs</span>
          {bet.awayTeam}
        </p>
        <time dateTime={bet.kickoffUtc} className="text-[10px] text-slate-400">
          {formatKickoff(bet.kickoffUtc)}
        </time>
      </div>

      {/* Metrics row */}
      <div className="flex flex-wrap items-end gap-3 sm:gap-4">
        {/* Edge */}
        <div>
          <p className="text-[9px] uppercase tracking-wider text-slate-300">Edge</p>
          <p className="flex items-center gap-0.5 text-xl font-black text-emerald-400 tabular-nums leading-none sm:text-2xl">
            <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
            {bet.edge_pct.toFixed(1)}%
          </p>
        </div>

        {/* Confidence */}
        <div>
          <p className="text-[9px] uppercase tracking-wider text-slate-300">Confidence</p>
          <p className={cn("text-sm font-bold leading-none sm:text-base", tier.cls)}>
            {(bet.confidence * 100).toFixed(0)}%
          </p>
          <p className={cn("text-[9px] mt-0.5", tier.cls)}>{tier.label}</p>
        </div>

        {/* Bet type */}
        <div>
          <p className="text-[9px] uppercase tracking-wider text-slate-300">Outcome</p>
          <p className="text-xs font-semibold capitalize text-slate-200 leading-none sm:text-sm">
            {bet.outcome}
          </p>
        </div>

        <div>
          <p className="text-[9px] uppercase tracking-wider text-slate-300">Stake</p>
          <p className="text-xs font-semibold text-slate-300 leading-none sm:text-sm">Disabled</p>
          <p className="mt-0.5 text-[9px] text-slate-400">uncertified generation</p>
        </div>
      </div>

      {/* Responsible gambling notice — required below every stake surface */}
      <div className="pt-0.5">
        <ResponsibleGamblingBanner compact />
      </div>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function SpotlightSkeleton() {
  return (
    <div className="space-y-2.5 animate-pulse" aria-busy="true" role="status">
      <span className="sr-only">Loading best bet</span>
      <div className="h-3 w-32 rounded bg-slate-800/60" />
      <div className="space-y-1">
        <div className="h-4 w-48 rounded bg-slate-800/60" />
        <div className="h-2.5 w-16 rounded bg-slate-800/40" />
      </div>
      <div className="flex gap-3">
        <div className="h-7 w-12 rounded bg-slate-800/60" />
        <div className="h-7 w-12 rounded bg-slate-800/60" />
        <div className="h-7 w-12 rounded bg-slate-800/60" />
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
        "rounded-2xl border border-white/[0.07] bg-slate-950/80 p-3 sm:p-4 shadow-lg",
        className,
      )}
    >
      <p className="mb-2 flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-300">
        <TrendingUp className="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
        Research market comparison
      </p>

      {isLoading ? (
        <SpotlightSkeleton />
      ) : isError ? (
        <div className="flex items-center gap-2 py-2.5 text-rose-400" role="alert">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <span className="text-xs">Scanner unavailable</span>
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
