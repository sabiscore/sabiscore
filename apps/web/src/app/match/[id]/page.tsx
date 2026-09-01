import { notFound } from "next/navigation";
import { FullAnalysisSection } from "@/components/full-analysis-section";
import { Phase8AnalyticsSection } from "@/components/phase8-analytics-section";
import { ResearchModeBanner } from "@/components/research-mode-banner";
import { MatchHeaderActions } from "@/components/match/match-header-actions";
import { JsonLd } from "@/components/JsonLd";
import { generateSportsEventJsonLd, generateBreadcrumbJsonLd } from "@/lib/seo";
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
  const homeTeamName = home || rawId.split(" vs ")[0] || "Home";
  const awayTeamName = away || rawId.split(" vs ")[1] || "Away";

  const eventJsonLd = generateSportsEventJsonLd({
    matchId: rawId,
    homeTeam: homeTeamName,
    awayTeam: awayTeamName,
    startDate: new Date().toISOString(),
    league,
  });

  const breadcrumbJsonLd = generateBreadcrumbJsonLd([
    { name: "Home", url: "/" },
    { name: "Matches", url: "/match" },
    { name: matchup, url: `/match/${encodeURIComponent(rawId)}` },
  ]);

  return (
    <article className="mx-auto max-w-6xl space-y-4 sm:space-y-5" aria-labelledby="match-analysis-title">
      <JsonLd data={[eventJsonLd, breadcrumbJsonLd]} />
      <header className="flex flex-col gap-2.5 border-b border-slate-800 pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-400">
            SabiScore Match Intelligence
          </p>
          <h1 id="match-analysis-title" className="mt-1 text-xl font-semibold text-white sm:text-2xl">
            {matchup}
          </h1>
          <p className="mt-1 max-w-3xl text-xs text-slate-400 sm:text-sm">
            Forecast, uncertainty, and football evidence are shown independently from Market Intelligence.
            Odds-derived edge, EV, CLV, and stake context require verified market evidence and remain fail-closed.
          </p>
        </div>
        <div className="flex flex-col sm:items-end gap-2">
          <span
            className={`inline-flex min-h-8 items-center rounded-full border px-3 py-1 text-xs font-semibold ${
              isVerifiedFixturePath
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
                : "border-amber-500/40 bg-amber-500/10 text-amber-200"
            }`}
          >
            {isVerifiedFixturePath ? "Verified fixture path" : "Hypothetical — non-executable"}
          </span>
          <MatchHeaderActions
            matchId={rawId}
            homeTeam={homeTeamName}
            awayTeam={awayTeamName}
            league={league}
          />
        </div>
      </header>
      <ResearchModeBanner />
      <FullAnalysisSection matchId={rawId} league={league} homeTeam={home} awayTeam={away} />
      <details className="group rounded-2xl border border-slate-800 bg-slate-950/40 p-3 sm:p-4">
        <summary className="flex min-h-10 cursor-pointer items-center text-xs font-semibold text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 sm:text-sm">
          Technical feature diagnostics
        </summary>
        <div className="pt-2.5">
          <Phase8AnalyticsSection matchId={rawId} league={league} />
        </div>
      </details>
    </article>
  );
}
