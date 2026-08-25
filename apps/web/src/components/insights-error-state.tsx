"use client";

import Link from "next/link";
import { useTransition } from "react";
import { useRouter } from "next/navigation";
import type { AnalysisErrorCategory } from "@/lib/full-analysis-contract";

interface InsightsErrorStateProps {
  errorType: AnalysisErrorCategory;
  matchup: string;
}

const CONFIG = {
  cold_start: {
    accent: "amber",
    label: "Engine Warming Up",
    heading: "Full AI insights are on their way",
    showWhyNote: true,
  },
  upstream_timeout: {
    accent: "amber",
    label: "Backend Response Delayed",
    heading: "Analysis is taking longer than expected",
    showWhyNote: false,
  },
  upstream_unavailable: {
    accent: "amber",
    label: "Backend Temporarily Unavailable",
    heading: "Analysis service is reconnecting",
    showWhyNote: false,
  },
  network_error: {
    accent: "amber",
    label: "Network Unavailable",
    heading: "The analysis request could not connect",
    showWhyNote: false,
  },
  backend_internal_error: {
    accent: "rose",
    label: "Service Temporarily Unavailable",
    heading: "We hit a snag",
    showWhyNote: false,
  },
  invalid_response: {
    accent: "rose",
    label: "Invalid Backend Response",
    heading: "The analysis contract could not be verified",
    showWhyNote: false,
  },
  insufficient_evidence: {
    accent: "amber",
    label: "Insufficient Verified Evidence",
    heading: "Not enough verified data to model this match",
    showWhyNote: false,
  },
  unknown: {
    accent: "rose",
    label: "Unexpected Error",
    heading: "We hit a snag",
    showWhyNote: false,
  },
} as const;

/**
 * Inline error state for the match insights page.
 *
 * Rendered directly inside the server component so Next.js 15's production
 * error sanitisation doesn't hide actionable information behind a digest hash.
 *
 * Compact card (not a full-viewport hero): the 6-layer analysis and Phase 8
 * sections mount below it and load independently, so this must not push them
 * off screen. Recovery is manual only — the API client already performed its
 * single bounded infrastructure retry before this card rendered, so there is
 * no countdown and no automatic page reload here.
 */
export function InsightsErrorState({ errorType, matchup }: InsightsErrorStateProps) {
  const cfg = CONFIG[errorType];
  const isAmber = cfg.accent === "amber";
  const router = useRouter();
  const [refreshing, startRefresh] = useTransition();

  // router.refresh() re-runs only this page's server components. A full
  // window.location.reload() discarded the 6-layer analysis and Phase 8 sections
  // that had already loaded, restarted the loading interstitial from 0%, and
  // re-downloaded the whole bundle to retry one fetch.
  const handleRetryNow = () => {
    startRefresh(() => router.refresh());
  };

  const body =
    errorType === "cold_start"
      ? `The prediction engine is starting up for ${matchup} — this takes 30–60 seconds after idle.`
      : errorType === "upstream_timeout"
      ? `The backend did not complete the ${matchup} analysis within the request budget.`
      : errorType === "upstream_unavailable"
      ? `The analysis backend is temporarily unavailable for ${matchup}.`
      : errorType === "network_error"
      ? `The ${matchup} request could not reach the analysis backend.`
      : errorType === "invalid_response"
      ? `The response for ${matchup} failed contract validation and was not displayed.`
      : errorType === "insufficient_evidence"
      ? `Required inputs for ${matchup} — recent form, head-to-head record and a coherent 1X2 market — are not available, so no probabilities or stake are produced.`
      : errorType === "backend_internal_error"
      ? `The prediction service is temporarily unavailable for ${matchup}. This usually resolves within a few minutes.`
      : `Something unexpected happened while generating insights for ${matchup}. This usually resolves on retry.`;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={`${cfg.label} — retry manually when ready`}
      className={`rounded-xl border p-3.5 sm:p-4 ${
        isAmber
          ? "border-amber-500/25 bg-amber-500/[0.04]"
          : "border-rose-500/25 bg-slate-900/40"
      }`}
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
        {/* Icon */}
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border ${
            isAmber
              ? "bg-amber-500/10 border-amber-500/30"
              : "bg-slate-800/50 border-rose-500/30"
          }`}
        >
          {isAmber ? (
            <svg
              className="h-4 w-4 text-amber-400 motion-safe:animate-pulse"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden
            >
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
          ) : (
            <svg
              className="h-4 w-4 text-rose-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          )}
        </div>

        {/* Text + actions */}
        <div className="min-w-0 flex-1 space-y-2">
          <div className="space-y-0.5">
            <p
              className={`text-[10px] font-semibold uppercase tracking-wider ${
                isAmber ? "text-amber-300" : "text-rose-300"
              }`}
            >
              {cfg.label}
            </p>
            <h2 className="text-base font-bold text-slate-100">{cfg.heading}</h2>
            <p className="text-xs text-slate-400">{body}</p>
            <p className="text-[11px] text-slate-400">
              The analysis sections below load independently and update on their own — no need to wait here.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Retrying cannot produce evidence that does not exist yet. */}
            {errorType !== "insufficient_evidence" && (
            <button
              type="button"
              disabled={refreshing}
              onClick={handleRetryNow}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-indigo-500/60 bg-indigo-500/20 px-3.5 py-1.5 text-xs font-semibold text-indigo-200 transition hover:bg-indigo-500/30 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-400"
            >
              <svg
                className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`}
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden
              >
                <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
                <path d="M21 3v5h-5" />
              </svg>
              {refreshing ? "Retrying…" : "Retry now"}
            </button>
            )}
            <Link
              href="/match"
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-slate-700/60 bg-slate-800/40 px-3.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
            >
              Pick another matchup
            </Link>
          </div>

          {cfg.showWhyNote && (
            <p className="text-xs text-slate-400">
              <span className="font-semibold text-slate-300">Why does this happen?</span>{" "}
              We use a free-tier backend that spins down after inactivity to keep costs low — the
              engine needs ~30 seconds to warm up.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
