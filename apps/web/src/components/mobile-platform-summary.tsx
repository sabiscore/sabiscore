"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Database, Gauge } from "lucide-react";
import {
  derivePlatformHealth,
  fetchPlatformHealth,
  PLATFORM_HEALTH_QUERY_KEY,
} from "@/lib/health-status";

export function MobilePlatformSummary() {
  const { data } = useQuery({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  const health = data ? derivePlatformHealth(data) : null;
  const core = health?.readiness;

  return (
    <div
      className="grid grid-cols-3 gap-1.5"
      role="group"
      aria-label={
        health
          ? `Core ${core?.ready} of ${core?.total}; providers ${health.configured} configured, ${health.live} live-verified; models ${health.modelsReady ? "ready" : "unavailable"}`
          : "Checking platform status"
      }
    >
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <Gauge className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Core</span>
          <span className="block truncate text-[11px] text-slate-200">
            {core ? `${core.ready}/${core.total}` : "…"}
          </span>
        </span>
      </div>
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <Activity className="h-3.5 w-3.5 text-amber-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Providers</span>
          <span className="block truncate text-[11px] text-slate-200">
            {health ? `${health.configured} cfg · ${health.live} live` : "…"}
          </span>
        </span>
      </div>
      <div className="flex min-h-10 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2">
        <Database className="h-3.5 w-3.5 text-emerald-300" aria-hidden="true" />
        <span className="min-w-0">
          <span className="block text-[9px] uppercase tracking-wide text-slate-300">Models</span>
          <span className="block truncate text-[11px] text-slate-200">
            {health ? (health.modelsReady ? "Ready" : "Down") : "…"}
          </span>
        </span>
      </div>
    </div>
  );
}
