import { notFound } from "next/navigation";
import Link from "next/link";
import { getTeamIntelligence, APIError, TeamIntelligenceResponse, TeamFormVerdict } from "@/lib/api";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type PageProps = {
  params: Promise<{ slug: string }>;
};

export async function generateMetadata({ params }: PageProps) {
  const { slug } = await params;
  const name = decodeURIComponent(slug).replace(/-/g, " ");
  return {
    title: `${name} — Team Intelligence`,
    description: `Rolling form, H2H analysis, and upcoming fixtures for ${name}.`,
  };
}

// ── Verdict badge ─────────────────────────────────────────────────────────────

function verdictColors(v: TeamFormVerdict): string {
  switch (v) {
    case "IMPROVING":  return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
    case "DECLINING":  return "border-rose-500/40 bg-rose-500/10 text-rose-300";
    case "VOLATILE":   return "border-amber-500/40 bg-amber-500/10 text-amber-300";
    default:           return "border-zinc-700 bg-zinc-800/50 text-zinc-300";
  }
}

function VerdictBadge({ verdict }: { verdict: TeamFormVerdict }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-widest ${verdictColors(verdict)}`}
      aria-label={`Form verdict: ${verdict}`}
    >
      {verdict}
    </span>
  );
}

// ── PPG card ──────────────────────────────────────────────────────────────────

function PPGCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-4 text-center">
      <p className="text-2xl font-bold text-zinc-100">
        {value !== null ? value.toFixed(2) : "—"}
      </p>
      <p className="mt-0.5 text-xs text-zinc-500 uppercase tracking-wider">{label}</p>
    </div>
  );
}

// ── Result dot ────────────────────────────────────────────────────────────────

function ResultDot({ result }: { result: string }) {
  const colors: Record<string, string> = {
    W: "bg-emerald-500",
    D: "bg-amber-400",
    L: "bg-rose-500",
  };
  return (
    <span
      className={`inline-block h-3 w-3 rounded-full ${colors[result] ?? "bg-zinc-600"}`}
      aria-label={result === "W" ? "Win" : result === "D" ? "Draw" : "Loss"}
      title={result === "W" ? "Win" : result === "D" ? "Draw" : "Loss"}
    />
  );
}

// ── Edge quality mini-bar ─────────────────────────────────────────────────────

function MiniEdgeBar({ score }: { score: number }) {
  const pct = Math.round(Math.min(1, Math.max(0, score)) * 100);
  const color = score >= 0.67 ? "bg-emerald-500" : score >= 0.33 ? "bg-amber-400" : "bg-rose-500";
  return (
    <div className="flex items-center gap-1.5" aria-label={`Edge quality ${pct}%`}>
      <div className="h-1.5 w-14 rounded-full bg-zinc-800 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-zinc-500">{pct}%</span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default async function TeamIntelligencePage({ params }: PageProps) {
  const { slug } = await params;

  let data: TeamIntelligenceResponse;
  try {
    data = await getTeamIntelligence(slug);
  } catch (err) {
    if (err instanceof APIError && err.status === 404) notFound();
    throw err;
  }

  return (
    // No horizontal padding here, and <div> not <main>: the root <main>
    // (app/layout.tsx) already supplies px-4 py-5 sm:px-6 lg:px-8 and is the
    // page's sole <main> landmark — same container-parity convention as
    // /performance and /monitoring.
    <div className="mx-auto max-w-3xl space-y-10">
      {/* Header */}
      <section aria-label="Team header" className="space-y-3">
        <Link
          href="/"
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          aria-label="Back to home"
        >
          ← Home
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold text-zinc-100">{data.team_name}</h1>
          {data.league && (
            <span className="rounded-full border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-400">
              {data.league}
            </span>
          )}
          <VerdictBadge verdict={data.form_verdict} />
        </div>
      </section>

      {/* PPG summary */}
      <section aria-label="Points per game summary" className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <PPGCard label="PPG last 5" value={data.ppg_last5} />
        <PPGCard label="PPG last 10" value={data.ppg_last10} />
        <div className="col-span-2 rounded-xl border border-zinc-800 bg-zinc-900/60 px-5 py-4 flex items-center gap-3">
          <div className="space-y-1">
            <p className="text-xs text-zinc-500 uppercase tracking-wider">Recent form</p>
            <div className="flex items-center gap-1">
              {data.recent_form.slice(-10).map((r, i) => (
                <ResultDot key={i} result={r.result} />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Recent form table */}
      <section aria-label="Recent match results" className="space-y-3">
        <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Recent Results</h2>
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-800 text-left text-[11px] text-zinc-500 uppercase tracking-wider">
                <th className="px-4 py-2">Date</th>
                <th className="px-4 py-2">Opponent</th>
                <th className="px-4 py-2">H/A</th>
                <th className="px-4 py-2">Score</th>
                <th className="px-4 py-2">Result</th>
                <th className="px-4 py-2 text-right">Pts</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_form.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-xs text-zinc-600">
                    No recent finished matches in the database.
                  </td>
                </tr>
              ) : (
                data.recent_form.map((r, i) => (
                  <tr
                    key={i}
                    className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-900/40 transition-colors"
                  >
                    <td className="px-4 py-2.5 text-xs text-zinc-400">
                      {new Date(r.match_date).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    </td>
                    <td className="px-4 py-2.5 text-zinc-200">{r.opponent}</td>
                    <td className="px-4 py-2.5 text-xs text-zinc-500 uppercase">{r.home_or_away}</td>
                    <td className="px-4 py-2.5 text-xs text-zinc-300">
                      {r.goals_for ?? "—"}–{r.goals_against ?? "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <ResultDot result={r.result} />
                    </td>
                    <td className="px-4 py-2.5 text-right font-bold text-zinc-300">{r.points}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* H2H summary */}
      {data.h2h_summary.length > 0 && (
        <section aria-label="Head-to-head summary" className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Head-to-Head vs Top Opponents</h2>
          <div className="overflow-x-auto rounded-xl border border-zinc-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-zinc-800 text-left text-[11px] text-zinc-500 uppercase tracking-wider">
                  <th className="px-4 py-2">Opponent</th>
                  <th className="px-4 py-2 text-right">P</th>
                  <th className="px-4 py-2 text-right">W</th>
                  <th className="px-4 py-2 text-right">D</th>
                  <th className="px-4 py-2 text-right">L</th>
                  <th className="px-4 py-2 text-right">GF</th>
                  <th className="px-4 py-2 text-right">GA</th>
                </tr>
              </thead>
              <tbody>
                {data.h2h_summary.map((h, i) => (
                  <tr key={i} className="border-b border-zinc-800/50 last:border-0 hover:bg-zinc-900/40 transition-colors">
                    <td className="px-4 py-2.5 text-zinc-200">{h.opponent}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-400">{h.played}</td>
                    <td className="px-4 py-2.5 text-right text-emerald-400 font-semibold">{h.wins}</td>
                    <td className="px-4 py-2.5 text-right text-amber-400">{h.draws}</td>
                    <td className="px-4 py-2.5 text-right text-rose-400">{h.losses}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-300">{h.goals_for}</td>
                    <td className="px-4 py-2.5 text-right text-zinc-400">{h.goals_against}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Upcoming fixtures */}
      {data.upcoming_fixtures.length > 0 && (
        <section aria-label="Upcoming fixtures" className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-300 uppercase tracking-wider">Upcoming Fixtures</h2>
          <div className="space-y-2">
            {data.upcoming_fixtures.map((f) => {
              // Real fixtures carry a canonical match_id — route by it so the
              // backend can verify fixture identity instead of falling back
              // to the unverified "Home vs Away" matchup path.
              const href = f.match_id
                ? `/match/${encodeURIComponent(f.match_id)}?league=${encodeURIComponent(f.league)}&home=${encodeURIComponent(f.home_team)}&away=${encodeURIComponent(f.away_team)}`
                : `/match/${encodeURIComponent(`${f.home_team} vs ${f.away_team}`)}?league=${encodeURIComponent(f.league)}`;
              return (
                <Link
                  key={f.match_id}
                  href={href}
                  className="flex items-center justify-between rounded-xl border border-zinc-800/60 bg-zinc-900/50 px-4 py-3 hover:border-indigo-500/30 hover:bg-zinc-900/80 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                  aria-label={`${f.home_team} vs ${f.away_team}`}
                >
                  <div className="space-y-0.5">
                    <p className="text-sm text-zinc-200">
                      {f.home_team}
                      <span className="mx-1.5 text-zinc-600">vs</span>
                      {f.away_team}
                    </p>
                    <p className="text-[11px] text-zinc-500">
                      {new Date(f.match_date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })}
                      <span className="mx-1.5">·</span>
                      {f.league}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {f.edge_quality_score !== null && f.edge_quality_score !== undefined && (
                      <MiniEdgeBar score={f.edge_quality_score} />
                    )}
                    {!f.has_prediction && (
                      <span className="text-[10px] text-zinc-600">No prediction</span>
                    )}
                    <svg className="h-3.5 w-3.5 text-zinc-700" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      <footer className="text-center text-[10px] text-zinc-700">
        Intelligence queried at {new Date(data.queried_at).toLocaleString()}
      </footer>
    </div>
  );
}
