"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useQuery } from "@tanstack/react-query";
import { getUpcomingMatches, type UpcomingMatch } from "@/lib/api";
import { edgeQualityLabel } from "@/lib/edge-quality";
import { cn } from "@/lib/utils";

// ─── Props ────────────────────────────────────────────────────────────────────

interface InsightsTeaseStripProps {
  matchId: string;
  league?: string;
  /** When true, strip is visible. AnimatePresence handles exit. */
  visible: boolean;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function parseTeams(matchId: string): [string, string] {
  const idx = matchId.indexOf(" vs ");
  if (idx === -1) return [matchId.trim(), ""];
  return [matchId.slice(0, idx).trim(), matchId.slice(idx + 4).trim()];
}

interface TeaseCard {
  label: string;
  value: string;
  sub?: string;
  accent: string;
}

function buildCards(matchId: string, league: string, match: UpcomingMatch | null): TeaseCard[] {
  const [home, away] = parseTeams(matchId);
  const cards: TeaseCard[] = [];

  if (match?.match_date) {
    const d = new Date(match.match_date);
    cards.push({
      label: "Kickoff",
      value: d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }),
      sub: d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }),
      accent: "text-amber-300",
    });
  } else {
    cards.push({ label: "League", value: league, accent: "text-indigo-300" });
  }

  if (match?.edge_quality_score != null) {
    const pct = Math.round(match.edge_quality_score * 100);
    // edge_quality_score is a confidence/freshness/completeness composite, not a
    // market edge (@/lib/edge-quality) — the tier must say "quality", never bare "Edge".
    const tier = `${edgeQualityLabel(match.edge_quality_score)} quality`;
    const accent = pct >= 67 ? "text-emerald-300" : pct >= 33 ? "text-amber-300" : "text-slate-400";
    cards.push({ label: "Edge Quality", value: `${pct}%`, sub: tier, accent });
  }

  if (match?.predictions?.confidence != null) {
    const conf = Math.round(match.predictions.confidence * 100);
    cards.push({ label: "Confidence", value: `${conf}%`, sub: "Model certainty", accent: "text-cyan-300" });
  }

  // Always show matchup
  cards.push({
    label: "Matchup",
    value: home,
    sub: `vs ${away}`,
    accent: "text-slate-100",
  });

  return cards.slice(0, 4);
}

// ─── Card skeleton ────────────────────────────────────────────────────────────

function TeaseCardSkeleton() {
  return (
    <div className="flex-shrink-0 w-[140px] rounded-xl border border-slate-800/60 bg-slate-900/40 px-4 py-3 animate-pulse">
      <div className="h-2 w-16 rounded bg-slate-800 mb-2" />
      <div className="h-4 w-20 rounded bg-slate-800" />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function InsightsTeaseStrip({ matchId, league = "EPL", visible }: InsightsTeaseStripProps) {
  const prefersReduced = useReducedMotion();
  const [home, away] = parseTeams(matchId);

  const { data, isLoading } = useQuery({
    queryKey: ["upcoming-tease", league],
    queryFn: () => getUpcomingMatches({ league, days_ahead: 14, limit: 20 }),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
  });

  const match =
    data?.upcoming_matches.find(
      (m) =>
        m.home_team.toLowerCase().includes(home.toLowerCase()) ||
        m.away_team.toLowerCase().includes(away.toLowerCase()),
    ) ?? null;

  const cards = buildCards(matchId, league, match);

  const containerVariants = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: { staggerChildren: prefersReduced ? 0 : 0.07 },
    },
    exit: {
      opacity: 0,
      transition: { duration: prefersReduced ? 0 : 0.2 },
    },
  };

  const cardVariants = {
    hidden: { opacity: 0, y: prefersReduced ? 0 : 8 },
    show: { opacity: 1, y: 0, transition: { duration: 0.25, ease: "easeOut" } },
  };

  return (
    <AnimatePresence>
      {visible && (
        <motion.section
          key="tease-strip"
          role="region"
          aria-label="Match preview snippets"
          variants={containerVariants}
          initial="hidden"
          animate="show"
          exit="exit"
          className="mb-4"
        >
          <div className="flex gap-3 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {isLoading
              ? Array.from({ length: 4 }).map((_, i) => <TeaseCardSkeleton key={i} />)
              : cards.map((card) => (
                  <motion.div
                    key={card.label}
                    variants={cardVariants}
                    className="flex-shrink-0 w-[140px] rounded-xl border border-slate-800/60 bg-slate-900/60 px-4 py-3"
                  >
                    <p className="text-[10px] uppercase tracking-wider text-slate-500">{card.label}</p>
                    <p className={cn("text-sm font-semibold mt-0.5 truncate", card.accent)}>
                      {card.value}
                    </p>
                    {card.sub && (
                      <p className="text-[10px] text-slate-500 truncate mt-0.5">{card.sub}</p>
                    )}
                  </motion.div>
                ))}
          </div>
        </motion.section>
      )}
    </AnimatePresence>
  );
}
