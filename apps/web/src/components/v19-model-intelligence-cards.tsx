"use client";

import { bookmakerLabel } from "@/lib/bookmaker";
import { memo } from "react";
import { Info, Clock } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  formatLagosTimestamp,
  type FullMatchAnalysisResponse,
} from "@/lib/full-analysis-contract";
import { generationLabel } from "@/lib/model-identity";

interface ModelIntelligenceCardsProps {
  data: FullMatchAnalysisResponse;
  className?: string;
}

const badgeClass = (state: string) => {
  if (["CERTIFIED", "COMPLETE", "ADMITTED", "VERIFIED"].includes(state)) {
    return "text-emerald-300 bg-emerald-950/40 border-emerald-500/30";
  }
  if (["PROVISIONAL", "ADVISORY_GAPS", "STALE", "EXCESSIVE_MARGIN"].includes(state)) {
    return "text-amber-300 bg-amber-950/40 border-amber-500/30";
  }
  return "text-slate-300 bg-slate-900/60 border-slate-700/50";
};

const CERTIFICATION_EXPLANATIONS: Record<string, string> = {
  CERTIFIED: "Passed all 8 promotion gates and frozen C6 live market benchmark.",
  PROVISIONAL: "Candidate holdout validated; awaiting live C6 milestone (N ≥ 200).",
  WITHHELD: "Forecast or staking is withheld due to critical evidence gaps or unverified model status.",
  UNVERIFIED: "Model generation has not completed empirical validation against the closing market.",
};

export const ModelIntelligenceCards = memo(function ModelIntelligenceCards({
  data,
  className,
}: ModelIntelligenceCardsProps) {
  const modelLabel = generationLabel(
    data.ensemble.generation ?? data.ensemble.model_version ?? "Unidentified",
  );
  const certification = data.ensemble.certification_state || "UNVERIFIED";
  const critical = data.evidence_quality.critical_gap_count;
  const advisory = data.evidence_quality.advisory_gap_count;
  const conflicts = data.evidence_quality.conflict_count;
  const isStale =
    data.evidence_quality.critical_gaps.includes("STALE_REQUIRED_EVIDENCE") ||
    data.evidence_quality.advisory_gaps.includes("STALE_ENRICHMENT_EVIDENCE");
  const evidenceState = conflicts > 0
    ? "CONFLICTED"
    : isStale
      ? "STALE"
      : critical > 0
        ? "CRITICAL_GAPS"
        : advisory > 0
          ? "ADVISORY_GAPS"
          : "COMPLETE";

  const market = data.market;
  const isOverroundExcessive = market != null && market.overround > 1.15;
  const marketState = !market
    // No snapshot is an absence of evidence, not a liquidity measurement.
    ? (data.odds_edge ? "UNVERIFIED" : "UNAVAILABLE")
    : isOverroundExcessive
      ? "EXCESSIVE_MARGIN"
      : "VERIFIED";

  const certExplanation =
    CERTIFICATION_EXPLANATIONS[certification] ?? CERTIFICATION_EXPLANATIONS.UNVERIFIED;

  return (
    <div className={cn("space-y-3", className)}>
      {/* Live Status Ribbon (Phase 14.A) */}
      <div
        role="region"
        aria-label="Live status ribbon"
        className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800/80 bg-slate-950/60 px-3 py-1.5 text-[11px] font-mono text-slate-300"
      >
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className={data.prediction_status === "AVAILABLE" ? "text-emerald-400" : "text-amber-400"}>●</span>
            <span className="text-slate-400">Prediction:</span>
            <span className="font-semibold text-slate-200">
              {data.prediction_status === "AVAILABLE" ? "Captured" : "Not captured"}
            </span>
          </div>
          <span className="text-slate-700 hidden sm:inline" aria-hidden="true">|</span>
          <div className="flex items-center gap-1.5">
            <span className={critical === 0 ? "text-emerald-400" : "text-amber-400"}>●</span>
            <span className="text-slate-400">Evidence:</span>
            <span className="font-semibold text-slate-200">
              {critical === 0 ? "Captured" : "Incomplete"}
            </span>
          </div>
          <span className="text-slate-700 hidden sm:inline" aria-hidden="true">|</span>
          <div className="flex items-center gap-1.5">
            <span className={market ? "text-emerald-400" : "text-slate-500"}>●</span>
            <span className="text-slate-400">Market snapshot:</span>
            <span className="font-semibold text-slate-200">
              {market ? "Verified" : "Unverified"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-slate-400">
          <Clock className="h-3 w-3" aria-hidden="true" />
          <span>Last updated:</span>
          <time className="text-slate-200" dateTime={data.generated_at}>
            {formatLagosTimestamp(data.generated_at)} WAT
          </time>
        </div>
      </div>

      {/* Model, Certification, Evidence, and Market Cards */}
      <section aria-label="Model, certification, evidence, and market" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
          <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Model</h2>
          <p className="mt-2 truncate font-mono text-sm text-slate-100" title={modelLabel}>
            {modelLabel}
          </p>
          <p className="mt-1 text-xs text-slate-400">
            {data.ensemble.prediction ?? "Forecast unavailable"}
            {data.probabilities_available ? ` · ${(data.ensemble.top_outcome_probability * 100).toFixed(1)}%` : ""}
          </p>
        </article>

        <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Certification</h2>
            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", badgeClass(certification))}>
              {certification.replaceAll("_", " ")}
            </span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-slate-300">
            {certExplanation}
          </p>
          <div className="mt-3 flex items-center gap-1.5 border-t border-slate-800/60 pt-2 text-[10px] text-slate-400">
            <Info className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span>Certification does not imply certainty about this fixture.</span>
          </div>
        </article>

        <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Evidence</h2>
            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", badgeClass(evidenceState))}>
              {evidenceState.replaceAll("_", " ")}
            </span>
          </div>
          <dl className="mt-2 space-y-1 text-xs text-slate-300">
            <div className="flex justify-between"><dt>Critical gaps</dt><dd>{critical}</dd></div>
            <div className="flex justify-between"><dt>Advisory gaps</dt><dd>{advisory}</dd></div>
            <div className="flex justify-between"><dt>Conflicts</dt><dd>{conflicts}</dd></div>
          </dl>
        </article>

        <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Market</h2>
            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", badgeClass(marketState))}>
              {marketState.replaceAll("_", " ")}
            </span>
          </div>
          {market ? (
            <dl className="mt-2 space-y-1 text-xs text-slate-300">
              <div className="flex justify-between gap-2"><dt>Bookmaker</dt><dd className="truncate">{market.bookmaker ? bookmakerLabel(market.bookmaker) : "Unreported"}</dd></div>
              <div className="flex justify-between"><dt>Overround</dt><dd>{market.overround.toFixed(3)}</dd></div>
              <div className="flex justify-between"><dt>Snapshot</dt><dd>{market.captured_at ? `${formatLagosTimestamp(market.captured_at)} WAT` : "Unreported"}</dd></div>
            </dl>
          ) : (
            <p className="mt-2 text-xs text-slate-400">No verified market snapshot is available for this fixture.</p>
          )}
          <p className="mt-2 text-[10px] text-slate-500">Market display uses backend-provided values.</p>
        </article>
      </section>
    </div>
  );
});
