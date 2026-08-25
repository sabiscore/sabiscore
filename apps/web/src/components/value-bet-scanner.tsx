"use client";

import { memo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, AlertCircle, Loader2, ArrowUpRight, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";

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
  // Phase 4 additions
  model_prob?: number;
  implied_prob?: number;
  created_at?: string;
}

interface ValueBetScanResponse {
  fixtures: ValueBetFixture[];
  total: number;
  days: number;
  source: string;
  data_gap?: boolean;
  status?: string;
  reason?: string | null;
  retryable?: boolean;
  freshness?: Record<string, unknown> | null;
  provenance?: string[];
  generated_at?: string | null;
}

// ─── League chip colors ───────────────────────────────────────────────────────

const LEAGUE_COLORS: Record<string, string> = {
  EPL: "border-purple-500/30 text-purple-300 bg-purple-500/10",
  "La Liga": "border-amber-500/30 text-amber-300 bg-amber-500/10",
  Bundesliga: "border-red-500/30 text-red-300 bg-red-500/10",
  "Serie A": "border-blue-500/30 text-blue-300 bg-blue-500/10",
  "Ligue 1": "border-cyan-500/30 text-cyan-300 bg-cyan-500/10",
  Eredivisie: "border-orange-500/30 text-orange-300 bg-orange-500/10",
  UCL: "border-indigo-500/30 text-indigo-300 bg-indigo-500/10",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function confidenceLabel(c: number): { label: string; cls: string } {
  if (c >= 0.8) return { label: "High", cls: "text-emerald-400 bg-emerald-500/15 border-emerald-500/30" };
  if (c >= 0.65) return { label: "Med", cls: "text-amber-400 bg-amber-500/15 border-amber-500/30" };
  return { label: "Low", cls: "text-rose-400 bg-rose-500/15 border-rose-500/30" };
}

function dataQualityLabel(fixture: ValueBetFixture): { label: string; cls: string } {
  if (fixture.model_prob == null && fixture.implied_prob == null) {
    return { label: "PARTIAL", cls: "text-fuchsia-400 bg-fuchsia-500/10 border-fuchsia-500/30" };
  }
  if (fixture.confidence >= 0.7 && fixture.model_prob && fixture.implied_prob) {
    return { label: "COMPLETE", cls: "text-emerald-400 bg-emerald-500/10 border-emerald-500/30" };
  }
  return { label: "PARTIAL", cls: "text-amber-400 bg-amber-500/10 border-amber-500/30" };
}

function formatKickoff(utcStr: string): string {
  try {
    const d = new Date(utcStr);
    return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  } catch {
    return utcStr;
  }
}

function PredictionAgePill({ createdAt }: { createdAt?: string }) {
  if (!createdAt) return null;
  const ageSecs = Math.round((Date.now() - new Date(createdAt).getTime()) / 1000);
  const title = `Prediction generated at ${new Date(createdAt).toLocaleString()}`;

  if (ageSecs < 30 * 60) {
    return <span className="text-[9px] text-emerald-500" title={title}>Fresh</span>;
  }
  if (ageSecs < 2 * 3600) {
    return <span className="text-[9px] text-slate-500" title={title}>{Math.round(ageSecs / 60)}m old</span>;
  }
  if (ageSecs < 24 * 3600) {
    const hrs = Math.round(ageSecs / 3600);
    return (
      <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-1.5 py-0 text-[9px] text-amber-400" title={title}>
        {hrs}h old
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-rose-500/30 bg-rose-500/10 px-1.5 py-0 text-[9px] text-rose-400" title={title}>
      Outdated ↻
    </span>
  );
}

async function fetchValueBets(days: number): Promise<ValueBetScanResponse> {
  const res = await fetch(`/api/value-bet-scan?days=${days}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  // Normalise — backend may return wrapped or flat array
  if (Array.isArray(data)) {
    return { fixtures: data, total: data.length, days, source: "api", data_gap: false };
  }
  return {
    fixtures: (data.fixtures ?? data.items ?? []).map((f: Record<string, unknown>) => ({
      matchId: (f.match_id ?? f.matchId ?? "") as string,
      homeTeam: (f.home_team ?? f.homeTeam ?? "") as string,
      awayTeam: (f.away_team ?? f.awayTeam ?? "") as string,
      league: (f.league ?? "") as string,
      kickoffUtc: (f.kickoff_utc ?? f.kickoffUtc ?? "") as string,
      outcome: (f.outcome ?? "") as string,
      edge_pct: Number(f.edge_pct ?? 0),
      confidence: Number(f.confidence ?? 0),
      kelly_stake_pct: f.kelly_stake_pct != null ? Number(f.kelly_stake_pct) : undefined,
      model_prob: f.model_prob != null ? Number(f.model_prob) : undefined,
      implied_prob: f.implied_prob != null ? Number(f.implied_prob) : undefined,
      created_at: (f.created_at ?? "") as string,
    })),
    total: Number(data.total ?? 0),
    days: Number(data.days ?? days),
    source: (data.source ?? "api") as string,
    data_gap: Boolean(data.data_gap ?? false),
    status: typeof data.status === "string" ? data.status : undefined,
    reason: typeof data.reason === "string" ? data.reason : null,
    retryable: Boolean(data.retryable ?? false),
    freshness: data.freshness && typeof data.freshness === "object" ? data.freshness : null,
    provenance: Array.isArray(data.provenance) ? data.provenance.map(String) : [],
    generated_at: typeof data.generated_at === "string" ? data.generated_at : null,
  } as ValueBetScanResponse;
}

// ─── Empty states ─────────────────────────────────────────────────────────────

function DataGapState({ data }: { data?: ValueBetScanResponse }) {
  return (
    <div className="flex flex-col items-center gap-2 py-4 text-center" data-testid="value-bet-data-gap">
      <TrendingUp className="h-6 w-6 text-slate-500" aria-hidden="true" />
      <p className="text-xs font-semibold text-slate-300">No fresh, fully gated candidates</p>
      <p className="max-w-md text-[11px] text-slate-400">
        The scanner reads persisted analysis only. Missing, stale, partial, zero-stake, or non-actionable records are intentionally excluded.
      </p>
      {data?.generated_at ? (
        <p className="text-[10px] text-slate-500">
          Checked {new Date(data.generated_at).toLocaleString()} · {data.provenance?.join(" + ") || "provenance unavailable"}
        </p>
      ) : null}
      <Link
        href="/match"
        className="mt-0.5 inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 transition-colors focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900"
      >
        <ExternalLink className="h-3 w-3" aria-hidden="true" />
        Go to Match
      </Link>
    </div>
  );
}

function LegitimateEmptyState({ days }: { days: number }) {
  return (
    <div className="flex flex-col items-center gap-2 py-4 text-center" data-testid="value-bet-empty">
      <TrendingUp className="h-6 w-6 text-slate-500" aria-hidden="true" />
      <p className="text-xs font-semibold text-slate-300">No value edges detected</p>
      <p className="text-[11px] text-slate-400">
        No bets above threshold for current filters in the next {days} days. Min edge 4.2%.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-1.5 py-4" role="alert" data-testid="value-bet-error">
      <div className="flex items-center gap-2 text-rose-400">
        <AlertCircle className="h-4 w-4" aria-hidden="true" />
        <span className="text-xs">Scanner unavailable. Try again shortly.</span>
      </div>
      <button
        onClick={onRetry}
        className="text-xs text-slate-400 underline underline-offset-2 hover:text-slate-200 transition-colors"
      >
        Retry
      </button>
    </div>
  );
}

// ─── Row ──────────────────────────────────────────────────────────────────────

function ValueBetRow({ fixture }: { fixture: ValueBetFixture }) {
  const { label, cls } = confidenceLabel(fixture.confidence);
  const { label: dqLabel, cls: dqCls } = dataQualityLabel(fixture);
  const leagueChip =
    LEAGUE_COLORS[fixture.league] ?? "border-slate-700/50 text-slate-400 bg-slate-800/50";
  const outcomeLabel = fixture.outcome
    ? fixture.outcome.replace(/_/g, " ")
    : "—";

  return (
    <tr
      data-testid="value-bet-row"
      className="border-b border-white/[0.04] transition-colors hover:bg-white/[0.02]"
    >
      {/* Match */}
      <td className="py-3 pl-4 pr-2">
        <p className="text-sm font-medium text-white">
          {fixture.homeTeam}{" "}
          <span className="text-slate-500" aria-hidden="true">vs</span>{" "}
          {fixture.awayTeam}
        </p>
        <div className="flex items-center gap-2">
          <time dateTime={fixture.kickoffUtc} className="text-[11px] text-slate-500">
            {formatKickoff(fixture.kickoffUtc)}
          </time>
          <PredictionAgePill createdAt={fixture.created_at} />
        </div>
      </td>

      {/* League */}
      <td className="px-2 py-3">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
            leagueChip,
          )}
        >
          {fixture.league}
        </span>
      </td>

      {/* Market / Bet */}
      <td className="px-2 py-3 text-xs text-slate-300 capitalize">{outcomeLabel}</td>

      {/* Model vs Implied */}
      <td className="px-2 py-3">
        {fixture.model_prob != null && fixture.implied_prob != null ? (
          <div className="text-[11px] tabular-nums text-slate-400 space-y-0.5">
            <div>
              <span className="text-slate-500">M</span>{" "}
              <span className="text-slate-200">{(fixture.model_prob * 100).toFixed(1)}%</span>
            </div>
            <div>
              <span className="text-slate-500">Mkt</span>{" "}
              <span className="text-slate-400">{(fixture.implied_prob * 100).toFixed(1)}%</span>
            </div>
          </div>
        ) : (
          <span className="text-[10px] text-slate-600">—</span>
        )}
      </td>

      {/* EV (renamed from Edge) */}
      <td className="px-2 py-3">
        <span className="flex items-center gap-1 text-sm font-bold text-emerald-400">
          <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
          {fixture.edge_pct.toFixed(1)}%
        </span>
      </td>

      {/* Data Quality */}
      <td className="px-2 py-3">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider",
            dqCls,
          )}
        >
          {dqLabel}
        </span>
      </td>

      {/* Confidence */}
      <td className="py-3 pl-2 pr-4">
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold",
            cls,
          )}
        >
          {label}
        </span>
      </td>
    </tr>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export const ValueBetScanner = memo(function ValueBetScanner({
  days = 7,
  className,
}: {
  days?: number;
  className?: string;
}) {
  const [activeDays, setActiveDays] = useState(days);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["value-bet-scan", activeDays],
    queryFn: () => fetchValueBets(activeDays),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const fixtures = data?.fixtures ?? [];
  const isDataGap = Boolean(data?.data_gap) && fixtures.length === 0;
  const isLegitimateEmpty = !isDataGap && fixtures.length === 0 && !isError && !isLoading;

  return (
    <section
      data-testid="value-bet-scanner"
      className={cn("rounded-2xl border border-white/[0.07] bg-slate-900/70 shadow-lg", className)}
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.06] px-4 py-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-emerald-400" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-white">Value Bet Scanner</h2>
          {fixtures.length > 0 && (
            <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[11px] font-bold text-emerald-300">
              {fixtures.length}
            </span>
          )}
        </div>

        {/* Day filter */}
        <div className="flex items-center gap-1" role="group" aria-label="Days horizon">
          {[3, 7, 14].map((d) => (
            <button
              key={d}
              data-testid={`days-filter-${d}`}
              onClick={() => setActiveDays(d)}
              aria-pressed={activeDays === d}
              className={cn(
                "min-h-[44px] rounded-lg px-2.5 py-1 text-xs font-medium transition-colors",
                activeDays === d
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:text-slate-200",
              )}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-4 text-slate-400" aria-live="polite" aria-busy="true">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          <span className="text-xs">Scanning for value…</span>
        </div>
      ) : isError ? (
        <ErrorState onRetry={() => void refetch()} />
      ) : isDataGap ? (
        <DataGapState data={data} />
      ) : isLegitimateEmpty ? (
        <LegitimateEmptyState days={activeDays} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left" aria-label="Value bet opportunities">
            <thead>
              <tr className="border-b border-white/[0.05] text-[11px] font-medium uppercase tracking-wider text-slate-500">
                <th scope="col" className="py-2 pl-4 pr-2">Match</th>
                <th scope="col" className="px-2 py-2">League</th>
                <th scope="col" className="px-2 py-2">Market</th>
                <th scope="col" className="px-2 py-2">Model / Mkt</th>
                <th scope="col" className="px-2 py-2">EV</th>
                <th scope="col" className="px-2 py-2">Quality</th>
                <th scope="col" className="py-2 pl-2 pr-4">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {fixtures.map((f) => (
                <ValueBetRow key={`${f.matchId}-${f.outcome}`} fixture={f} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Footer */}
      {data && !isDataGap && (
        <p className="border-t border-white/[0.04] px-4 py-2 text-[10px] text-slate-400">
          Source: {data.source} · Min EV 4.2% · {activeDays}d window
        </p>
      )}
    </section>
  );
});
