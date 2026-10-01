"use client";

import { memo } from "react";
import { ShieldCheck, Database, Clock, Sparkles } from "lucide-react";
import { formatLagosTime } from "@/lib/lagos-time";
import { cn } from "@/lib/utils";

export interface EvidenceProvenanceStripProps {
  modelVersion: string;
  dataAsOf: string | number | Date;
  marketSnapshotAt?: string | number | Date | null;
  evidenceQuality: "Complete" | "Advisory" | "Critical";
  certificationState: "Certified" | "Provisional" | "Withheld";
  onOpenDrawer?: () => void;
  className?: string;
}

export const EvidenceProvenanceStrip = memo(function EvidenceProvenanceStrip({
  modelVersion,
  dataAsOf,
  marketSnapshotAt,
  evidenceQuality,
  certificationState,
  onOpenDrawer,
  className,
}: EvidenceProvenanceStripProps) {
  const formattedDataTime = dataAsOf ? `${formatLagosTime(dataAsOf)} WAT` : "N/A";
  const formattedMarketTime = marketSnapshotAt
    ? `${formatLagosTime(marketSnapshotAt)} WAT`
    : "Verified Pre-Match";

  // Certification pill styles
  const certBadge = {
    Certified: "text-emerald-400 bg-emerald-950/40 border-emerald-500/30",
    Provisional: "text-amber-400 bg-amber-950/40 border-amber-500/30",
    Withheld: "text-slate-400 bg-slate-900/60 border-slate-700/40",
  }[certificationState];

  // Evidence pill styles
  const evidenceBadge = {
    Complete: "text-emerald-400 bg-emerald-950/40 border-emerald-500/30",
    Advisory: "text-amber-400 bg-amber-950/40 border-amber-500/30",
    Critical: "text-rose-400 bg-rose-950/40 border-rose-500/30",
  }[evidenceQuality];

  return (
    <div
      role="region"
      aria-label="Evidence Provenance and Certification Summary"
      className={cn(
        "flex flex-wrap items-center justify-between gap-2.5 rounded-lg border border-slate-800 bg-slate-950/80 px-3.5 py-2 text-xs font-mono text-slate-300 shadow-sm backdrop-blur-md",
        className
      )}
    >
      <div className="flex flex-wrap items-center gap-3">
        {/* Model Generation */}
        <div className="flex items-center gap-1.5" title="Serving Model Generation">
          <Sparkles className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
          <span className="text-slate-400">Model:</span>
          <span className="font-semibold text-slate-200">{modelVersion}</span>
        </div>

        <span className="hidden text-slate-700 sm:inline" aria-hidden="true">|</span>

        {/* Data As Of */}
        <div className="flex items-center gap-1.5" title="Data cutoff time in West Africa Time">
          <Clock className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          <span className="text-slate-400">Data as of:</span>
          <time dateTime={typeof dataAsOf === "string" ? dataAsOf : undefined} className="text-slate-200">
            {formattedDataTime}
          </time>
        </div>

        <span className="hidden text-slate-700 sm:inline" aria-hidden="true">|</span>

        {/* Market Snapshot */}
        <div className="flex items-center gap-1.5" title="Bookmaker market price snapshot time">
          <Database className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
          <span className="text-slate-400">Market snapshot:</span>
          <span className="text-slate-200">{formattedMarketTime}</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Evidence Status Pill */}
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-medium tracking-tight",
            evidenceBadge
          )}
        >
          <span>Evidence:</span>
          <span className="font-semibold">{evidenceQuality}</span>
        </span>

        {/* Certification Status Pill */}
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-medium tracking-tight",
            certBadge
          )}
        >
          <ShieldCheck className="h-3 w-3" aria-hidden="true" />
          <span className="font-semibold">{certificationState}</span>
        </span>

        {onOpenDrawer && (
          <button
            type="button"
            onClick={onOpenDrawer}
            className="ml-1 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[11px] font-sans font-medium text-slate-300 hover:border-slate-600 hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-1 focus:ring-cyan-500"
          >
            Inspect Sources
          </button>
        )}
      </div>
    </div>
  );
});
