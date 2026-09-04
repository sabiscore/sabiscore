"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
} from "recharts";
import { ShieldCheck, Info, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

// ─── Types ──────────────────────────────────────────────────────────────────
// Shapes below are read directly from `_compute_calibration_metrics()` /
// `block_bootstrap_ci()` in backend/src/api/endpoints/performance.py and
// backend/src/models/evaluation/metrics.py — not guessed from the frontend
// side. `binned_probabilities`, top-level `brier_score`, `rps`, and
// `walk_forward_seasons` are never present on the wire and have been dropped.

/** One Künsch (1989) block-bootstrap confidence interval, as returned by
 * `block_bootstrap_ci()`. `ci_lower`/`ci_upper` are `null` when no bootstrap
 * replicate scored — never fabricate a range in that case. */
export interface BootstrapCI {
  point_estimate: number;
  ci_lower: number | null;
  ci_upper: number | null;
  ci_level: number;
  n_bootstrap: number;
  block_size: number;
  n_samples: number;
  note?: string;
}

/** One reliability bin for a single outcome class. `predicted_mean`/
 * `empirical_frequency` are `null` for an unfilled bin (`count: 0`) —
 * never a fabricated 0.0 or bin-midpoint stand-in. */
export interface CalibrationBin {
  bin_index: number;
  predicted_mean: number | null;
  empirical_frequency: number | null;
  count: number;
}

interface CalibrationData {
  sample_size?: number;
  meets_sample_floor?: boolean;
  minimum_sample_size?: number;
  curves?: {
    home_win?: CalibrationBin[];
    draw?: CalibrationBin[];
    away_win?: CalibrationBin[];
  };
  ece?: {
    mean?: number;
    class_0?: number;
    class_1?: number;
    class_2?: number;
  };
  brier_decomposition?: {
    mean?: {
      brier_score?: number;
      reliability?: number;
      resolution?: number;
      uncertainty?: number;
    };
  };
  confidence_intervals?: {
    rps?: BootstrapCI;
    brier_score?: BootstrapCI;
    ece_mean?: BootstrapCI;
  };
}

type OutcomeCurves = NonNullable<CalibrationData["curves"]>;
type OutcomeKey = "home_win" | "draw" | "away_win";

interface PlotBin {
  x: number;
  y: number;
  count: number;
}

// ─── Pure helpers (exported for direct unit testing) ───────────────────────

function roundTo(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function hasObservedValue(
  b: CalibrationBin,
): b is CalibrationBin & { predicted_mean: number; empirical_frequency: number } {
  return b.predicted_mean != null && b.empirical_frequency != null;
}

/** Drop unfilled bins rather than plotting a fabricated zero. */
export function toPlotBins(rawBins: CalibrationBin[]): PlotBin[] {
  return rawBins.filter(hasObservedValue).map((b) => ({
    x: roundTo(b.predicted_mean, 2),
    y: roundTo(b.empirical_frequency, 3),
    count: b.count,
  }));
}

/** Pool the three per-class curves into one count-weighted "overall" curve,
 * keyed by `bin_index` so a class's unfilled bin never drags the average
 * down. This uses data already in the response — `binned_probabilities`
 * (which the "Overall Ensemble" tab used to silently fall back to reading as
 * `curves.home_win`) is never present on the wire. */
export function poolCurves(curves: OutcomeCurves): PlotBin[] {
  const byIndex = new Map<number, { x: number; y: number; count: number }>();
  for (const classBins of [curves.home_win, curves.draw, curves.away_win]) {
    for (const b of (classBins ?? []).filter(hasObservedValue)) {
      if (!b.count) continue;
      const acc = byIndex.get(b.bin_index) ?? { x: 0, y: 0, count: 0 };
      acc.x += b.predicted_mean * b.count;
      acc.y += b.empirical_frequency * b.count;
      acc.count += b.count;
      byIndex.set(b.bin_index, acc);
    }
  }
  return [...byIndex.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, acc]) => ({
      x: roundTo(acc.x / acc.count, 2),
      y: roundTo(acc.y / acc.count, 3),
      count: acc.count,
    }));
}

/** Format an aggregate bootstrap CI, or "—" when it wasn't computed. */
function formatCi(ci: BootstrapCI | undefined, fmt: (v: number) => string): string {
  if (!ci || ci.ci_lower == null || ci.ci_upper == null) return "—";
  return `[${fmt(ci.ci_lower)}, ${fmt(ci.ci_upper)}]`;
}

const OUTCOME_TABS: Array<{ id: "overall" | OutcomeKey; label: string }> = [
  { id: "overall", label: "Overall Ensemble" },
  { id: "home_win", label: "Home Win" },
  { id: "draw", label: "Draw" },
  { id: "away_win", label: "Away Win" },
];

export function CalibrationCurveChart({
  league,
  className,
}: {
  league?: string;
  className?: string;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<"overall" | OutcomeKey>("overall");
  const prefersReducedMotion = useReducedMotion();

  const { data, isLoading, error, refetch } = useQuery<CalibrationData>({
    queryKey: ["calibration-curve", league],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (league) params.append("league", league);
      const res = await fetch(`/api/model-performance/calibration?${params.toString()}`, {
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error("Failed to fetch calibration curve data");
      }
      return res.json();
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  const curves = data?.curves;
  const bins: PlotBin[] = curves
    ? selectedOutcome === "overall"
      ? poolCurves(curves)
      : toPlotBins(curves[selectedOutcome] ?? [])
    : [];

  // Extract metrics — no hardcoded fallback. An absent field renders "—", never
  // a plausible-looking number nobody measured.
  const eceValue = data?.ece?.mean ?? null;
  const brierMean = data?.brier_decomposition?.mean;
  const brierTotal = brierMean?.brier_score ?? null;
  const brierRel = brierMean?.reliability ?? null;
  const brierRes = brierMean?.resolution ?? null;
  const brierUnc = brierMean?.uncertainty ?? null;

  return (
    <div
      className={cn(
        "rounded-2xl border border-white/[0.08] bg-slate-900/80 p-5 shadow-xl backdrop-blur",
        className
      )}
      role="region"
      aria-label="Reliability Diagram and Probability Calibration"
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.08] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
              <ShieldCheck className="h-4 w-4" />
            </span>
            <h2 className="text-lg font-bold text-white tracking-tight">
              Probability Calibration & Reliability Diagram
            </h2>
          </div>
          <p className="mt-1 text-xs text-slate-400">
            Empirical vs. predicted probabilities, binned per outcome class.
          </p>
        </div>

        <button
          type="button"
          onClick={() => refetch()}
          className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-slate-800 text-slate-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
          aria-label="Refresh calibration data"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
        </button>
      </div>

      {/* Outcome Selector Tabs */}
      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label="Select outcome class">
        {OUTCOME_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            aria-pressed={selectedOutcome === tab.id}
            onClick={() => setSelectedOutcome(tab.id)}
            className={cn(
              "min-h-9 rounded-lg px-3 py-1 text-xs font-semibold transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400",
              selectedOutcome === tab.id
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                : "bg-white/[0.03] text-slate-400 border border-white/[0.05] hover:bg-white/[0.06] hover:text-slate-200"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {data && data.meets_sample_floor === false ? (
        <div className="mt-5 flex h-72 flex-col items-center justify-center rounded-xl bg-slate-800/40 p-4 text-center">
          <Info className="h-6 w-6 text-amber-400 mb-2" />
          <p className="text-sm font-semibold text-slate-200">Not enough settled predictions yet</p>
          <p className="mt-1 text-xs text-slate-400 max-w-md">
            Calibration requires at least {data.minimum_sample_size ?? "more"} settled predictions to compute
            a meaningful decomposition — currently {data.sample_size ?? 0}.
          </p>
        </div>
      ) : (
      <>
      {/* Chart Section */}
      <div className="mt-5">
        {isLoading ? (
          <div className="flex h-72 items-center justify-center rounded-xl bg-slate-800/40">
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <RefreshCw className="h-4 w-4 animate-spin text-emerald-400" />
              <span>Calculating reliability diagram...</span>
            </div>
          </div>
        ) : error ? (
          <div className="flex h-72 flex-col items-center justify-center rounded-xl bg-slate-800/40 p-4 text-center">
            <Info className="h-6 w-6 text-amber-400 mb-2" />
            <p className="text-sm font-semibold text-slate-200">Calibration metrics currently settling</p>
            <p className="mt-1 text-xs text-slate-400 max-w-md">
              Walk-forward verification requires a continuous series of settled fixtures to compute empirical bins.
            </p>
          </div>
        ) : bins.length === 0 ? (
          <div className="flex h-72 items-center justify-center rounded-xl bg-slate-800/40 text-sm text-slate-400">
            Awaiting settled match prediction records.
          </div>
        ) : (
          <div className="h-72 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart
                data={bins}
                margin={{ top: 15, right: 20, bottom: 20, left: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
                <XAxis
                  dataKey="x"
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.2, 0.4, 0.6, 0.8, 1.0]}
                  stroke="#94a3b8"
                  fontSize={11}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                  label={{
                    value: "Forecasted Probability Bin",
                    position: "insideBottom",
                    offset: -12,
                    fill: "#94a3b8",
                    fontSize: 11,
                  }}
                />
                <YAxis
                  type="number"
                  domain={[0, 1]}
                  ticks={[0, 0.2, 0.4, 0.6, 0.8, 1.0]}
                  stroke="#94a3b8"
                  fontSize={11}
                  tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                  label={{
                    value: "Observed Empirical Frequency",
                    angle: -90,
                    position: "insideLeft",
                    offset: 12,
                    fill: "#94a3b8",
                    fontSize: 11,
                  }}
                />
                <Tooltip
                  content={({ active, payload }) => {
                    if (active && payload && payload.length) {
                      const d = payload[0].payload as PlotBin;
                      return (
                        <div className="rounded-xl border border-white/10 bg-slate-950/95 p-3 shadow-2xl backdrop-blur text-xs">
                          <p className="font-bold text-emerald-400">
                            Bin: {(d.x * 100).toFixed(0)}% (N = {d.count})
                          </p>
                          <p className="mt-1 text-slate-200">
                            Observed: <span className="font-semibold text-white">{(d.y * 100).toFixed(1)}%</span>
                          </p>
                        </div>
                      );
                    }
                    return null;
                  }}
                />
                {/* 45-degree Perfect Calibration Line */}
                <ReferenceLine
                  segment={[
                    { x: 0, y: 0 },
                    { x: 1, y: 1 },
                  ]}
                  stroke="#64748b"
                  strokeDasharray="4 4"
                  label={{
                    value: "Perfect Calibration",
                    position: "insideTopLeft",
                    fill: "#64748b",
                    fontSize: 10,
                  }}
                />
                {/* Actual Reliability Curve */}
                <Line
                  type="monotone"
                  dataKey="y"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#10b981", stroke: "#07110f", strokeWidth: 1.5 }}
                  activeDot={{ r: 6, fill: "#34d399" }}
                  name="Observed Frequency"
                  isAnimationActive={!prefersReducedMotion}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* Murphy Brier Decomposition & ECE Metric Cards */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5 border-t border-white/[0.08] pt-4">
        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Multiclass ECE
          </p>
          <p className="mt-1 text-xl font-bold text-emerald-400 tabular-nums">
            {eceValue !== null ? `${(eceValue * 100).toFixed(2)}%` : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Expected Calibration Error (≤ 3% goal)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Brier Total
          </p>
          <p className="mt-1 text-xl font-bold text-white tabular-nums">
            {brierTotal !== null ? brierTotal.toFixed(3) : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Rel - Res + Unc (lower is better)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Reliability (REL)
          </p>
          <p className="mt-1 text-xl font-bold text-emerald-400 tabular-nums">
            {brierRel !== null ? brierRel.toFixed(4) : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Calibration error (0.0 is perfect)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Resolution (RES)
          </p>
          <p className="mt-1 text-xl font-bold text-sky-400 tabular-nums">
            {brierRes !== null ? brierRes.toFixed(4) : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Discrimination (higher is better)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Uncertainty (UNC)
          </p>
          <p className="mt-1 text-xl font-bold text-amber-400 tabular-nums">
            {brierUnc !== null ? brierUnc.toFixed(4) : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Inherent event entropy</p>
        </div>
      </div>

      {/* Aggregate Künsch (1989) block-bootstrap confidence intervals — the only
          real CIs this endpoint computes; there is no per-bin CI on the wire. */}
      {(data?.confidence_intervals?.rps?.n_bootstrap !== 0 ||
        data?.confidence_intervals?.brier_score?.n_bootstrap !== 0 ||
        data?.confidence_intervals?.ece_mean?.n_bootstrap !== 0) && (
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
          {data?.confidence_intervals?.rps?.n_bootstrap !== 0 && (
            <span>RPS 95% CI: {formatCi(data?.confidence_intervals?.rps, (v) => v.toFixed(3))}</span>
          )}
          {data?.confidence_intervals?.brier_score?.n_bootstrap !== 0 && (
            <span>
              Brier 95% CI: {formatCi(data?.confidence_intervals?.brier_score, (v) => v.toFixed(3))}
            </span>
          )}
          {data?.confidence_intervals?.ece_mean?.n_bootstrap !== 0 && (
            <span>
              ECE 95% CI:{" "}
              {formatCi(data?.confidence_intervals?.ece_mean, (v) => `${(v * 100).toFixed(2)}%`)}
            </span>
          )}
        </div>
      )}
      </>
      )}
    </div>
  );
}

export default CalibrationCurveChart;
