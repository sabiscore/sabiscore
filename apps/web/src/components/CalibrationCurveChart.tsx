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
  status: "OK" | "METRICS_UNAVAILABLE";
  reason?: string;
  sample_size?: number;
  meets_sample_floor?: boolean;
  minimum_sample_size?: number;
  league?: string | null;
  model_version?: string;
  generated_at?: string;
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

type CalibrationErrorKind = "service_unavailable" | "invalid_response";

class CalibrationLoadError extends Error {
  constructor(readonly kind: CalibrationErrorKind) {
    super(kind);
  }
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

function isCalibrationData(value: unknown): value is CalibrationData {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<CalibrationData>;
  if (candidate.status !== "OK" && candidate.status !== "METRICS_UNAVAILABLE") return false;
  if (
    candidate.sample_size !== undefined &&
    (!Number.isFinite(candidate.sample_size) || candidate.sample_size < 0)
  ) {
    return false;
  }
  return true;
}

async function fetchCalibrationData(league?: string, window?: number): Promise<CalibrationData> {
  const params = new URLSearchParams();
  if (league) params.set("league", league);
  if (window) params.set("window", String(window));

  let response: Response;
  try {
    response = await fetch(`/api/model-performance/calibration?${params.toString()}`, {
      cache: "no-store",
    });
  } catch {
    throw new CalibrationLoadError("service_unavailable");
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new CalibrationLoadError(response.ok ? "invalid_response" : "service_unavailable");
  }

  if (
    isCalibrationData(body) &&
    body.status === "METRICS_UNAVAILABLE" &&
    body.reason === "insufficient_settled_predictions"
  ) {
    return body;
  }
  if (!response.ok) throw new CalibrationLoadError("service_unavailable");
  if (!isCalibrationData(body)) throw new CalibrationLoadError("invalid_response");
  return body;
}

const OUTCOME_TABS: Array<{ id: "overall" | OutcomeKey; label: string }> = [
  { id: "overall", label: "Overall Ensemble" },
  { id: "home_win", label: "Home Win" },
  { id: "draw", label: "Draw" },
  { id: "away_win", label: "Away Win" },
];

export function CalibrationCurveChart({
  league,
  window,
  className,
}: {
  league?: string;
  window?: number;
  className?: string;
}) {
  const [selectedOutcome, setSelectedOutcome] = useState<"overall" | OutcomeKey>("overall");
  const prefersReducedMotion = useReducedMotion();

  const { data, isLoading, error, refetch } = useQuery<CalibrationData, CalibrationLoadError>({
    queryKey: ["calibration-curve", league, window],
    queryFn: () => fetchCalibrationData(league, window),
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, loadError) =>
      loadError.kind === "service_unavailable" && failureCount < 1,
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
  const selectedOutcomeLabel = OUTCOME_TABS.find((tab) => tab.id === selectedOutcome)?.label ?? "Selected outcome";
  const belowSampleFloor =
    data?.meets_sample_floor === false || data?.reason === "insufficient_settled_predictions";
  const generatedAt = data?.generated_at ? new Date(data.generated_at) : null;
  const hasValidGeneratedAt = generatedAt != null && !Number.isNaN(generatedAt.getTime());

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

      {data && belowSampleFloor ? (
        <div className="mt-5 flex h-72 flex-col items-center justify-center rounded-xl bg-slate-800/40 p-4 text-center">
          <Info className="h-6 w-6 text-amber-400 mb-2" />
          <p className="text-sm font-semibold text-slate-200">Not enough settled predictions yet</p>
          <p className="mt-1 text-xs text-slate-400 max-w-md">
            {data.minimum_sample_size != null
              ? `Calibration requires at least ${data.minimum_sample_size} settled predictions to compute a meaningful decomposition — currently ${data.sample_size ?? 0}.`
              : `Calibration begins after the configured settlement floor is reached — currently ${data.sample_size ?? 0} settled predictions.`}
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
          <div className="flex h-72 flex-col items-center justify-center rounded-xl bg-slate-800/40 p-4 text-center" role="alert">
            <Info className="h-6 w-6 text-amber-400 mb-2" />
            <p className="text-sm font-semibold text-slate-200">
              {error.kind === "invalid_response"
                ? "Calibration response could not be verified"
                : "Calibration service unavailable"}
            </p>
            <p className="mt-1 text-xs text-slate-400 max-w-md">
              {error.kind === "invalid_response"
                ? "The response did not match the expected calibration contract, so no metrics are shown."
                : "The performance service could not be reached. Existing calibration gates remain unchanged."}
            </p>
          </div>
        ) : bins.length === 0 ? (
          <div className="flex h-72 items-center justify-center rounded-xl bg-slate-800/40 text-sm text-slate-400">
            Awaiting settled match prediction records.
          </div>
        ) : (
          <div
            className="h-72 w-full"
            role="img"
            aria-label={`${selectedOutcomeLabel} reliability diagram with ${bins.length} observed bins`}
            aria-describedby="calibration-chart-summary"
          >
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

      {bins.length > 0 && (
        <div className="mt-4 border-t border-white/[0.08] pt-4">
          <p id="calibration-chart-summary" className="text-xs text-slate-400">
            {selectedOutcomeLabel}: {bins.length} observed probability bins
            {data?.sample_size != null ? ` from ${data.sample_size} settled predictions` : ""}. Empty bins are omitted.
          </p>
          <details className="mt-2 rounded-lg border border-white/[0.08] bg-white/[0.02]">
            <summary className="flex min-h-11 cursor-pointer items-center px-3 py-2 text-xs font-semibold text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400">
              View calibration observations
            </summary>
            <div className="overflow-x-auto border-t border-white/[0.08]">
              <table className="w-full min-w-[28rem] text-left text-xs">
                <caption className="sr-only">Calibration observations for {selectedOutcomeLabel}</caption>
                <thead className="text-slate-400">
                  <tr>
                    <th className="px-3 py-2 font-medium" scope="col">Forecasted probability</th>
                    <th className="px-3 py-2 font-medium" scope="col">Observed frequency</th>
                    <th className="px-3 py-2 font-medium" scope="col">Observations</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.05] text-slate-200">
                  {bins.map((bin) => (
                    <tr key={`${selectedOutcome}-${bin.x}-${bin.y}`}>
                      <td className="px-3 py-2 tabular-nums">{(bin.x * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2 tabular-nums">{(bin.y * 100).toFixed(1)}%</td>
                      <td className="px-3 py-2 tabular-nums">{bin.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </div>
      )}

      {data?.status === "OK" && (
        <dl className="mt-4 grid gap-2 border-t border-white/[0.08] pt-4 text-xs sm:grid-cols-4">
          <div><dt className="text-slate-500">League scope</dt><dd className="mt-0.5 text-slate-300">{data.league ?? "All leagues"}</dd></div>
          <div><dt className="text-slate-500">Record window</dt><dd className="mt-0.5 text-slate-300">{window ? `Last ${window} days` : "All settled records"}</dd></div>
          <div><dt className="text-slate-500">Model scope</dt><dd className="mt-0.5 text-slate-300">Current serving generation</dd></div>
          <div>
            <dt className="text-slate-500">Generated</dt>
            <dd className="mt-0.5 text-slate-300">
              {hasValidGeneratedAt ? <time dateTime={data.generated_at}>{generatedAt.toLocaleString()}</time> : "Unknown"}
            </dd>
          </div>
        </dl>
      )}

      {/* Murphy Brier Decomposition & ECE Metric Cards */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-5 border-t border-white/[0.08] pt-4">
        <div className="rounded-xl border border-white/[0.05] bg-white/[0.02] p-3">
          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400">
            Multiclass ECE
          </p>
          <p className="mt-1 text-xl font-bold text-emerald-400 tabular-nums">
            {eceValue !== null ? `${(eceValue * 100).toFixed(2)}%` : "—"}
          </p>
          <p className="mt-0.5 text-[10px] text-slate-500">Expected Calibration Error (lower is better)</p>
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
