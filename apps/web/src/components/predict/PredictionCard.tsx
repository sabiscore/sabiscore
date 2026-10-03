import React from "react";
import {
  AlertTriangle,
  CircleSlash,
  FlaskConical,
  ShieldAlert,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import {
  TRUTH_STATE_LABEL,
  type PredictionResult,
  type PredictionSummary,
  type TruthState,
} from "@/lib/prediction-truth";
import { describeEvidenceCode } from "@/lib/full-analysis-contract";
import { certificationLabel, generationLabel } from "@/lib/model-identity";

const STATE_STYLE: Record<TruthState, { icon: LucideIcon; classes: string }> = {
  RESEARCH_MODE: {
    icon: FlaskConical,
    classes: "border-[#00F0FF]/40 bg-[#00F0FF]/10 text-[#00F0FF]",
  },
  INSUFFICIENT_VERIFIED_DATA: {
    icon: AlertTriangle,
    classes: "border-amber-400/40 bg-amber-400/10 text-amber-200",
  },
  NO_VERIFIED_EDGE: {
    icon: CircleSlash,
    classes: "border-slate-500/50 bg-slate-500/10 text-slate-200",
  },
  POTENTIAL_VALUE: {
    icon: TrendingUp,
    classes: "border-emerald-400/40 bg-emerald-400/10 text-emerald-200",
  },
  WITHHELD: {
    icon: ShieldAlert,
    classes: "border-slate-500/50 bg-slate-500/10 text-slate-200",
  },
};

const MARKET_LABEL: Record<PredictionSummary["market"]["health"], string> = {
  VERIFIED_EVALUABLE: "Verified market snapshot",
  AVAILABLE_NOT_EVALUABLE: "Market present, not evaluable",
  UNAVAILABLE: "Market unavailable",
};

function StateBadge({ state }: { state: TruthState }) {
  const { icon: Icon, classes } = STATE_STYLE[state];
  return (
    <span
      data-testid="truth-state-badge"
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold ${classes}`}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {TRUTH_STATE_LABEL[state]}
    </span>
  );
}

function Shell({ children, label }: { children: React.ReactNode; label: string }) {
  return (
    <article
      data-testid="prediction-card"
      className="w-full rounded-2xl border border-[#2A2A2E] bg-[#1B1B1D] p-5 shadow-2xl"
      aria-label={label}
    >
      {children}
    </article>
  );
}

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-3">
      <dt className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-400">
        {term}
      </dt>
      <dd className="mt-1 font-mono text-xs text-slate-100">{children}</dd>
    </div>
  );
}

export function PredictionCard({ result }: { result: PredictionResult }) {
  if (result.status !== "OK") {
    return (
      <Shell label="Match forecast status">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-heading text-lg font-bold text-white">Match forecast</h2>
          <StateBadge state={result.truth_state} />
        </div>
        <p data-testid="withheld-message" className="mt-3 text-sm text-slate-300">
          {result.message}
        </p>
        {result.status === "WITHHELD" && result.data_gaps.length > 0 && (
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-slate-300">
            {result.data_gaps.map((gap) => (
              <li key={gap}>{describeEvidenceCode(gap)}</li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-xs text-slate-400">
          No probabilities, odds or stakes are shown while evidence is missing.
        </p>
      </Shell>
    );
  }

  const s = result.summary;
  const homePct = Math.round(s.probabilities.home * 100);
  const drawPct = Math.round(s.probabilities.draw * 100);
  const awayPct = Math.max(0, 100 - homePct - drawPct);
  const home = s.home_team ?? "Home";
  const away = s.away_team ?? "Away";

  return (
    <Shell label={`Match forecast for ${home} vs ${away}`}>
      <div className="flex flex-col gap-2 border-b border-[#2A2A2E] pb-4 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="font-heading text-lg font-bold tracking-tight text-white sm:text-xl">
          {home} <span className="font-normal text-slate-500">vs</span> {away}
        </h2>
        <StateBadge state={s.truth_state} />
      </div>

      <section className="mt-5 space-y-2" aria-labelledby="prob-heading">
        <div className="flex flex-wrap items-center justify-between gap-1 text-xs">
          <h3 id="prob-heading" className="font-heading font-semibold text-white">
            Outcome probabilities
          </h3>
          <span data-testid="translated-probabilities" className="font-mono font-semibold text-slate-100">
            Home: {homePct}% | Draw: {drawPct}% | Away: {awayPct}%
          </span>
        </div>
        <div
          role="img"
          aria-label={`${home} ${homePct}%, Draw ${drawPct}%, ${away} ${awayPct}%`}
          className="flex h-3.5 w-full overflow-hidden rounded-full border border-[#2A2A2E] bg-[#0E0E10] p-0.5"
        >
          <div style={{ width: `${homePct}%` }} className="h-full rounded-l-full bg-indigo-400" />
          <div style={{ width: `${drawPct}%` }} className="h-full bg-slate-500" />
          <div style={{ width: `${awayPct}%` }} className="h-full rounded-r-full bg-teal-300" />
        </div>
        <p className="text-[11px] text-slate-400">
          Model-estimated probabilities, not a prediction of certainty.
        </p>
      </section>

      <dl className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Fact term="Model generation">{generationLabel(s.model.generation)}</Fact>
        <Fact term="Certification">{certificationLabel(s.model.certification_state)}</Fact>
        <Fact term="Evidence health">
          {s.evidence.critical} critical / {s.evidence.advisory} advisory / {s.evidence.conflicts} conflicts
        </Fact>
        <Fact term="Market health">{MARKET_LABEL[s.market.health]}</Fact>
        <Fact term="Data freshness">
          {s.freshness.tag}
          {s.freshness.staleness_seconds !== null ? ` (${s.freshness.staleness_seconds}s)` : ""}
        </Fact>
        <Fact term="Calibration">
          {s.model.calibration_applied ? s.model.calibration_method : "raw (uncalibrated)"}
        </Fact>
        <Fact term="Verdict">{s.verdict}</Fact>
        <Fact term="Staking">
          {s.stake_permitted && s.suggested_stake_pct !== null
            ? `Backend-computed: ${s.suggested_stake_pct}%`
            : "Withheld"}
        </Fact>
      </dl>

      <section className="mt-5 rounded-xl border border-[#2A2A2E] bg-[#0E0E10] p-4" aria-labelledby="form-heading">
        <h3 id="form-heading" className="font-heading text-sm font-semibold text-white">
          Recent Attacking Form (Last 5 Matches)
        </h3>
        <p className="mt-1 text-xs text-slate-300">
          Not shown: recent xG form is not an input to the current forecasting model.
        </p>
      </section>

      {s.counter_case.length > 0 && (
        <section className="mt-5" aria-labelledby="counter-heading">
          <h3 id="counter-heading" className="font-heading text-sm font-semibold text-white">
            Why this might not hold
          </h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-slate-300">
            {s.counter_case.map((gap) => (
              <li key={gap}>{describeEvidenceCode(gap)}</li>
            ))}
          </ul>
        </section>
      )}
    </Shell>
  );
}
