import { evidenceStateFor, type EvidenceStateDescriptor } from "./evidence-state";
import { groupEvidenceGaps } from "./full-analysis-contract";

/**
 * Evidence Passport — per-family provenance, freshness, and resolution status
 * for /match/[id] (docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md §5). Composes two
 * things the platform already produces; it introduces no new family taxonomy
 * and fetches no new endpoint:
 *
 *  - `field_availability` / `unavailable_reasons` — the resolution status the
 *    full-analysis endpoint already computes
 *    (backend/src/api/endpoints/full_analysis.py `field_availability` /
 *    `unavailable_reasons`, ~lines 886-903): fixture, prediction, market,
 *    uncertainty, elo. Booleans + prose reasons — no raw backend enum token
 *    lives in either of those two fields.
 *  - GET /api/v1/sources/freshness (proxied at /api/sources/freshness) — the
 *    V4 source registry's per-category freshness. Only "market" has an
 *    honest 1:1 category match today (see FAMILY_SOURCE_CATEGORY below); the
 *    other families render without a provenance sub-line rather than
 *    guessing one.
 */

export interface SourceFreshnessItem {
  name: string;
  category: string;
  freshness_status: string;
  enabled: boolean;
}

export interface EvidencePassportProvenance {
  sourceName: string;
  category: string;
  freshnessLabel: string;
  freshnessTone: EvidenceStateDescriptor["tone"];
}

export interface EvidencePassportRow {
  key: string;
  label: string;
  resolved: boolean;
  statusLabel: string;
  tone: EvidenceStateDescriptor["tone"];
  reason: string | null;
  gapCount: number;
  provenance: EvidencePassportProvenance | null;
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

/**
 * sources/freshness categories (backend/src/connectors/source_registry.py)
 * that correspond to a field_availability family. Only "market" has a
 * registered source today (odds-market-features -> "betting_market").
 */
const FAMILY_SOURCE_CATEGORY: Record<string, string> = {
  market: "betting_market",
};

function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * evidence-state.ts's dictionary already covers STALE and DATA_GAP exactly as
 * sources/freshness emits them. LIVE/RECENT are unique to source freshness
 * (fixture-list evidence never uses them), so they're layered on top instead
 * of duplicating the whole fail-closed dictionary.
 */
const FRESHNESS_TOKEN_OVERRIDES: Record<string, EvidenceStateDescriptor> = {
  LIVE: { label: "Fresh", tone: "positive" },
  RECENT: { label: "Recent", tone: "warning" },
};

function freshnessDescriptor(token: string): EvidenceStateDescriptor {
  return FRESHNESS_TOKEN_OVERRIDES[String(token).toUpperCase()] ?? evidenceStateFor(token);
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
  sources: readonly SourceFreshnessItem[];
}): EvidencePassportRow[] {
  const { fieldAvailability, unavailableReasons, advisoryGaps, sources } = input;
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

    const category = FAMILY_SOURCE_CATEGORY[key];
    const source = category ? sources.find((s) => s.category === category) : undefined;
    const provenance: EvidencePassportProvenance | null = source
      ? {
          sourceName: source.name,
          category: titleCase(source.category),
          freshnessLabel: freshnessDescriptor(source.freshness_status).label,
          freshnessTone: freshnessDescriptor(source.freshness_status).tone,
        }
      : null;

    return {
      key,
      label: FAMILY_LABELS[key] ?? titleCase(key),
      resolved,
      statusLabel: resolved ? "Resolved" : "Gapped",
      tone: resolved ? "positive" : "warning",
      reason: resolved ? null : unavailableReasons[key] ?? "Evidence unavailable for this family.",
      gapCount,
      provenance,
    };
  });
}
