import { notFound } from "next/navigation";
import { FullAnalysisSection } from "@/components/full-analysis-section";
import { Phase8AnalyticsSection } from "@/components/phase8-analytics-section";
import { ResearchModeBanner } from "@/components/research-mode-banner";
import { canonicalLeagueId } from "@/lib/league";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type PageProps = {
  params?: Promise<{ id: string }>;
  searchParams?: Promise<{ league?: string; home?: string; away?: string }>;
};

function matchupLabelFor(id: string, home?: string, away?: string): string {
  return home && away ? `${home} vs ${away}` : decodeURIComponent(id);
}

export async function generateMetadata({ params, searchParams }: PageProps) {
  if (!params) {
    return {
      title: "Match Not Found",
      description: "The requested match could not be found.",
    };
  }

  try {
    const { id } = await params;
    const resolvedSearchParams = searchParams ? await searchParams : undefined;
    const { league, home, away } = resolvedSearchParams || {};
    const matchup = matchupLabelFor(id, home, away);
    return {
      title: `${matchup} — Match Intelligence`,
      description: `Evidence-led SabiScore Match Intelligence for ${matchup} in ${league || "EPL"}.`,
    };
  } catch {
    return {
      title: "Match Intelligence",
      description: "Evidence-led match intelligence and explicit availability states.",
    };
  }
}

export default async function MatchInsightsPage({ params, searchParams }: PageProps) {
  if (!params) notFound();

  let id: string;
  let league = "EPL";
  let home: string | undefined;
  let away: string | undefined;

  try {
    const resolvedParams = await params;
    id = resolvedParams.id;
    const resolvedSearchParams = searchParams ? await searchParams : undefined;
    league = canonicalLeagueId(resolvedSearchParams?.league) ?? "EPL";
    home = resolvedSearchParams?.home;
    away = resolvedSearchParams?.away;
  } catch {
    notFound();
  }

  const rawId = decodeURIComponent(id);
  const matchup = matchupLabelFor(id, home, away);
  const isVerifiedFixturePath = Boolean(home && away);

  return (
    <article className="mx-auto max-w-6xl space-y-8" aria-labelledby="match-analysis-title">
      <header className="flex flex-col gap-3 border-b border-slate-800 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-400">
            SabiScore Match Intelligence
          </p>
          <h1 id="match-analysis-title" className="mt-2 text-2xl font-semibold text-white sm:text-3xl">
            {matchup}
          </h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">
            Forecast, uncertainty, and football evidence are shown independently from Market Intelligence.
            Odds-derived edge, EV, CLV, and stake context require verified market evidence and remain fail-closed.
          </p>
        </div>
        <span
          className={`inline-flex min-h-11 items-center rounded-full border px-4 py-2 text-sm font-semibold ${
            isVerifiedFixturePath
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
              : "border-amber-500/40 bg-amber-500/10 text-amber-200"
          }`}
        >
          {isVerifiedFixturePath ? "Verified fixture path" : "Hypothetical — non-executable"}
        </span>
      </header>
      <ResearchModeBanner />
      <FullAnalysisSection matchId={rawId} league={league} homeTeam={home} awayTeam={away} />
      <details className="group rounded-2xl border border-slate-800 bg-slate-950/40 p-4">
        <summary className="flex min-h-11 cursor-pointer items-center text-sm font-semibold text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
          Technical feature diagnostics
        </summary>
        <div className="pt-4">
          <Phase8AnalyticsSection matchId={rawId} league={league} />
        </div>
      </details>
    </article>
  );
}
