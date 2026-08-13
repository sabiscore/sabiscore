import { cn } from "@/lib/utils";

type BrandMarkProps = {
  className?: string;
  title?: string;
  decorative?: boolean;
};

/**
 * SabiSignal — the canonical SabiScore mark.
 *
 * The path encodes observed data -> inference -> forecast, with the cyan terminal
 * node reserved for the predicted outcome. Keep this SVG geometric and
 * single-colour-capable so it remains legible from 16px favicon size upward.
 */
export function SabiSignalMark({
  className,
  title = "SabiScore",
  decorative = false,
}: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? true : undefined}
      aria-label={decorative ? undefined : title}
    >
      {!decorative && <title>{title}</title>}
      <path
        d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
        stroke="currentColor"
        strokeWidth="4.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="38.4" cy="38.5" r="3.4" fill="var(--brand-prediction, #29CFF3)" />
      <circle cx="10.5" cy="13.5" r="2.2" fill="currentColor" opacity="0.52" />
    </svg>
  );
}

type SabiScoreBrandProps = {
  className?: string;
  markClassName?: string;
  wordmarkClassName?: string;
  showDescriptor?: boolean;
  compact?: boolean;
};

/** Canonical SabiScore lockup for navigation and product chrome. */
export function SabiScoreBrand({
  className,
  markClassName,
  wordmarkClassName,
  showDescriptor = false,
  compact = false,
}: SabiScoreBrandProps) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-2.5", className)}>
      <span className="brand-mark-shell" aria-hidden="true">
        <SabiSignalMark className={cn("h-6 w-6 text-[var(--brand-mint)]", markClassName)} decorative />
      </span>
      {!compact && (
        <span className="min-w-0 leading-none">
          <span
            className={cn(
              "brand-wordmark block truncate text-[15px] font-semibold text-[var(--brand-wordmark)]",
              wordmarkClassName,
            )}
          >
            SabiScore
          </span>
          {showDescriptor && (
            <span className="mt-1 block text-[10px] font-medium uppercase tracking-[0.16em] text-[var(--brand-muted)]">
              Predictive intelligence
            </span>
          )}
        </span>
      )}
    </span>
  );
}
