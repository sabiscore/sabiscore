"use client";

import { useEffect, useRef } from "react";
import { X, ShieldAlert, AlertTriangle, Layers } from "lucide-react";
import { formatLagosTimestamp } from "@/lib/lagos-time";
import { cn } from "@/lib/utils";

export interface EvidenceSourceRecord {
  provider: string;
  sourceRecordId: string;
  timestamp: string | number | Date;
  freshness: "Fresh" | "Recent" | "Stale" | "Unknown";
  reconciliationState: "Reconciled" | "Conflicted" | "Quarantined" | "Unreconciled";
  fieldAffected: string;
  agreementStatus: "Agreed" | "Disputed" | "Single-Source";
  notes?: string;
}

export interface EvidenceDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  matchTitle: string;
  sources: EvidenceSourceRecord[];
  criticalGaps?: string[];
  advisoryGaps?: string[];
  marketProvenance?: {
    bookmaker: string;
    market: string;
    capturedAt: string;
    status: string;
  } | null;
}

export function EvidenceDrawer({
  isOpen,
  onClose,
  matchTitle,
  sources,
  criticalGaps = [],
  advisoryGaps = [],
  marketProvenance,
}: EvidenceDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  // Keyboard accessibility: ESC closes modal
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    }
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      closeButtonRef.current?.focus();
    }
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="evidence-drawer-title"
      className="fixed inset-0 z-50 flex items-center justify-end bg-black/60 backdrop-blur-sm transition-opacity"
    >
      <div
        className="relative h-full w-full max-w-xl overflow-y-auto border-l border-slate-800 bg-slate-950 p-6 text-slate-200 shadow-2xl transition-transform"
        tabIndex={-1}
      >
        {/* Header */}
        <div className="flex items-start justify-between border-b border-slate-800 pb-4">
          <div>
            <span className="text-[11px] font-mono uppercase tracking-wider text-cyan-400">
              Evidence Provenance & Audit
            </span>
            <h2 id="evidence-drawer-title" className="text-lg font-bold text-white">
              Source Data Inspection
            </h2>
            <p className="mt-0.5 text-xs text-slate-400">{matchTitle}</p>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close evidence inspection drawer"
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-900 hover:text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {/* Market Snapshot Provenance */}
        {marketProvenance && (
          <div className="mt-5 rounded-lg border border-slate-800 bg-slate-900/60 p-3.5">
            <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
              <Layers className="h-4 w-4 text-cyan-400" />
              <span>Verified Market Snapshot Provenance</span>
            </div>
            <div className="mt-2.5 grid grid-cols-2 gap-2 text-xs font-mono text-slate-400">
              <div>
                Bookmaker: <span className="text-slate-200">{marketProvenance.bookmaker}</span>
              </div>
              <div>
                Market: <span className="text-slate-200">{marketProvenance.market}</span>
              </div>
              <div className="col-span-2">
                Captured: <span className="text-slate-200">{formatLagosTimestamp(marketProvenance.capturedAt)} WAT</span>
              </div>
            </div>
          </div>
        )}

        {/* Data Gaps Budget Section */}
        {(criticalGaps.length > 0 || advisoryGaps.length > 0) && (
          <div className="mt-5 space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Data Gap Budget
            </h3>
            {criticalGaps.length > 0 && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-950/20 p-3 text-xs text-rose-300">
                <div className="flex items-center gap-1.5 font-semibold text-rose-400">
                  <ShieldAlert className="h-4 w-4" />
                  <span>Critical Gaps (Forced Non-Executable State)</span>
                </div>
                <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-slate-300">
                  {criticalGaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
            {advisoryGaps.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-3 text-xs text-amber-300">
                <div className="flex items-center gap-1.5 font-semibold text-amber-400">
                  <AlertTriangle className="h-4 w-4" />
                  <span>Advisory Gaps (Confidence-Adjusted, Non-Blocking)</span>
                </div>
                <ul className="mt-1.5 list-inside list-disc space-y-0.5 text-slate-300">
                  {advisoryGaps.map((gap) => (
                    <li key={gap}>{gap}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Source Records Audit Table */}
        <div className="mt-6">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
            Observed Source Records ({sources.length})
          </h3>
          <div className="mt-2.5 divide-y divide-slate-800/80 rounded-lg border border-slate-800 bg-slate-900/30">
            {sources.length === 0 ? (
              <div className="p-4 text-center text-xs text-slate-500">
                No external provider observations recorded.
              </div>
            ) : (
              sources.map((src, i) => (
                <div key={i} className="p-3 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-200">{src.provider}</span>
                    <span
                      className={cn(
                        "rounded px-1.5 py-0.5 text-[10px] font-mono uppercase",
                        src.reconciliationState === "Reconciled"
                          ? "bg-emerald-950/60 text-emerald-400 border border-emerald-500/30"
                          : "bg-rose-950/60 text-rose-400 border border-rose-500/30"
                      )}
                    >
                      {src.reconciliationState}
                    </span>
                  </div>
                  <div className="mt-1 text-slate-400">
                    Target Field: <span className="font-mono text-slate-300">{src.fieldAffected}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
                    <span>Record ID: {src.sourceRecordId}</span>
                    <span>{formatLagosTimestamp(src.timestamp)} WAT</span>
                  </div>
                  {src.notes && (
                    <div className="mt-1.5 rounded bg-slate-950/60 p-1.5 text-[11px] text-slate-400">
                      {src.notes}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Footer Note */}
        <div className="mt-8 rounded border border-slate-800 bg-slate-900/40 p-3 text-[11px] text-slate-500">
          SabiScore fail-closed evidence contract: zero synthesis, no median imputation, and immutable source hashes.
        </div>
      </div>
    </div>
  );
}
