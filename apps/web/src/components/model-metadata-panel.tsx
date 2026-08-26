"use client";

import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { PredictionMatrix } from "@/components/brand/prediction-matrix";
import { Tooltip } from "@/components/ui/ResponsibleGamblingTooltip";
import { certificationLabel, generationLabel, promotionLabel } from "@/lib/model-identity";
import { fetchModelStatus, MODEL_STATUS_QUERY_KEY } from "@/lib/model-status";

/**
 * Consumer surface (homepage hero rail). Per APEX §11 this panel carries
 * *meaning*, never engineering provenance: `active_version`, `generation`,
 * `generation_hash`, `feature_schema_version` and `served_head` are internal
 * identifiers and live on `/admin/model-health` instead. Every value below is
 * routed through `lib/model-identity.ts`, which fails closed on an unknown
 * backend enum rather than echoing it.
 */
export function ModelMetadataPanel() {
  const { data, isError, isPending } = useQuery({
    queryKey: MODEL_STATUS_QUERY_KEY,
    queryFn: fetchModelStatus,
    staleTime: 60_000,
  });
  // Both numbers come from the manifest the backend actually served — never a
  // hardcoded league count, which would overstate coverage the moment the
  // active generation's league set changes.
  const declaredLeagues = Object.values(data?.models ?? {});
  const loadedLeagues = declaredLeagues.filter((model) => model.loaded).length;
  const stats: { label: string; value: string; hint?: string }[] = [
    {
      label: "Model generation",
      value: generationLabel(data?.active_version),
      hint: "The forecasting generation currently serving this workspace.",
    },
    {
      label: "Validation",
      value: certificationLabel(data?.certification_state),
      hint: "Research mode means forecasts are analytical output only — no stake is recommended until validation passes.",
    },
    {
      label: "Availability",
      value: promotionLabel(data?.promotion_state),
    },
    {
      label: "Leagues covered",
      value: declaredLeagues.length > 0 ? `${loadedLeagues} of ${declaredLeagues.length}` : "Unknown",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-live="polite">
      {stats.map((stat) => {
        // Loading has no resolved value yet — rendering "Unknown" here would be
        // indistinguishable from a genuinely absent field once data arrives.
        const displayValue = isPending ? "Loading…" : isError ? "Unavailable" : stat.value;
        return (
          <div
            key={stat.label}
            className="relative min-h-[56px] overflow-hidden rounded-xl border border-white/5 bg-slate-900/70 p-2.5"
            role="group"
            aria-label={stat.hint ? `${stat.label}: ${displayValue} — ${stat.hint}` : `${stat.label}: ${displayValue}`}
          >
            <PredictionMatrix className="absolute right-2 top-2 opacity-55" activeCell={8} />
            <div className="flex items-center gap-1 pr-7">
              <p className="text-[10px] uppercase tracking-wider text-slate-300">{stat.label}</p>
              {stat.hint && (
                <Tooltip content={stat.hint}>
                  <Info className="h-3 w-3 text-slate-400 hover:text-slate-200" aria-hidden="true" />
                </Tooltip>
              )}
            </div>
            {isPending ? (
              <span
                className="mt-1 block h-3.5 w-20 animate-pulse rounded bg-slate-700/50"
                aria-hidden="true"
              />
            ) : (
              <p className="mt-0.5 break-words text-sm font-bold text-white sm:text-base">{displayValue}</p>
            )}
            {stat.hint && !isPending && (
              <p className="mt-0.5 pr-2 text-[10px] leading-3.5 text-slate-400">{stat.hint}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
