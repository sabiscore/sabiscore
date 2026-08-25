import { ShieldAlert } from "lucide-react";
import { cn } from "@/lib/utils";

export function ResearchModeBanner({ className }: { className?: string }) {
  return (
    <section
      role="status"
      aria-label="Research forecast; staking disabled"
      className={cn(
        "rounded-xl border border-[hsl(var(--signal-warning)/0.35)] bg-[hsl(var(--signal-warning)/0.08)] px-3.5 py-2 sm:px-4 sm:py-2.5",
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <ShieldAlert
          className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--signal-warning))]"
          aria-hidden="true"
        />
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-[hsl(var(--signal-warning))]">
            Research forecast — staking disabled
          </p>
          <p className="mt-0.5 text-xs leading-5 text-slate-300">
            This model generation has not yet been certified against the market baseline.
            Probabilities and market comparison are shown for analysis; no stake is recommended
            for any fixture until certification passes.
          </p>
        </div>
      </div>
    </section>
  );
}
