"use client";

import { memo } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { cn } from "@/lib/utils";

interface LeagueOffseasonNoticeProps {
  /** Display name of the league (e.g. "Premier League"). */
  leagueName: string;
  /** ISO 8601 date of the next season kick-off (e.g. "2026-08-08"). */
  nextSeasonStart: string | null;
  /** True when the provider has not yet published a confirmed start date. */
  nextSeasonStartEstimated?: boolean | null;
  className?: string;
}

function formatNextSeasonDate(iso: string | null): string {
  if (!iso) return "date to be confirmed";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  try {
    const diff = new Date(iso).getTime() - Date.now();
    return Math.max(0, Math.ceil(diff / 86_400_000));
  } catch {
    return null;
  }
}

/**
 * Shown when a league's fixture list is empty and the backend reports offseason=true.
 * WCAG 2.2 AA compliant: decorative icon is aria-hidden, text conveys all meaning.
 */
export const LeagueOffseasonNotice = memo(function LeagueOffseasonNotice({
  leagueName,
  nextSeasonStart,
  nextSeasonStartEstimated = null,
  className,
}: LeagueOffseasonNoticeProps) {
  const days = nextSeasonStartEstimated ? null : daysUntil(nextSeasonStart);
  const formattedDate = formatNextSeasonDate(nextSeasonStart);
  const prefersReduced = useReducedMotion();

  return (
    <motion.section
      role="status"
      aria-live="polite"
      aria-label={`${leagueName} is in off-season`}
      initial={prefersReduced ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={prefersReduced ? { duration: 0 } : { duration: 0.35, ease: "easeOut" }}
      className={cn(
        "flex flex-col items-center gap-4 rounded-xl border border-dashed",
        "border-zinc-700 bg-zinc-900/60 px-6 py-10 text-center",
        className,
      )}
    >
      {/* Decorative calendar icon */}
      <span aria-hidden="true" className="text-4xl select-none">
        📅
      </span>

      <div className="space-y-1">
        <h3 className="text-base font-semibold text-zinc-100">
          {leagueName} — Off Season
        </h3>
        <p className="text-sm text-zinc-400">
          No upcoming fixtures are scheduled right now.
        </p>
      </div>

      {nextSeasonStart && (
        <div className="rounded-lg bg-zinc-800 px-4 py-2 text-sm">
          <span className="text-zinc-400">
            {nextSeasonStartEstimated ? "Season currently expected around " : "Next season kicks off "}
          </span>
          <time
            dateTime={nextSeasonStart}
            className="font-medium text-emerald-400"
          >
            {formattedDate}
          </time>
          {days !== null && days > 0 && (
            <span className="ml-1 text-zinc-500">({days} days away)</span>
          )}
          {nextSeasonStartEstimated && (
            <span className="mt-1 block text-xs text-amber-300">
              Date not yet confirmed by the provider.
            </span>
          )}
        </div>
      )}

      <p className="max-w-xs text-xs text-zinc-500">
        Historical data and model ratings remain available. Predictions will
        resume once fixtures are released.
      </p>
    </motion.section>
  );
});
