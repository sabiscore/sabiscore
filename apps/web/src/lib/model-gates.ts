/**
 * Display constants for model-performance colouring — NOT certified policy gates.
 *
 * The authoritative promotion gates live in
 * `backend/src/models/certification_policy.py` (version-stamped, SHA-256-hashed).
 * The actual RPS gate there is **relative**: candidate mean RPS must be strictly
 * better than the incumbent (`primary_metric_improvement.min_mean_rps_improvement
 * > 0.0`). No absolute RPS threshold exists in the frozen policy.
 *
 * `RPS_DISPLAY_FLOOR` is retained only to colour the live-RPS tile on the
 * performance page green/red as a reader aid. It is a legacy display target —
 * it is not version-stamped, not covered by `policy_sha256()`, and must never
 * be cited as a certification gate. If the value changes, update this constant
 * AND grep for bare "0.21" in prose files.
 */

/** Legacy display floor for the RPS tile. NOT a frozen certification-policy gate.
 *  The actual promotion gate is relative — see certification_policy.py. */
export const RPS_DISPLAY_FLOOR = 0.21;

/** Uniform choice across a 3-outcome market — a property of the problem, not a
 *  measurement. The backend emits this alongside real series data; this constant
 *  exists only as the fallback when it has not answered yet. */
export const RANDOM_BASELINE_ACCURACY = 1 / 3;

/** True when a measured RPS is at or below the display floor.
 *  Returns null for an absent measurement (renders "—", not a failure).
 *  Note: this colours the tile, it does not certify promotion. */
export function meetsRpsGate(rps: number | null | undefined): boolean | null {
  return typeof rps === "number" && Number.isFinite(rps) ? rps <= RPS_DISPLAY_FLOOR : null;
}
