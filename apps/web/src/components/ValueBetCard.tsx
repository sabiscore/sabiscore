"use client";

import { useState } from "react";
import { TrendingUp, AlertCircle, Copy, Check, ExternalLink } from "lucide-react";
import { toast } from "react-hot-toast";
import type { ValueBet } from "@/types/value-bet";
import type { MatchActionability } from "@/lib/api";
import { formatCurrency } from "../lib/format";
import { safeMessage } from "../lib/error-utils";
import { KellyTooltip, EdgeTooltip } from "./ui/ResponsibleGamblingTooltip";
import { TeamVsDisplay } from "./team-display";
import { FeatureFlag, useFeatureFlag } from "@/lib/feature-flags";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────

interface ValueBetContext {
  matchId: string;
  homeTeam: string;
  awayTeam: string;
  bookmaker?: string;
  clvExpected?: number | null;
}

interface ValueBetCardProps {
  bet: ValueBet;
  context: ValueBetContext;
  bankroll?: number;
  /** CLV-centered actionability block from FullMatchAnalysisResponse (optional). */
  actionability?: MatchActionability | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const getValueBetDefaults = (bet: ValueBet) => ({
  betType: bet.bet_type ?? "unknown",
  marketOdds: bet.market_odds ?? 1.0,
  modelProb: bet.model_prob ?? 0,
  marketProb: bet.market_prob ?? 0,
  edge: bet.edge ?? bet.value_pct ?? 0,
  kellyStake: bet.kelly_stake ?? 0,
  qualityTier: bet.quality?.tier ?? "VALUE",
  recommendation: bet.quality?.recommendation ?? bet.recommendation ?? "Evaluate carefully",
});

// Edge quality tier from edge_quality_score (≥0.60 HIGH, 0.40–0.59 MEDIUM, <0.40 LOW)
function resolveEdgeTier(actionability: MatchActionability | null | undefined, qualityTier: string) {
  if (actionability != null) {
    const s = actionability.edge_quality_score;
    if (s >= 0.6) return "HIGH";
    if (s >= 0.4) return "MEDIUM";
    return "LOW";
  }
  // Fall back to existing quality tier vocabulary
  if (qualityTier === "PREMIUM") return "HIGH";
  if (qualityTier === "VALUE") return "MEDIUM";
  return "LOW";
}

const TIER_STYLES = {
  HIGH: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  MEDIUM: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  LOW: "bg-slate-700/30 text-slate-400 border-slate-600/30",
} as const;

const TIER_LABELS = { HIGH: "High Edge", MEDIUM: "Medium Edge", LOW: "Low Edge" } as const;

// ─── Sub-components ───────────────────────────────────────────────────────────

function KellyVisualizer({ fraction, abstain }: { fraction: number; abstain: boolean }) {
  const MAX = 0.05;
  const pct = abstain ? 0 : Math.min(1, Math.max(0, fraction) / MAX);
  const label = abstain ? "No bet" : `${(fraction * 100).toFixed(1)}%`;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-slate-400">Suggested exposure</span>
        <span className={cn("text-xs font-bold tabular-nums", abstain ? "text-slate-400" : "text-slate-200")}>
          {label}
        </span>
      </div>
      <div
        className="h-1.5 rounded-full bg-slate-800 overflow-hidden"
        role="progressbar"
        aria-valuenow={Math.round(pct * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Kelly stake: ${label} of bankroll (Quarter-Kelly, capped at 5%)`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500 ease-out",
            abstain ? "bg-slate-700" : pct >= 0.8 ? "bg-rose-400" : pct >= 0.5 ? "bg-amber-400" : "bg-emerald-400",
          )}
          style={{ width: `${pct * 100}%` }}
        />
      </div>
      <p className="mt-0.5 text-[10px] text-slate-400">Quarter-Kelly · capped at 5%</p>
    </div>
  );
}

function CLVBadge({ clvPct }: { clvPct: number | null | undefined }) {
  // Only rendered when clv_pct > 0 — never shows 0% or N/A
  if (clvPct == null || clvPct <= 0) return null;
  return (
    <span
      className="inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300"
      title="Closing-line value computed against Pinnacle closing implied probability"
    >
      +{clvPct.toFixed(1)}% vs close
    </span>
  );
}

function ConvergenceIndicator({ delta }: { delta: number | null | undefined }) {
  // Null when closing odds unavailable — never show 0 as "neutral"
  if (delta == null) return null;
  const positive = delta > 0;
  const neutral = delta === 0;
  return (
    <div
      className="flex items-center gap-1"
      title={`Market drift: opening-to-closing implied probability delta. ${positive ? "Positive = sharp money confirms model." : "Negative = model lagged the market."}`}
    >
      <span className="text-[10px] text-slate-400">Drift Δ</span>
      <span
        className={cn(
          "text-xs font-bold tabular-nums",
          neutral ? "text-slate-400" : positive ? "text-emerald-400" : "text-rose-400",
        )}
      >
        {positive ? "▲" : delta < 0 ? "▼" : "—"}
        {" "}{Math.abs(delta * 100).toFixed(1)}pp
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ValueBetCard({ bet, context, bankroll = 1000, actionability }: ValueBetCardProps) {
  const [copied, setCopied] = useState(false);
  const bookmakerName = context.bookmaker ?? "Preferred Book";
  const premiumVisualsEnabled = useFeatureFlag(FeatureFlag.PREMIUM_VISUAL_HIERARCHY);

  const safe = getValueBetDefaults(bet);
  const isAbstain = actionability?.abstain === true;
  const edgeTier = resolveEdgeTier(actionability, safe.qualityTier);

  const kellyFraction = Math.max(safe.kellyStake, 0);
  const stakeValue = isAbstain ? 0 : bankroll * kellyFraction;
  const bookmakerOdds = safe.marketOdds;
  const potentialReturnValue = stakeValue * bookmakerOdds;
  const potentialProfitValue = potentialReturnValue - stakeValue;
  const edgePercentage = safe.edge * 100;

  const clvPct = actionability?.clv_pct ?? context.clvExpected ?? null;
  const convergenceDelta = actionability?.closing_line_convergence_delta ?? null;
  const suggestedStake = actionability?.suggested_stake_pct != null
    ? actionability.suggested_stake_pct / 100
    : kellyFraction;

  const getMarketLabel = () => {
    switch (safe.betType) {
      case "home_win": return `${context.homeTeam} Win`;
      case "away_win": return `${context.awayTeam} Win`;
      case "draw": return "Draw";
      default: return safe.betType.replace(/_/g, " ");
    }
  };

  const copyBetDetails = async () => {
    const betDetails = [
      "🎯 VALUE BET ALERT",
      `${context.homeTeam} vs ${context.awayTeam}`,
      `Market: ${getMarketLabel()}`,
      `Odds: ${bookmakerOdds.toFixed(2)} @ ${bookmakerName}`,
      `Edge: ${edgePercentage.toFixed(1)}%`,
      `Suggested Exposure: ${(suggestedStake * 100).toFixed(1)}%`,
      `Tier: ${TIER_LABELS[edgeTier]}`,
      clvPct != null && clvPct > 0 ? `CLV: +${clvPct.toFixed(1)}% vs close` : null,
    ].filter(Boolean).join("\n");

    try {
      if (!navigator?.clipboard) throw new Error("Clipboard API not available");
      await navigator.clipboard.writeText(betDetails);
      setCopied(true);
      toast.success(safeMessage("Bet details copied!"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(safeMessage("Failed to copy bet details"));
    }
  };

  const openBookmaker = () => {
    toast.success(safeMessage(`Opening ${bookmakerName}...`));
  };

  // ── ABSTAIN state ──
  if (isAbstain) {
    return (
      <div className="relative overflow-hidden rounded-xl border border-slate-700/40 bg-slate-900/50 p-4 sm:p-5 space-y-3">
        <div className="flex items-center gap-3">
          <AlertCircle className="h-5 w-5 flex-shrink-0 text-amber-400" aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold text-amber-300">No bet advised</p>
            {actionability?.abstain_reason && (
              <p className="text-xs text-slate-400 mt-0.5">{actionability.abstain_reason}</p>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>{context.homeTeam} vs {context.awayTeam}</span>
          <span className="rounded-full border border-slate-700/50 bg-slate-800/50 px-2 py-0.5 font-medium">
            ABSTAIN
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "group relative overflow-hidden rounded-xl border p-4 sm:p-5 backdrop-blur-sm transition-all",
        premiumVisualsEnabled
          ? "border-white/10 bg-gradient-to-br from-slate-950/80 to-slate-900/60 hover:border-cyan-400/40 hover:shadow-[0_15px_45px_rgba(0,212,255,0.25)]"
          : "border-slate-700/50 bg-gradient-to-br from-slate-800/50 to-slate-900/50 hover:border-emerald-500/50 hover:shadow-lg hover:shadow-emerald-500/20",
      )}
    >
      {/* Edge tier badge (E.3: driven by edge_quality_score) */}
      <div className="absolute right-4 top-4 flex items-center gap-1.5">
        <CLVBadge clvPct={clvPct} />
        <span
          className={cn(
            "inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold",
            TIER_STYLES[edgeTier],
          )}
        >
          {TIER_LABELS[edgeTier]}
        </span>
      </div>

      {/* Match info */}
      <div className="mb-2.5 sm:mb-3">
        <div className="mb-1">
          <TeamVsDisplay
            homeTeam={context.homeTeam}
            awayTeam={context.awayTeam}
            size="sm"
            showCountryFlags={true}
            className="justify-start"
          />
        </div>
        <p className="text-xs sm:text-sm text-slate-400">
          {getMarketLabel()} @ {bookmakerName}
        </p>
      </div>

      {/* Edge + Odds */}
      <div className="mb-2.5 sm:mb-3 grid grid-cols-2 gap-2.5 sm:gap-3">
        <div className="rounded-lg bg-slate-800/50 p-2.5 sm:p-3">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <TrendingUp className="h-3.5 w-3.5" aria-hidden="true" />
            <span>Edge</span>
            <EdgeTooltip />
          </div>
          <p className="mt-1 text-xl sm:text-2xl font-bold text-emerald-400">
            +{edgePercentage.toFixed(1)}%
          </p>
        </div>
        <div className="rounded-lg bg-slate-800/50 p-2.5 sm:p-3">
          <div className="text-xs text-slate-400">Odds</div>
          <p className="mt-1 text-xl sm:text-2xl font-bold text-white">
            {bookmakerOdds.toFixed(2)}
          </p>
        </div>
      </div>

      {/* Kelly stake visualizer (E.3) */}
      <div className="mb-2.5 sm:mb-3 rounded-lg border border-slate-700/50 bg-slate-900/50 p-3 sm:p-3.5 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <span className="text-xs sm:text-sm font-medium text-slate-300">Recommended Stake</span>
            <KellyTooltip />
          </div>
          <span className="text-xs text-slate-400">
            {(suggestedStake * 100).toFixed(1)}% Kelly
          </span>
        </div>
        <KellyVisualizer fraction={suggestedStake} abstain={false} />
        <div className="flex items-baseline gap-2">
          <span className="text-xl sm:text-2xl font-bold text-white">{formatCurrency(stakeValue)}</span>
          <span className="text-xs sm:text-sm text-slate-400">
            → {formatCurrency(potentialReturnValue)} return
          </span>
        </div>
        <div className="text-xs text-emerald-400">
          Potential profit: {formatCurrency(potentialProfitValue)}
        </div>
      </div>

      {/* Probability breakdown + convergence */}
      <div className="mb-2.5 sm:mb-3 space-y-1.5">
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">Fair Probability</span>
          <span className="font-medium text-white">
            {(safe.modelProb * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">Implied Probability</span>
          <span className="font-medium text-slate-400">
            {(safe.marketProb * 100).toFixed(1)}%
          </span>
        </div>
        <div className="flex items-center justify-between">
          <ConvergenceIndicator delta={convergenceDelta} />
        </div>
      </div>

      {/* Action buttons */}
      <div className="grid grid-cols-2 gap-2 sm:gap-2.5">
        <button
          type="button"
          onClick={copyBetDetails}
          aria-label="Copy bet details to clipboard"
          className={cn(
            "flex items-center justify-center gap-2 rounded-lg border px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm font-medium transition-all active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 min-h-[44px]",
            premiumVisualsEnabled
              ? "border-white/10 bg-slate-900/60 text-slate-200 hover:border-cyan-400/30 hover:bg-cyan-400/10"
              : "border-slate-600 bg-slate-700/50 text-white hover:bg-slate-700",
          )}
        >
          {copied ? (
            <><Check className="h-4 w-4" aria-hidden="true" />Copied</>
          ) : (
            <><Copy className="h-4 w-4" aria-hidden="true" />Copy</>
          )}
        </button>

        <button
          type="button"
          onClick={openBookmaker}
          aria-label={`Open ${bookmakerName} to place bet`}
          className={cn(
            "flex items-center justify-center gap-2 rounded-lg px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm font-medium transition-all active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 min-h-[44px]",
            premiumVisualsEnabled
              ? "bg-gradient-to-r from-cyan-500 to-indigo-600 text-white shadow-[0_8px_20px_rgba(0,212,255,0.3)] hover:scale-[1.02]"
              : "bg-emerald-600 text-white hover:bg-emerald-700",
          )}
        >
          <ExternalLink className="h-4 w-4" aria-hidden="true" />
          Place Bet
        </button>
      </div>

      {/* Marginal/avoid warning */}
      {(safe.qualityTier === "MARGINAL" || safe.qualityTier === "AVOID") && (
        <div className="mt-2.5 sm:mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 sm:p-3">
          <AlertCircle className="h-4 w-4 flex-shrink-0 text-amber-400" aria-hidden="true" />
          <p className="text-xs text-amber-300">
            {safe.qualityTier === "MARGINAL"
              ? "Edge is marginal. Consider waiting for better opportunities."
              : "Edge below threshold. Not recommended."}
          </p>
        </div>
      )}
    </div>
  );
}
