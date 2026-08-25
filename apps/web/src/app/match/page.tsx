import Link from "next/link";
import { MatchSelector } from "@/components/match-selector";
import { UpcomingMatchesSection } from "@/components/upcoming-matches-section";

export const metadata = {
  // layout.tsx's metadata.title.template already appends " | Sabiscore" —
  // repeating it here rendered "Match Insights | Sabiscore | Sabiscore".
  title: "Match Insights",
  description: "Choose a league and matchup to generate Sabiscore betting insights.",
};

export default function MatchLandingPage() {
  const featureCards = [
    {
      title: "Smart Kelly",
      body: "Auto-sizes stakes with Quarter Kelly and liquidity safeguards.",
    },
    {
      title: "Market Radar",
      body: "Compares model edge against live bookmaker lines in seconds.",
    },
    {
      title: "Confidence Bands",
      body: "Monte Carlo bands show volatility and probability swings.",
    },
  ];

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 sm:gap-6">
      <section className="space-y-2 sm:space-y-2.5 text-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-indigo-500/30 bg-indigo-500/10 px-3 py-0.5 text-xs font-semibold text-indigo-200">
          <span>Live Match Insights</span>
          <span className="text-indigo-400">Fetched fresh per request</span>
        </div>
        {/* "Actionable edges for any fixture" promised the ACTIONABLE verdict
            tier for every input — the evidence gates contradict that, and the
            manual path is explicitly a non-executable hypothetical. Matches the
            homepage hero's evidence-first phrasing instead. */}
        <h1 className="text-2xl font-bold tracking-tight text-slate-100 sm:text-3xl md:text-4xl">
          Evidence-gated analysis for the fixture you choose
        </h1>
        <p className="mx-auto max-w-2xl text-xs text-slate-400 sm:text-sm">
          Pick a verified fixture or enter a matchup. Forecasts, market comparison, and
          staking guidance appear only when the backend confirms the required evidence.
        </p>
      </section>

      <MatchSelector />

      <UpcomingMatchesSection />

      <section className="grid gap-3 sm:gap-4 md:grid-cols-3">
        {featureCards.map((feature) => (
          <div key={feature.title} className="glass-card space-y-1.5 p-3.5 sm:p-4">
            <h2 className="text-sm font-semibold text-slate-100 sm:text-base">{feature.title}</h2>
            <p className="text-xs text-slate-400 leading-normal">{feature.body}</p>
          </div>
        ))}
      </section>

      <section className="rounded-2xl border border-slate-800/60 bg-slate-900/40 p-3.5 sm:p-4 text-xs text-slate-400">
        <p className="mb-2 font-semibold text-slate-200">Need a refresher on the numbers?</p>
        <ul className="list-disc space-y-1.5 pl-5 text-left">
          <li>&ldquo;Edge&rdquo; shows how far the market deviates from Sabiscore fair odds.</li>
          <li>&ldquo;Kelly stake&rdquo; scales position sizing to protect bankroll and downside.</li>
          <li>
            &ldquo;CLV&rdquo; captures expected price movement; use it to gauge closing line efficiency.
          </li>
        </ul>
        <p className="mt-3 text-slate-400">
          Want deeper methodology notes? Dive into the <Link href="/docs" className="text-indigo-300 hover:text-indigo-200">product docs</Link>.
        </p>
      </section>
    </div>
  );
}
