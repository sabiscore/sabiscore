import { BettingIntelligenceDashboard } from "@/components/betting-intelligence-dashboard";

export const metadata = {
  title: "Match Intelligence",
  description:
    "Evidence-first match forecasts with Market Intelligence shown only when verified canonical odds are available.",
};

export default function IntelligencePage() {
  return (
    <section aria-labelledby="match-intelligence-title" className="space-y-5">
      <header className="mx-auto max-w-[1200px] px-6 pt-6">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-cyan-400">
          Evidence-gated football analysis
        </p>
        <h1 id="match-intelligence-title" className="mt-2 text-3xl font-extrabold text-white">
          SabiScore Match Intelligence
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          Match Intelligence covers verified fixture identity, model probabilities, uncertainty, and
          supporting football evidence. Market Intelligence appears only when a coherent verified
          1X2 price snapshot exists; missing, stale, or conflicting market evidence remains explicitly
          unavailable and never implies execution permission.
        </p>
      </header>

      {/* The legacy component name remains an internal compatibility detail. Its
          old page heading is hidden so the public workspace has one semantic H1;
          the evidence, market, and fail-closed controls remain unchanged. */}
      <div className="[&_.bi-title]:hidden [&_.bi-sub]:hidden">
        <BettingIntelligenceDashboard />
      </div>
    </section>
  );
}
