"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, Database, type LucideIcon } from "lucide-react";
import {
  derivePlatformHealth,
  fetchPlatformHealth,
  PLATFORM_HEALTH_QUERY_KEY,
} from "@/lib/health-status";

function HealthPill({
  icon: Icon,
  label,
  value,
  status,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  status: "Ready" | "Partial" | "Unavailable";
}) {
  const isReady = status === "Ready";

  return (
    <div className="flex min-h-11 items-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2">
      <Icon className={isReady ? "h-4 w-4 text-emerald-300" : "h-4 w-4 text-amber-300"} aria-hidden="true" />
      <span>
        <span className="block text-[11px] font-semibold uppercase tracking-wide text-slate-300">{label}</span>
        <span className="block text-xs text-slate-300">{value}</span>
      </span>
    </div>
  );
}

export function PlatformHealthPills() {
  const { data } = useQuery({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
  const health = data ? derivePlatformHealth(data) : null;
  const checks = data?.backendChecks ?? {};
  const databaseReady = Boolean(
    checks.database && typeof checks.database === "object" &&
      ["ok", "ready", "healthy"].includes(
        String((checks.database as { status?: unknown }).status).toLowerCase(),
      )
  );

  return (
    <>
      <HealthPill
        icon={Database}
        label="Postgres"
        value={health ? (databaseReady ? "Ready" : "Unavailable") : "Checking"}
        status={databaseReady ? "Ready" : "Unavailable"}
      />
      {/*
        Live validation is intentionally separate: production keeps provider
        probes off by default to preserve quota. This state instead shows
        whether every configured provider is actually enabled.
      */}
      <HealthPill
        icon={Activity}
        label="Providers"
        value={health ? `${health.configured} configured · ${health.live} live-verified` : "Checking"}
        status={health && health.live === health.configured && health.configured > 0 ? "Ready" : health?.configured ? "Partial" : "Unavailable"}
      />
      <HealthPill
        icon={BarChart3}
        label="Models"
        value={health ? (health.modelsReady ? "Ready" : "Unavailable") : "Checking"}
        status={health?.modelsReady ? "Ready" : "Unavailable"}
      />
    </>
  );
}
