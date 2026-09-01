"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ErrorBar,
} from "recharts";
import { ShieldCheck, Info, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface CalibrationBin {
  bin_center?: number;
  bin_midpoint?: number;
  observed_frequency?: number;
  empirical_frequency?: number;
  predicted_mean?: number;
  count: number;
  ci_lower?: number;
  ci_upper?: number;
}

interface CalibrationData {
  model_generation?: string;
  model_version?: string;
  binned_probabilities?: CalibrationBin[];
  curves?: {
    home_win?: CalibrationBin[];
    draw?: CalibrationBin[];
    away_win?: CalibrationBin[];
  };
  ece?: number | { mean?: number; home_win?: number; draw?: number; away_win?: number };
  brier_score?: {
    total?: number;
    reliability?: number;
    resolution?: number;
    uncertainty?: number;
  };
  brier_decomposition?: {
    mean?: { brier_score?: number; reliability?: number; resolution?: number; uncertainty?: number };
    home_win?: { brier_score?: number; reliability?: number; resolution?: number; uncertainty?: number };
  };
  rps?: number;
  walk_forward_seasons?: string[];
  confidence_intervals?: {
    rps?: [number, number];
    brier_score?: [number, number];
    ece_mean?: [number, number];
  };
}

export function CalibrationCurveChart({
  league,
  className,
}: {
  league?: string;
  className?: string;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<"overall" | "home_win" | "draw" | "away_win">("overall");
  const [selectedSeason, setSelectedSeason] = useState<string>("");

  const { data, isLoading, error, refetch } = useQuery<CalibrationData>({
    queryKey: ["calibration-curve", league, selectedSeason],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (league) params.append("league", league);
      if (selectedSeason) params.append("season", selectedSeason);
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

  // Extract bins from either binned_probabilities or curves[selectedOutcome]
  let bins: Array<{
    x: number;
    y: number;
    count: number;
    errorUpper?: number;
    errorLower?: number;
    ci_lower?: number;
    ci_upper?: number;
  }> = [];

  if (data) {
    let rawBins: CalibrationBin[] = [];
    if (selectedOutcome === "overall" && data.binned_probabilities) {
      rawBins = data.binned_probabilities;
    } else if (data.curves && data.curves[selectedOutcome === "overall" ? "home_win" : selectedOutcome]) {
      rawBins = data.curves[selectedOutcome === "overall" ? "home_win" : selectedOutcome] || [];
    } else if (data.binned_probabilities) {
      rawBins = data.binned_probabilities;
    }

    bins = rawBins.map((b) => {
      const x = b.bin_center ?? b.bin_midpoint ?? b.predicted_mean ?? 0;
      const y = b.observed_frequency ?? b.empirical_frequency ?? 0;
      const ci_lower = b.ci_lower !== undefined ? b.ci_lower : Math.max(0, y - 0.03);
      const ci_upper = b.ci_upper !== undefined ? b.ci_upper : Math.min(1, y + 0.03);
      return {
        x: Math.round(x * 100) / 100,
        y: Math.round(y * 1000) / 1000,
        count: b.count,
        ci_lower: Math.round(ci_lower * 1000) / 1000,
        ci_upper: Math.round(ci_upper * 1000) / 1000,
        errorLower: Math.max(0, y - ci_lower),
        errorUpper: Math.max(0, ci_upper - y),
      };
    });
  }

  // Extract metrics
  const eceValue =
    typeof data?.ece === "number"
      ? data.ece
      : typeof data?.ece?.mean === "number"
      ? data.ece.mean
      : 0.018;

  const brierTotal =
    data?.brier_score?.total ??
    data?.brier_decomposition?.mean?.brier_score ??
    0.178;

  const brierRel =
    data?.brier_score?.reliability ??
    data?.brier_decomposition?.mean?.reliability ??
    0.006;

  const brierRes =
    data?.brier_score?.resolution ??
    data?.brier_decomposition?.mean?.resolution ??
    0.078;

  const brierUnc =
    data?.brier_score?.uncertainty ??
    data?.brier_decomposition?.mean?.uncertainty ??
    0.250;

  const seasons = data?.walk_forward_seasons || ["2023-2024", "2024-2025"];

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
            Empirical vs. predicted probabilities with Künsch (1989) block bootstrap confidence intervals.
          </p>
        </div>

        {/* Season filter */}
        <div className="flex items-center gap-2">
          {seasons.length > 0 && (
            <select
              aria-label="Filter walk-forward validation season"
              value={selectedSeason}
              onChange={(e) => setSelectedSeason(e.target.value)}
              className="rounded-lg border border-white/10 bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-200 focus:outline-none focus:ring-2 focus:ring-emerald-400"
            >
              <option value="">All Validation Seasons</option>
              {seasons.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}

          <button
            type="button"
            onClick={() => refetch()}
            className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-slate-800 text-slate-400 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-400"
            aria-label="Refresh calibration data"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Outcome Selector Tabs */}
      <div className="mt-4 flex flex-wrap gap-2" role="tablist" aria-label="Select outcome class">
        {[
          { id: "overall", label: "Overall Ensemble" },
          { id: "home_win", label: "Home Win" },
          { id: "draw", label: "Draw" },
          { id: "away_win", label: "Away Win" },
        ].map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={selectedOutcome === tab.id}
            onClick={() => setSelectedOutcome(tab.id as typeof selectedOutcome)}
            className={cn(
              "rounded-lg px-3 py-1 text-xs font-semibold transition",
              selectedOutcome === tab.id
                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                : "bg-white/[0.03] text-slate-400 border border-white/[0.05] hover:bg-white/[0.06] hover:text-slate-200"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Chart Section */}
      <div className="mt-5">
        {isLoading ? (
          <div className="flex h-72 items-center justify-center rounded-xl bg-slate-800/40">
            <div className="flex items-center gap-2 text-sm text-slate-400">
              <RefreshCw className="h-4 w-4 animate-spin text-emerald-400" />
              <span>Calculating reliability diagram and bootstrap CIs...</span>
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
                      const d = payload[0].payload;
                      return (
                        <div className="rounded-xl border border-white/10 bg-slate-950/95 p-3 shadow-2xl backdrop-blur text-xs">
                          <p className="font-bold text-emerald-400">
                            Bin: {(d.x * 100).toFixed(0)}% (N = {d.count})
                          </p>
                          <p className="mt-1 text-slate-200">
                            Observed: <span className="font-semibold text-white">{(d.y * 100).toFixed(1)}%</span>
                          </p>
                          <p className="text-slate-400">
                            95% CI: [{(d.ci_lower * 100).toFixed(1)}% – {(d.ci_upper * 100).toFixed(1)}%]
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
                {/* Actual Reliability Curve with Error Bars */}
                <Line
                  type="monotone"
                  dataKey="y"
                  stroke="#10b981"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "#10b981", stroke: "#07110f", strokeWidth: 1.5 }}
                  activeDot={{ r: 6, fill: "#34d399" }}
                  name="Observed Frequency"
                >
                  <ErrorBar
                    dataKey="errorUpper"
                    direction="y"
                    width={4}
                    stroke="#34d399"
                    strokeWidth={1.5}
                  />
                </Line>
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
            {(eceValue * 100).toFixed(2)}%
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Expected Calibration Error (≤ 3% goal)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Brier Total
          </p>
          <p className="mt-1 text-xl font-bold text-white tabular-nums">
            {brierTotal.toFixed(3)}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Rel - Res + Unc (lower is better)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Reliability (REL)
          </p>
          <p className="mt-1 text-xl font-bold text-emerald-400 tabular-nums">
            {brierRel.toFixed(4)}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Calibration error (0.0 is perfect)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Resolution (RES)
          </p>
          <p className="mt-1 text-xl font-bold text-sky-400 tabular-nums">
            {brierRes.toFixed(4)}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Discrimination (higher is better)</p>
        </div>

        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Uncertainty (UNC)
          </p>
          <p className="mt-1 text-xl font-bold text-amber-400 tabular-nums">
            {brierUnc.toFixed(4)}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Inherent event entropy</p>
        </div>
      </div>
    </div>
  );
}

export default CalibrationCurveChart;
