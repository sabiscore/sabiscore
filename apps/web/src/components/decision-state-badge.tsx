import { CheckCircle2, CircleDashed, MinusCircle } from "lucide-react";

import type { DecisionState } from "@/lib/full-analysis-contract";
import { cn } from "@/lib/utils";

// Directive v8 §3.2: the state is carried by the word and the icon's shape
// (filled check / bar / dashed ring); colour only repeats it, so the three
// states stay distinguishable without colour vision. Colours come only from the
// --state-* tokens (v10 U8); the label stays neutral for contrast.
const DECISION_STATE_META: Record<
  DecisionState,
  { label: string; Icon: typeof CheckCircle2; className: string }
> = {
  PLAY: {
    label: "Play",
    Icon: CheckCircle2,
    className: "border-[hsl(var(--state-play)/0.4)] bg-[hsl(var(--state-play)/0.1)] [&>svg]:text-[hsl(var(--state-play))]",
  },
  PASS: {
    label: "Pass",
    Icon: MinusCircle,
    className: "border-[hsl(var(--state-pass)/0.4)] bg-[hsl(var(--state-pass)/0.1)] [&>svg]:text-[hsl(var(--state-pass))]",
  },
  WITHHELD: {
    label: "Withheld",
    Icon: CircleDashed,
    className: "border-[hsl(var(--state-withheld)/0.5)] bg-[hsl(var(--state-withheld)/0.15)] [&>svg]:text-[hsl(var(--state-withheld))]",
  },
};

export function DecisionStateBadge({ state }: { state: DecisionState }) {
  const { label, Icon, className } = DECISION_STATE_META[state];
  return (
    <span
      data-decision-state={state}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold text-slate-100",
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {label}
    </span>
  );
}
