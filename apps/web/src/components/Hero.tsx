import React from "react";
import Image from "next/image";
import Link from "next/link";
import { Activity, ShieldCheck, Settings2, WalletCards } from "lucide-react";
import { ModelMetadataPanel } from "@/components/model-metadata-panel";
import { PlatformHealthPills } from "@/components/platform-health-pills";
import { MobilePlatformSummary } from "@/components/mobile-platform-summary";

const TRUST_BADGES = [
  "Verified fixtures first",
  "Explicit evidence gaps",
  "Zero stake when blocked",
];

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
];

export function Hero() {
  return (
    <section
      data-testid="hero-section"
      className="relative overflow-hidden rounded-2xl border border-[#2A2A2E] bg-[#1B1B1D] p-4 text-left shadow-[0_20px_50px_rgba(0,0,0,0.8)] sm:px-6 sm:py-5"
    >
      <div className="relative grid items-center gap-4 lg:grid-cols-[1.2fr,0.8fr] lg:gap-6">
        <div className="space-y-3 sm:space-y-4">
          <div className="flex items-center gap-2">
            {/* LCP element with explicit priority attribute */}
            <Image
              src="/icon.svg"
              alt="SabiScore Emblem"
              width={28}
              height={28}
              priority
              className="h-7 w-7 rounded-lg"
            />
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[#00F0FF]/30 bg-[#00F0FF]/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.2em] text-[#00F0FF]">
              <Activity size={11} aria-hidden="true" />
              Evidence-First Football Intelligence
            </span>
          </div>

          <h2 className="font-heading max-w-3xl text-2xl font-black leading-tight text-white sm:text-3xl md:text-4xl tracking-tight">
            Edge-First Predictive Modeling & Live Football Intelligence
          </h2>

          <p className="max-w-2xl text-xs sm:text-sm leading-relaxed text-slate-300">
            Calibrated ensemble predictions, live odds comparison, and bankroll-aware
            Quarter-Kelly decision support appear only when verified evidence is confirmed.
          </p>

          <div className="flex flex-wrap gap-1.5">
            {TRUST_BADGES.map((badge) => (
              <span
                key={badge}
                className="inline-flex items-center gap-1 rounded-lg border border-[#2A2A2E] bg-[#0E0E10] px-2.5 py-1 text-[11px] font-mono text-slate-200"
              >
                {badge}
              </span>
            ))}
          </div>

          <div className="flex flex-wrap gap-2.5 pt-1">
            <Link
              href="#verified-fixtures"
              className="inline-flex items-center justify-center rounded-xl bg-gradient-to-r from-[#00F0FF] to-blue-500 px-5 py-2.5 text-xs font-bold text-slate-950 shadow-[0_8px_25px_rgba(0,240,255,0.25)] motion-safe:transition motion-safe:hover:scale-[1.02] focus:outline-none focus:ring-2 focus:ring-[#00F0FF]"
            >
              Explore Verified Fixtures
            </Link>
            <Link
              href="/docs"
              className="inline-flex items-center justify-center rounded-xl border border-[#2A2A2E] bg-[#0E0E10] px-4 py-2.5 text-xs font-semibold text-white transition hover:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-300"
            >
              Read Quant Documentation
            </Link>
          </div>

          <div className="grid gap-2 pt-1 sm:grid-cols-3 lg:grid-cols-1">
            {PREMIUM_PILLARS.map((pillar) => (
              <div
                key={pillar.title}
                className="flex items-center gap-2.5 rounded-xl border border-[#2A2A2E] bg-[#0E0E10] px-3 py-2"
              >
                <pillar.icon className="h-4 w-4 shrink-0 text-[#00F0FF]" aria-hidden="true" />
                <div className="min-w-0">
                  <p className="font-heading text-xs font-semibold text-white">{pillar.title}</p>
                  <p className="text-[10px] text-slate-400">{pillar.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="lg:hidden">
          <MobilePlatformSummary />
        </div>

        <div className="hidden flex-col gap-2.5 rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-4 shadow-[0_15px_40px_rgba(0,0,0,0.8)] lg:flex">
          <div>
            <p className="font-heading text-[10px] uppercase tracking-[0.24em] text-slate-400">
              Live Model Pulse
            </p>
            <div className="mt-1.5">
              <ModelMetadataPanel />
            </div>
          </div>

          <div className="rounded-xl border border-[#2A2A2E] bg-[#1B1B1D] px-3 py-2">
            <p className="mb-1.5 font-heading text-[9px] uppercase tracking-[0.2em] text-slate-400">
              Platform Health Status
            </p>
            <div className="grid gap-1.5 sm:grid-cols-3">
              <PlatformHealthPills />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
