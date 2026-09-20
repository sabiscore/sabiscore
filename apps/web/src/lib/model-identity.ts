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

/** The backend's `ALLOWED_CERTIFICATION_STATES`, mirrored for exhaustiveness. */
export const OPERATOR_OVERRIDE_STATE = "OPERATOR_OVERRIDE_UNCERTIFIED";

/**
 * §11: `certified model` → "Production-validated"; `unverified model` →
 * "Research mode". The backend's `ALLOWED_CERTIFICATION_STATES` is
 * {UNVERIFIED, CERTIFIED, OPERATOR_OVERRIDE_UNCERTIFIED};
 * `/api/models/status` can also emit "UNKNOWN".
 *
 * ⚠️ The override is NOT certification (ADR-0011) and must not borrow its
 * language — but it also must not read as inert. Under an override the system
 * is actively publishing stakes from a model that failed its gates, so
 * "Pending validation" (the fail-closed default this state would otherwise
 * fall through to) would understate what is happening, not overstate it.
 */
export function certificationLabel(state: unknown): string {
  switch (String(state ?? "").toUpperCase()) {
    case "CERTIFIED":
      return "Production-validated";
    case "UNVERIFIED":
      return "Research mode";
    case OPERATOR_OVERRIDE_STATE:
      return "Unvalidated · staking under operator override";
    default:
      return "Pending validation";
  }
}

/**
 * Certification, strictly. An operator override permits staking without
 * conferring certification, so this stays false for it — matching the
 * backend's own `active_generation_is_certified()`, which returns false under
 * an override for the same reason.
 */
export function certificationIsCertified(state: unknown): boolean {
  return String(state ?? "").toUpperCase() === "CERTIFIED";
}

/** True when staking is live on an operator override rather than earned. */
export function isOperatorOverride(state: unknown): boolean {
  return String(state ?? "").toUpperCase() === OPERATOR_OVERRIDE_STATE;
}

/**
 * ⚠️ `promotion_state` alone can no longer describe serving behaviour.
 *
 * `ACTIVE_FAIL_CLOSED` used to imply "staking blocked", and that sentence was
 * true for as long as certification was the only thing that could unblock
 * staking. Under ADR-0011 the manifest keeps `ACTIVE_FAIL_CLOSED` while
 * `staking_authorization()` returns `permitted=true` — so echoing the old
 * copy would tell a reader staking is blocked on a system that is actively
 * staking. The certification state is therefore required to describe it
 * honestly, and is accepted as a second argument rather than inferred.
 */
export function promotionLabel(state: unknown, certificationState?: unknown): string {
  const promotion = String(state ?? "").toUpperCase();
  if (promotion !== "ACTIVE_FAIL_CLOSED") return "Status unavailable";
  if (isOperatorOverride(certificationState)) {
    return "Serving forecasts · staking enabled by operator override";
  }
  if (certificationIsCertified(certificationState)) {
    return "Serving forecasts · staking permitted";
  }
  return "Serving forecasts · staking blocked";
}
