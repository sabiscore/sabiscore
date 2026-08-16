export type FreshnessTag = "LIVE" | "RECENT" | "STALE" | "UNKNOWN";

export interface FreshnessState {
  tag: FreshnessTag;
  label: "Fresh" | "Recent" | "Stale" | "Unknown";
  ageLabel: string;
  ariaLabel: string;
  className: string;
}

const TAG_STYLE: Record<FreshnessTag, Pick<FreshnessState, "label" | "className">> = {
  LIVE: {
    label: "Fresh",
    className: "border-emerald-500/25 bg-emerald-500/8 text-emerald-300",
  },
  RECENT: {
    label: "Recent",
    className: "border-amber-500/25 bg-amber-500/8 text-amber-300",
  },
  STALE: {
    label: "Stale",
    className: "border-rose-500/25 bg-rose-500/8 text-rose-300",
  },
  UNKNOWN: {
    label: "Unknown",
    className: "border-slate-600/30 bg-slate-700/20 text-slate-300",
  },
};

function validAge(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function deriveTag(age: number): FreshnessTag {
  if (age === 0) return "LIVE";
  if (age < 86_400) return "RECENT";
  return "STALE";
}

function formatAge(age: number, tag: FreshnessTag): string {
  if (tag === "UNKNOWN" || age === 0) return "";
  if (age < 3_600) return ` · ${Math.max(1, Math.round(age / 60))}m ago`;
  if (age < 86_400) return ` · ${Math.round(age / 3_600)}h ago`;
  return ` · ${Math.round(age / 86_400)}d ago`;
}

/**
 * Canonical client-side evidence freshness mapper.
 *
 * Absence is never coerced to zero. An explicit backend availability=false wins
 * over both an age and a tag so old cached payloads cannot render missing
 * evidence as Fresh. When a trustworthy backend tag is present it is retained;
 * otherwise the same 0 / <24h / >=24h thresholds used by the backend apply.
 */
export function mapEvidenceFreshness({
  stalenessSeconds,
  available,
  tag,
}: {
  stalenessSeconds: number | null | undefined;
  available?: boolean | null;
  tag?: FreshnessTag | null;
}): FreshnessState {
  if (available === false || !validAge(stalenessSeconds)) {
    const style = TAG_STYLE.UNKNOWN;
    return {
      tag: "UNKNOWN",
      ...style,
      ageLabel: "",
      ariaLabel: "Data freshness unknown",
    };
  }

  const resolvedTag: FreshnessTag =
    tag && tag !== "UNKNOWN" ? tag : deriveTag(stalenessSeconds);
  const style = TAG_STYLE[resolvedTag];
  const ageLabel = formatAge(stalenessSeconds, resolvedTag);
  return {
    tag: resolvedTag,
    ...style,
    ageLabel,
    ariaLabel: `Data freshness ${style.label.toLowerCase()}${ageLabel}`,
  };
}
