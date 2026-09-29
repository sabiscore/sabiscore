import type { FullMatchMarket } from "@/lib/full-analysis-contract";

type Outcome = FullMatchMarket["outcomes"][number]["outcome"];

// The words MarketComparisonTable prints beside this chart (toLabel there).
const LABEL: Record<Outcome, string> = { home_win: "Home Win", draw: "Draw", away_win: "Away Win" };

const W = 100; // viewBox width: every x is a backend probability times W, nothing else
const ROW = 10;
const pos = (p: number) => Math.round(p * W * 100) / 100;

// Directive v10 U5: a picture of MarketComparisonTable, which stays the
// accessible text. Fair (hollow), model (filled) and a break-even tick at the
// implied probability, exactly as the backend sent them (v8 §3.6). Neutral
// unless the backend permits a stake and the row's gap is positive — the same
// rule as the table's Gap cell.
export function ProbabilityDumbbell({
  market,
  stakePermitted = false,
}: {
  market: FullMatchMarket;
  stakePermitted?: boolean;
}) {
  return (
    <div className="space-y-1">
      <svg
        viewBox={`-2 0 ${W + 4} ${market.outcomes.length * ROW}`}
        className="w-full max-w-sm"
        aria-hidden="true"
        focusable="false"
      >
        {market.outcomes.map((row, i) => {
          const y = i * ROW + 6.5;
          const play = stakePermitted && row.edge !== null && row.edge > 0;
          return (
            <g key={row.outcome} data-outcome={row.outcome}>
              <text x={0} y={y - 3.3} fontSize={3.2} className="fill-slate-300">
                {LABEL[row.outcome]}
              </text>
              <line x1={0} x2={W} y1={y} y2={y} strokeWidth={0.4} className="stroke-slate-700" />
              {row.model_prob !== null && (
                <line
                  data-mark="gap"
                  x1={pos(row.fair)}
                  x2={pos(row.model_prob)}
                  y1={y}
                  y2={y}
                  strokeWidth={0.8}
                  strokeLinecap="round"
                  className={play ? "stroke-[hsl(var(--state-play))]" : "stroke-[hsl(var(--state-withheld))]"}
                />
              )}
              {/* Hollow: filled with the card surface so the track does not show through. */}
              <circle
                data-mark="fair"
                cx={pos(row.fair)}
                cy={y}
                r={1.4}
                strokeWidth={0.5}
                className="fill-slate-950 stroke-[hsl(var(--state-withheld))]"
              />
              {row.model_prob !== null && (
                <circle
                  data-mark="model"
                  cx={pos(row.model_prob)}
                  cy={y}
                  r={1.4}
                  className={play ? "fill-[hsl(var(--state-play))]" : "fill-[hsl(var(--state-withheld))]"}
                />
              )}
              {/* Drawn last so the break-even mark is never hidden behind a dot. */}
              <line
                data-mark="implied"
                x1={pos(row.implied)}
                x2={pos(row.implied)}
                y1={y - 2.2}
                y2={y + 2.2}
                strokeWidth={0.5}
                className="stroke-slate-400"
              />
            </g>
          );
        })}
      </svg>
      <p className="whitespace-pre text-[10px] text-slate-400">● model  ○ fair  | break-even</p>
    </div>
  );
}
