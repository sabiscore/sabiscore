"use client";

import React from "react";
import { TrendingUp, AlertTriangle, ShieldCheck, Zap } from "lucide-react";
import type { PredictionResponse } from "@/types/prediction";

interface PredictionCardProps {
  prediction: PredictionResponse;
  oddsUnavailable?: boolean;
}

export function PredictionCard({
  prediction,
  oddsUnavailable = false,
}: PredictionCardProps) {
  const { home_team, away_team, probabilities, market, recommendation, telemetry } =
    prediction;

  // Format probabilities as percentages
  const homePct = Math.round(probabilities.home * 100);
  const drawPct = Math.round(probabilities.draw * 100);
  const awayPct = Math.max(0, 100 - homePct - drawPct); // Guarantee sum = 100%

  // Staking logic checks
  const hasLiveOdds = !oddsUnavailable && (market.odds_available !== false) && market.home_odds > 1.0;
  const isActionable =
    hasLiveOdds &&
    recommendation.action === "ACTIONABLE" &&
    recommendation.kelly_fraction > 0.0 &&
    recommendation.edge >= 0.042;

  const kellyPct = (recommendation.kelly_fraction * 100).toFixed(1);
  const bestBetLabel =
    recommendation.best_bet === "home"
      ? `${home_team} (Home)`
      : recommendation.best_bet === "away"
        ? `${away_team} (Away)`
        : recommendation.best_bet === "draw"
          ? "Draw"
          : "None";

  // Attacking form momentum
  const deltaXg = telemetry.delta_rolling_xg;
  const isPositiveHomeMomentum = deltaXg > 0;

  return (
    <article
      data-testid="prediction-card"
      className="w-full rounded-2xl border border-[#2A2A2E] bg-[#1B1B1D] p-5 shadow-2xl transition-all"
      aria-label={`Match prediction for ${home_team} vs ${away_team}`}
    >
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-[#2A2A2E] pb-4 gap-2">
        <div>
          <span className="inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#00F0FF]">
            <Zap className="h-3 w-3 text-[#00F0FF]" aria-hidden="true" />
            AI Stacked Match Intelligence
          </span>
          <h2 className="font-heading text-lg sm:text-xl font-bold text-white tracking-tight">
            {home_team} <span className="text-slate-500 font-normal">vs</span> {away_team}
          </h2>
        </div>

        <div className="flex items-center gap-2">
          {telemetry.source === "redis_cache" ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-400">
              <ShieldCheck className="h-3 w-3" />
              Verified Telemetry
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-800/60 px-2.5 py-0.5 text-[10px] font-semibold text-slate-300">
              Fast-Path Inference
            </span>
          )}
        </div>
      </div>

      {/* 1. Win Probabilities Progress Bar */}
      <section className="mt-5 space-y-2" aria-labelledby="prob-heading">
        <div className="flex items-center justify-between text-xs">
          <span id="prob-heading" className="font-heading font-semibold text-white">
            Win Probability Distribution
          </span>
          {/* Consumer English Headline */}
          <span
            data-testid="translated-probabilities"
            className="font-mono text-xs font-semibold text-slate-200"
          >
            Home: {homePct}% | Draw: {drawPct}% | Away: {awayPct}%
          </span>
        </div>

        {/* Multi-Segment Visual Progress Bar */}
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={homePct}
          aria-label={`Win probabilities: ${home_team} ${homePct}%, Draw ${drawPct}%, ${away_team} ${awayPct}%`}
          className="relative flex h-3.5 w-full overflow-hidden rounded-full bg-[#0E0E10] border border-[#2A2A2E] p-0.5"
        >
          <div
            style={{ width: `${homePct}%` }}
            title={`Home Win: ${homePct}%`}
            className="h-full rounded-l-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-500"
          />
          <div
            style={{ width: `${drawPct}%` }}
            title={`Draw: ${drawPct}%`}
            className="h-full bg-slate-600 transition-all duration-500"
          />
          <div
            style={{ width: `${awayPct}%` }}
            title={`Away Win: ${awayPct}%`}
            className="h-full rounded-r-full bg-gradient-to-r from-cyan-400 to-teal-400 transition-all duration-500"
          />
        </div>
        <div className="flex justify-between text-[11px] text-slate-400 font-mono pt-0.5">
          <span>{home_team} ({homePct}%)</span>
          <span>Draw ({drawPct}%)</span>
          <span>{away_team} ({awayPct}%)</span>
        </div>
      </section>

      {/* Graceful Degradation Alert if Live Odds Fail */}
      {!hasLiveOdds && (
        <div
          data-testid="odds-unavailable-banner"
          className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200 flex items-center gap-2"
        >
          <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0" />
          <span>Live odds unavailable. Staking recommendations paused.</span>
        </div>
      )}

      {/* 2. Actionable Staking (Kelly) Section */}
      <section className="mt-4" aria-labelledby="staking-heading">
        {isActionable ? (
          <div
            data-testid="recommendation-actionable"
            className="rounded-xl border border-[#00FF66]/40 bg-[#00FF66]/10 p-4 shadow-[0_0_20px_rgba(0,255,102,0.1)] transition-all"
          >
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#00FF66]">
                  Verified Mathematical Edge
                </span>
                <p className="font-heading text-base sm:text-lg font-bold text-white mt-0.5">
                  Actionable Edge: Bet <span className="font-mono text-[#00FF66]">{kellyPct}%</span> of your bankroll.
                </p>
                <p className="text-xs text-slate-300 mt-1">
                  Recommended Selection: <strong className="text-white">{bestBetLabel}</strong>
                  {recommendation.stake_capped && (
                    <span className="ml-2 text-[10px] text-slate-400">(Quarter-Kelly hard cap enforced at 5%)</span>
                  )}
                </p>
              </div>

              <div className="text-left sm:text-right font-mono text-xs text-slate-300">
                <p>
                  Edge: <span className="text-[#00FF66] font-bold">+{(recommendation.edge * 100).toFixed(1)}%</span>
                </p>
                <p>
                  EV: <span className="text-white font-bold">+{(recommendation.expected_value * 100).toFixed(1)}%</span>
                </p>
              </div>
            </div>
          </div>
        ) : (
          <div
            data-testid="recommendation-muted"
            className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-4 text-slate-400 transition-all"
          >
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <div>
                <p className="font-heading text-sm sm:text-base font-bold text-slate-300">
                  No Value: Skip this match.
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  Bookmaker odds match or exceed model projection. Zero edge detected; model abstains from staking.
                </p>
              </div>
              <div className="font-mono text-xs text-slate-400 text-left sm:text-right">
                <span>Safe Abstention</span>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 3. Expected Goals (xG) Momentum */}
      <section className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3" aria-labelledby="xg-heading">
        <div className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-3.5">
          <p id="xg-heading" className="text-xs font-semibold text-slate-300">
            Recent Attacking Form (Last 5 Matches)
          </p>
          <div className="mt-2 flex items-center justify-between">
            <div className="font-mono text-sm text-slate-200">
              <span className="text-slate-400 text-xs">{home_team}:</span> {telemetry.rolling_xg_home.toFixed(2)} xG
            </div>
            <div className="font-mono text-sm text-slate-200">
              <span className="text-slate-400 text-xs">{away_team}:</span> {telemetry.rolling_xg_away.toFixed(2)} xG
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-3.5 flex flex-col justify-between">
          <p className="text-xs font-semibold text-slate-300">Form Momentum Trend</p>
          <div className="mt-2 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-[#00F0FF] shrink-0" aria-hidden="true" />
            <span
              data-testid="xg-trend-indicator"
              className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-xs font-bold text-[#00F0FF] bg-[#00F0FF]/10 border border-[#00F0FF]/30"
            >
              {isPositiveHomeMomentum ? `▲ +${deltaXg.toFixed(2)}` : `▼ ${deltaXg.toFixed(2)}`} xG momentum
            </span>
            <span className="text-[10px] text-slate-400">
              ({isPositiveHomeMomentum ? `${home_team} attacking edge` : `${away_team} attacking edge`})
            </span>
          </div>
        </div>
      </section>
    </article>
  );
}
