"use client";

import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { PredictionMatrix } from "@/components/brand/prediction-matrix";
import { Tooltip } from "@/components/ui/ResponsibleGamblingTooltip";

type ModelRecord = {
  feature_schema_version?: unknown;
  feature_count?: unknown;
  served_head?: unknown;
};

type ModelStatus = {
  active_version?: unknown;
  generation?: unknown;
  generation_hash?: unknown;
  certification_state?: unknown;
  promotion_state?: unknown;
  validation_status?: unknown;
  models?: Record<string, ModelRecord>;
};

function unique(values: unknown[]): string {
  const normalized = [...new Set(values.filter((value) => value != null).map(String))];
  return normalized.length === 1 ? normalized[0] : normalized.length > 1 ? "Mixed" : "Unknown";
}

async function fetchModelStatus(): Promise<ModelStatus> {
  const response = await fetch("/api/models/status", { cache: "no-store" });
  if (!response.ok) throw new Error("Model status unavailable");
  return response.json() as Promise<ModelStatus>;
}

export function ModelMetadataPanel() {
  const { data, isError, isPending } = useQuery({
    queryKey: ["model-status"],
    queryFn: fetchModelStatus,
    staleTime: 60_000,
  });
  const models = Object.values(data?.models ?? {});
  const stats: { label: string; value: string; hint?: string }[] = [
    {
      label: "Active model",
      value: data?.active_version ? String(data.active_version) : "Unknown",
      hint: "The model artifact currently serving live predictions.",
    },
    { label: "Generation", value: data?.generation ? String(data.generation) : "Unknown" },
    {
      label: "Generation hash",
      value: data?.generation_hash ? String(data.generation_hash).slice(0, 16) : "Unknown",
    },
    { label: "Feature schema", value: unique(models.map((model) => model.feature_schema_version ?? model.feature_count)) },
    { label: "Served head", value: unique(models.map((model) => model.served_head)) },
    {
      label: "Certification",
      value: data?.certification_state ? String(data.certification_state) : "Pending",
      hint: "Whether this model has been validated for public staking. Unverified models are research output only — no stakes are permitted until certification passes.",
    },
    {
      label: "Promotion",
      value: data?.promotion_state ? String(data.promotion_state) : "Unknown",
      hint: "ACTIVE_FAIL_CLOSED means the model serves predictions but blocks staking until it is certified.",
    },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2" aria-live="polite">
      {stats.map((stat) => {
        // Loading has no resolved value yet — rendering "Unknown" here would be
        // indistinguishable from a genuinely absent field once data arrives.
        const displayValue = isPending ? "Loading…" : isError ? "Unavailable" : stat.value;
        return (
          <div
            key={stat.label}
            className="relative min-h-24 overflow-hidden rounded-2xl border border-white/5 bg-slate-900/70 p-4"
            role="group"
            aria-label={stat.hint ? `${stat.label}: ${displayValue} — ${stat.hint}` : `${stat.label}: ${displayValue}`}
          >
            <PredictionMatrix className="absolute right-3 top-3 opacity-55" activeCell={8} />
            <div className="flex items-center gap-1 pr-10">
              <p className="text-[11px] uppercase tracking-widest text-slate-300">{stat.label}</p>
              {stat.hint && (
                <Tooltip content={stat.hint}>
                  <Info className="h-3 w-3 text-slate-400 hover:text-slate-200" aria-hidden="true" />
                </Tooltip>
              )}
            </div>
            {isPending ? (
              <span
                className="mt-2 block h-5 w-24 animate-pulse rounded bg-slate-700/50"
                aria-hidden="true"
              />
            ) : (
              <p className="mt-1 break-words text-lg font-bold text-white">{displayValue}</p>
            )}
            {stat.hint && !isPending && (
              <p className="mt-2 pr-2 text-xs leading-5 text-slate-400">{stat.hint}</p>
            )}
          </div>
        );
      })}
    </div>
  );
}
