"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { Clock, AlertCircle } from "lucide-react";
// recharts is ~100 kB and renders client-side only (it measures its container),
// so it is loaded on demand rather than in the /performance first-load bundle.
const RollingAccuracyChart = dynamic(
  () => import("@/components/rolling-accuracy-chart").then((m) => m.RollingAccuracyChart),
  {
    ssr: false,
    loading: () => (
      <div
        className="h-80 animate-pulse rounded-2xl bg-slate-800/50"
        role="status"
        aria-label="Loading accuracy chart"
      />
    ),
  },
);
import { ValueBetScanner } from "@/components/value-bet-scanner";
import { formatLagosTimestamp } from "@/lib/full-analysis-contract";
import { canonicalLeagueId } from "@/lib/league";
import { RPS_PROMOTION_GATE, meetsRpsGate } from "@/lib/model-gates";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

/**
 * Mirrors GET /api/v1/model-performance/summary.
 *
 * The previous shape (accuracy_30d / accuracy_season / clv_30d / roi_30d /
 * bets_tracked) was written against an endpoint that had never once returned
 * 200, and shares no field with what the settlement join actually produces.
 *
 * CLV and ROI are deliberately absent rather than pending:
 *   · CLV needs the closing price beside each prediction; `MatchPredictionLog`
 *     stores probabilities only, so there is nothing to join a closing line to.
 *   · ROI needs a realised return on a placed stake, and this platform never
 *     places one by construction (NO_BET / HOLD / shadow evaluation only).
 * Leaving them on screen as permanent em-dashes would imply they are merely
 * awaiting data. They are not.
 */
interface PerfSummary {
  status?: "OK" | "METRICS_UNAVAILABLE";
  reason?: string;
  total_settled?: number;
  settled_predictions?: number;
  accuracy_overall?: number;
  rps_overall?: number;
  n_splits?: number;
  validated_at?: string;
  error?: string;
}

// ─── Summary stats ────────────────────────────────────────────────────────────

function StatCard({
  label,
  value,
  detail,
  positive,
}: {
  label: string;
  value: string;
  detail?: string;
  positive?: boolean | null;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-slate-900/70 px-4 py-4 shadow-lg">
      <p className="text-xs font-medium uppercase tracking-wider text-slate-500">{label}</p>
      <p
        className={cn(
          "mt-1 text-2xl font-bold tracking-tight tabular-nums",
          positive === undefined || positive === null
            ? "text-white"
            : positive
              ? "text-emerald-400"
              : "text-amber-400",
        )}
      >
        {value}
      </p>
      {detail && <p className="mt-0.5 text-xs leading-snug text-slate-500">{detail}</p>}
    </div>
  );
}

/** Empty states carry a cause and a resolving condition, never a bare shrug. */
function SummaryNotice({
  tone,
  title,
  children,
}: {
  tone: "info" | "error";
  title: string;
  children: React.ReactNode;
}) {
  const Icon = tone === "error" ? AlertCircle : Clock;
  return (
    <div
      data-testid="performance-summary-notice"
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex gap-3 rounded-2xl border px-4 py-4",
        tone === "error"
          ? "border-rose-500/30 bg-rose-500/[0.07]"
          : "border-amber-500/30 bg-amber-500/[0.07]",
      )}
    >
      <Icon
        className={cn("mt-0.5 h-5 w-5 shrink-0", tone === "error" ? "text-rose-400" : "text-amber-400")}
        aria-hidden="true"
      />
      <div className="min-w-0 space-y-1">
        <p
          className={cn(
            "text-sm font-semibold",
            tone === "error" ? "text-rose-200" : "text-amber-200",
          )}
        >
          {title}
        </p>
        <div className="text-sm leading-relaxed text-slate-400">{children}</div>
      </div>
    </div>
  );
}

const LEAGUES = [
  { id: "", name: "All Leagues" },
  { id: "EPL", name: "EPL" },
  { id: "La Liga", name: "La Liga" },
  { id: "Bundesliga", name: "Bundesliga" },
  { id: "Serie A", name: "Serie A" },
  { id: "Ligue 1", name: "Ligue 1" },
  { id: "Eredivisie", name: "Eredivisie" },
  { id: "UCL", name: "UCL" },
];

const WINDOWS = [
  { value: 14, label: "14d" },
  { value: 30, label: "30d" },
  { value: 90, label: "90d" },
];

// ─── Main client component ────────────────────────────────────────────────────

export function PerformancePageClient() {
  const [selectedLeague, setSelectedLeague] = useState("");
  const [selectedWindow, setSelectedWindow] = useState(30);

  const { data: summary, isLoading } = useQuery<PerfSummary>({
    queryKey: ["model-performance-summary"],
    queryFn: async () => {
      const res = await fetch("/api/model-performance/summary", { cache: "no-store" });
      // A 503 here is usually the backend answering correctly that nothing has
      // settled yet, not an outage — the body says which. Throwing on !res.ok
      // would collapse both into one unexplained blank panel.
      return (await res.json()) as PerfSummary;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const hasMetrics = summary?.status === "OK";
  const accuracy = summary?.accuracy_overall;
  const rps = summary?.rps_overall;
  const rpsMeetsGate = meetsRpsGate(rps);
  const settled = summary?.total_settled ?? summary?.settled_predictions ?? 0;

  return (
    <div className="space-y-6">
      {/* Summary stats — rendered only when a walk-forward run actually produced them */}
      <section aria-label="Model performance summary">
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-hidden="true">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-800/50" />
            ))}
          </div>
        ) : hasMetrics ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard
                label="Model accuracy"
                value={accuracy !== undefined ? `${(accuracy * 100).toFixed(1)}%` : "—"}
                detail="Top-pick hit rate across walk-forward folds"
                positive={accuracy !== undefined ? accuracy >= 1 / 3 : null}
              />
              <StatCard
                label="Ranked probability score"
                value={rps !== undefined ? rps.toFixed(3) : "—"}
                detail={`Lower is better · promotion gate ≤ ${RPS_PROMOTION_GATE.toFixed(2)}`}
                positive={rpsMeetsGate}
              />
              <StatCard
                label="Settled predictions"
                value={settled.toLocaleString()}
                detail="Predictions matched to a final result"
              />
              <StatCard
                label="Validation folds"
                value={summary?.n_splits !== undefined ? String(summary.n_splits) : "—"}
                detail="Chronological splits — never random"
              />
            </div>
            {summary?.validated_at && (
              <p className="mt-2 text-right text-[11px] text-slate-600">
                Walk-forward validated{" "}
                <time dateTime={summary.validated_at}>
                  {formatLagosTimestamp(summary.validated_at)} WAT
                </time>
              </p>
            )}
          </>
        ) : summary?.reason === "backend_unreachable" ? (
          <SummaryNotice tone="error" title="Performance service unreachable">
            {summary.error
              ? `The backend did not respond: ${summary.error}.`
              : "The backend did not respond."}{" "}
            Metrics will reappear once it recovers.
          </SummaryNotice>
        ) : (
          <SummaryNotice tone="info" title="Awaiting settled predictions">
            Accuracy and ranked probability score are computed only from predictions that
            have been matched to a completed fixture&apos;s final score.{" "}
            {settled > 0
              ? `${settled.toLocaleString()} have settled so far — not yet enough for a walk-forward run.`
              : "None have settled yet."}{" "}
            No figure is shown here until real results back it.
          </SummaryNotice>
        )}
      </section>

      {/* Chart controls */}
      <div className="flex flex-wrap items-center gap-2">
        <div
          className="flex flex-wrap items-center gap-1 rounded-xl border border-white/[0.06] bg-slate-900/60 p-1"
          role="group"
          aria-label="League filter"
        >
          {LEAGUES.map((l) => (
            <button
              key={l.id}
              type="button"
              data-testid={`league-filter-${l.id || "all"}`}
              onClick={() => setSelectedLeague(l.id)}
              aria-pressed={selectedLeague === l.id}
              className={cn(
                "min-h-9 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                selectedLeague === l.id
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:text-slate-200",
              )}
            >
              {l.name}
            </button>
          ))}
        </div>

        <div
          className="flex items-center gap-1 rounded-xl border border-white/[0.06] bg-slate-900/60 p-1"
          role="group"
          aria-label="Rolling window"
        >
          {WINDOWS.map((w) => (
            <button
              key={w.value}
              type="button"
              data-testid={`window-filter-${w.value}`}
              onClick={() => setSelectedWindow(w.value)}
              aria-pressed={selectedWindow === w.value}
              className={cn(
                "min-h-9 rounded-lg px-2.5 py-1 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400",
                selectedWindow === w.value
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:text-slate-200",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {/* Two league vocabularies exist in apps/web; the proxy boundary takes the
          canonical one. Never send a raw display string (see lib/league.ts). */}
      <RollingAccuracyChart
        league={canonicalLeagueId(selectedLeague) ?? ""}
        window={selectedWindow}
      />

      <ValueBetScanner days={7} />
    </div>
  );
}
