import { cn } from "@/lib/utils";

type BrandMarkProps = {
  className?: string;
  title?: string;
  decorative?: boolean;
};

/**
 * SabiSignal — the canonical SabiScore mark.
 *
 * The continuous S-curve represents observed data flowing through inference into
 * a forecast. The terminal node is deliberately distinct from the signal path so
 * the mark remains legible at navigation, auth, and favicon-adjacent sizes.
 *
 * This inline version intentionally avoids SVG filters/gradients: the mark is
 * rendered frequently and at small sizes, so crisp geometry and low paint cost are
 * more valuable than the effects used by the standalone app icon.
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
      focusable="false"
      shapeRendering="geometricPrecision"
    >
      {!decorative && <title>{title}</title>}

      {/* Quiet signal rail: preserves the depth of the supplied master SVG. */}
      <path
        d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
        stroke="currentColor"
        strokeWidth="7.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.12"
      />

      {/* Primary predictive signal. */}
      <path
        d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
        stroke="currentColor"
        strokeWidth="4.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Fine highlight gives the path optical sharpness without a blur filter. */}
      <path
        d="M10.5 13.5H29.2C33.6 13.5 37 16.2 37 19.8C37 23.4 33.8 25.7 29.4 25.7H18.6C14.2 25.7 11 28.1 11 31.8C11 35.6 14.3 38.5 18.9 38.5H34.4"
        stroke="#FFFFFF"
        strokeWidth="1.05"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.24"
      />

      {/* Historical origin node. */}
      <circle cx="10.5" cy="13.5" r="2.35" fill="currentColor" opacity="0.62" />

      {/* Forecast/output node — lime is intentionally distinct from brand mint. */}
      <circle
        cx="38.4"
        cy="38.5"
        r="3.65"
        fill="var(--brand-forecast, #C4FF4D)"
      />
      <circle cx="38.4" cy="38.5" r="1.35" fill="#FFFFFF" opacity="0.92" />
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
        <SabiSignalMark
          className={cn("h-6 w-6 text-[var(--brand-mint)]", markClassName)}
          decorative
        />
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
