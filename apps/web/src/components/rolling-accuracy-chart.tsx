"use client";

import { memo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { AlertCircle, Clock, TrendingUp } from "lucide-react";
import { RANDOM_BASELINE_ACCURACY } from "@/lib/model-gates";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

/** One walk-forward fold, projected by the backend's `_accuracy_series()`.
 *  Points are folds, not calendar days — each carries the population it scored. */
interface AccuracyPoint {
  date: string | null;
  accuracy: number;
  rps: number;
  n_matches: number;
}

interface ModelPerformanceResponse {
  status?: "OK" | "METRICS_UNAVAILABLE";
  reason?: string;
  league: string | null;
  window: number;
  series?: AccuracyPoint[];
  current_accuracy?: number;
  baseline_accuracy?: number;
  settled_predictions?: number;
  error?: string;
}

// ─── Data fetch ───────────────────────────────────────────────────────────────

async function fetchModelPerformance(
  league: string,
  window: number,
): Promise<ModelPerformanceResponse> {
  const params = new URLSearchParams({ window: String(window) });
  if (league) params.set("league", league);
  const res = await fetch(`/api/model-performance?${params}`, { cache: "no-store" });
  // 503 here is normally "nothing has settled in this window yet" — a correct
  // answer with a reason in the body, not a failure. Let the component say which.
  return (await res.json()) as ModelPerformanceResponse;
}

// ─── Fold labels ──────────────────────────────────────────────────────────────

/**
 * Label each fold for the x axis and the tooltip.
 *
 * Points are folds, not calendar days, so two chronological splits can end on
 * the same date — which rendered as two identical "Aug 29" ticks with two
 * identical tooltips and no way to tell the folds apart. Prefix the fold
 * ordinal only for the dates that actually repeat, so the common case stays a
 * clean date.
 */
export function withFoldLabels<T extends { date: string | null }>(
  series: readonly T[],
): Array<T & { label: string }> {
  const dates = series.map((pt) =>
    pt.date
      ? new Date(pt.date).toLocaleDateString([], { month: "short", day: "numeric" })
      : "—",
  );
  const repeated = new Set(dates.filter((d, i) => dates.indexOf(d) !== i));
  return series.map((pt, i) => ({
    ...pt,
    label: repeated.has(dates[i]) ? `F${i + 1} · ${dates[i]}` : dates[i],
  }));
}

// ─── Custom tooltip ───────────────────────────────────────────────────────────

function AccuracyTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ payload: AccuracyPoint & { label: string } }>;
  label?: string;
}) {
  const point = payload?.[0]?.payload;
  if (!active || !point) return null;
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/95 px-3 py-2 shadow-xl backdrop-blur-sm">
      <p className="mb-1.5 text-xs font-semibold text-slate-300">{label}</p>
      <dl className="space-y-0.5 text-xs">
        <div className="flex items-center gap-2">
          <dt className="text-slate-400">Accuracy</dt>
          <dd className="font-bold tabular-nums text-white">
            {(point.accuracy * 100).toFixed(1)}%
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-slate-400">RPS</dt>
          <dd className="font-bold tabular-nums text-white">{point.rps.toFixed(3)}</dd>
        </div>
        <div className="flex items-center gap-2">
          <dt className="text-slate-400">Scored on</dt>
          <dd className="font-bold tabular-nums text-white">
            {point.n_matches} {point.n_matches === 1 ? "match" : "matches"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function ChartSkeleton() {
  return (
    <div className="flex h-48 items-center justify-center animate-pulse" aria-hidden="true">
      <div className="h-40 w-full rounded-lg bg-slate-800/50" />
    </div>
  );
}

/** Empty and error states both name their cause — never a bare "no data". */
function ChartNotice({
  tone,
  message,
}: {
  tone: "info" | "error";
  message: string;
}) {
  const Icon = tone === "error" ? AlertCircle : Clock;
  return (
    <div
      className="flex flex-col items-center gap-2 py-12 text-center"
      data-testid={tone === "error" ? "chart-error" : "chart-empty"}
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon
        className={cn("h-7 w-7", tone === "error" ? "text-rose-400" : "text-slate-600")}
        aria-hidden="true"
      />
      <p className="max-w-sm text-sm text-slate-500">{message}</p>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export const RollingAccuracyChart = memo(function RollingAccuracyChart({
  league = "",
  window: rollingWindow = 30,
  className,
}: {
  league?: string;
  window?: number;
  className?: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["model-performance", league, rollingWindow],
    queryFn: () => fetchModelPerformance(league, rollingWindow),
    staleTime: 10 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const series = data?.series ?? [];
  const currentAccuracy = data?.current_accuracy;
  const baselineAccuracy = data?.baseline_accuracy ?? RANDOM_BASELINE_ACCURACY;

  const chartData = withFoldLabels(series);

  return (
    <section
      data-testid="rolling-accuracy-chart"
      className={cn("rounded-2xl border border-white/[0.07] bg-slate-900/70 p-4 shadow-lg", className)}
    >
      {/* Header */}
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-sky-400" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-white">
            Walk-forward accuracy
            {league ? ` · ${league}` : " · All leagues"}
          </h2>
        </div>
        {currentAccuracy !== undefined && (
          <span
            className={cn(
              "rounded-full border px-2.5 py-0.5 text-xs font-bold tabular-nums",
              currentAccuracy >= baselineAccuracy
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                : "border-amber-500/30 bg-amber-500/10 text-amber-300",
            )}
          >
            {(currentAccuracy * 100).toFixed(1)}%
          </span>
        )}
      </div>

      {/* Chart */}
      {isLoading ? (
        <ChartSkeleton />
      ) : isError || data?.reason === "backend_unreachable" ? (
        <ChartNotice
          tone="error"
          message="Could not reach the performance service. The chart will fill in once it responds."
        />
      ) : series.length === 0 ? (
        <ChartNotice
          tone="info"
          message={`No predictions have settled against a final result in the last ${rollingWindow} days${
            league ? ` for ${league}` : ""
          }, so there is nothing to score yet.`}
        />
      ) : (
        <div aria-label={`Walk-forward accuracy across ${series.length} chronological folds`}>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: -18, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis
                dataKey="label"
                tick={{ fill: "#64748b", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                domain={[0, 1]}
                tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
                tick={{ fill: "#64748b", fontSize: 10 }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip content={<AccuracyTooltip />} />
              <ReferenceLine
                y={baselineAccuracy}
                stroke="#f59e0b"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: "Random (33%)",
                  position: "insideTopRight",
                  fill: "#f59e0b",
                  fontSize: 9,
                }}
              />
              <Line
                type="monotone"
                dataKey="accuracy"
                name="Model accuracy"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={{ r: 2.5, fill: "#38bdf8" }}
                activeDot={{ r: 4, fill: "#38bdf8" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <p className="mt-2 text-right text-[10px] text-slate-600">
        {series.length > 0
          ? `${series.length} chronological folds · last ${rollingWindow} days`
          : `Last ${rollingWindow} days`}
      </p>
    </section>
  );
});
