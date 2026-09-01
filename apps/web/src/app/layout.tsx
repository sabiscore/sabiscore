import type { Metadata, Viewport } from "next";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import {
  Activity,
  BarChart3,
  BookOpen,
  CalendarClock,
  Code,
  LayoutDashboard,
  ShieldCheck,
  Sparkles,
  Trophy,
} from "lucide-react";
import "./globals.css";
import { Providers } from "./providers";
import { ToastProvider } from "./toast-provider";
import { ConsentProvider } from "../components/consent-banner";
import { ErrorBoundary } from "../components/error-boundary";
import { ClientEffects } from "./client-effects";
import { ReadinessRing } from "../components/readiness-ring";
import { BackendStatusBanner } from "../components/backend-status-banner";
import { MobileNav } from "../components/mobile-nav";
import { PlatformHealthPills } from "../components/platform-health-pills";
import { MobilePlatformSummary } from "../components/mobile-platform-summary";
import { SabiScoreBrand } from "../components/brand/sabiscore-brand";
import { NotificationCenter } from "../components/NotificationCenter";
import { UserNav } from "../components/auth/user-nav";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL ??
  (process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "https://sabiscore.com");

const WORKSPACE_LINKS: { label: string; href: string; icon: LucideIcon }[] = [
  { label: "Intelligence", href: "/intelligence", icon: Sparkles },
  { label: "Matches", href: "/match", icon: CalendarClock },
  { label: "Performance", href: "/performance", icon: BarChart3 },
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Developers", href: "/developer", icon: Code },
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

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Sabiscore Analytics",
    template: "%s | Sabiscore",
  },
  description:
    "Backend-owned football prediction, market value, and risk analytics for SabiScore.",
  authors: [{ name: "Sabiscore Team" }],
  creator: "Sabiscore",
  manifest: "/manifest.json",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
  },
  openGraph: {
    type: "website",
    siteName: "Sabiscore",
    title: "Sabiscore Analytics",
    description:
      "Backend-owned football prediction, market value, and risk analytics.",
    url: SITE_URL,
  },
  twitter: {
    card: "summary",
    title: "Sabiscore Analytics",
    description:
      "Backend-owned football prediction, market value, and risk analytics.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

export const viewport: Viewport = {
  themeColor: "#07110f",
  width: "device-width",
  initialScale: 1,
};

export const preferredRegion = "auto";
export const dynamic = "force-dynamic";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen bg-[var(--brand-nav)] text-slate-100 antialiased">
        <a
          href="#main-content"
          className="sr-only fixed left-3 top-3 z-[100] min-h-11 items-center rounded-md bg-emerald-300 px-4 py-2 font-semibold text-slate-950 focus:not-sr-only focus:flex focus:outline-none focus:ring-2 focus:ring-white"
        >
          Skip to main content
        </a>
        <ErrorBoundary>
          <Providers>
            <ClientEffects />
            <ToastProvider />
            <ConsentProvider requireConsent={true}>
              <div className="min-h-screen lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
                <aside
                  className="hidden border-r border-white/10 bg-[var(--brand-elevated)] lg:block"
                  aria-label="Workspace navigation and backend authority"
                >
                  <div className="sticky top-0 flex h-screen flex-col">
                    <div className="border-b border-white/10 px-4 py-3.5">
                      <Link
                        href="/"
                        className="inline-flex rounded-md focus:outline-none focus:ring-2 focus:ring-emerald-300"
                        aria-label="SabiScore home"
                      >
                        <SabiScoreBrand showDescriptor />
                      </Link>
                    </div>

                    <nav className="flex-1 overflow-y-auto px-3 py-3" aria-label="Primary navigation">
                      <p className="px-2 text-xs font-semibold uppercase tracking-wide text-slate-300">Workspace</p>
                      <div className="mt-2 space-y-0.5">
                        {WORKSPACE_LINKS.map((item) => (
                          <Link
                            key={item.href}
                            href={item.href}
                            className="flex min-h-10 items-center gap-2 rounded-md px-3 py-1.5 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                          >
                            <item.icon className="h-4 w-4 text-emerald-300" aria-hidden="true" />
                            {item.label}
                          </Link>
                        ))}
                      </div>

                      <p className="mt-4 px-2 text-xs font-semibold uppercase tracking-wide text-slate-300">Leagues</p>
                      <div className="mt-2 space-y-0.5">
                        {LEAGUES.map((league) => (
                          <Link
                            key={league.code}
                            href={`/intelligence?league=${encodeURIComponent(league.code)}`}
                            className="flex min-h-10 items-center justify-between rounded-md px-3 py-1.5 text-sm text-slate-300 transition hover:bg-white/5 hover:text-white focus:outline-none focus:ring-2 focus:ring-emerald-300"
                          >
                            <span className="flex items-center gap-2">
                              <Trophy className="h-4 w-4 text-emerald-300" aria-hidden="true" />
                              {league.label}
                            </span>
                            <span className="text-[11px] font-semibold text-slate-300">{league.code}</span>
                          </Link>
                        ))}
                      </div>
                    </nav>

                    <div className="border-t border-white/10 p-3">
                      <div className="rounded-md border border-white/10 bg-white/[0.03] p-2.5">
                        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                          <ShieldCheck className="h-4 w-4 text-emerald-300" aria-hidden="true" />
                          Backend authority
                        </div>
                        <p className="mt-1 text-xs leading-5 text-slate-400">
                          Providers, model inference, EV, Kelly sizing, and decisions stay server-side.
                        </p>
                      </div>
                    </div>
                  </div>
                </aside>

                <div className="min-w-0">
                  <header className="sticky top-0 z-40 border-b border-white/10 bg-[var(--brand-nav)]/95 backdrop-blur">
                    <div className="flex min-h-12 flex-wrap items-center justify-between gap-2 px-3 py-1 sm:gap-2.5 sm:px-4 sm:py-1.5">
                      <div className="flex items-center gap-2.5">
                        <Link
                          href="/"
                          className="rounded-md focus:outline-none focus:ring-2 focus:ring-emerald-200 lg:hidden"
                          aria-label="SabiScore home"
                        >
                          <SabiScoreBrand compact />
                        </Link>
                        <MobileNav />
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-300">
                            Live workspace
                          </p>
                          <h1 className="text-sm font-semibold text-white sm:text-base">
                            Prediction and market intelligence
                          </h1>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <div className="hidden flex-wrap items-center gap-2 md:flex">
                          <PlatformHealthPills />
                          <div className="min-w-[132px] rounded-md border border-white/10 bg-white/[0.03] px-2.5 py-1">
                            <ReadinessRing />
                          </div>
                        </div>
                        <NotificationCenter />
                        <UserNav />
                      </div>

                      <div className="w-full md:hidden">
                        <MobilePlatformSummary />
                      </div>
                    </div>
                  </header>
                  <BackendStatusBanner />

                  <main id="main-content" className="min-h-[calc(100vh-48px)] px-2.5 py-2.5 sm:px-4 sm:py-3 lg:px-5">
                    {children}
                  </main>
                  {process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA && (
                    <footer className="py-1.5 text-center text-[10px] text-slate-400 select-none">
                      {process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA.slice(0, 7)}
                    </footer>
                  )}
                </div>
              </div>
            </ConsentProvider>
          </Providers>
        </ErrorBoundary>
      </body>
    </html>
  );
}
