"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Database,
  Filter,
  Microscope,
  Settings2,
  ShieldCheck,
  Target,
  TrendingUp,
  WalletCards,
  Zap,
} from "lucide-react";
import { BestBetSpotlight } from "@/components/best-bet-spotlight";
import { MatchSelector } from "@/components/match-selector";
import { ModelMetadataPanel } from "@/components/model-metadata-panel";
import { MobilePlatformSummary } from "@/components/mobile-platform-summary";
import { PlatformHealthPills } from "@/components/platform-health-pills";
import { ResearchModeBanner } from "@/components/research-mode-banner";
import { UpcomingMatchesPanel } from "@/components/upcoming-matches-panel";
import { FeatureFlag, useFeatureFlag } from "@/lib/feature-flags";
import { VERDICT_TOKENS, type Verdict } from "@/lib/verdict-tokens";

const TRUST_BADGES = ["Verified fixtures first", "Explicit evidence gaps", "Zero stake when blocked"];

const PREMIUM_VALUE_STREAM = [
  {
    title: "Edge telemetry",
    description: "Evidence checks across configured providers with automatic fallbacks and DATA_GAP surfacing.",
    icon: BarChart3,
    footer: "Fail-closed evidence checks",
  },
  {
    title: "Phase 8 candidate enrichment",
    description: "Candidate feature vector remains shadow-only pending model validation and promotion evidence.",
    icon: Microscope,
    footer: "Shadow evaluation only",
  },
  {
    title: "CLV + Kelly toolkit",
    description: "Closing-line value and edge-quality research with a fail-closed staking gate.",
    icon: Target,
    footer: "Fail-closed stake gate",
  },
] satisfies Array<{ title: string; description: string; icon: LucideIcon; footer: string }>;

const PREMIUM_PILLARS = [
  {
    title: "Data integrity",
    detail: "Configured providers reconciled with explicit gaps and provenance",
    icon: ShieldCheck,
  },
  {
    title: "Model governance",
    detail: "Artifact and validation status appear only when backend metadata confirms them",
    icon: Settings2,
  },
  {
    title: "Value creation",
    detail: "Quarter-Kelly and CLV tooling remains gated by verified evidence",
    icon: WalletCards,
  },
] satisfies Array<{ title: string; detail: string; icon: LucideIcon }>;

const LEGACY_FEATURES = [
  {
    title: "Phase 8 Candidate Enrichment",
    description: "Candidate feature intelligence is available for shadow evaluation only and is not active in production verdicts.",
    icon: Database,
  },
  {
    title: "CLV + Edge Quality",
    description: "Edge quality scored 0-1 per fixture. Closing-line value computed at kick-off. Fractional Kelly + RL abstention gate on every bet.",
    icon: Target,
  },
  {
    title: "Promotion-Gated Validation",
    description: "RPS ≤ 0.21 remains the promotion threshold; live walk-forward evidence is still pending.",
    icon: CheckCircle2,
  },
] satisfies Array<{ title: string; description: string; icon: LucideIcon }>;

// Pipeline steps for the "How it works" section
const PIPELINE_STEPS = [
  {
    step: "01",
    label: "Collect evidence",
    detail: "Configured sources are queried for fixtures, lineups, injuries, odds, and standings when available.",
    icon: Database,
  },
  {
    step: "02",
    label: "Validate & reconcile",
    detail: "Fixture identity resolved across providers. Conflicts surfaced explicitly — never silently merged.",
    icon: ShieldCheck,
  },
  {
    step: "03",
    label: "Run the active model",
    detail: "The backend reports the served artifact, feature schema, and calibration state; missing certification stays unavailable.",
    icon: Filter,
  },
  {
    step: "04",
    label: "Compare to market",
    detail: "Fair market probabilities de-vigged from bookmaker odds. Edge = model probability minus fair market probability.",
    icon: TrendingUp,
  },
  {
    step: "05",
    label: "Surface the result",
    detail: "Six evidence-gated verdict levels with a plain-English rationale and explicit data-gap report.",
    icon: Zap,
  },
] satisfies Array<{ step: string; label: string; detail: string; icon: LucideIcon }>;

// Verdict definitions
const VERDICT_DEFINITIONS = [
  {
    enum: "PARTIAL",
    label: "Incomplete Data",
    detail: "Critical evidence is missing. No bet is surfaced.",
  },
  {
    enum: "NO_BET",
    label: "Skip This Match",
    detail: "Data is complete but no positive edge was found.",
  },
  {
    enum: "HOLD",
    label: "Monitor Closely",
    detail: "Positive signal detected but evidence is thin. Watch for updates.",
  },
  {
    enum: "SPECULATIVE",
    label: "Watchlist Only",
    detail: "A tentative signal is visible for research. No stake is permitted.",
  },
  {
    enum: "ACTIONABLE",
    label: "Certification-Gated Signal",
    detail: "This verdict can become executable only when every evidence and certification gate is open.",
  },
  {
    enum: "HIGH_CONVICTION",
    label: "Certification-Gated Strong Signal",
    detail: "Independent evidence may be strong, but uncertified generations remain research-only.",
  },
] satisfies Array<{
  enum: string;
  label: string;
  detail: string;
}>;

// Supported competitions
const COMPETITIONS = [
  { name: "Premier League", short: "EPL" },
  { name: "La Liga", short: "ESP" },
  { name: "Bundesliga", short: "GER" },
  { name: "Serie A", short: "ITA" },
  { name: "Ligue 1", short: "FRA" },
  { name: "Eredivisie", short: "NED" },
  { name: "Champions League", short: "UCL" },
] satisfies Array<{ name: string; short: string }>;

export default function HomePage() {
  const premiumEnabled = useFeatureFlag(FeatureFlag.PREMIUM_VISUAL_HIERARCHY);

  return (
    // No wrapper padding, min-h-screen, or background here: the root <main>
    // (app/layout.tsx) already supplies px-2.5 py-2.5 sm:px-4 sm:py-3 over the
    // shell's own background, and is the page's sole <main> landmark — same
    // container-parity convention as /performance and /monitoring.
    <>
      <div className="container mx-auto">
        <div className="mx-auto max-w-6xl space-y-2.5 sm:space-y-3">
          <ResearchModeBanner />
          {premiumEnabled ? <PremiumHome /> : <LegacyHome />}
        </div>
      </div>

      {/* Responsible gambling — shown on every layout */}
      <aside className="container mx-auto mb-3 mt-2 max-w-6xl">
        <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3.5 py-2 text-xs text-amber-200/80">
          <strong className="text-amber-300">Responsible use:</strong>{" "}
          Staking is disabled while this generation remains uncertified. No prediction is certain.
          If gambling is affecting you or someone you know, seek support at{" "}
          <a
            href="https://www.begambleaware.org"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-amber-100"
          >
            BeGambleAware.org
          </a>.
        </div>
      </aside>

      <footer className="border-t border-slate-800/50 py-3.5">
        <div className="container mx-auto text-center text-slate-400">
          <p className="text-xs font-medium sm:text-sm">SabiScore production intelligence workspace</p>
          <p className="mt-0.5 text-[11px]">Built for responsible football research and advanced analytics</p>
        </div>
      </footer>
    </>
  );
}

function PremiumHome() {
  return (
    <>
      <section id="verified-fixtures" className="scroll-mt-28 rounded-2xl border border-cyan-400/20 bg-slate-950/80 p-2.5 sm:p-3.5">
        <div className="px-1 pb-1.5 sm:px-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-400">Primary workflow</p>
          <h1 className="mt-0.5 text-lg font-bold text-white sm:text-xl">Upcoming verified fixtures</h1>
          <p className="mt-0.5 max-w-3xl text-xs leading-normal text-slate-400">
            Start from a scheduled fixture with a stable identity. Forecast and market availability remain explicit for every match.
          </p>
        </div>
        <UpcomingMatchesPanel title="Verified fixtures" />
      </section>

      {/* Hero */}
      <section className="relative overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 p-3.5 text-left shadow-[0_20px_50px_rgba(2,6,23,0.5)] sm:px-5 sm:py-4">
        <div className="relative grid items-center gap-3 lg:grid-cols-[1.2fr,0.8fr] lg:gap-4">
          <div className="space-y-2.5 sm:space-y-3">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-white/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-100">
              <Activity size={11} aria-hidden="true" />
              Evidence-first intelligence
            </span>
            <h1 className="max-w-3xl text-xl font-black leading-tight text-white sm:text-2xl md:text-3xl">
              Edge-first football intelligence for analysts
            </h1>
            <p className="max-w-2xl text-xs leading-relaxed text-slate-300">
              Model forecasts, market context, and bankroll-aware decision support appear only
              when the backend confirms the required evidence.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {TRUST_BADGES.map((badge) => (
                <span
                  key={badge}
                  className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-slate-900/70 px-2.5 py-0.5 text-[11px] text-slate-200"
                >
                  {badge}
                </span>
              ))}
            </div>
            <div className="flex flex-wrap gap-2.5 pt-0.5">
              <Link
                href="#verified-fixtures"
                className="inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-cyan-400 to-indigo-500 px-4 py-2 text-xs font-semibold text-slate-950 shadow-[0_8px_25px_rgba(0,212,255,0.25)] motion-safe:transition motion-safe:hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-cyan-200"
              >
                Back to verified fixtures
              </Link>
              <Link
                href="/docs"
                className="inline-flex items-center justify-center rounded-xl border border-white/20 px-4 py-2 text-xs font-semibold text-white transition hover:border-white/40 focus:outline-none focus:ring-2 focus:ring-slate-300"
              >
                Explore Docs
              </Link>
            </div>
          </div>

          <div className="lg:hidden">
            <MobilePlatformSummary />
          </div>

          <div className="hidden flex-col gap-2 rounded-xl border border-white/10 bg-slate-950/70 p-3 shadow-[0_15px_40px_rgba(3,7,18,0.7)] sm:p-3.5 lg:flex">
            <div>
              <p className="text-[10px] uppercase tracking-[0.24em] text-slate-300">Model pulse</p>
              <div className="mt-1.5"><ModelMetadataPanel /></div>
            </div>

            <div className="rounded-xl border border-white/5 bg-slate-900/60 px-2.5 py-1.5">
              <p className="mb-1.5 text-[9px] uppercase tracking-[0.2em] text-slate-300">
                Platform status
              </p>
              <div className="grid gap-1.5 sm:grid-cols-3">
                <PlatformHealthPills />
              </div>
            </div>

            <div className="space-y-1">
              {PREMIUM_PILLARS.map((pillar) => (
                <div key={pillar.title} className="flex items-center justify-between rounded-xl border border-white/5 bg-slate-900/60 px-2.5 py-1.5">
                  <div className="flex items-center gap-2">
                    <pillar.icon className="h-3.5 w-3.5 text-cyan-300 shrink-0" aria-hidden="true" />
                    <div>
                      <p className="text-xs font-semibold text-white">{pillar.title}</p>
                      <p className="text-[10px] text-slate-400">{pillar.detail}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Manual matchups remain an explicit non-executable compatibility path. */}
      <section id="match-generator" className="scroll-mt-32">
        <details className="group rounded-2xl border border-amber-500/20 bg-slate-950/80 p-2.5 sm:p-3">
          <summary className="flex min-h-9 cursor-pointer items-center justify-between rounded-xl px-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-300">
            <span>
              <span className="block text-[10px] font-semibold uppercase tracking-[0.24em] text-amber-300">Hypothetical — non-executable</span>
              <span className="mt-0.5 block text-sm font-bold text-white sm:text-base">Explore a manual matchup</span>
            </span>
            <span aria-hidden="true" className="text-slate-400 transition group-open:rotate-180">⌄</span>
          </summary>
          <div className="pt-2">
            <MatchSelector />
          </div>
        </details>
      </section>

      {/* Spotlight + value stream */}
      <section className="grid items-start gap-3 lg:grid-cols-[1fr,1fr]">
        <BestBetSpotlight />
        <div className="grid gap-2">
          {PREMIUM_VALUE_STREAM.map((card) => (
            <div key={card.title} className="glass-card flex flex-col justify-between gap-1.5 p-3 sm:p-3.5">
              <div className="flex items-center gap-2 text-slate-200">
                <card.icon className="h-4 w-4 text-cyan-300" aria-hidden="true" />
                <h2 className="text-xs font-semibold text-white sm:text-sm">{card.title}</h2>
              </div>
              <p className="text-xs text-slate-400 leading-normal">{card.description}</p>
              <span className="text-[9px] uppercase tracking-[0.2em] text-slate-300">{card.footer}</span>
            </div>
          ))}
        </div>
      </section>

      {/* How SabiScore works */}
      <section className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 sm:p-4">
        <h2 className="mb-0.5 text-base font-bold text-white sm:text-lg">How SabiScore works</h2>
        <p className="mb-2.5 text-xs text-slate-400">Five evidence-gated steps from raw data to an explained verdict.</p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {PIPELINE_STEPS.map((s) => (
            <div key={s.step} className="flex flex-col gap-1.5 rounded-xl border border-white/5 bg-slate-900/60 p-2.5">
              <div className="flex items-center gap-1.5">
                <span className="text-[9px] font-bold tracking-widest text-slate-300">{s.step}</span>
                <s.icon className="h-3.5 w-3.5 text-cyan-400" aria-hidden="true" />
              </div>
              <p className="text-xs font-semibold text-white">{s.label}</p>
              <details className="mt-0.5">
                <summary className="cursor-pointer text-[10px] text-slate-300 hover:text-slate-100">Technical detail ▸</summary>
                <p className="mt-1 text-[10px] leading-normal text-slate-400">{s.detail}</p>
              </details>
            </div>
          ))}
        </div>
      </section>

      {/* Verdict education */}
      <section className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 sm:p-4">
        <h2 className="mb-0.5 text-base font-bold text-white sm:text-lg">Understanding verdicts</h2>
        <p className="mb-2.5 text-xs text-slate-400">
          Each verdict is an evidence gate, not a confidence dial. Stronger labels require more independent sources.
        </p>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {VERDICT_DEFINITIONS.map((v) => (
            <div
              key={v.enum}
              className={`rounded-xl border p-2.5 ${VERDICT_TOKENS[v.enum as Verdict].border} ${VERDICT_TOKENS[v.enum as Verdict].bg}`}
            >
              <div className="mb-1 flex items-center gap-2">
                <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider ${VERDICT_TOKENS[v.enum as Verdict].color}`}>
                  {v.enum}
                </span>
              </div>
              <p className="text-xs font-semibold text-white">{v.label}</p>
              <p className="mt-0.5 text-[10px] leading-normal text-slate-400">{v.detail}</p>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[10px] text-slate-300">
          No verdict is a certain outcome. Stronger evidence reduces uncertainty — it does not eliminate it.
        </p>
      </section>

      {/* Supported competitions */}
      <section className="rounded-2xl border border-white/10 bg-slate-950/60 p-3 sm:p-4">
        <h2 className="mb-0.5 text-base font-bold text-white sm:text-lg">Supported competitions</h2>
        <p className="mb-2 text-xs text-slate-400">
          Listed coverage is subject to the active artifact and league policy reported by the backend.
        </p>
        <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
          {COMPETITIONS.map((c) => (
            <div key={c.short} className="flex items-center justify-between rounded-xl border border-white/5 bg-slate-900/60 px-2.5 py-1.5">
              <div>
                <p className="text-xs font-semibold text-white">{c.name}</p>
                <p className="text-[10px] text-slate-300">{c.short}</p>
              </div>
            </div>
          ))}
        </div>
      </section>


    </>
  );
}

function LegacyHome() {
  return (
    <>
      <section className="space-y-6 text-center animate-fade-in">
        <div className="inline-block rounded-full border border-indigo-500/20 bg-indigo-500/10 px-4 py-2">
          <span className="text-sm font-semibold text-indigo-400">
            Evidence-gated analysis | Explicit availability | Zero-fabrication
          </span>
        </div>
        <h1 className="bg-gradient-to-r from-slate-100 via-indigo-200 to-purple-200 bg-clip-text text-5xl font-bold leading-tight text-transparent md:text-7xl">
          Edge-First Football
          <br />
          Intelligence Platform
        </h1>
        <p className="mx-auto max-w-3xl text-xl leading-relaxed text-slate-400">
          Verified fixtures and backend-reported model evidence.{" "}
          <span className="font-semibold text-indigo-400">Every stake gate fails closed</span> when evidence is incomplete.
        </p>
        <div className="flex items-center justify-center gap-4 pt-4">
          <Link
            href="/intelligence"
            className="rounded-xl bg-indigo-600 px-8 py-4 font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all duration-200 hover:scale-105 hover:bg-indigo-500 hover:shadow-indigo-500/40 focus:outline-none focus:ring-2 focus:ring-indigo-200"
          >
            Review verified fixtures
          </Link>
          <Link
            href="/docs"
            className="rounded-xl border border-slate-700/50 bg-slate-800/50 px-8 py-4 font-semibold text-slate-200 transition-all duration-200 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-300"
          >
            View Docs
          </Link>
        </div>
      </section>

      <section className="animate-fade-in">
        <ModelMetadataPanel />
      </section>

      <section className="animate-fade-in">
        <UpcomingMatchesPanel title="Verified Fixtures" />
      </section>

      <section className="animate-fade-in">
        <details className="rounded-2xl border border-amber-500/20 p-4">
          <summary className="flex min-h-11 cursor-pointer items-center text-amber-200">Hypothetical matchup — non-executable</summary>
          <div className="pt-4"><MatchSelector /></div>
        </details>
      </section>

      <section className="grid grid-cols-1 gap-8 md:grid-cols-3 animate-fade-in">
        {LEGACY_FEATURES.map((feature) => (
          <div key={feature.title} className="glass-card space-y-4 p-8 transition-colors hover:bg-slate-900/60 group">
            <feature.icon className="h-8 w-8 text-indigo-300 transition-transform group-hover:scale-110" aria-hidden="true" />
            <h3 className="text-xl font-bold text-slate-100">{feature.title}</h3>
            <p className="leading-relaxed text-slate-400">{feature.description}</p>
          </div>
        ))}
      </section>
    </>
  );
}
