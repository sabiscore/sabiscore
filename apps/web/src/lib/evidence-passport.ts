import type { EvidenceStateDescriptor } from "./evidence-state";
import { groupEvidenceGaps } from "./full-analysis-contract";

/**
 * Evidence Passport — per-family resolution status for /match/[id]
 * (docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md §5), built only from what the
 * full-analysis endpoint computed for this fixture: `field_availability` /
 * `unavailable_reasons` (backend/src/api/endpoints/full_analysis.py) and the
 * advisory gap codes. No raw backend enum token lives in either field.
 *
 * It used to add a per-family "provenance" sub-line from GET
 * /api/v1/sources/freshness. That registry is populated by
 * `record_source_check`, which nothing calls, so every source reads
 * "never_checked" and the market row said "Data unavailable" beside
 * "Resolved" on fixtures whose odds had just been fetched (live 2026-09-26).
 * A status that is never measured is not provenance; it was removed.
 */

export interface EvidencePassportRow {
  key: string;
  label: string;
  resolved: boolean;
  statusLabel: string;
  tone: EvidenceStateDescriptor["tone"];
  reason: string | null;
  gapCount: number;
}

const FAMILY_LABELS: Record<string, string> = {
  fixture: "Fixture Identity",
  prediction: "Model Prediction",
  market: "Market Price",
  uncertainty: "Model Uncertainty",
  elo: "Team Strength (Elo)",
};

/** Preferred order — mirrors the object-literal order full_analysis.py builds. */
const FAMILY_ORDER = ["fixture", "prediction", "market", "uncertainty", "elo"];

/**
 * Which full-analysis-contract.ts EVIDENCE_FAMILIES labels (as grouped by
 * groupEvidenceGaps over evidence_quality.advisory_gaps) correspond to a
 * field_availability family. Deliberately partial: most field_availability
 * families are gated by critical_gap codes (e.g. FIXTURE_IDENTITY_UNVERIFIED,
 * MODEL_UNCERTAINTY_UNAVAILABLE) rather than the canonical feature-name codes
 * groupEvidenceGaps groups — associating those would fabricate a relationship
 * the backend never draws.
 */
const FAMILY_GAP_GROUP_LABELS: Record<string, readonly string[]> = {
  market: ["Market prices", "Market movement"],
  elo: ["Team strength ratings"],
};

function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatEvidenceAge(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "Unknown";
  if (seconds < 60) return "Less than a minute ago";
  if (seconds < 3_600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3_600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

export function buildEvidencePassport(input: {
  fieldAvailability: Record<string, boolean>;
  unavailableReasons: Record<string, string>;
  advisoryGaps: readonly string[];
}): EvidencePassportRow[] {
  const { fieldAvailability, unavailableReasons, advisoryGaps } = input;
  const gapCountByLabel = new Map(groupEvidenceGaps(advisoryGaps).map((g) => [g.label, g.count]));

  const keys = Object.keys(fieldAvailability);
  const orderedKeys = [
    ...FAMILY_ORDER.filter((key) => keys.includes(key)),
    ...keys.filter((key) => !FAMILY_ORDER.includes(key)),
  ];

  return orderedKeys.map((key) => {
    const resolved = Boolean(fieldAvailability[key]);
    const gapCount = (FAMILY_GAP_GROUP_LABELS[key] ?? []).reduce(
      (sum, label) => sum + (gapCountByLabel.get(label) ?? 0),
      0,
    );

    return {
      key,
      label: FAMILY_LABELS[key] ?? titleCase(key),
      resolved,
      statusLabel: resolved ? "Resolved" : "Gapped",
      tone: resolved ? "positive" : "warning",
      reason: resolved ? null : unavailableReasons[key] ?? "Evidence unavailable for this family.",
      gapCount,
    };
  });
}
