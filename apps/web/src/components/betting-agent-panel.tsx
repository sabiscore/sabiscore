"use client";

import { memo } from "react";
import type { RLRecommendation } from "@/lib/api";
import { cn } from "@/lib/utils";

interface BettingAgentPanelProps {
  recommendation?: RLRecommendation | null;
  premiumVisuals?: boolean;
  stakePermitted?: boolean;
  researchMode?: boolean;
}

const MAX_KELLY_CAP = 0.05; // mirrors settings.rl_max_kelly_cap

const toPct = (value: number, digits = 1) =>
  `${(Math.max(0, value) * 100).toFixed(digits)}%`;

// ── Semi-circular gauge ──────────────────────────────────────────────────────

interface StakeGaugeProps {
  fraction: number;
  abstain: boolean;
}

function StakeGauge({ fraction, abstain }: StakeGaugeProps) {
  const pct = Math.min(1, Math.max(0, fraction) / MAX_KELLY_CAP);
  const RADIUS = 38;
  const CIRCUMFERENCE = Math.PI * RADIUS; // half-circle
  const strokeOffset = CIRCUMFERENCE * (1 - pct);

  const color = abstain
    ? "#f59e0b"           // amber  — abstain
    : pct >= 0.75
    ? "#f87171"           // rose   — aggressive
    : pct >= 0.40
    ? "#34d399"           // emerald— healthy
    : "#22d3ee";          // cyan   — conservative

  return (
    <svg
      viewBox="0 0 92 54"
      className="w-full max-w-[130px] mx-auto"
      aria-label={`Stake gauge: ${abstain ? "abstain" : toPct(fraction, 2)}`}
      role="img"
    >
      {/* Track */}
      <path
        d="M9,46 A38,38 0 0,1 83,46"
        fill="none"
        stroke="#1e293b"
        strokeWidth="9"
        strokeLinecap="round"
      />
      {/* Fill */}
      <path
        d="M9,46 A38,38 0 0,1 83,46"
        fill="none"
        stroke={color}
        strokeWidth="9"
        strokeLinecap="round"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={strokeOffset}
        style={{ transition: "stroke-dashoffset 0.7s ease, stroke 0.3s ease" }}
      />
      {/* Label */}
      <text
        x="46"
        y="44"
        textAnchor="middle"
        fontSize="12"
        fill={color}
        fontWeight="700"
        fontFamily="ui-monospace, monospace"
      >
        {abstain ? "—" : toPct(fraction, 2)}
      </text>
    </svg>
  );
}

// ── Reward component row ─────────────────────────────────────────────────────

function RewardRow({ label, value }: { label: string; value: number }) {
  const isPos = value >= 0;
  const barPct = `${Math.min(100, Math.abs(value) * 200).toFixed(1)}%`;
  return (
    <div className="flex items-center gap-2.5 text-xs" aria-label={`${label}: ${value.toFixed(4)}`}>
      <span className="w-14 text-slate-400 flex-shrink-0 font-mono">{label}</span>
      <div className="flex-1 h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full motion-safe:transition-all motion-safe:duration-700",
            isPos ? "bg-emerald-500" : "bg-rose-500"
          )}
          style={{ width: barPct }}
        />
      </div>
      <span
        className={cn(
          "w-16 text-right tabular-nums font-semibold",
          isPos ? "text-emerald-300" : "text-rose-300"
        )}
      >
        {isPos ? "+" : ""}{value.toFixed(4)}
      </span>
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

const REWARD_WEIGHTS: Record<string, number> = {
  R_pnl: 0.40,
  R_ic: 0.25,
  R_cal: 0.15,
  R_risk: 0.15,
  R_abs: 0.05,
};

const REWARD_LABELS: Record<string, string> = {
  R_pnl: "P&L",
  R_ic: "IC",
  R_cal: "Cal",
  R_risk: "Risk",
  R_abs: "Abs",
};

function BettingAgentPanelInner({
  recommendation,
  premiumVisuals = false,
  stakePermitted = false,
  researchMode = true,
}: BettingAgentPanelProps) {
  if (!recommendation) return null;

  const { stake_fraction, abstain, reward_components, reason } = recommendation;
  const isStakingAllowed = stakePermitted === true && !researchMode && !abstain;
  const isStakeBlocked = !isStakingAllowed;

  const components = Object.entries(reward_components ?? {});
  const weightedTotal = components.reduce((acc, [key, val]) => {
    const w = REWARD_WEIGHTS[key] ?? 0;
    return acc + w * val;
  }, 0);

  const decisionPill = !isStakingAllowed
    ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
    : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";

  const decisionBadgeText = abstain
    ? "⚠ Abstain"
    : !isStakingAllowed
    ? "⚠ Staking Disabled"
    : "✓ Active Stake";

  const decisionLabel = abstain
    ? "No Bet"
    : !isStakingAllowed
    ? "Disabled"
    : "Place Bet";

  const stakeFractionLabel = !isStakingAllowed
    ? (abstain ? "—" : "Disabled")
    : toPct(stake_fraction, 2);

  const gaugeCaption = abstain
    ? "No bet recommended"
    : !isStakingAllowed
    ? "Staking disabled in research mode"
    : `of ${toPct(MAX_KELLY_CAP)} Kelly cap`;

  return (
    <section
      aria-label="RL betting agent recommendation"
      className={cn(
        "glass-card p-8 space-y-6 border",
        premiumVisuals
          ? "border-emerald-500/20 bg-slate-950/70 shadow-[0_15px_45px_rgba(16,185,129,0.12)]"
          : "border-emerald-500/20"
      )}
    >
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className={cn(
          "text-2xl font-bold flex items-center gap-2.5",
          premiumVisuals ? "text-emerald-400" : "text-slate-100"
        )}>
          <svg className="w-6 h-6 text-emerald-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.75}
              d="M12 8c-1.657 0-3 1.12-3 2.5S10.343 13 12 13s3 1.12 3 2.5S13.657 18 12 18m0-10V6m0 12v-2m8-4a8 8 0 11-16 0 8 8 0 0116 0z" />
          </svg>
          RL Betting Agent
        </h2>
        <span className={cn("text-xs px-2.5 py-1 rounded-full border font-semibold", decisionPill)}>
          {decisionBadgeText}
        </span>
      </div>

      {/* Gauge + stake summary */}
      <div className="flex items-center gap-6">
        <div className="flex-shrink-0 w-[130px]">
          <StakeGauge fraction={isStakingAllowed ? stake_fraction : 0} abstain={isStakeBlocked} />
          <p className="text-xs text-slate-500 text-center mt-1.5">
            {gaugeCaption}
          </p>
        </div>
        <div className="flex-1 space-y-3 text-sm">
          <div className="flex justify-between items-center">
            <span className="text-slate-400">Stake fraction</span>
            <span className={cn("font-bold tabular-nums text-base", isStakingAllowed ? "text-emerald-300" : "text-slate-400")}>
              {stakeFractionLabel}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-400">Decision</span>
            <span className={cn("font-semibold", !isStakingAllowed ? "text-amber-300" : "text-emerald-300")}>
              {decisionLabel}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-400">Kelly cap</span>
            <span className="text-slate-300 tabular-nums">{toPct(MAX_KELLY_CAP)}</span>
          </div>
          {isStakingAllowed && (
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Weighted reward</span>
              <span className={cn(
                "font-semibold tabular-nums",
                weightedTotal >= 0 ? "text-emerald-300" : "text-rose-300"
              )}>
                {weightedTotal >= 0 ? "+" : ""}{weightedTotal.toFixed(4)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Reward component breakdown */}
      {components.length > 0 && isStakingAllowed && (
        <div className="rounded-xl bg-slate-900/50 p-5 border border-slate-800/60 space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-500 uppercase tracking-wider font-medium">
              Reward Components (C14 · Σw = 1.0)
            </p>
            <span className="text-[10px] text-slate-600 font-mono">
              w: pnl=.40 ic=.25 cal=.15 risk=.15 abs=.05
            </span>
          </div>
          {components.map(([key, value]) => (
            <RewardRow
              key={key}
              label={REWARD_LABELS[key] ?? key}
              value={value}
            />
          ))}
        </div>
      )}

      {/* Reason string */}
      {reason && (
        <div className="rounded-xl bg-slate-900/50 p-4 border border-slate-800/50">
          <p className="text-xs text-slate-500 font-medium uppercase tracking-wider mb-1.5">
            Agent reasoning
          </p>
          <p className="text-xs text-slate-400 leading-relaxed font-mono break-words">{reason}</p>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-[10px] text-slate-600 leading-relaxed border-t border-slate-800/50 pt-3">
        Advisory only — research mode active. This recommendation does not place bets and staking controls are disabled. Kelly-fraction fallback is
        active when no trained SAC model is present at{" "}
        <code className="text-slate-500">settings.rl_agent_path</code>.
      </p>
    </section>
  );
}

export const BettingAgentPanel = memo(BettingAgentPanelInner);
