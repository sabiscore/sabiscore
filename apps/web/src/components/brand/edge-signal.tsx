import { cn } from "@/lib/utils";

type EdgeSignalProps = {
  className?: string;
  decorative?: boolean;
};

/**
 * The Edge — model-vs-market delta glyph. The cyan point means a validated
 * value signal is present; it must only be rendered where the product already
 * has evidence for an edge/value state.
 */
export function EdgeSignal({ className, decorative = true }: EdgeSignalProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
      aria-hidden={decorative ? true : undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : "Market edge identified"}
    >
      <path d="M3 6L9.2 12L3 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M17 6L12.2 10.6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <path d="M12.2 13.4L17 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
      <circle cx="20.1" cy="12" r="2" fill="var(--brand-prediction, #29CFF3)" />
    </svg>
  );
}
