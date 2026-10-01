"use client";

import { memo } from "react";
import { Info } from "lucide-react";
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
  if (["CERTIFIED", "COMPLETE", "ADMITTED"].includes(state)) {
    return "text-emerald-300 bg-emerald-950/40 border-emerald-500/30";
  }
  if (["PROVISIONAL", "ADVISORY_GAPS"].includes(state)) {
    return "text-amber-300 bg-amber-950/40 border-amber-500/30";
  }
  return "text-slate-300 bg-slate-900/60 border-slate-700/50";
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
  const evidenceState = conflicts > 0
    ? "CONFLICTED"
    : critical > 0
      ? "CRITICAL_GAPS"
      : advisory > 0
        ? "ADVISORY_GAPS"
        : "COMPLETE";
  const candidateStatus = data.feature_integration?.status ?? "WITHHELD";

  return (
    <section aria-label="Model, certification, evidence, and market" className={cn("grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4", className)}>
      <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
        <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Model</h2>
        <p className="mt-2 truncate font-mono text-sm text-slate-100" title={modelLabel}>
          {modelLabel}
        </p>
        <p className="mt-1 text-xs text-slate-400">
          {data.ensemble.prediction ?? "Forecast unavailable"}
          {data.probabilities_available ? ` · ${(data.ensemble.top_outcome_probability * 100).toFixed(1)}%` : ""}
        </p>
        <p className="mt-2 text-[10px] text-slate-500">Candidate-M feature integration: {candidateStatus.toLowerCase()}.</p>
      </article>

      <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Certification</h2>
          <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", badgeClass(certification))}>
            {certification.replaceAll("_", " ")}
          </span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-slate-300">
          This state describes the serving model. Gate 7 and live C6 results are reported separately when available.
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
        {data.feature_integration?.reason && (
          <p className="mt-2 line-clamp-2 text-[10px] text-slate-500" title={data.feature_integration.reason}>
            Candidate evidence: {data.feature_integration.reason}
          </p>
        )}
      </article>

      <article className="rounded-xl border border-slate-800/80 bg-slate-900/50 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-[11px] font-mono uppercase tracking-wider text-slate-400">Market</h2>
          <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold", badgeClass(data.market ? "VERIFIED" : "UNVERIFIED"))}>
            {data.market ? "AVAILABLE" : "UNAVAILABLE"}
          </span>
        </div>
        {data.market ? (
          <dl className="mt-2 space-y-1 text-xs text-slate-300">
            <div className="flex justify-between gap-2"><dt>Bookmaker</dt><dd className="truncate">{data.market.bookmaker ?? "Unreported"}</dd></div>
            <div className="flex justify-between"><dt>Overround</dt><dd>{data.market.overround.toFixed(3)}</dd></div>
            <div className="flex justify-between"><dt>Snapshot</dt><dd>{data.market.captured_at ? `${formatLagosTimestamp(data.market.captured_at)} WAT` : "Unreported"}</dd></div>
          </dl>
        ) : (
          <p className="mt-2 text-xs text-slate-400">No verified market snapshot is available for this fixture.</p>
        )}
        <p className="mt-2 text-[10px] text-slate-500">Market display uses backend-provided values.</p>
      </article>
    </section>
  );
});
