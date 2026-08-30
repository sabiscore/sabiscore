"use client";

import { memo, useState, useCallback } from "react";
import { HelpCircle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "framer-motion";
import {
  getFullAnalysis,
} from "@/lib/api";
import {
  mapFullAnalysisPresentation,
  describeEvidenceCode,
  formatLagosTimestamp,
  groupEvidenceGaps,
  isNarrativeRedundant,
  type FullMatchAnalysisResponse,
  type FullMatchEloContext,
  type FullMatchUncertainty,
  type FullMatchRLRecommendation,
  type FullMatchOddsEdge,
  type MatchActionability,
} from "@/lib/full-analysis-contract";
import { cn } from "@/lib/utils";
import { InsightsTeaseStrip } from "@/components/insights-tease-strip";
import { Tooltip, KellyTooltip, EdgeTooltip } from "@/components/ui/ResponsibleGamblingTooltip";
import { VERDICT_TOKENS } from "@/lib/verdict-tokens";
import { mapEvidenceFreshness } from "@/lib/freshness";
import { generationLabel } from "@/lib/model-identity";

// ─── Verdict description copy (Phase 3) ──────────────────────────────────────

const VERDICT_COPY: Record<string, string> = {
  HIGH_CONVICTION: "Verified model, market, and risk gates are aligned.",
  ACTIONABLE: "Positive edge with sufficient verified model support.",
  SPECULATIVE: "Watchlist only. No stake is permitted without stronger evidence.",
  HOLD: "Model and market are aligned. No edge above threshold.",
  NO_BET: "Verified data is available, but no market currently offers positive value.",
  PARTIAL: "No bet. Critical evidence gaps or conflicts block action.",
};

// ─── Derive action chip (Phase 3) ────────────────────────────────────────────

// ─── Props ────────────────────────────────────────────────────────────────────

interface FullAnalysisDashboardProps {
  matchId: string;
  league?: string;
  /** Real team names when matchId is a canonical fixture ID rather than a
   * "Home vs Away" string — parseTeams() can't recover names from a bare ID. */
  homeTeam?: string;
  awayTeam?: string;
}

// ─── Verdict config ───────────────────────────────────────────────────────────

type Verdict = FullMatchAnalysisResponse["verdict"];
type FullAnalysisPresentation = ReturnType<typeof mapFullAnalysisPresentation>;

const VERDICT_META = VERDICT_TOKENS;

// ─── Helpers ──────────────────────────────────────────────────────────────────

const pct = (v: number, d = 1) => `${(Math.max(0, v) * 100).toFixed(d)}%`;
const fmt = (v: number, d = 0) => v.toFixed(d);
const toLabel = (k: string) =>
  k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

function parseTeams(matchId: string): [string, string] {
  const idx = matchId.indexOf(" vs ");
  if (idx === -1) return [matchId.trim(), ""];
  return [matchId.slice(0, idx).trim(), matchId.slice(idx + 4).trim()];
}

// Deterministic hype copy — template table, never LLM-generated at render time
const HYPE_COPY: Record<string, string[]> = {
  HIGH_CONVICTION: [
    "Verified evidence gates passed.",
    "Model and market evidence are aligned.",
    "The certified model is available.",
    "Risk controls permit a bounded stake.",
  ],
  ACTIONABLE: [
    "Verified evidence supports analysis.",
    "The evidence gates are satisfied.",
    "A bounded decision is available.",
    "League staking limits remain enforced.",
  ],
  SPECULATIVE: [
    "Watchlist only; no stake is permitted.",
    "Evidence is not sufficient for action.",
    "Monitor for stronger model evidence.",
    "Speculative evidence remains non-actionable.",
  ],
  HOLD: [
    "Market has this priced in.",
    "No edge to speak of today.",
    "Sitting this one out is the move.",
    "Wait for a better spot.",
  ],
  PARTIAL: [
    "Live feeds incomplete — exercise caution.",
    "Data gaps. Partial picture only.",
    "Model working with limited visibility.",
    "Incomplete data. Use as context only.",
  ],
};

function sabiInsightCopy(verdict: Verdict, matchId: string): string {
  const pool = HYPE_COPY[verdict] ?? HYPE_COPY.HOLD;
  const hash = matchId.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return pool[hash % pool.length];
}

// ─── Sabi Insights badge (E.6) ────────────────────────────────────────────────

function SabiInsightsBadge({
  verdict,
  matchId,
  copy,
}: {
  verdict: Verdict;
  matchId: string;
  copy?: string;
}) {
  const displayedCopy = copy ?? sabiInsightCopy(verdict, matchId);
  return (
    <p className="text-[11px] text-slate-400 italic leading-relaxed truncate">
      <span className="sr-only">Sabi Insights: </span>
      {displayedCopy}
    </p>
  );
}

// ─── Victory micro-animation (E.6) ────────────────────────────────────────────

// ─── Probability orbs (E.1 + E.2) ────────────────────────────────────────────

interface OrbProps {
  label: string;
  value: number;
  strokeColor: string;
  isTop: boolean;
  available?: boolean;
}

function ProbabilityOrb({ label, value, strokeColor, isTop, available = true }: OrbProps) {
  const prefersReduced = useReducedMotion();
  const r = 32;
  const circumference = 2 * Math.PI * r;
  const targetOffset = circumference * (1 - Math.max(0, value));

  return (
    <div className="flex flex-col items-center gap-2">
      <svg
        width="88"
        height="88"
        viewBox="0 0 88 88"
        aria-label={available ? `${label}: ${Math.round(value * 100)}%` : `${label}: unavailable`}
        role="img"
        className="flex-shrink-0"
      >
        {/* Track */}
        <circle cx="44" cy="44" r={r} fill="none" stroke="rgba(30,41,59,0.8)" strokeWidth="6" />
        {/* Fill */}
        <motion.circle
          cx="44"
          cy="44"
          r={r}
          fill="none"
          stroke={available ? strokeColor : "#334155"}
          strokeWidth="6"
          strokeLinecap="round"
          strokeDasharray={`${circumference} ${circumference}`}
          initial={{ strokeDashoffset: prefersReduced ? targetOffset : circumference }}
          animate={{ strokeDashoffset: targetOffset }}
          transition={prefersReduced ? { duration: 0 } : { duration: 0.8, ease: "easeOut", delay: 0.15 }}
          style={{ transform: "rotate(-90deg)", transformOrigin: "44px 44px" }}
        />
        <text
          x="44" y="40" textAnchor="middle" dominantBaseline="middle"
          fontSize="13" fontWeight="700" fill={isTop ? "white" : "#94a3b8"}
        >
          {available ? `${Math.round(value * 100)}%` : "—"}
        </text>
        {isTop && (
          <text x="44" y="56" textAnchor="middle" fontSize="8" fill="#34d399">
            ▲ TOP
          </text>
        )}
      </svg>
      <span className={cn("text-xs font-medium tracking-wide", isTop ? "text-white" : "text-slate-400")}>
        {label}
      </span>
    </div>
  );
}

// ─── Enhanced match hero (E.1) ────────────────────────────────────────────────

function EnhancedMatchHero({
  matchId,
  data,
  presentation,
  league = "EPL",
  homeTeam,
  awayTeam,
}: {
  matchId: string;
  data: FullMatchAnalysisResponse;
  presentation: FullAnalysisPresentation;
  league?: string;
  homeTeam?: string;
  awayTeam?: string;
}) {
  const prefersReduced = useReducedMotion();
  const meta = VERDICT_META[data.verdict];
  const [parsedHome, parsedAway] = parseTeams(matchId);
  const home = homeTeam ?? parsedHome;
  const away = awayTeam ?? parsedAway;
  const { ensemble } = data;
  const probabilities = presentation.displayedProbabilities;
  const elo = data.elo_context;

  const slideIn = (direction: "left" | "right") =>
    prefersReduced
      ? {}
      : {
          initial: { opacity: 0, x: direction === "left" ? -28 : 28 },
          animate: { opacity: 1, x: 0 },
          transition: { type: "spring", stiffness: 200, damping: 28 },
        };

  return (
    <div className={cn("rounded-2xl border p-3.5 sm:p-4.5 space-y-3 sm:space-y-3.5", meta.bg, meta.border)}>
      <section aria-labelledby="decision-heading" className="rounded-xl border border-white/10 bg-slate-950/40 p-3 sm:p-3.5">
        <p id="decision-heading" className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
          Decision
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2 sm:gap-2.5">
          <VerdictBadge verdict={data.verdict} />
          <strong className="text-sm sm:text-base text-white">{presentation.primaryDecision}</strong>
        </div>
        <p className="mt-1.5 text-xs sm:text-sm leading-5 sm:leading-6 text-slate-300">{presentation.reason}</p>
        <p className="mt-1.5 text-[11px] sm:text-xs text-slate-400">
          Evidence quality: {presentation.evidenceCounts.critical} critical gaps · {presentation.evidenceCounts.advisory} advisory gaps · {presentation.evidenceCounts.conflicts} conflicts
        </p>
      </section>
      {/* ── Teams clash ── */}
      <div className="flex items-center justify-between gap-3">
        <motion.div {...slideIn("left")} className="flex-1 min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-0.5">Home</p>
          <p className="text-base font-bold text-slate-100 truncate">{home || "—"}</p>
        </motion.div>

        <div className="flex-shrink-0 text-center px-2">
          <span className="text-xs font-semibold text-slate-400 tracking-widest">vs</span>
        </div>

        <motion.div {...slideIn("right")} className="flex-1 min-w-0 text-right">
          <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-0.5">Away</p>
          <p className="text-base font-bold text-slate-100 truncate">{away || "—"}</p>
        </motion.div>
      </div>

      {/* ── Probability orbs ── */}
      <div className="flex items-end justify-around py-2" role="group" aria-label="Match outcome probabilities">
        <ProbabilityOrb
          label="Home Win"
          value={probabilities?.home ?? 0}
          strokeColor="hsl(var(--home-accent))"
          isTop={presentation.topOutcome === "home_win"}
          available={presentation.predictionAvailable}
        />
        <ProbabilityOrb
          label="Draw"
          value={probabilities?.draw ?? 0}
          strokeColor="hsl(var(--draw-accent))"
          isTop={presentation.topOutcome === "draw"}
          available={presentation.predictionAvailable}
        />
        <ProbabilityOrb
          label="Away Win"
          value={probabilities?.away ?? 0}
          strokeColor="hsl(var(--away-accent))"
          isTop={presentation.topOutcome === "away_win"}
          available={presentation.predictionAvailable}
        />
      </div>

      {/* ── Quick-stat strip ── */}
      <div className="flex items-center justify-between border-t border-slate-800/40 pt-3 text-center">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Home Elo</p>
          <p className="text-xs font-semibold text-slate-200 tabular-nums">
            {elo ? fmt(elo.home_elo) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Elo Δ</p>
          <p className={cn("text-xs font-bold tabular-nums", !elo ? "text-slate-400" : elo.elo_difference > 0 ? "text-emerald-400" : elo.elo_difference < 0 ? "text-rose-400" : "text-slate-400")}>
            {elo
              ? `${elo.elo_difference >= 0 ? "+" : ""}${fmt(elo.elo_difference)}`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Away Elo</p>
          <p className="text-xs font-semibold text-slate-200 tabular-nums">
            {elo ? fmt(elo.away_elo) : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Top outcome probability</p>
          <p className="text-xs font-bold text-white tabular-nums">
            {presentation.topOutcomeProbability === null
              ? "Unavailable"
              : pct(presentation.topOutcomeProbability)}
          </p>
        </div>
      </div>

      {/* ── Model provenance strip (Phase D) ── */}
      {(ensemble.calibration_applied || ensemble.overlay_applied) && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-slate-800/40 pt-2.5">
          <span className="text-[9px] uppercase tracking-widest text-slate-400 mr-0.5">Model</span>
          {ensemble.calibration_applied && (
            <span
              className="inline-flex items-center rounded-full border border-violet-500/25 bg-violet-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-violet-400"
              title={`Probability calibration applied — method: ${ensemble.calibration_method ?? "isotonic"}`}
            >
              {ensemble.calibration_method ?? "calibrated"}
            </span>
          )}
          {ensemble.overlay_applied && (
            <span
              className="inline-flex items-center rounded-full border border-cyan-500/25 bg-cyan-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-cyan-400"
              title="Bivariate Poisson draw overlay applied"
            >
              +Poisson
            </span>
          )}
          {/* APEX §11: the raw artifact version is engineering provenance and
              lives on /admin/model-health, not on a consumer match page. */}
          <span className="text-[9px] text-slate-400 ml-auto truncate">
            {generationLabel(ensemble.model_version)}
          </span>
        </div>
      )}

      {/* ── Verdict + freshness + commentary ── */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/40 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative inline-flex">
            <VerdictBadge verdict={data.verdict} />
          </div>
          {/* WP-F: suppress alarming STALE badge when no live evidence was produced.
              A baseline/reduced-evidence response references historical training data,
              not a live evidence bundle — "810d ago" is meaningless and alarming. */}
          {presentation.isReducedEvidenceBaseline ||
          (data.staleness_available && data.staleness_seconds >= 365 * 86400) ? (
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/40 bg-slate-800/40 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-400"
              title="Evidence freshness: time since team statistics were last updated from providers."
            >
              Historical data only
            </span>
          ) : (
            <FreshnessPill
              tag={data.freshness_tag}
              stalenessSecs={data.staleness_seconds}
              available={data.staleness_available}
            />
          )}
          <PredictionAgePill generatedAt={data.generated_at} />
          {/* Phase F: UCL soft-coverage badge */}
          {league === "UCL" && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-300"
              title={data.competition_stage ? `UCL ${data.competition_stage.replace(/_/g, " ")}` : "UEFA Champions League — soft coverage"}
            >
              UCL{data.competition_stage ? ` · ${data.competition_stage.toUpperCase()}` : ""}
            </span>
          )}
          {/* Phase F: High Stakes flag when match_importance_score ≥ 0.70 */}
          {(data.match_importance_score ?? 0) >= 0.70 && (
            <span
              className="inline-flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-rose-300"
              title={`High-stakes fixture · importance ${((data.match_importance_score ?? 0) * 100).toFixed(0)}%`}
            >
              High Stakes ⚡
            </span>
          )}
          {data.partial_intelligence && (
            <span className="text-xs font-semibold uppercase tracking-wider text-fuchsia-400 border border-fuchsia-500/20 bg-fuchsia-500/10 rounded-full px-3 py-1">
              Partial
            </span>
          )}
        </div>
        <SabiInsightsBadge verdict={data.verdict} matchId={matchId} copy={presentation.reason} />
      </div>
      {/* ── Verdict description (Phase 3) ── */}
      <p className="text-xs text-slate-400 leading-relaxed border-t border-slate-800/30 pt-2">
        {VERDICT_COPY[data.verdict] ?? ""}
      </p>
    </div>
  );
}

function getActionabilitySummary(data: FullMatchAnalysisResponse) {
  const presentation = mapFullAnalysisPresentation(data);
  return {
    action: presentation.primaryDecision,
    rationale: presentation.reason,
    coverage: `${presentation.evidenceCounts.critical} critical / ${presentation.evidenceCounts.advisory} advisory / ${presentation.evidenceCounts.conflicts} conflicts`,
    tone: presentation.stakePermitted
      ? "text-emerald-300 border-emerald-500/20 bg-emerald-500/8"
      : presentation.primaryDecision === "Watchlist"
        ? "text-amber-300 border-amber-500/20 bg-amber-500/8"
        : "text-rose-300 border-rose-500/20 bg-rose-500/8",
  };
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="space-y-3.5 sm:space-y-4 animate-pulse" role="status" aria-busy="true" aria-label="Loading intelligence dashboard">
      <div className="h-12 rounded-2xl bg-slate-800/70" />
      <div className="h-16 rounded-2xl bg-slate-800/50" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4">
        <div className="h-36 sm:h-40 rounded-2xl bg-slate-800/50" />
        <div className="h-36 sm:h-40 rounded-2xl bg-slate-800/50" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 sm:gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-32 sm:h-36 rounded-2xl bg-slate-800/40" />
        ))}
      </div>
    </div>
  );
}

// ─── Freshness pill ───────────────────────────────────────────────────────────

function FreshnessPill({
  tag,
  stalenessSecs,
  available,
}: {
  tag: "LIVE" | "RECENT" | "STALE" | "UNKNOWN";
  stalenessSecs: number | null | undefined;
  available: boolean;
}) {
  const freshness = mapEvidenceFreshness({
    stalenessSeconds: stalenessSecs,
    available,
    tag,
  });
  const dot = {
    LIVE: "bg-emerald-400",
    RECENT: "bg-amber-400",
    STALE: "bg-rose-400",
    UNKNOWN: "bg-slate-500",
  }[freshness.tag];
  return (
    <span
      aria-label={freshness.ariaLabel}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
        freshness.className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} aria-hidden />
      {freshness.label}{freshness.ageLabel}
    </span>
  );
}

// ─── Prediction age pill (CE-5) ──────────────────────────────────────────────

function PredictionAgePill({ generatedAt }: { generatedAt: string }) {
  const generatedMs = new Date(generatedAt).getTime();
  const ageSecs = Number.isFinite(generatedMs)
    ? Math.max(0, Math.round((Date.now() - generatedMs) / 1000))
    : 0;

  const title = `Prediction generated at ${formatLagosTimestamp(generatedAt)} WAT. Regenerate for latest signal.`;

  // Wording is deliberately about the ANALYSIS, not the evidence. A bare "Fresh"
  // sat beside the evidence-freshness pill and read as a claim about the data,
  // which can be UNKNOWN at the same moment the analysis was just produced.
  if (ageSecs < 30 * 60) {
    return (
      <span className="text-[10px] font-medium text-emerald-400" title={title}>
        Analyzed just now
      </span>
    );
  }
  if (ageSecs < 2 * 3600) {
    const mins = Math.round(ageSecs / 60);
    return (
      <span className="text-[10px] text-slate-500" title={title}>
        Analyzed {mins}m ago
      </span>
    );
  }
  if (ageSecs < 24 * 3600) {
    const hrs = Math.round(ageSecs / 3600);
    return (
      <span
        className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-400"
        title={title}
      >
        Analyzed {hrs}h ago — regenerate?
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-400"
      title={title}
    >
      Outdated ↻
    </span>
  );
}

// ─── Verdict badge ────────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const meta = VERDICT_META[verdict];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-4 py-1.5 text-sm font-semibold",
        meta.bg,
        meta.border,
        meta.color
      )}
    >
      <span
        className={cn("h-2 w-2 rounded-full", meta.dot)}
        aria-hidden="true"
      />
      {meta.label}
    </span>
  );
}

// ─── Prob bar ────────────────────────────────────────────────────────────────

function ProbBar({
  label,
  value,
  color,
  isTop,
}: {
  label: string;
  value: number;
  color: string;
  isTop: boolean;
}) {
  const prefersReduced = useReducedMotion();
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className={cn("font-medium", isTop ? "text-white" : "text-slate-400")}>
          {label}
          {isTop && (
            <svg className="inline ml-1.5 w-3.5 h-3.5 text-emerald-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden>
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          )}
        </span>
        <span className={cn("font-bold tabular-nums", isTop ? "text-white" : "text-slate-400")}>
          {pct(value)}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
        <motion.div
          className={cn("h-full rounded-full", color)}
          initial={{ width: prefersReduced ? `${value * 100}%` : 0 }}
          animate={{ width: `${value * 100}%` }}
          transition={prefersReduced ? { duration: 0 } : { duration: 0.7, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

// ─── Ensemble card ────────────────────────────────────────────────────────────

export function EnsembleCard({ data }: { data: FullMatchAnalysisResponse["ensemble"] }) {
  const max = Math.max(data.home_win_prob, data.draw_prob, data.away_win_prob);
  const available = data.probabilities_available;
  return (
    <div className="glass-card p-4 sm:p-5 space-y-3.5 sm:space-y-4 border border-slate-800/60">
      <div className="flex items-center justify-between">
        <p className="text-xs uppercase tracking-wider text-slate-400">Ensemble Prediction</p>
        <span className="text-xs text-slate-400">{data.league}</span>
      </div>
      {available ? <div className="space-y-3">
        <ProbBar
          label="Home Win"
          value={data.home_win_prob}
          color="bg-gradient-to-r from-[hsl(var(--home-accent))] to-indigo-400"
          isTop={data.home_win_prob === max}
        />
        <ProbBar
          label="Draw"
          value={data.draw_prob}
          color="bg-gradient-to-r from-[hsl(var(--draw-accent))] to-purple-400"
          isTop={data.draw_prob === max}
        />
        <ProbBar
          label="Away Win"
          value={data.away_win_prob}
          color="bg-gradient-to-r from-[hsl(var(--away-accent))] to-emerald-400"
          isTop={data.away_win_prob === max}
        />
      </div> : (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-3 text-xs text-amber-200/80">
          Official outcome probabilities are unavailable. Diagnostic baseline values are not displayed.
        </div>
      )}
      <div className="pt-1 border-t border-slate-800/50 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">Top outcome probability</span>
          <span className="text-sm font-bold text-white">
            {available ? pct(data.top_outcome_probability) : "Unavailable"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-slate-400">{generationLabel(data.model_version)}</span>
          <div className="flex items-center gap-1">
            {data.calibration_applied && (
              <span
                className="rounded-full border border-violet-500/25 bg-violet-500/10 px-1.5 py-px text-[9px] font-semibold text-violet-400"
                title={`Calibration: ${data.calibration_method ?? "isotonic"}`}
              >
                {data.calibration_method ?? "cal"}
              </span>
            )}
            {data.overlay_applied && (
              <span
                className="rounded-full border border-cyan-500/25 bg-cyan-500/10 px-1.5 py-px text-[9px] font-semibold text-cyan-400"
                title="Bivariate Poisson draw overlay"
              >
                BP
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── RL recommendation card ───────────────────────────────────────────────────

export function RLCard({
  rec,
  effectiveKellyCap,
  stakePermitted,
}: {
  rec: FullMatchRLRecommendation;
  effectiveKellyCap: number;
  stakePermitted: boolean;
}) {
  const gaugeRadius = 38;
  const circumference = Math.PI * gaugeRadius;
  const fillPct = stakePermitted && effectiveKellyCap > 0
    ? Math.min(1, rec.stake_fraction / effectiveKellyCap)
    : 0;
  const strokeOffset = circumference * (1 - fillPct);
  const arcColor = rec.abstain
    ? "#f59e0b"
    : fillPct >= 0.75
    ? "#f87171"
    : fillPct >= 0.4
    ? "#34d399"
    : "#22d3ee";

  return (
    <div className="glass-card p-4 sm:p-5 space-y-3.5 sm:space-y-4 border border-slate-800/60">
      <p className="text-xs uppercase tracking-wider text-slate-400">RL Bet Recommendation</p>

      <div className="flex items-center gap-5">
        <svg viewBox="0 0 92 54" className="w-28 flex-shrink-0" aria-label={!stakePermitted ? "No bet" : `Stake ${pct(rec.stake_fraction, 2)} of ${pct(effectiveKellyCap)} cap`} role="img">
          <path d="M9,46 A38,38 0 0,1 83,46" fill="none" stroke="#1e293b" strokeWidth="9" strokeLinecap="round" />
          <path
            d="M9,46 A38,38 0 0,1 83,46"
            fill="none"
            stroke={arcColor}
            strokeWidth="9"
            strokeLinecap="round"
            strokeDasharray={`${circumference} ${circumference}`}
            strokeDashoffset={strokeOffset}
          />
          <text x="46" y="46" textAnchor="middle" fontSize="10" fill="#94a3b8" dominantBaseline="middle">
            {!stakePermitted ? "NO BET" : pct(rec.stake_fraction, 2)}
          </text>
        </svg>

        <div className="space-y-1.5">
          <p className={cn("text-lg font-bold", !stakePermitted ? "text-amber-300" : "text-emerald-300")}>
            {!stakePermitted ? "No bet" : `Stake ${pct(rec.stake_fraction, 2)}`}
          </p>
          <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-400">
            Effective Kelly cap {pct(effectiveKellyCap, 1)}
            <KellyTooltip />
          </div>
          {rec.reason && (
            <p className="text-xs text-slate-400 leading-relaxed max-w-xs">{rec.reason}</p>
          )}
        </div>
      </div>

      {/* The reward decomposition describes a stake the policy actually sized. On
          an abstention the backend emits zeros plus a constant abstention term,
          and `slice` would drop that term while presenting the zeros as
          measurements — the vΩ.24 neutral-default-as-data defect. */}
      {!rec.abstain && stakePermitted && Object.keys(rec.reward_components).length > 0 && (
        <div className="grid grid-cols-2 gap-2 pt-1">
          {Object.entries(rec.reward_components).slice(0, 4).map(([k, v]) => (
            <div key={k} className="rounded-lg bg-slate-900/60 px-3 py-2">
              <p className="text-[10px] uppercase tracking-wider text-slate-400">{toLabel(k)}</p>
              <p className="text-sm font-semibold text-slate-200">{fmt(v, 3)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Model drivers card ───────────────────────────────────────────────────────

function ModelDriversCard({ drivers }: { drivers: string[] }) {
  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800/60 p-3.5 sm:p-4.5 space-y-2.5">
      <p className="text-xs uppercase tracking-wider text-slate-400">Model Drivers</p>
      {drivers.length === 0 ? (
        <p className="text-sm text-slate-400">No validated model-driver report is available.</p>
      ) : (
        <ul className="space-y-1.5" aria-label="Model feature drivers">
          {drivers.slice(0, 5).map((d, i) => {
            const opacity = Math.max(0.5, 1 - i * 0.1);
            return (
              <li key={d} className="flex items-center gap-2" style={{ opacity }}>
                <span className="flex-shrink-0 w-4.5 h-4.5 rounded-full bg-fuchsia-500/20 text-fuchsia-400 flex items-center justify-center text-[10px] font-bold select-none" aria-hidden>
                  {i + 1}
                </span>
                <span className="truncate text-fuchsia-300 text-xs sm:text-sm">{toLabel(d)}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ─── Elo context card ─────────────────────────────────────────────────────────

export function EloContextCard({ elo }: { elo: FullMatchEloContext }) {
  if (!elo) {
    return (
      <div className="rounded-xl bg-slate-900/60 border border-slate-800/60 p-3.5 sm:p-4.5 space-y-2.5">
        <p className="text-xs uppercase tracking-wider text-slate-400">Elo Context</p>
        <div className="space-y-1.5">
          {["Home Elo", "Away Elo", "Elo Diff", "Momentum"].map((label) => (
            <div key={label} className="flex justify-between text-xs sm:text-sm">
              <span className="text-slate-400">{label}</span>
              <span className="font-semibold text-slate-400 tabular-nums">
                <span className="sr-only">{label} unavailable</span>
                <span aria-hidden="true">—</span>
              </span>
            </div>
          ))}
        </div>
        <p className="text-[11px] text-slate-400">
          Ratings need verified match history, which is unavailable for this fixture.
        </p>
      </div>
    );
  }

  const diff = elo.elo_difference;
  const diffColor = diff > 50 ? "text-emerald-400" : diff < -50 ? "text-rose-400" : "text-slate-300";

  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800/60 p-3.5 sm:p-4.5 space-y-2.5">
      <p className="text-xs uppercase tracking-wider text-slate-400">Elo Context</p>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="text-slate-400">Home Elo</span>
          <span className="font-semibold text-slate-200 tabular-nums">{fmt(elo.home_elo)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="text-slate-400">Away Elo</span>
          <span className="font-semibold text-slate-200 tabular-nums">{fmt(elo.away_elo)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm border-t border-slate-800/50 pt-1.5">
          <span className="text-slate-400">Elo Diff</span>
          <span className={cn("font-bold tabular-nums", diffColor)}>
            {diff >= 0 ? "+" : ""}{fmt(diff)}
          </span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="text-slate-400">Momentum</span>
          <span className="font-semibold text-slate-200 tabular-nums">{fmt(elo.elo_momentum_cross, 2)}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Uncertainty card ─────────────────────────────────────────────────────────

export function UncertaintyCard({ unc, available }: { unc: FullMatchUncertainty; available: boolean }) {
  if (!unc) {
    return (
      <div className="rounded-xl bg-slate-900/60 border border-slate-800/60 p-3.5 sm:p-4.5 space-y-2.5">
        <p className="text-xs uppercase tracking-wider text-slate-400">BNN Uncertainty</p>
        <p className="text-sm font-semibold text-slate-300">Unavailable</p>
        <p className="text-[11px] text-slate-400">
          No measured uncertainty is available; no interval or percentage is inferred.
        </p>
      </div>
    );
  }
  const isLow = unc.confidence_tier === "LOW_EVIDENCE";
  return (
    <div className="rounded-xl bg-slate-900/60 border border-slate-800/60 p-3.5 sm:p-4.5 space-y-2.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs uppercase tracking-wider text-slate-400">
          BNN Uncertainty
          <Tooltip content="Bayesian Neural Network — instead of one number, the model reports a range reflecting what it doesn't know.">
            <HelpCircle className="h-3.5 w-3.5 text-slate-400 hover:text-slate-300" />
          </Tooltip>
        </div>
        <span
          className={cn(
            "text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full border",
            isLow
              ? "text-amber-300 bg-amber-500/10 border-amber-500/20"
              : "text-emerald-300 bg-emerald-500/10 border-emerald-500/20"
          )}
        >
          {isLow ? "Low Evidence" : "OK"}
        </span>
      </div>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="flex items-center gap-1.5 text-slate-400">
            Epistemic
            <Tooltip content="Unknown-unknowns — reducible with more data. High values trigger abstention.">
              <HelpCircle className="h-3.5 w-3.5 text-slate-400 hover:text-slate-300" />
            </Tooltip>
          </span>
          <span className="font-semibold tabular-nums text-slate-200">{pct(unc.epistemic_unc)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="flex items-center gap-1.5 text-slate-400">
            Aleatoric
            <Tooltip content="Irreducible randomness in football outcomes. Cannot be reduced by more data.">
              <HelpCircle className="h-3.5 w-3.5 text-slate-400 hover:text-slate-300" />
            </Tooltip>
          </span>
          <span className="font-semibold tabular-nums text-slate-200">{pct(unc.aleatoric_unc)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="flex items-center gap-1.5 text-slate-400">
            CI
            <Tooltip content="Width of the 95% credible interval for the top predicted class. Narrower = more precise.">
              <HelpCircle className="h-3.5 w-3.5 text-slate-400 hover:text-slate-300" />
            </Tooltip>
          </span>
          <span className={cn("font-semibold tabular-nums", available ? "text-slate-200" : "text-slate-400")}>
            {available
              ? `[${pct(unc.credible_interval[0])}, ${pct(unc.credible_interval[1])}]`
              : "—"}
          </span>
        </div>
      </div>
      {!available && (
        <p className="text-[11px] text-slate-400">
          Spread reflects missing evidence, not model disagreement about an outcome.
        </p>
      )}
    </div>
  );
}

// ─── Odds edge card ───────────────────────────────────────────────────────────

export function OddsEdgeCard({ edge }: { edge: FullMatchOddsEdge }) {
  const hasEdge = edge.edge > 0;
  return (
    <div className={cn(
      "rounded-xl border p-3.5 sm:p-4.5 space-y-2.5",
      hasEdge
        ? "bg-emerald-500/5 border-emerald-500/20"
        : "bg-slate-900/60 border-slate-800/60"
    )}>
      <p className="text-xs uppercase tracking-wider text-slate-400">Market Edge</p>
      <div className="space-y-1.5">
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="text-slate-400">Market</span>
          <span className="font-semibold text-slate-200">{toLabel(edge.market)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="text-slate-400">Odds</span>
          <span className="font-semibold tabular-nums text-slate-200">{fmt(edge.market_odds, 2)}</span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm border-t border-slate-800/50 pt-1.5">
          <span className="flex items-center gap-1.5 text-slate-400">
            Edge
            <EdgeTooltip />
          </span>
          <span className={cn("font-bold tabular-nums", hasEdge ? "text-emerald-400" : "text-slate-400")}>
            {hasEdge ? "+" : ""}{pct(edge.edge)}
          </span>
        </div>
        <div className="flex justify-between text-xs sm:text-sm">
          <span className="flex items-center gap-1.5 text-slate-400">
            Kelly
            <KellyTooltip />
          </span>
          <span className="font-semibold tabular-nums text-slate-200">{pct(edge.kelly_stake, 2)}</span>
        </div>
      </div>
    </div>
  );
}

// ─── Data gap banner ──────────────────────────────────────────────────────────

function DataGapBanner({ gaps }: { gaps: string[] }) {
  if (gaps.length === 0) return null;
  const COLLAPSE_THRESHOLD = 8;
  return (
    <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3.5 py-2.5 sm:px-4 sm:py-3 flex items-start gap-3" role="alert">
      <svg className="w-4 h-4 flex-shrink-0 text-amber-400 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      </svg>
      <div className="min-w-0 space-y-1">
        <p className="text-xs font-semibold text-amber-300 uppercase tracking-wider">
          {gaps.length} data gap{gaps.length === 1 ? "" : "s"} detected
        </p>
        {gaps.length <= COLLAPSE_THRESHOLD ? (
          <p className="text-xs text-amber-200/60">{gaps.map(toLabel).join(" · ")}</p>
        ) : (
          <>
            <p className="text-xs text-amber-200/60">
              Live evidence is missing for these inputs, so the model fell back to a reduced-evidence
              baseline and the verdict stays cautious.
            </p>
            {/* Grouped by kind rather than listed raw: ~50 canonical feature
                names ("away_attack_vs_home_defense") are model internals, and
                title-casing them told a reader nothing they could act on. The
                exact codes stay one disclosure away for auditability. */}
            <ul className="flex flex-wrap gap-x-3 gap-y-1 pt-0.5">
              {groupEvidenceGaps(gaps).map((group) => (
                <li key={group.label} className="text-xs text-amber-200/70">
                  {group.label}
                  <span className="ml-1 tabular-nums text-amber-200">{group.count}</span>
                </li>
              ))}
            </ul>
            <details>
              <summary className="cursor-pointer list-none text-xs font-semibold text-amber-300/80 hover:text-amber-200">
                Show all {gaps.length} missing fields ▸
              </summary>
              <p className="mt-1.5 text-xs leading-relaxed text-amber-200/50">
                {gaps.map(toLabel).join(" · ")}
              </p>
            </details>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Edge delta bar (CE-2) ────────────────────────────────────────────────────

function EdgeDeltaBar({
  ensemble,
  oddsEdge,
}: {
  ensemble: FullMatchAnalysisResponse["ensemble"];
  oddsEdge: FullMatchOddsEdge;
}) {
  const market = oddsEdge.market;
  const modelProb =
    market === "home_win"
      ? ensemble.home_win_prob
      : market === "away_win"
      ? ensemble.away_win_prob
      : ensemble.draw_prob;
  const impliedProb = oddsEdge.market_odds > 0 ? 1 / oddsEdge.market_odds : 0;
  const deltaPct = (modelProb - impliedProb) * 100;
  const absDelta = Math.abs(deltaPct);

  const isPositive = deltaPct > 0;
  const isNeutral = absDelta < 2;
  const barColor = isNeutral
    ? "bg-amber-500"
    : isPositive
    ? "bg-emerald-500"
    : "bg-rose-500";
  const textColor = isNeutral
    ? "text-amber-400"
    : isPositive
    ? "text-emerald-400"
    : "text-rose-400";
  const barWidthPct = Math.min(100, (absDelta / 15) * 100);
  const marketLabel = market.replace(/_/g, " ");

  return (
    <div
      className="rounded-xl border border-slate-800/60 bg-slate-900/50 p-3.5 sm:p-4 space-y-2.5"
      role="group"
      aria-label="Model vs market edge delta"
    >
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Edge Delta</p>
        <span className="text-[10px] text-slate-400 capitalize">{marketLabel}</span>
      </div>
      <div className="flex items-center gap-4">
        <div className="flex-1 space-y-1">
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Model {pct(modelProb)}</span>
            <span className="text-slate-400">Market {pct(impliedProb)}</span>
          </div>
          <div className="relative h-2 w-full overflow-hidden rounded-full bg-slate-800">
            <div
              className={cn("h-full rounded-full transition-all duration-700", barColor)}
              style={{ width: `${barWidthPct}%` }}
            />
          </div>
        </div>
        <div className="flex-shrink-0 text-right">
          <p className={cn("text-lg font-bold tabular-nums", textColor)}>
            {isPositive ? "+" : ""}{deltaPct.toFixed(1)}%
          </p>
          <p className="text-[10px] text-slate-400">
            {isNeutral ? "Neutral" : isPositive ? "EV advantage" : "Fade signal"}
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── Data freshness section (Phase 3) ────────────────────────────────────────

interface SourceFreshnessItem {
  name: string;
  category: string;
  freshness_status: "LIVE" | "RECENT" | "STALE" | "DATA_GAP";
  enabled: boolean;
}

interface SourceFreshnessResponse {
  status: "AVAILABLE" | "UNAVAILABLE" | "FETCH_FAILED" | "UNKNOWN";
  sources: SourceFreshnessItem[];
}

function DataFreshnessSection() {
  const { data } = useQuery<SourceFreshnessResponse>({
    queryKey: ["sourcesFreshness"],
    queryFn: async () => {
      const res = await fetch("/api/sources/freshness", { cache: "no-store" });
      const payload = await res.json().catch(() => null) as SourceFreshnessResponse | null;
      if (!payload || !Array.isArray(payload.sources)) {
        return { status: "UNKNOWN", sources: [] };
      }
      return payload;
    },
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (!data) return null;
  if (data.status !== "AVAILABLE") {
    return (
      <div className="rounded-xl border border-slate-800/40 bg-slate-900/30 px-3.5 py-2.5 sm:px-4 sm:py-3 text-xs text-slate-400">
        Source freshness: <span className="font-semibold text-amber-300">{data.status}</span>
      </div>
    );
  }
  if (data.sources.length === 0) {
    return (
      <div className="rounded-xl border border-slate-800/40 bg-slate-900/30 px-3.5 py-2.5 sm:px-4 sm:py-3 text-xs text-slate-400">
        Source freshness: <span className="font-semibold">UNKNOWN</span>
      </div>
    );
  }

  const dotColor: Record<string, string> = {
    LIVE: "#22c55e",
    RECENT: "#f59e0b",
    STALE: "#ef4444",
    DATA_GAP: "#475569",
  };

  return (
    <div className="rounded-xl border border-slate-800/40 bg-slate-900/30 px-3.5 py-2.5 sm:px-4 sm:py-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-2">Source Freshness</p>
      <div className="flex flex-wrap gap-4">
        {data.sources.slice(0, 6).map((src) => (
          <div
            key={src.name}
            className="flex items-center gap-1.5"
            title={`${src.name}: ${src.freshness_status}`}
          >
            <span
              className="h-2 w-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: dotColor[src.freshness_status] ?? "#475569" }}
              aria-hidden
            />
            <span className="text-[10px] text-slate-400">{src.category}</span>
          </div>
        ))}
        <div className="ml-auto flex items-center gap-2.5 text-[9px] text-slate-300">
          <span><span className="text-emerald-500">●</span> Live</span>
          <span><span className="text-amber-500">●</span> Recent</span>
          <span><span className="text-rose-500">●</span> Stale</span>
          <span><span className="text-slate-400">●</span> Gap</span>
        </div>
      </div>
    </div>
  );
}

// ─── Evidence Status Card (WP-E): structured "why no prediction" summary ─────
// Shown when stake is not permitted so users understand what's missing and
// what would help, rather than seeing grey dashes with no explanation.
//
// ⚠️ Do NOT put `capitalize` on the gap text. `describeEvidenceCode` returns a
// lowercase sentence fragment (it is also interpolated mid-sentence by
// `mapFullAnalysisPresentation`), so `capitalize` Title-Cased real copy into
// "This Model Hasn't Passed Certification Yet" — which reads exactly like the
// raw-enum `titleCaseCode` fallback the map exists to replace.
export function EvidenceStatusCard({ data }: { data: FullMatchAnalysisResponse }) {
  const presentation = mapFullAnalysisPresentation(data);
  if (presentation.stakePermitted) return null;

  const critical = data.evidence_quality.critical_gaps;
  const conflicts = data.evidence_quality.conflicts;
  const blocking = [...critical, ...conflicts];
  const fixtureVerified = !critical.includes("FIXTURE_IDENTITY_UNVERIFIED");
  // Show uncollapsed when ≤5 blocking gaps; use <details> to collapse a long list
  const needsCollapse = blocking.length > 5;
  // Filter identity gap from list body (it's surfaced via the header check row)
  const listGaps = blocking.filter((g) => g !== "FIXTURE_IDENTITY_UNVERIFIED");

  return (
    <div
      role="region"
      aria-label="Why no prediction — evidence status"
      className="rounded-xl border border-slate-800/50 bg-slate-900/30 p-3.5 sm:p-4 space-y-2.5"
    >
      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
        Why no prediction
      </p>

      {/* Fixture identity row */}
      <div className="flex items-start gap-2.5 text-sm">
        <span
          className={cn(
            "mt-0.5 flex-shrink-0 text-[11px]",
            fixtureVerified ? "text-emerald-400" : "text-rose-400"
          )}
          aria-hidden
        >
          {fixtureVerified ? "●" : "✗"}
        </span>
        <span className={fixtureVerified ? "text-slate-300" : "text-slate-400"}>
          Fixture {fixtureVerified ? "identified in schedule" : "could not be matched to a scheduled fixture — team history unverifiable"}
        </span>
      </div>

      {/* Blocking gaps list */}
      {listGaps.length > 0 && (
        needsCollapse ? (
          <details className="space-y-1">
            <summary className="cursor-pointer select-none text-[11px] text-slate-400 hover:text-slate-300 transition-colors list-none flex items-center gap-1.5">
              <span className="text-rose-400">✗</span>
              {listGaps.length} required input{listGaps.length !== 1 ? "s" : ""} unavailable
              <span className="ml-auto text-[10px] text-slate-400">▼ show</span>
            </summary>
            <ul className="mt-2 space-y-1.5 pl-1" aria-label="Missing inputs">
              {listGaps.map((gap) => (
                <li key={gap} className="flex items-start gap-2 text-xs text-slate-400">
                  <span className="mt-0.5 flex-shrink-0 text-rose-400 text-[10px]" aria-hidden>✗</span>
                  <span className="first-letter:uppercase">{describeEvidenceCode(gap)}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : (
          <ul className="space-y-1.5" aria-label="Missing inputs">
            {listGaps.map((gap) => (
              <li key={gap} className="flex items-start gap-2 text-xs text-slate-400">
                <span className="mt-0.5 flex-shrink-0 text-rose-400 text-[10px]" aria-hidden>✗</span>
                <span className="first-letter:uppercase">{describeEvidenceCode(gap)}</span>
              </li>
            ))}
          </ul>
        )
      )}

      <p className="text-[11px] text-slate-400 border-t border-slate-800/30 pt-2">
        {blocking.length > 0
          ? "Check back closer to kickoff — providers update when squads and markets are confirmed."
          : "Model abstained on risk grounds. Evidence may be sufficient closer to kickoff."}
      </p>
    </div>
  );
}

function ActionabilityStrip({ data }: { data: FullMatchAnalysisResponse }) {
  const summary = getActionabilitySummary(data);

  return (
    <div className="grid grid-cols-1 gap-2.5 sm:gap-3 md:grid-cols-3" role="group" aria-label="Actionability summary">
      <div className={cn("rounded-xl border px-3.5 py-2.5 sm:px-4 sm:py-3", summary.tone)}>
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Next move</p>
        <p className="mt-0.5 text-sm font-semibold">{summary.action}</p>
      </div>
      <div className="rounded-xl border border-slate-800/50 bg-slate-900/40 px-3.5 py-2.5 sm:px-4 sm:py-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Why</p>
        <p className="mt-0.5 text-sm text-slate-200">{summary.rationale}</p>
      </div>
      <div className="rounded-xl border border-slate-800/50 bg-slate-900/40 px-3.5 py-2.5 sm:px-4 sm:py-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-400">Coverage</p>
        <p className="mt-0.5 text-sm text-slate-200">{summary.coverage}</p>
      </div>
    </div>
  );
}

// ─── Actionability Evidence Panel (Sprint 4 Slice A) ─────────────────────────

function EdgeQualityGauge({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tier = pct >= 70 ? "High" : pct >= 45 ? "Medium" : "Low";
  const gradient =
    pct >= 70
      ? "bg-gradient-to-r from-emerald-500 to-emerald-400"
      : pct >= 45
      ? "bg-gradient-to-r from-amber-500 to-amber-300"
      : "bg-gradient-to-r from-rose-600 to-rose-400";

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] uppercase tracking-wider text-slate-400">Edge quality</span>
        <div className="flex items-center gap-1.5">
          <span className={cn(
            "text-[9px] font-bold uppercase tracking-wider rounded-full px-1.5 py-0.5",
            pct >= 70 ? "text-emerald-300 bg-emerald-500/15" :
            pct >= 45 ? "text-amber-300 bg-amber-500/15" :
            "text-rose-300 bg-rose-500/15"
          )}>
            {tier}
          </span>
          <span className="text-xs font-bold tabular-nums text-slate-200">{pct}%</span>
        </div>
      </div>
      <div
        className="h-2 rounded-full bg-slate-800 overflow-hidden"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${pct}% — ${tier} edge quality`}
        aria-label={`Edge quality score: ${pct}% (${tier})`}
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-500 ease-out", gradient)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function ActionabilityEvidencePanel({ actionability }: { actionability: MatchActionability }) {
  return (
    <section
      className="rounded-2xl border border-slate-800/50 bg-slate-900/50 p-3.5 sm:p-4 space-y-3"
      aria-label="Edge quality and evidence"
    >
      <h3 className="text-xs uppercase tracking-[0.3em] text-slate-400">CLV Evidence</h3>

      {/* Edge quality gauge */}
      <EdgeQualityGauge score={actionability.edge_quality_score} />

      {/* Stats row */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 sm:grid-cols-4 text-center">
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Stake</p>
          <p className="text-sm font-bold text-slate-200 tabular-nums">
            {actionability.abstain ? "No bet" : `${actionability.suggested_stake_pct.toFixed(1)}%`}
          </p>
        </div>
        <div>
          {/* CLV: always null pre-kick-off; computed against closing odds post-match */}
          <p
            className="text-[10px] uppercase tracking-wider text-slate-400"
            title="Closing-line value — computed against Pinnacle closing odds at match end"
          >
            CLV
          </p>
          {actionability.clv_pct != null ? (
            <p
              className={cn(
                "text-sm font-bold tabular-nums",
                actionability.clv_pct > 0 ? "text-emerald-400" : "text-rose-400",
              )}
            >
              {actionability.clv_pct > 0 ? "+" : ""}
              {actionability.clv_pct.toFixed(1)}pp
            </p>
          ) : (
            <p
              className="text-sm font-bold text-slate-400 tabular-nums"
              title="CLV is computed against the closing implied probability at kick-off. Pre-match value is unavailable."
            >
              <span className="sr-only">CLV not yet available — computed at match end. </span>
              <span aria-hidden="true">Pre-match</span>
              <span className="ml-1 inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-slate-700/60 text-[8px] font-bold text-slate-400 select-none" aria-hidden>
                ?
              </span>
            </p>
          )}
        </div>
        <div>
          <p
            className="text-[10px] uppercase tracking-wider text-slate-400"
            title="Opening-to-current implied-probability drift — proxy for market intelligence before closing line"
          >
            Drift Δ
          </p>
          <p className={cn(
            "text-sm font-bold tabular-nums",
            actionability.closing_line_convergence_delta == null
              ? "text-slate-400"
              : actionability.closing_line_convergence_delta > 0
              ? "text-emerald-400"
              : actionability.closing_line_convergence_delta < 0
              ? "text-rose-400"
              : "text-slate-400"
          )}>
            {actionability.closing_line_convergence_delta != null
              ? `${actionability.closing_line_convergence_delta > 0 ? "+" : ""}${(actionability.closing_line_convergence_delta * 100).toFixed(1)}pp`
              : "—"}
          </p>
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400">Signal</p>
          <p className={cn(
            "text-sm font-bold uppercase",
            actionability.abstain ? "text-rose-400" : "text-cyan-400"
          )}>
            {actionability.abstain ? "ABSTAIN" : "ACTIVE"}
          </p>
        </div>
      </div>

      {/* Evidence list */}
      {actionability.top_evidence.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Key signals</p>
          <ul className="space-y-1" aria-label="Key signals">
            {actionability.top_evidence.map((ev) => (
              <li key={ev} className="flex items-start gap-2 text-xs text-slate-300">
                <span className="mt-0.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-cyan-400" aria-hidden />
                {ev}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Caveats */}
      {actionability.caveats.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-slate-400 mb-1.5">Caveats</p>
          <ul className="space-y-1" aria-label="Caveats">
            {actionability.caveats.map((c) => (
              <li key={c} className="flex items-start gap-2 text-xs text-amber-400/80">
                <span className="mt-0.5 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-amber-400" aria-hidden />
                {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Abstain reason */}
      {actionability.abstain && actionability.abstain_reason && (
        <p className="text-xs text-rose-400/80 italic">
          {actionability.abstain_reason}
        </p>
      )}
    </section>
  );
}

// ─── Error state ──────────────────────────────────────────────────────────────

function sanitizeErrorMessage(raw: string): string {
  const trimmed = raw.trimStart().toLowerCase();
  if (trimmed.startsWith("<!doctype") || trimmed.startsWith("<html")) {
    return "Backend service temporarily unavailable. Try again in a few minutes.";
  }
  return raw.length > 140 ? `${raw.slice(0, 140)}…` : raw;
}

function DashboardError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  const [retrying, setRetrying] = useState(false);
  const safe = sanitizeErrorMessage(message);

  const handleRetry = useCallback(() => {
    if (!onRetry) return;
    setRetrying(true);
    onRetry();
    setTimeout(() => setRetrying(false), 2000);
  }, [onRetry]);

  return (
    <div
      className="rounded-2xl border border-rose-500/20 bg-rose-500/5 p-4 sm:p-5 text-center space-y-2.5"
      role="alert"
    >
      <svg
        className="w-7 h-7 mx-auto text-rose-400"
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
      <p className="text-sm font-medium text-rose-300">Intelligence unavailable</p>
      <p className="text-xs text-slate-300">{safe}</p>
      {onRetry && (
        <button
          type="button"
          onClick={handleRetry}
          disabled={retrying}
          className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700/60 bg-slate-800/40 px-3.5 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-700/60 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-slate-500"
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
  );
}

// ─── Narrative block with expand/collapse ─────────────────────────────────────

const NARRATIVE_CLIP = 240;

export function NarrativeBlock({ text }: { text: string }) {
  const needsClip = text.length > NARRATIVE_CLIP;
  const [expanded, setExpanded] = useState(false);
  const displayed = needsClip && !expanded ? `${text.slice(0, NARRATIVE_CLIP)}…` : text;

  return (
    <div className="rounded-2xl border border-slate-800/50 bg-slate-900/50 p-3.5 sm:p-4.5">
      <p className="text-xs uppercase tracking-wider text-slate-400 mb-1.5">Narrative</p>
      <p id="narrative-text" className="text-xs sm:text-sm leading-relaxed text-slate-200">{displayed}</p>
      {needsClip && (
        <button
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 inline-flex min-h-11 items-center rounded px-2 text-[11px] font-medium text-slate-400 transition-colors hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-500"
          aria-expanded={expanded}
          aria-controls="narrative-text"
        >
          {expanded ? "Show less ↑" : "Show more ↓"}
        </button>
      )}
    </div>
  );
}

// ─── Main dashboard ───────────────────────────────────────────────────────────

function FullAnalysisDashboardInner({
  matchId,
  league = "EPL",
  homeTeam,
  awayTeam,
}: FullAnalysisDashboardProps) {
  const prefersReduced = useReducedMotion();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["fullAnalysis", matchId, league],
    queryFn: () => getFullAnalysis(matchId, league),
    staleTime: 55_000,
    enabled: Boolean(matchId),
    retry: false,
  });

  if (isLoading) return (
    <>
      <InsightsTeaseStrip matchId={matchId} league={league} visible={true} />
      <DashboardSkeleton />
    </>
  );

  if (error) {
    const msg = error instanceof Error ? error.message : "Unknown error";
    return <DashboardError message={msg} onRetry={() => void refetch()} />;
  }

  if (!data) return null;
  const presentation = mapFullAnalysisPresentation(data);

  return (
    <motion.section
      initial={prefersReduced ? false : { opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={prefersReduced ? { duration: 0 } : { duration: 0.4 }}
      aria-label="Full match intelligence dashboard"
      className="full-analysis-surface space-y-3.5 sm:space-y-4"
    >
      {/* ── Enhanced match hero (E.1 + Phase F) ── */}
      <EnhancedMatchHero
        matchId={matchId}
        data={data}
        presentation={presentation}
        league={league}
        homeTeam={homeTeam}
        awayTeam={awayTeam}
      />

      {presentation.stakePermitted && <ActionabilityStrip data={data} />}

      {/* ── WP-E: Evidence status card (why no prediction, structured breakdown) ── */}
      <EvidenceStatusCard data={data} />

      {/* ── CLV Evidence Panel (Sprint 4 Slice A) ── */}
      {data.actionability && presentation.stakePermitted && (
        <ActionabilityEvidencePanel actionability={data.actionability} />
      )}

      {/* ── Narrative: suppress only when it restates the already-visible decision reason ── */}
      {!isNarrativeRedundant(data.narrative, presentation.reason) && (
        <NarrativeBlock text={data.narrative ?? ""} />
      )}

      {/* ── Data gap banner ── */}
      <DataGapBanner gaps={data.data_gaps} />

      {/* ── Ensemble + RL (2-col) ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 sm:gap-4">
        <EnsembleCard data={data.ensemble} />
        <RLCard
          rec={data.rl_recommendation}
          effectiveKellyCap={presentation.effectiveKellyCap}
          stakePermitted={presentation.stakePermitted}
        />
      </div>

      {/* ── Model drivers · Elo · Uncertainty (3-col) ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4">
        <ModelDriversCard drivers={data.model_drivers} />
        <EloContextCard elo={data.elo_context} />
        <UncertaintyCard unc={data.uncertainty} available={presentation.predictionAvailable} />
      </div>

      {/* ── Edge delta bar (CE-2): model vs market gap ── */}
      {data.odds_edge && (
        <EdgeDeltaBar ensemble={data.ensemble} oddsEdge={data.odds_edge} />
      )}

      {/* ── Odds edge ── */}
      {data.odds_edge ? (
        <OddsEdgeCard edge={data.odds_edge} />
      ) : (
        <div className="rounded-xl border border-slate-800/40 bg-slate-900/30 px-3.5 py-2.5 sm:px-4 sm:py-3 flex items-center gap-3">
          <svg className="w-4 h-4 flex-shrink-0 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <p className="text-xs text-slate-400">Live market odds unavailable — edge calculation skipped.</p>
        </div>
      )}

      {/* ── Phase 9 shadow-mode candidate signal strip ── */}
      {data.phase9_candidate_features && (
        <Phase9ShadowStrip features={data.phase9_candidate_features} shadowOnly={data.phase9_shadow_only ?? true} />
      )}

      {/* ── Source freshness (Phase 3) ── */}
      <DataFreshnessSection />

      {/* ── Footer ── */}
      <p className="text-[11px] text-slate-400 text-right tabular-nums">
        Generated <time dateTime={data.generated_at} title={presentation.generatedAbsoluteLagos}>
          {presentation.generatedRelative} ({presentation.generatedAbsoluteLagos} WAT)
        </time>
        {" · "}match {data.match_id}
      </p>
    </motion.section>
  );
}

// ---------------------------------------------------------------------------
// Phase 9 / V4 shadow-mode strip — shown only when USE_PHASE9_CANDIDATE_FEATURES=true
// Never influences any verdict, probability, or value-bet shown above.
// ---------------------------------------------------------------------------
function Phase9ShadowStrip({
  features,
  shadowOnly,
}: {
  features: NonNullable<FullMatchAnalysisResponse["phase9_candidate_features"]>;
  shadowOnly: boolean;
}) {
  const me = features.market_efficiency;
  const hasValue = me?.has_value;
  const margin = me?.bookmaker_margin != null ? (me.bookmaker_margin * 100).toFixed(1) : null;
  const sharpness = me?.market_sharpness;
  const topBet = me?.value_bets?.[0];

  return (
    <div
      className="rounded-xl border border-violet-800/30 bg-violet-950/20 px-3.5 py-2.5 sm:px-4 sm:py-3 space-y-2"
      role="group"
      aria-label="Phase 9 candidate signal strip (shadow mode)"
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1 rounded-full bg-violet-900/50 px-2 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-700/40">
          V4 · SHADOW
        </span>
        {shadowOnly && (
          <span className="text-[10px] text-slate-400">
            Candidate signals — not used in prediction
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-3 text-[11px]">
        {margin !== null && (
          <span className="text-slate-400">
            Margin: <strong className="text-slate-200">{margin}%</strong>
          </span>
        )}
        {sharpness && sharpness !== "unknown" && (
          <span className="text-slate-400">
            Market: <strong className={sharpness === "sharp" ? "text-emerald-400" : "text-amber-400"}>{sharpness}</strong>
          </span>
        )}
        {hasValue && topBet && (
          <span className="text-slate-400">
            Top edge:{" "}
            <strong className="text-violet-300">
              {topBet.outcome.replace("_", " ")} EV {(topBet.ev * 100).toFixed(1)}%
            </strong>
            {topBet.kelly_fraction != null && (
              <span className="ml-1 text-slate-400">
                (Kelly {(topBet.kelly_fraction * 100).toFixed(1)}%)
              </span>
            )}
          </span>
        )}
        {features.hybrid_xg && Object.keys(features.hybrid_xg).length > 0 && (
          <span className="text-slate-400">
            Hybrid xG:{" "}
            <strong className="text-slate-200">
              {Object.values(features.hybrid_xg)
                .slice(0, 2)
                .map((v) => (v as number).toFixed(2))
                .join(" / ")}
            </strong>
          </span>
        )}
      </div>
    </div>
  );
}

export const FullAnalysisDashboard = memo(FullAnalysisDashboardInner);
