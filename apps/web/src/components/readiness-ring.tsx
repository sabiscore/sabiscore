"use client";

import { memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  deriveBackendReadiness,
  fetchPlatformHealth,
  PLATFORM_HEALTH_QUERY_KEY,
  type CapabilityStatus,
} from "@/lib/health-status";

// Component liveness (DB/migrations/cache/models ready) never proves the system can
// actually produce a prediction — this line reports that separately (INV-20), and
// must never conflate "nothing to test yet" (off-season, just-deployed) with "broken".
const CAPABILITY_COPY: Record<CapabilityStatus, { text: string; className: string }> = {
  verified: { text: "Runtime capability check passed", className: "text-emerald-400" },
  unverified_no_fixtures: { text: "No fixtures to verify yet", className: "text-slate-300" },
  // Pipeline ran and fail-closed correctly — a fixture days out has no odds or
  // lineups published yet. Amber (partial), never rose: this is not an outage.
  unverified_insufficient_evidence: {
    text: "Awaiting pre-match evidence",
    className: "text-amber-400",
  },
  failed: { text: "Prediction pipeline not verified", className: "text-rose-400" },
  unknown: { text: "No fixtures to verify yet", className: "text-slate-300" },
};

// ─── Data fetching ────────────────────────────────────────────────────────────

// ─── SVG Ring ─────────────────────────────────────────────────────────────────

const RING_R = 28;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R;

function ringColor(score: number): string {
  if (score >= 0.7) return "stroke-emerald-400";
  if (score >= 0.4) return "stroke-amber-400";
  return "stroke-rose-500";
}

function ringTrackColor(score: number): string {
  if (score >= 0.7) return "stroke-emerald-900/40";
  if (score >= 0.4) return "stroke-amber-900/40";
  return "stroke-rose-900/40";
}

function ReadinessRingInner({ score, label }: { score: number; label: string }) {
  const filled = Math.max(0, Math.min(1, score));
  const dash = filled * RING_CIRCUMFERENCE;
  const gap = RING_CIRCUMFERENCE - dash;
  const color = ringColor(score);
  const trackColor = ringTrackColor(score);
  const pct = Math.round(filled * 100);

  return (
    <div
      className="relative flex items-center justify-center"
      role="img"
      aria-label={`Core system readiness: ${label} (${pct}%)`}
    >
      <svg
        width={72}
        height={72}
        viewBox="0 0 72 72"
        className="-rotate-90"
        aria-hidden="true"
      >
        {/* Track */}
        <circle
          cx={36}
          cy={36}
          r={RING_R}
          fill="none"
          strokeWidth={5}
          className={cn("transition-all", trackColor)}
          strokeDasharray={`${RING_CIRCUMFERENCE} ${RING_CIRCUMFERENCE}`}
        />
        {/* Arc */}
        <circle
          cx={36}
          cy={36}
          r={RING_R}
          fill="none"
          strokeWidth={5}
          strokeLinecap="round"
          className={cn("transition-all duration-700", color)}
          strokeDasharray={`${dash} ${gap}`}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="text-base font-bold tabular-nums text-white leading-none">{pct}%</span>
      </div>
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function RingSkeleton() {
  return (
    <div className="flex items-center gap-4 animate-pulse" aria-busy="true" aria-label="Loading readiness">
      <div className="h-[72px] w-[72px] rounded-full bg-slate-800/60" />
      <div className="space-y-2">
        <div className="h-3 w-24 rounded bg-slate-800/60" />
        <div className="h-2 w-16 rounded bg-slate-800/40" />
      </div>
    </div>
  );
}

// ─── Public component ─────────────────────────────────────────────────────────

export const ReadinessRing = memo(function ReadinessRing({ className }: { className?: string }) {
  const { data, isLoading } = useQuery({
    queryKey: PLATFORM_HEALTH_QUERY_KEY,
    queryFn: fetchPlatformHealth,
    staleTime: 60_000,
  });

  const stats = data ? deriveBackendReadiness(data) : null;

  return (
    <div className={cn("flex items-center gap-4", className)}>
      {isLoading || !stats ? (
        <RingSkeleton />
      ) : (
        <>
          <ReadinessRingInner score={stats.score} label={stats.label} />
          <div className="space-y-1 min-w-0">
            <p className="text-sm font-semibold text-white leading-none">
              {stats.label}
            </p>
            <p className="text-[11px] text-slate-400">
              {stats.ready} ready · {stats.unavailable} unavailable
            </p>
            <p className="text-[10px] uppercase tracking-[0.3em] text-slate-300">
              {stats.ready} of {stats.total} core checks
            </p>
            <p className={cn("text-[11px]", CAPABILITY_COPY[stats.capability].className)}>
              {CAPABILITY_COPY[stats.capability].text}
            </p>
          </div>
        </>
      )}
    </div>
  );
});
