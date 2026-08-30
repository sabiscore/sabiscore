"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, BadgeCheck, Database } from "lucide-react";
import {
  derivePlatformHealth,
  fetchPlatformHealth,
  PLATFORM_HEALTH_QUERY_KEY,
} from "@/lib/health-status";
import {
  displayCertification,
  displayModelVersion,
  fetchModelStatus,
  MODEL_STATUS_QUERY_KEY,
} from "@/lib/model-status";

export function MobilePlatformSummary() {
  const { data: healthData } = useQuery({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  const { data: modelData, isError: modelError } = useQuery({
    queryKey: MODEL_STATUS_QUERY_KEY,
    queryFn: fetchModelStatus,
    staleTime: 60_000,
  });

  const health = healthData ? derivePlatformHealth(healthData) : null;
  const modelVersion = modelError ? "Unavailable" : modelData ? displayModelVersion(modelData) : "…";
  const certification = modelError ? "Unavailable" : modelData ? displayCertification(modelData) : "…";
  const providerLabel = health ? `${health.configured} cfg · ${health.live} verified` : "…";

  return (
    <div
      className="grid grid-cols-3 gap-1.5"
      role="group"
      aria-label={
        health || modelData
          ? `Model ${modelVersion}; certification ${certification}; providers ${health?.configured ?? 0} configured; live-validated ${health?.live ?? 0}`
          : "Checking platform and model status"
      }
    >
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <Database className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Model</span>
          <span className="block truncate text-[11px] text-slate-200" title={modelVersion}>
            {modelVersion}
          </span>
        </span>
      </div>
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <BadgeCheck className="h-3.5 w-3.5 text-amber-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Certification</span>
          <span className="block truncate text-[11px] text-slate-200" title={certification}>
            {certification}
          </span>
        </span>
      </div>
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <Activity className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Providers</span>
          <span className="block truncate text-[11px] text-slate-200">
            {providerLabel}
          </span>
        </span>
      </div>
    </div>
  );
}
