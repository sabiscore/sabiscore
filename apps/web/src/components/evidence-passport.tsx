"use client";

import { useQuery } from "@tanstack/react-query";
import { buildEvidencePassport, type SourceFreshnessItem } from "@/lib/evidence-passport";
import type { FullMatchAnalysisResponse } from "@/lib/full-analysis-contract";
import { cn } from "@/lib/utils";

interface SourceFreshnessResponse {
  status: string;
  sources: SourceFreshnessItem[];
}

const TONE_CHIP: Record<string, string> = {
  positive: "border-emerald-500/25 bg-emerald-500/8 text-emerald-300",
  warning: "border-amber-500/25 bg-amber-500/8 text-amber-300",
  info: "border-sky-500/25 bg-sky-500/8 text-sky-300",
  neutral: "border-slate-600/30 bg-slate-700/20 text-slate-300",
};

const TONE_TEXT: Record<string, string> = {
  positive: "text-emerald-400",
  warning: "text-amber-400",
  info: "text-sky-400",
  neutral: "text-slate-400",
};

/**
 * Evidence Passport (docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md §5) — always-
 * visible per-family provenance, freshness, and resolution status.
 *
 * Unlike EvidenceStatusCard (the "why no bet" explainer, which renders
 * nothing once staking is permitted), this renders unconditionally: a gapped
 * family is shown as gapped, a resolved one is shown as resolved — never
 * omitted, never filled.
 */
export function EvidencePassport({ data }: { data: FullMatchAnalysisResponse }) {
  const { data: freshness } = useQuery<SourceFreshnessResponse>({
    queryKey: ["sourcesFreshness"],
    queryFn: async () => {
      const res = await fetch("/api/sources/freshness", { cache: "no-store" });
      const payload = (await res.json().catch(() => null)) as SourceFreshnessResponse | null;
      if (!payload || !Array.isArray(payload.sources)) {
        return { status: "UNKNOWN", sources: [] };
      }
      return payload;
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const rows = buildEvidencePassport({
    fieldAvailability: data.field_availability,
    unavailableReasons: data.unavailable_reasons,
    advisoryGaps: data.evidence_quality.advisory_gaps,
    sources: freshness?.sources ?? [],
  });

  return (
    <div
      role="region"
      aria-label="Evidence passport — per-family provenance and status"
      className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-3.5 sm:p-4 space-y-2.5"
    >
      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
        Evidence passport
      </p>
      <ul className="space-y-2.5" aria-label="Evidence families">
        {rows.map((row) => (
          <li
            key={row.key}
            className="space-y-1 border-t border-slate-800/30 pt-2.5 first:border-t-0 first:pt-0"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-slate-200">{row.label}</span>
              <span
                className={cn(
                  "inline-flex flex-shrink-0 items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
                  TONE_CHIP[row.tone],
                )}
              >
                {row.statusLabel}
                {row.gapCount > 0 ? ` · ${row.gapCount}` : ""}
              </span>
            </div>
            {row.reason && <p className="text-xs text-slate-400">{row.reason}</p>}
            {row.provenance && (
              <p className="text-[11px] text-slate-500">
                {row.provenance.sourceName} ({row.provenance.category}){" "}
                <span className={TONE_TEXT[row.provenance.freshnessTone]}>
                  · {row.provenance.freshnessLabel}
                </span>
              </p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
