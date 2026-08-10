"use client";

import { useQuery } from "@tanstack/react-query";

type ModelRecord = {
  feature_schema_version?: unknown;
  feature_count?: unknown;
  served_head?: unknown;
};

type ModelStatus = {
  active_version?: unknown;
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
  const { data, isError } = useQuery({
    queryKey: ["model-status"],
    queryFn: fetchModelStatus,
    staleTime: 60_000,
  });
  const models = Object.values(data?.models ?? {});
  const stats = [
    { label: "Active model", value: data?.active_version ? String(data.active_version) : "Unknown" },
    { label: "Feature schema", value: unique(models.map((model) => model.feature_schema_version ?? model.feature_count)) },
    { label: "Served head", value: unique(models.map((model) => model.served_head)) },
    { label: "Validation", value: data?.validation_status ? String(data.validation_status) : "Pending" },
  ];

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2" aria-live="polite">
      {stats.map((stat) => (
        <div key={stat.label} className="min-h-24 rounded-2xl border border-white/5 bg-slate-900/70 p-4">
          <p className="text-[11px] uppercase tracking-widest text-slate-500">{stat.label}</p>
          <p className="mt-1 break-words text-lg font-bold text-white">{isError ? "Unavailable" : stat.value}</p>
        </div>
      ))}
    </div>
  );
}
