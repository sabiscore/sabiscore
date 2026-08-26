/**
 * Mandate 2 R3 / APEX §15.2 — evidence tokens must render as a distinct,
 * intentional visual state, never a bare backend enum string and never
 * collapsed into one generic red "error".
 *
 * `backend/src/api/endpoints/fixtures.py`'s `_build_evidence()` and
 * `_fixture_summary()` (lines 204-434) are the source of truth for these
 * tokens: `VERIFIED`, `STALE`, `DATA_GAP` (model/team_metrics/availability),
 * `RESEARCH_ONLY` (`RESEARCH_ONLY_MARKET_STATUS`, line 41 — a market/odds
 * snapshot exists but has no durable provenance), `DATA_UNAVAILABLE`
 * (odds_status when no snapshot exists at all), `MODEL_READY`/
 * `MODEL_UNAVAILABLE` (the sibling `evidence_status` field), and
 * `CONFLICTING` (a value the TypeScript type already anticipates and
 * `betting-intelligence-dashboard.tsx` already branches on elsewhere).
 *
 * The wire type (`source_status: Record<string, string>` in
 * `betting-intelligence-api.ts`) is intentionally open-ended, so this module
 * **fails closed** exactly like `model-identity.ts`: an unrecognised token
 * yields a neutral label, never the raw string.
 *
 * Enforced by `evidence-state.test.ts`.
 */

export interface EvidenceStateDescriptor {
  label: string;
  tone: "positive" | "warning" | "info" | "neutral";
}

const EVIDENCE_STATES: Record<string, EvidenceStateDescriptor> = {
  VERIFIED: { label: "Verified", tone: "positive" },
  MODEL_READY: { label: "Verified", tone: "positive" },
  STALE: { label: "Stale", tone: "warning" },
  CONFLICTING: { label: "Limited evidence", tone: "warning" },
  DATA_GAP: { label: "Data unavailable", tone: "neutral" },
  DATA_UNAVAILABLE: { label: "Provider unavailable", tone: "neutral" },
  MODEL_UNAVAILABLE: { label: "Model unavailable", tone: "neutral" },
  RESEARCH_ONLY: { label: "Research mode", tone: "info" },
};

const FAIL_CLOSED_DEFAULT: EvidenceStateDescriptor = {
  label: "Status unavailable",
  tone: "neutral",
};

/** Fail-closed lookup: an unrecognised token never leaks the raw string. */
export function evidenceStateFor(token: unknown): EvidenceStateDescriptor {
  const key = String(token ?? "").toUpperCase();
  return EVIDENCE_STATES[key] ?? FAIL_CLOSED_DEFAULT;
}
