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
    <div className="flex min-h-9 items-center gap-1.5 rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1">
      <Icon className={isReady ? "h-3.5 w-3.5 text-emerald-300" : "h-3.5 w-3.5 text-amber-300"} aria-hidden="true" />
      <span>
        <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-300">{label}</span>
        <span className="block text-[11px] text-slate-300">{value}</span>
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
        Shows live-validated vs configured count. "Live-validated" means the
        provider returned a successful response during the last explicit probe
        (PROVIDER_LIVE_TESTS=true). Production keeps probes off by default to
        preserve quota, so this may read 0 even when providers are working.
      */}
      <HealthPill
        icon={Activity}
        label="Providers"
        value={health ? `${health.configured} configured · ${health.live} live-validated` : "Checking"}
        status={health?.providerActivation.label ?? "Unavailable"}
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
