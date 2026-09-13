"use client";

import { memo } from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import {
  BarChart3,
  BookOpen,
  CalendarClock,
  Code,
  LayoutDashboard,
  Menu,
  ShieldCheck,
  Sparkles,
  Trophy,
  X,
} from "lucide-react";
import { SabiScoreBrand } from "@/components/brand/sabiscore-brand";

const WORKSPACE_LINKS = [
  { label: "Intelligence", href: "/intelligence", icon: Sparkles },
  { label: "Matches", href: "/match", icon: CalendarClock },
  { label: "Performance", href: "/performance", icon: BarChart3 },
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Developers", href: "/developer", icon: Code },
  { label: "Docs", href: "/docs", icon: BookOpen },
] as const;

const LEAGUES = [
  { label: "Premier League", code: "EPL" },
  { label: "La Liga", code: "LA_LIGA" },
  { label: "Serie A", code: "SERIE_A" },
  { label: "Bundesliga", code: "BUNDESLIGA" },
  { label: "Ligue 1", code: "LIGUE_1" },
  { label: "Eredivisie", code: "EREDIVISIE" },
  { label: "Champions League", code: "UCL" },
] as const;

export const MobileNav = memo(function MobileNav() {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          aria-label="Open navigation"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-md text-slate-300 transition-colors hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300 focus:ring-offset-2 focus:ring-offset-[var(--brand-nav)] lg:hidden"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] bg-slate-950/75 backdrop-blur-sm" />

        <Dialog.Content
          className="fixed inset-y-0 left-0 z-[70] flex h-dvh max-h-dvh w-[min(18rem,calc(100vw-1rem))] flex-col overflow-hidden border-r border-white/10 bg-[var(--brand-elevated)] shadow-2xl shadow-black/40 focus:outline-none"
          aria-describedby="mobile-navigation-description"
        >
          <div className="flex min-h-[4rem] shrink-0 items-center justify-between border-b border-white/10 px-5 py-4">
            <Dialog.Close asChild>
              <Link
                href="/"
                aria-label="SabiScore home"
                className="min-w-0 rounded-md focus:outline-none focus:ring-2 focus:ring-emerald-300"
              >
                <SabiScoreBrand />
              </Link>
            </Dialog.Close>

            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close navigation"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-md text-slate-400 transition-colors hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          <Dialog.Title className="sr-only">SabiScore navigation</Dialog.Title>

          <Dialog.Description
            id="mobile-navigation-description"
            className="sr-only"
          >
            Navigate between SabiScore workspace areas and supported football
            leagues.
          </Dialog.Description>

          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 [scrollbar-width:thin]">
            <nav aria-label="Mobile workspace navigation">
              <p className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-300">
                Workspace
              </p>

              <div className="mt-2 space-y-0.5">
                {WORKSPACE_LINKS.map((item) => {
                  const Icon = item.icon;

                  return (
                    <Dialog.Close key={item.href} asChild>
                      <Link
                        href={item.href}
                        className="flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                      >
                        <Icon
                          className="h-4 w-4 shrink-0 text-emerald-300"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 truncate">{item.label}</span>
                      </Link>
                    </Dialog.Close>
                  );
                })}
              </div>
            </nav>

            <nav className="mt-5" aria-label="Mobile league navigation">
              <p className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-300">
                Leagues
              </p>

              <div className="mt-2 space-y-0.5">
                {LEAGUES.map((league) => (
                  <Dialog.Close key={league.code} asChild>
                    <Link
                      href={`/intelligence?league=${encodeURIComponent(league.code)}`}
                      className="flex min-h-11 items-center justify-between gap-3 rounded-md px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <Trophy
                          className="h-4 w-4 shrink-0 text-emerald-300"
                          aria-hidden="true"
                        />
                        <span className="truncate">{league.label}</span>
                      </span>

                      <span className="shrink-0 text-[11px] font-semibold text-slate-300">
                        {league.code}
                      </span>
                    </Link>
                  </Dialog.Close>
                ))}
              </div>
            </nav>

            <section
              className="mt-6 rounded-md border border-white/10 bg-white/[0.03] p-3"
              aria-labelledby="mobile-backend-authority"
            >
              <div
                id="mobile-backend-authority"
                className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400"
              >
                <ShieldCheck
                  className="h-4 w-4 shrink-0 text-emerald-300"
                  aria-hidden="true"
                />
                Backend authority
              </div>

              <p className="mt-1 text-xs leading-5 text-slate-400">
                Providers, model inference, EV, Kelly sizing, and decisions
                stay server-side.
              </p>
            </section>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
});
