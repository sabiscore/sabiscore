/**
 * APEX §11 — internal provenance IDs must never become consumer branding.
 *
 * `v5_phase7`, `v5_phase7-20260808`, `phase7_68`, `6bab9609e900c253`,
 * `SoftmaxMetaModel` and `ACTIVE_FAIL_CLOSED` are engineering provenance. The
 * directive names several of them explicitly as forbidden on consumer
 * surfaces, permitting them only in "developer/admin diagnostics" — which in
 * this app means `/admin/model-health` (bearer-token guarded, and
 * `robots.ts`-disallowed).
 *
 * This module is the single mapping from internal state to §11's product
 * language. It **fails closed**: an unrecognised value yields a neutral label,
 * never the raw string, so a backend enum added later cannot silently leak.
 *
 * Enforced repo-wide by `model-identity-contract.test.ts`, which is the reason
 * to add a mapping here rather than a one-off ternary at a call site.
 */

/**
 * Manifest fields that carry engineering provenance and no consumer meaning.
 * The contract test uses this list; keep it in sync with
 * `backend/models/active_generation.json`.
 */
export const INTERNAL_PROVENANCE_FIELDS = [
  "active_version",
  "generation",
  "generation_hash",
  "feature_schema_version",
  "served_head",
  "model_version",
  "artifact",
  "artifact_sha256",
] as const;

/** §11: `model_version` → "Model generation". */
export function generationLabel(activeVersion: unknown): string {
  const match = /^v(\d+)[._-]/i.exec(String(activeVersion ?? ""));
  return match ? `Generation ${match[1]}` : "Current generation";
}

/**
 * §11: `certified model` → "Production-validated"; `unverified model` →
 * "Research mode". The backend's `ALLOWED_CERTIFICATION_STATES` is exactly
 * {UNVERIFIED, CERTIFIED}; `/api/models/status` can also emit "UNKNOWN".
 */
export function certificationLabel(state: unknown): string {
  switch (String(state ?? "").toUpperCase()) {
    case "CERTIFIED":
      return "Production-validated";
    case "UNVERIFIED":
      return "Research mode";
    default:
      return "Pending validation";
  }
}

/**
 * Whether staking is permitted follows certification, so the label must never
 * imply availability the backend has not granted.
 */
export function certificationIsCertified(state: unknown): boolean {
  return String(state ?? "").toUpperCase() === "CERTIFIED";
}

/**
 * `ACTIVE_FAIL_CLOSED` is the only promotion state the manifest currently
 * carries. Anything else is described neutrally rather than echoed.
 */
export function promotionLabel(state: unknown): string {
  switch (String(state ?? "").toUpperCase()) {
    case "ACTIVE_FAIL_CLOSED":
      return "Serving forecasts · staking blocked";
    default:
      return "Status unavailable";
  }
}
