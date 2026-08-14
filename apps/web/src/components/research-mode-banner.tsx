import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export function ResearchModeBanner({ className }: { className?: string }) {
  return (
    <section
      role="status"
      aria-label="Research forecast; staking disabled"
      className={cn(
        "rounded-xl border border-[hsl(var(--signal-warning)/0.35)] bg-[hsl(var(--signal-warning)/0.08)] px-4 py-3",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          className="mt-0.5 h-5 w-5 shrink-0 text-[hsl(var(--signal-warning))]"
          aria-hidden="true"
        />
        <div>
          <p className="text-sm font-bold uppercase tracking-[0.16em] text-[hsl(var(--signal-warning))]">
            Research forecast — staking disabled
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-300">
            This model generation has not yet been certified against the market baseline.
            Probabilities and market comparison are shown for analysis; no stake is recommended
            for any fixture until certification passes.
          </p>
        </div>
      </div>
    </section>
  );
}
