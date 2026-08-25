import { BettingIntelligenceDashboard } from "@/components/betting-intelligence-dashboard";

export const metadata = {
  title: "Match Intelligence",
  description:
    "Evidence-first match forecasts with Market Intelligence shown only when verified canonical odds are available.",
};

export default function IntelligencePage() {
  return (
    <section aria-labelledby="match-intelligence-title" className="space-y-2">
      <header className="mx-auto max-w-[1200px] px-3 pt-1.5 sm:px-4 sm:pt-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.24em] text-cyan-400">
          Evidence-gated football analysis
        </p>
        <h1 id="match-intelligence-title" className="mt-0.5 text-xl font-extrabold text-white sm:text-2xl">
          SabiScore Match Intelligence
        </h1>
        <p className="mt-0.5 max-w-3xl text-xs leading-normal text-slate-400">
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
