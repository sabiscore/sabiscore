"use client";

import { memo, useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  BarChart3,
  BookOpen,
  CalendarClock,
  Menu,
  Sparkles,
  Trophy,
  X,
} from "lucide-react";
import { SabiScoreBrand } from "@/components/brand/sabiscore-brand";

const NAV_LINKS = [
  { label: "Intelligence", href: "/intelligence", icon: Sparkles },
  { label: "Matches", href: "/match", icon: CalendarClock },
  { label: "Performance", href: "/performance", icon: BarChart3 },
  { label: "Monitoring", href: "/monitoring", icon: Activity },
  { label: "Docs", href: "/docs", icon: BookOpen },
];

const LEAGUES = [
  { label: "Premier League", code: "EPL" },
  { label: "La Liga", code: "LA_LIGA" },
  { label: "Serie A", code: "SERIE_A" },
  { label: "Bundesliga", code: "BUNDESLIGA" },
  { label: "Ligue 1", code: "LIGUE_1" },
  { label: "Eredivisie", code: "EREDIVISIE" },
  { label: "Champions League", code: "UCL" },
];

export const MobileNav = memo(function MobileNav() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [open]);

  return (
    <div className="lg:hidden">
      <button
        type="button"
        aria-label="Open navigation"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="grid h-10 w-10 place-items-center rounded-md text-slate-300 hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <nav
            className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col bg-[var(--brand-elevated)] shadow-2xl"
            aria-label="Mobile navigation"
          >
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <SabiScoreBrand />
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => setOpen(false)}
                className="grid h-9 w-9 place-items-center rounded-md text-slate-400 hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-4">
              <p className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Workspace
              </p>
              <div className="mt-3 space-y-1">
                {NAV_LINKS.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setOpen(false)}
                    className="flex min-h-11 items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                  >
                    <item.icon className="h-4 w-4 text-emerald-300" aria-hidden="true" />
                    {item.label}
                  </Link>
                ))}
              </div>
              <p className="mt-6 px-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Leagues
              </p>
              <div className="mt-3 space-y-1">
                {LEAGUES.map((league) => (
                  <Link
                    key={league.code}
                    href={`/intelligence?league=${encodeURIComponent(league.code)}`}
                    onClick={() => setOpen(false)}
                    className="flex min-h-11 items-center justify-between rounded-md px-3 py-2 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                  >
                    <span className="flex items-center gap-2">
                      <Trophy className="h-4 w-4 text-emerald-300" aria-hidden="true" />
                      {league.label}
                    </span>
                    <span className="text-[11px] font-semibold text-slate-500">{league.code}</span>
                  </Link>
                ))}
              </div>
            </div>
          </nav>
        </>
      )}
    </div>
  );
});
