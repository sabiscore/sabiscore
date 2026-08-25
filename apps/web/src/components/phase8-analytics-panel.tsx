"use client";

/**
 * Phase 8 Sprint 2: Phase 8 Feature Intelligence Panel
 *
 * Displays Pi-ratings, Berrar ratings, EWMA form, market movement, and
 * match importance score for a given match. Features with missing live data
 * are visually distinguished as DATA_GAP with a neutral value.
 *
 * When USE_PHASE8_FEATURES is disabled on the backend the panel renders a
 * "Phase 8 analytics not yet enabled" notice rather than hiding itself.
 */

import { memo, useState, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import {
  getPhase8Features,
  APIError,
  type Phase8FeaturesResponse,
  type Phase8FeatureGroup,
  type Phase8FeatureValue,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { PanelWarmingState } from "@/components/panel-warming-state";

// ─── Props ────────────────────────────────────────────────────────────────────

interface Phase8AnalyticsPanelProps {
  matchId: string;
  league?: string;
}

// ─── Feature group icon map ────────────────────────────────────────────────────

const GROUP_ICON: Record<string, string> = {
  pi_ratings: "π",
  berrar_ratings: "β",
  ewma_form: "∿",
  market_movement: "📈",
  match_context: "⚑",
};

const GROUP_COLOR: Record<
  string,
  { bg: string; border: string; text: string; badge: string }
> = {
  pi_ratings: {
    bg: "bg-violet-500/8",
    border: "border-violet-500/25",
    text: "text-violet-300",
    badge: "bg-violet-500/15 text-violet-200 border-violet-500/30",
  },
  berrar_ratings: {
    bg: "bg-sky-500/8",
    border: "border-sky-500/25",
    text: "text-sky-300",
    badge: "bg-sky-500/15 text-sky-200 border-sky-500/30",
  },
  ewma_form: {
    bg: "bg-teal-500/8",
    border: "border-teal-500/25",
    text: "text-teal-300",
    badge: "bg-teal-500/15 text-teal-200 border-teal-500/30",
  },
  market_movement: {
    bg: "bg-amber-500/8",
    border: "border-amber-500/25",
    text: "text-amber-300",
    badge: "bg-amber-500/15 text-amber-200 border-amber-500/30",
  },
  match_context: {
    bg: "bg-rose-500/8",
    border: "border-rose-500/25",
    text: "text-rose-300",
    badge: "bg-rose-500/15 text-rose-200 border-rose-500/30",
  },
};

const DEFAULT_COLOR = {
  bg: "bg-slate-800/30",
  border: "border-slate-700/40",
  text: "text-slate-300",
  badge: "bg-slate-700/30 text-slate-400 border-slate-600/30",
};

// ─── Formatters ───────────────────────────────────────────────────────────────

function formatFeatureValue(name: string, value: number): string {
  if (name.includes("berrar_rating") && !name.includes("diff")) return value.toFixed(0);
  if (name.includes("_rate")) return `${(value * 100).toFixed(1)}%`;
  if (name.includes("_ppg")) return value.toFixed(2);
  if (name.includes("drift") || name.includes("direction")) return value.toFixed(3);
  if (name === "match_importance_score") return value.toFixed(2);
  return value.toFixed(3);
}

function toLabel(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Convert freshness_seconds to a compact human label + color class.
 * null = DATA_GAP (feature has no live value); 0 = just fetched (Fresh).
 * Never "Live" — this measures feature-data recency, not match state. */
export function freshnessLabel(seconds: number | null): { label: string; cls: string } {
  if (seconds === null) return { label: "—", cls: "text-slate-400" };
  if (seconds === 0) return { label: "Fresh", cls: "text-emerald-400" };
  if (seconds < 3_600) return { label: `${Math.round(seconds / 60)}m`, cls: "text-emerald-400" };
  if (seconds < 86_400) return { label: `${Math.round(seconds / 3600)}h`, cls: "text-amber-400" };
  return { label: `${Math.round(seconds / 86400)}d`, cls: "text-rose-400" };
}

/** Summary freshness chip label for a group card header (only called when all_available=true).
 * Never "LIVE" — this measures feature-data recency, not match state. */
export function groupFreshnessChip(seconds: number): { label: string; cls: string; bg: string } {
  if (seconds < 3_600) return { label: "FRESH", cls: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/25" };
  if (seconds < 86_400) return { label: "RECENT", cls: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/25" };
  return { label: "STALE", cls: "text-rose-400", bg: "bg-rose-500/10 border-rose-500/25" };
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Phase8Skeleton() {
  return (
    <div
      className="space-y-3 animate-pulse"
      aria-busy="true"
      aria-label="Loading Phase 8 analytics"
    >
      <div className="h-8 w-48 rounded-lg bg-slate-800/70" />
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 sm:gap-4">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-44 rounded-2xl bg-slate-800/50" />
        ))}
      </div>
    </div>
  );
}

// ─── Feature row ──────────────────────────────────────────────────────────────

const FeatureRow = memo(function FeatureRow({
  feature,
  prefersReduced,
}: {
  feature: Phase8FeatureValue;
  prefersReduced: boolean | null;
}) {
  const isGap = feature.is_data_gap;
  const age = freshnessLabel(feature.freshness_seconds);
  return (
    <motion.div
      key={feature.name}
      className="flex items-center justify-between py-1 px-2 rounded-lg hover:bg-slate-800/40 transition-colors"
      initial={prefersReduced ? false : { opacity: 0, x: -6 }}
      animate={{ opacity: 1, x: 0 }}
      transition={prefersReduced ? { duration: 0 } : { duration: 0.2 }}
    >
      <span
        className={cn(
          "text-xs font-mono truncate max-w-[55%]",
          isGap ? "text-slate-400" : "text-slate-200"
        )}
        title={feature.name}
      >
        {toLabel(feature.name)}
      </span>
      <div className="flex items-center gap-1.5">
        {!isGap && feature.source && (
          <span
            className="text-[9px] font-medium text-slate-400 truncate max-w-[4rem]"
            title={`Source: ${feature.source}`}
            aria-label={`Source: ${feature.source}`}
          >
            {feature.source}
          </span>
        )}
        {!isGap && (
          <span
            className={cn("text-[9px] tabular-nums font-medium", age.cls)}
            title={`Data age: ${feature.freshness_seconds ?? 0}s`}
            aria-label={`Freshness: ${age.label}`}
          >
            {age.label}
          </span>
        )}
        <span
          className={cn(
            "text-xs font-semibold tabular-nums",
            isGap ? "text-slate-400 line-through" : "text-slate-100"
          )}
          aria-label={
            isGap
              ? `${toLabel(feature.name)}: data gap — default value shown`
              : `${toLabel(feature.name)}: ${formatFeatureValue(feature.name, feature.value)}`
          }
        >
          {formatFeatureValue(feature.name, feature.value)}
          {isGap && (
            <span className="ml-1 text-[9px] font-bold text-slate-400 uppercase tracking-wider">
              GAP
            </span>
          )}
        </span>
      </div>
    </motion.div>
  );
});

// ─── Feature group card ────────────────────────────────────────────────────────

const FeatureGroupCard = memo(function FeatureGroupCard({
  group,
  prefersReduced,
}: {
  group: Phase8FeatureGroup;
  prefersReduced: boolean | null;
}) {
  const colors = GROUP_COLOR[group.group_id] ?? DEFAULT_COLOR;
  const icon = GROUP_ICON[group.group_id] ?? "◈";

  return (
    <motion.article
      className={cn(
        "rounded-2xl border p-4 flex flex-col gap-2",
        colors.bg,
        colors.border
      )}
      initial={prefersReduced ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={prefersReduced ? { duration: 0 } : { duration: 0.3, ease: "easeOut" }}
      aria-label={`${group.label} feature group`}
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "inline-flex items-center justify-center w-7 h-7 rounded-lg text-sm font-bold border",
              colors.badge
            )}
            aria-hidden="true"
          >
            {icon}
          </span>
          <h3 className={cn("text-sm font-semibold", colors.text)}>
            {group.label}
          </h3>
        </div>
        {(() => {
          const chip = group.all_available
            ? groupFreshnessChip(group.group_freshness_seconds)
            : { label: "PARTIAL", cls: "text-slate-300", bg: "bg-slate-800/60 border-slate-700/60" };
          return (
            <span
              className={cn(
                "text-[10px] font-bold rounded-full px-2 py-0.5 border",
                chip.cls,
                chip.bg,
              )}
              aria-label={
                group.all_available
                  ? `Data freshness: ${chip.label.toLowerCase()}`
                  : "Some features use default values"
              }
            >
              {chip.label}
            </span>
          );
        })()}
      </div>

      {/* Reference note */}
      <p className="text-[10px] text-slate-400 leading-tight" aria-hidden="true">
        {group.reference}
      </p>

      {/* Feature rows */}
      <div className="space-y-0.5 mt-1">
        {group.features.map((feat) => (
          <FeatureRow
            key={feat.name}
            feature={feat}
            prefersReduced={prefersReduced}
          />
        ))}
      </div>
    </motion.article>
  );
});

// ─── Disabled state ────────────────────────────────────────────────────────────

function Phase8DisabledNotice() {
  return (
    <div
      role="status"
      className="rounded-2xl border border-slate-700/40 bg-slate-800/20 p-3.5 sm:p-4 flex flex-col gap-1.5"
    >
      <p className="text-sm font-semibold text-slate-300">
        Advanced Feature Intelligence — Coming Soon
      </p>
      <p className="text-xs text-slate-400 max-w-prose">
        Deeper feature analytics (team strength ratings, form momentum, market
        movement, match importance) are in staged rollout pending model
        validation. The predictions and analysis above are unaffected.
      </p>
    </div>
  );
}

// ─── Error state ──────────────────────────────────────────────────────────────

function Phase8Error({
  error,
  onRetry,
}: {
  error: Error;
  onRetry?: () => void;
}) {
  const [retrying, setRetrying] = useState(false);
  const raw = error.message ?? "";
  const trimmed = raw.trimStart().toLowerCase();
  const isHtml =
    trimmed.startsWith("<!doctype") ||
    trimmed.startsWith("<html") ||
    trimmed.startsWith("unexpected token '<'");
  const safe = isHtml
    ? "Backend service temporarily unavailable. Try again in a few minutes."
    : raw.length > 120
      ? `${raw.slice(0, 120)}…`
      : raw || "An unexpected error occurred.";

  const handleRetry = useCallback(() => {
    if (!onRetry) return;
    setRetrying(true);
    onRetry();
    setTimeout(() => setRetrying(false), 2000);
  }, [onRetry]);

  return (
    <div
      role="alert"
      className="rounded-2xl border border-rose-500/20 bg-rose-500/5 p-3.5 sm:p-4 flex items-start gap-3"
    >
      <svg
        className="mt-0.5 h-4 w-4 flex-shrink-0 text-rose-400"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={1.5}
          d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-rose-300">Phase 8 analytics unavailable</p>
        <p className="mt-0.5 text-xs text-slate-400">{safe}</p>
        {onRetry && (
          <button
            type="button"
            onClick={handleRetry}
            disabled={retrying}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-slate-700/60 bg-slate-800/40 px-3 py-1 text-xs font-medium text-slate-300 transition hover:bg-slate-700/60 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-500"
          >
            <svg
              className={`h-3 w-3 ${retrying ? "animate-spin" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden
            >
              <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
              <path d="M21 3v5h-5" />
            </svg>
            {retrying ? "Retrying…" : "Try again"}
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Data gap banner ──────────────────────────────────────────────────────────

function DataGapBanner({ count, total }: { count: number; total: number }) {
  if (count === 0) return null;
  return (
    <div
      role="status"
      aria-label={`${count} of ${total} Phase 8 features showing defaults`}
      className="flex items-start gap-2 rounded-xl border border-fuchsia-500/20 bg-fuchsia-500/5 p-3"
    >
      <span
        className="mt-0.5 h-4 w-4 rounded-full bg-fuchsia-500/20 border border-fuchsia-500/40 flex-shrink-0 flex items-center justify-center text-[9px] font-bold text-fuchsia-400"
        aria-hidden="true"
      >
        !
      </span>
      <p className="text-xs text-fuchsia-400/80 leading-snug">
        <span className="font-semibold text-fuchsia-300">
          {count} of {total} features
        </span>{" "}
        show registry defaults (live data unavailable). Prediction accuracy
        for these features may be reduced.
      </p>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export const Phase8AnalyticsPanel = memo(function Phase8AnalyticsPanel({
  matchId,
  league = "EPL",
}: Phase8AnalyticsPanelProps) {
  const prefersReduced = useReducedMotion();

  const {
    data,
    isLoading,
    error,
    refetch,
  } = useQuery<Phase8FeaturesResponse, Error>({
    queryKey: ["phase8-features", matchId, league],
    queryFn: () => getPhase8Features(matchId, league),
    staleTime: 60_000,
  });

  if (isLoading) return <Phase8Skeleton />;
  if (error) {
    if (error instanceof APIError && error.code === "COLD_START") {
      return (
        <PanelWarmingState
          label="Phase 8 analytics"
          onRetry={() => void refetch()}
        />
      );
    }
    return <Phase8Error error={error} onRetry={() => void refetch()} />;
  }
  if (!data) return null;
  if (data.status === "disabled" || !data.phase8_enabled) {
    return <Phase8DisabledNotice />;
  }

  const gapCount = data.data_gaps.length;
  const totalCount = data.total_phase8_features;

  return (
    <section aria-label="Phase 8 feature intelligence" className="space-y-4">
      {/* Availability + partial-data row — the section divider header lives in Phase8AnalyticsSection */}
      <div className="flex items-center justify-between">
        <span
          className="text-[10px] font-bold text-violet-400 bg-violet-500/10 border border-violet-500/25 rounded-full px-2 py-0.5"
          aria-label={`${data.available_features} of ${totalCount} Phase 8 features available`}
        >
          {data.available_features}/{totalCount} FRESH
        </span>
        {data.status === "partial" && (
          <span className="text-[10px] text-fuchsia-400 font-semibold">
            PARTIAL DATA
          </span>
        )}
      </div>

      {/* Data gap banner */}
      <DataGapBanner count={gapCount} total={totalCount} />

      {/* Feature groups grid */}
      <div
        className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
        role="list"
        aria-label="Phase 8 feature groups"
      >
        {data.feature_groups.map((group) => (
          <div role="listitem" key={group.group_id}>
            <FeatureGroupCard
              group={group}
              prefersReduced={prefersReduced}
            />
          </div>
        ))}
      </div>
    </section>
  );
});

export default Phase8AnalyticsPanel;
