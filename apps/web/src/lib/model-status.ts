import { certificationLabel, generationLabel } from "@/lib/model-identity";
import type { StakingAuthorization } from "@/lib/api";

export const MODEL_STATUS_QUERY_KEY = ["model-status"] as const;

export type ModelRecord = {
  feature_schema_version?: unknown;
  feature_count?: unknown;
  served_head?: unknown;
  artifact?: unknown;
  artifact_sha256?: unknown;
  required?: unknown;
  loaded?: unknown;
};

export type ModelStatus = {
  active_version?: unknown;
  generation?: unknown;
  generation_hash?: unknown;
  certification_state?: unknown;
  promotion_state?: unknown;
  validation_status?: unknown;
  manifest_valid?: unknown;
  models_loaded?: unknown;
  stake_permitted?: unknown;
  /** "CERTIFIED" | "OPERATOR_OVERRIDE" | "NONE" | "UNKNOWN" (ADR-0011). */
  staking_basis?: unknown;
  /** The full ADR-0011 authorization block. Read via normalizeStakingAuthorization. */
  staking_authorization?: unknown;
  models?: Record<string, ModelRecord>;
};

/**
 * Narrow the untyped `staking_authorization` block to something renderable,
 * or return null.
 *
 * ⚠️ Fails closed, deliberately and in one direction only. This function can
 * only ever *withhold* the override disclosure, never fabricate one: it
 * returns non-null solely when the backend said `is_override === true`. The
 * cost of a false negative is a missing warning on a surface that already
 * shows "Unvalidated · staking under operator override"; the cost of a false
 * positive would be accusing a genuinely certified model of riding an
 * override. Neither is good, but only one of them invents a fact.
 */
export function normalizeStakingAuthorization(
  status: ModelStatus | null | undefined,
): StakingAuthorization | null {
  const raw = status?.staking_authorization;
  if (!raw || typeof raw !== "object") return null;
  const auth = raw as Record<string, unknown>;
  if (auth.is_override !== true) return null;

  return {
    permitted: auth.permitted === true,
    basis: typeof auth.basis === "string" ? auth.basis : "UNKNOWN",
    certification_state:
      typeof auth.certification_state === "string" ? auth.certification_state : "UNKNOWN",
    is_override: true,
    authorizing_identity:
      typeof auth.authorizing_identity === "string" ? auth.authorizing_identity : null,
    rationale: typeof auth.rationale === "string" ? auth.rationale : null,
    authorized_at: typeof auth.authorized_at === "string" ? auth.authorized_at : null,
    acknowledged_failures: Array.isArray(auth.acknowledged_failures)
      ? auth.acknowledged_failures.filter((f): f is string => typeof f === "string")
      : [],
  };
}

export async function fetchModelStatus(): Promise<ModelStatus> {
  const response = await fetch("/api/models/status", { cache: "no-store" });
  if (!response.ok) throw new Error("Model status unavailable");
  return response.json() as Promise<ModelStatus>;
}

/**
 * Consumer-facing. Returns §11 product language, never the raw
 * `active_version` — see `lib/model-identity.ts` for why, and
 * `/admin/model-health` for the raw provenance.
 */
export function displayModelVersion(status: ModelStatus | null | undefined): string {
  if (!status?.active_version) return "Unavailable";
  return generationLabel(status.active_version);
}

/** Consumer-facing. `UNVERIFIED` → "Research mode", not the raw enum. */
export function displayCertification(status: ModelStatus | null | undefined): string {
  if (!status?.certification_state) return "Unavailable";
  return certificationLabel(status.certification_state);
}
