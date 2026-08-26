"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle, XCircle, AlertCircle, Loader2, RefreshCw, Database, Cpu, HardDrive } from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchModelStatus, MODEL_STATUS_QUERY_KEY, type ModelStatus } from "@/lib/model-status";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ReadinessCheck {
  status: string;
  message?: string;
  trained?: boolean;
  load_in_progress?: boolean;
  artifacts_found?: number;
}

interface ReadinessPayload {
  status: string;
  checks: {
    database?: ReadinessCheck;
    cache?: ReadinessCheck;
    models?: ReadinessCheck;
  };
  models: boolean;
  model_error?: string | null;
  timestamp: string;
}

interface SmokePayload {
  db_connected: boolean;
  models_loaded: boolean;
  version: string;
  timestamp: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function StatusIcon({ status }: { status: string }) {
  if (status === "ready" || status === "healthy")
    return <CheckCircle className="h-4 w-4 text-emerald-400" aria-hidden="true" />;
  if (status === "degraded")
    return <AlertCircle className="h-4 w-4 text-amber-400" aria-hidden="true" />;
  if (status === "not_ready" || status === "unhealthy" || status === "error")
    return <XCircle className="h-4 w-4 text-rose-400" aria-hidden="true" />;
  return <Loader2 className="h-4 w-4 animate-spin text-slate-400" aria-hidden="true" />;
}

/**
 * Raw manifest provenance. Admin-only by APEX §11 — do not lift these onto a
 * consumer surface; use `lib/model-identity.ts` there.
 */
const PROVENANCE_FIELDS: { label: string; value: (s?: ModelStatus) => string | null }[] = [
  { label: "Active version", value: (s) => str(s?.active_version) },
  { label: "Generation", value: (s) => str(s?.generation) },
  { label: "Generation hash", value: (s) => str(s?.generation_hash) },
  { label: "Certification state", value: (s) => str(s?.certification_state) },
  { label: "Promotion state", value: (s) => str(s?.promotion_state) },
  {
    label: "Feature schema",
    value: (s) => uniqueOf(Object.values(s?.models ?? {}).map((m) => m.feature_schema_version)),
  },
  {
    label: "Served head",
    value: (s) => uniqueOf(Object.values(s?.models ?? {}).map((m) => m.served_head)),
  },
];

function str(value: unknown): string | null {
  return value == null ? null : String(value);
}

function uniqueOf(values: unknown[]): string | null {
  const seen = [...new Set(values.filter((v) => v != null).map(String))];
  if (seen.length === 0) return null;
  return seen.length === 1 ? seen[0] : `Mixed (${seen.join(", ")})`;
}

function statusColor(status: string): string {
  if (status === "ready" || status === "healthy") return "text-emerald-400";
  if (status === "degraded") return "text-amber-400";
  return "text-rose-400";
}

function CheckRow({
  label,
  icon: Icon,
  check,
}: {
  label: string;
  icon: React.ElementType;
  check?: ReadinessCheck;
}) {
  if (!check) return null;
  return (
    <div className="flex items-start gap-3 rounded-xl border border-white/[0.05] bg-slate-900/60 px-4 py-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-white">{label}</p>
          <StatusIcon status={check.status} />
          <span className={cn("text-xs font-medium capitalize", statusColor(check.status))}>
            {check.status.replace("_", " ")}
          </span>
        </div>
        {check.message && (
          <p className="mt-0.5 truncate text-xs text-slate-500">{check.message}</p>
        )}
        {check.artifacts_found !== undefined && (
          <p className="mt-0.5 text-[11px] text-slate-600">
            {check.artifacts_found} artifact{check.artifacts_found !== 1 ? "s" : ""} found
          </p>
        )}
        {check.load_in_progress && (
          <p className="mt-0.5 flex items-center gap-1 text-[11px] text-sky-400">
            <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
            Loading in progress…
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ModelHealthClient() {
  const {
    data: readiness,
    isLoading: rLoading,
    isError: rError,
    refetch: refetchReadiness,
    dataUpdatedAt: rUpdatedAt,
  } = useQuery<ReadinessPayload>({
    queryKey: ["admin-readiness"],
    queryFn: async () => {
      const res = await fetch("/api/health/ready", { cache: "no-store" });
      return res.json();
    },
    refetchInterval: 30_000,
    staleTime: 0,
  });

  const { data: smoke, isLoading: sLoading } = useQuery<SmokePayload>({
    queryKey: ["admin-smoke"],
    queryFn: async () => {
      const res = await fetch("/api/health/smoke", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    },
    refetchInterval: 60_000,
    staleTime: 0,
  });

  const {
    data: modelStatus,
    isLoading: mLoading,
    isError: mError,
  } = useQuery({
    queryKey: MODEL_STATUS_QUERY_KEY,
    queryFn: fetchModelStatus,
    staleTime: 60_000,
  });

  const overallReady = readiness?.status === "ready";
  const lastUpdated = rUpdatedAt
    ? new Date(rUpdatedAt).toLocaleTimeString()
    : "—";

  return (
    <div className="space-y-5">
      {/* Top status banner */}
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "flex items-center justify-between rounded-2xl border px-5 py-4",
          overallReady
            ? "border-emerald-500/30 bg-emerald-500/10"
            : "border-rose-500/30 bg-rose-500/10",
        )}
      >
        <div className="flex items-center gap-3">
          {rLoading ? (
            <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-hidden="true" />
          ) : overallReady ? (
            <CheckCircle className="h-5 w-5 text-emerald-400" aria-hidden="true" />
          ) : (
            <XCircle className="h-5 w-5 text-rose-400" aria-hidden="true" />
          )}
          <div>
            <p className={cn("text-sm font-bold", overallReady ? "text-emerald-300" : "text-rose-300")}>
              {rLoading ? "Checking…" : overallReady ? "System Ready" : "Not Ready"}
            </p>
            <p className="text-xs text-slate-500">Last checked: {lastUpdated}</p>
          </div>
        </div>

        <button
          onClick={() => { void refetchReadiness(); }}
          data-testid="refresh-health"
          aria-label="Refresh health check"
          className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-white/20 hover:text-white"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          Refresh
        </button>
      </div>

      {/* Per-component checks */}
      {rError ? (
        <div className="flex items-center gap-2 text-rose-400" role="alert">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <span className="text-sm">Could not fetch readiness data from backend</span>
        </div>
      ) : (
        <div className="space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Component Checks
          </h2>
          <CheckRow label="Database" icon={Database} check={readiness?.checks.database} />
          <CheckRow label="Cache" icon={HardDrive} check={readiness?.checks.cache} />
          <CheckRow label="ML Models" icon={Cpu} check={readiness?.checks.models} />
        </div>
      )}

      {/* Smoke check summary */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Smoke Check
        </h2>
        <div className="grid grid-cols-3 gap-2">
          {(
            [
              { label: "DB Connected", ok: smoke?.db_connected, text: undefined as string | undefined },
              { label: "Models Loaded", ok: smoke?.models_loaded, text: undefined as string | undefined },
              { label: "Version", ok: true as boolean | undefined, text: smoke?.version ?? "—" },
            ]
          ).map(({ label, ok, text }) => (
            <div
              key={label}
              className="flex flex-col items-center gap-1 rounded-xl border border-white/[0.06] bg-slate-900/60 py-3"
            >
              {sLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-slate-500" aria-hidden="true" />
              ) : text ? (
                <span className="text-sm font-bold text-slate-200">{text}</span>
              ) : ok ? (
                <CheckCircle className="h-4 w-4 text-emerald-400" aria-hidden="true" />
              ) : (
                <XCircle className="h-4 w-4 text-rose-400" aria-hidden="true" />
              )}
              <p className="text-[10px] font-medium uppercase tracking-wider text-slate-500">
                {label}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* Model provenance — APEX §11 permits raw internal identifiers only in
          developer/admin diagnostics. This page is bearer-token guarded and
          robots-disallowed; consumer surfaces render product language via
          lib/model-identity.ts instead. */}
      <div className="space-y-2">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Model Provenance
        </h2>
        {mError ? (
          <div className="flex items-center gap-2 text-rose-400" role="alert">
            <AlertCircle className="h-4 w-4" aria-hidden="true" />
            <span className="text-sm">Could not fetch model status from backend</span>
          </div>
        ) : (
          <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {PROVENANCE_FIELDS.map(({ label, value }) => (
              <div
                key={label}
                className="rounded-xl border border-white/[0.06] bg-slate-900/60 px-4 py-2.5"
              >
                <dt className="text-[10px] uppercase tracking-wider text-slate-500">{label}</dt>
                <dd className="mt-0.5 break-all font-mono text-xs text-slate-200">
                  {mLoading ? "…" : (value(modelStatus) ?? "—")}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      {/* Model error detail */}
      {readiness?.model_error && (
        <div
          role="alert"
          className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3"
        >
          <p className="text-xs font-semibold text-rose-300">Model error</p>
          <p className="mt-1 text-xs text-rose-400">{readiness.model_error}</p>
        </div>
      )}

      {/* Raw timestamp */}
      {readiness?.timestamp && (
        <p className="text-right text-[10px] text-slate-700">
          Backend timestamp: {readiness.timestamp}
        </p>
      )}
    </div>
  );
}
