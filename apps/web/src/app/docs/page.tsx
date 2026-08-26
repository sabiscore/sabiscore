"use client";

import Link from 'next/link';
import { FeatureFlag, useFeatureFlag } from '@/lib/feature-flags';
import { cn } from '@/lib/utils';

export default function DocsPage() {
  const premiumVisualsEnabled = useFeatureFlag(FeatureFlag.PREMIUM_VISUAL_HIERARCHY);

  return (
    // No wrapper padding, min-h-screen, or background here: the root <main>
    // (app/layout.tsx) already supplies px-4 py-5 sm:px-6 lg:px-8 over the
    // shell's own background — same container-parity convention as
    // /performance and /monitoring.
    <div className="container mx-auto text-white">
        {/* Header */}
        <div className="mb-6 sm:mb-8">
          <Link
            href="/"
            className={cn(
              "inline-flex items-center mb-5 sm:mb-6 transition-colors",
              premiumVisualsEnabled
                ? "text-cyan-400 hover:text-cyan-300"
                : "text-indigo-400 hover:text-indigo-300"
            )}
          >
            ← Back to Home
          </Link>
          <div className="flex flex-wrap items-center gap-4">
            <h1 className={cn(
              "text-5xl font-bold mb-4",
              premiumVisualsEnabled && "bg-gradient-to-r from-cyan-400 to-indigo-400 bg-clip-text text-transparent"
            )}>
              Documentation
            </h1>
            {premiumVisualsEnabled && (
              <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-semibold uppercase text-slate-300">
                Premium Docs
              </span>
            )}
          </div>
          <p className="text-xl text-slate-400">
            Learn how to use Sabiscore to maximize your betting edge
          </p>
        </div>

        {/* Content Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 sm:gap-5">
          {/* Getting Started */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              Getting Started
            </h2>
            <ul className="space-y-3 text-slate-300">
              <li>• Create an account to access predictions</li>
              <li>• Review match predictions and value bets</li>
              <li>• Set up bankroll management</li>
              <li>• Track your betting performance</li>
            </ul>
          </div>

          {/* Key Metrics */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              Key Metrics
            </h2>
            <ul className="space-y-3 text-slate-300">
              <li>• <strong>Edge %</strong>: Your advantage over bookmaker odds</li>
              <li>• <strong>Confidence</strong>: Model certainty (0-100%)</li>
              <li>• <strong>Kelly</strong>: Recommended stake size</li>
              <li>• <strong>CLV</strong>: Closing Line Value tracking</li>
            </ul>
          </div>

          {/* Model Performance */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              Model Performance
            </h2>
            <ul className="space-y-3 text-slate-300">
              <li>• <strong>Pending</strong> live accuracy until sufficient labelled production results exist</li>
              <li>• <strong>RPS ≤ 0.21</strong> promotion threshold — live walk-forward validation pending</li>
              <li>• No public average-edge figure is shown before labelled live outcomes are available</li>
              <li>• CLV computed against closing-line implied probability only</li>
            </ul>
          </div>

          {/* Technical Stack */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              Technical Stack
            </h2>
            <ul className="space-y-3 text-slate-300">
              <li>• <strong>Models</strong>: certified Phase 7 artifacts for five calibrated leagues</li>
              <li>• <strong>Phase 8</strong>: candidate feature intelligence remains shadow-only</li>
              <li>• <strong>Data</strong>: 12,765 real completed matches across six leagues (2019–2026), temporally held out by season</li>
              <li>• <strong>Update</strong>: Evidence is fetched fresh per request; off-season notice when no fixtures</li>
            </ul>
          </div>

          {/* Sprint 4 What's New */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border md:col-span-2",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <div className="flex items-center gap-3 mb-4">
              <h2 className={cn(
                "text-2xl font-bold",
                premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
              )}>
                Sprint 4 — What&apos;s New
              </h2>
              <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-0.5 text-xs font-semibold text-emerald-300 uppercase tracking-wider">
                2026-06-11
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 text-slate-300 text-sm">
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 1 — BNN deployment safety</p>
                <p className="text-slate-400">Soft-loading wrapper splits torch implementation from the FastAPI boot path. Backend starts cleanly on Render without GPU wheels.</p>
              </div>
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 2 — canonical 89-feature retrain scaffold</p>
                <p className="text-slate-400">Auto-detects candidate feature availability for shadow evaluation. RPS ≤ 0.210 remains a promotion threshold pending live validation.</p>
              </div>
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 3 — Per-league calibration</p>
                <p className="text-slate-400">Isotonic (≥ 2 000 rows) or Platt scaling per league. Ensemble diversity diagnostics prune redundant base learners when draw-F1 is non-degrading.</p>
              </div>
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 4 — UCL stage coverage</p>
                <p className="text-slate-400"><code className="text-sky-400">competition_stage</code> field surfaced on every fixture — Group · R16 · QF · SF · Final — with colour-coded badges in the match list.</p>
              </div>
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 5 — CLV pre-match UX</p>
                <p className="text-slate-400">CLV label now carries a tooltip explaining it is computed at match end against the Pinnacle closing line. Drift Δ serves as the pre-match market intelligence proxy.</p>
              </div>
              <div className="space-y-1">
                <p className="font-semibold text-slate-200">Phase 6 — Interface polish</p>
                <p className="text-slate-400">Mobile hamburger nav, Upcoming Fixtures on the premium home page, Phase 8 panel de-duplicated header, off-season notice wired for both home states.</p>
              </div>
            </div>
          </div>

          {/* API Access */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border md:col-span-2",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              API Reference
            </h2>
            <div className="space-y-4 text-slate-300">
              <p>
                SabiScore exposes a versioned REST API. All routes are prefixed <code className="text-sky-400">/api/v1</code>.
              </p>
              <div className="bg-slate-900/50 rounded-lg p-4 font-mono text-sm space-y-3 overflow-x-auto">
                <div>
                  <div className="mb-1 text-green-400"># Upcoming matches with predictions + value bets</div>
                  <div>GET /api/v1/upcoming/matches?league=EPL&amp;days_ahead=7&amp;limit=20</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># All upcoming fixtures (merged, all leagues)</div>
                  <div>GET /api/v1/upcoming/all?days=7</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># Full match analysis (edge quality, CLV evidence, uncertainty)</div>
                  <div>GET /api/v1/matches/upcoming/:matchId/full-analysis?league=EPL</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># Phase 8 feature intelligence for a match</div>
                  <div>GET /api/v1/features/phase8?match_id=:id&amp;league=EPL</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># Team rolling form + H2H + upcoming fixtures</div>
                  <div>GET /api/v1/teams/:slug/intelligence</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># League off-season status &amp; next season start</div>
                  <div>GET /api/v1/leagues/:league/offseason-status</div>
                </div>
                <div>
                  <div className="mb-1 text-green-400"># Model health &amp; feature freshness</div>
                  <div>GET /api/v1/health/ready</div>
                </div>
              </div>
              <div className="text-sm text-slate-400 space-y-1.5">
                <p>
                  <strong className="text-slate-300">Key response fields:</strong>{" "}
                  <code className="text-sky-400">edge_quality_score</code> (0–1 composite),{" "}
                  <code className="text-sky-400">competition_stage</code> (UCL group/r16/qf/sf/final),{" "}
                  <code className="text-sky-400">clv_pct</code> (null pre-match; computed against closing odds at kick-off),{" "}
                  <code className="text-sky-400">closing_line_convergence_delta</code> (pre-match market drift proxy),{" "}
                  <code className="text-sky-400">data_gaps</code> (features defaulted due to missing live data),{" "}
                  <code className="text-sky-400">offseason</code> + <code className="text-sky-400">next_season_start</code> (off-season fixture state).
                </p>
                <p>
                  <strong className="text-slate-300">Data integrity guardrails:</strong>{" "}
                  <code className="text-sky-400">shot_quality_diff</code> is permanently DATA_GAP until StatsBomb ATE ≥ 0.02 is confirmed.
                  No synthetic data is injected to mask missing live inputs (Guardrail 1).
                  CLV is always computed against the <em>closing</em> implied probability, never the opening line (Guardrail 11).
                </p>
              </div>
            </div>
          </div>

          {/* Support */}
          <div className={cn(
            "rounded-xl p-5 sm:p-6 border md:col-span-2",
            premiumVisualsEnabled
              ? "glass-card border-white/10 bg-slate-950/70 shadow-[0_15px_45px_rgba(8,14,35,0.55)]"
              : "bg-slate-800/50 border-slate-700/50"
          )}>
            <h2 className={cn(
              "text-2xl font-bold mb-4",
              premiumVisualsEnabled ? "text-cyan-400" : "text-indigo-400"
            )}>
              Support & Resources
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <h3 className="font-semibold mb-2 text-slate-200">Community</h3>
                <p className="text-sm text-slate-400">
                  Join our Discord for tips, strategies, and support from fellow bettors.
                </p>
              </div>
              <div>
                <h3 className="font-semibold mb-2 text-slate-200">Updates</h3>
                <p className="text-sm text-slate-400">
                  Follow us on Twitter for model updates, performance reports, and feature releases.
                </p>
              </div>
              <div>
                <h3 className="font-semibold mb-2 text-slate-200">Contact</h3>
                <p className="text-sm text-slate-400">
                  Email support@sabiscore.com for technical issues or partnership inquiries.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* CTA */}
        <div className="mt-8 sm:mt-10 text-center">
          <Link
            href="/match"
            className={cn(
              "inline-block px-8 py-4 font-semibold rounded-xl transition-all duration-200 hover:scale-105",
              premiumVisualsEnabled
                ? "bg-gradient-to-r from-cyan-400 to-indigo-500 text-slate-950 shadow-[0_10px_30px_rgba(0,212,255,0.35)] hover:shadow-[0_15px_40px_rgba(0,212,255,0.5)]"
                : "bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-500/25 hover:shadow-indigo-500/40"
            )}
          >
            Start Using Sabiscore
          </Link>
        </div>
      </div>
  );
}


