/**
 * evidence-copy-contract.test.ts
 *
 * Guard test for EVIDENCE_CODE_COPY in full-analysis-contract.ts.
 *
 * PURPOSE:
 *   Ensure every backend-emitted gap/evidence code has consumer-safe copy
 *   so raw feature identifiers never reach users.
 *
 * MAINTENANCE NOTE (§3.3 v5 directive):
 *   This test is hand-maintained, NOT auto-derived from feature_contract.json.
 *   Reason: feature_contract.json is the ML feature-schema contract, not a
 *   gap-code registry. Gap codes include non-feature identifiers like
 *   MODEL_GENERATION_UNCERTIFIED, causal_analysis, and variable-derived codes
 *   from full_analysis.py's _effective_kelly_cap() (e.g. LEAGUE_POLICY_UNAVAILABLE).
 *   A static AST scrape would silently miss roughly half the emitted codes.
 *
 *   When adding a new gap code to full_analysis.py or upcoming_match_service.py,
 *   also add it here and to EVIDENCE_CODE_COPY in full-analysis-contract.ts.
 *
 * SOURCES INSPECTED (2026-08-30):
 *   - backend/src/api/endpoints/full_analysis.py  (critical_gaps.append / advisory_gaps.append)
 *   - backend/src/services/upcoming_match_feature_service.py
 */

import { describe, test, expect } from "vitest";
import { describeEvidenceCode } from "./full-analysis-contract";

/**
 * Hand-maintained list of gap codes the backend emits.
 * Cross-checked against full_analysis.py and upcoming_match_service.py.
 *
 * Each entry: [code, isCasingDriftAlias]
 * Casing-drift aliases (lowercase) are from upcoming_match_service.py; their
 * UPPERCASE canonical siblings come from full_analysis.py.
 */
const BACKEND_EMITTED_CODES: string[] = [
  // ── Fixture / identity gaps ──────────────────────────────────────────────
  "FIXTURE_IDENTITY_UNVERIFIED",

  // ── Model / prediction gaps ──────────────────────────────────────────────
  "REQUIRED_MODEL_INPUTS_UNAVAILABLE",
  "MODEL_PREDICTION_UNAVAILABLE",
  "MODEL_GENERATION_UNCERTIFIED",
  "MODEL_UNCERTAINTY_UNAVAILABLE",
  "MODEL_PREDICTION_REDUCED_EVIDENCE",

  // ── Evidence freshness ───────────────────────────────────────────────────
  "STALE_REQUIRED_EVIDENCE",
  "STALE_ENRICHMENT_EVIDENCE",

  // ── Policy gaps ───────────────────────────────────────────────────────────
  "LEAGUE_POLICY_UNAVAILABLE",

  // ── Market gaps ───────────────────────────────────────────────────────────
  "COHERENT_1X2_MARKET_UNAVAILABLE",

  // ── Feature-level tactical / analytical gaps ──────────────────────────────
  "ppda_ratio",
  "progressive_carry_diff",
  "set_piece_xg_diff",
  "shot_quality_diff",
  "elo_league_adjusted",
  "causal_analysis",
  "key_passes_under_pressure_diff",
  // Observed live 2026-08-31 in advisory_gaps on EPL/SERIE_A/LA_LIGA fixtures;
  // was the only unmapped code across the 11 the backend actually emitted.
  "total_goals_expected",

  // ── Casing-drift aliases (upcoming_match_service.py uses lowercase) ────────
  // Without these aliases the code falls through to titleCaseCode() and the raw
  // feature identifier reaches the user.
  "model_generation_uncertified",
  "required_model_inputs_unavailable",

  // ── Staking disclosure codes (ADR-0011 / docs/DEBT.md item 108) ────────────
  // upcoming_match_service.py appends exactly one of these to data_gaps on every
  // fixture evaluated under the operator override. Today UpcomingMatch.data_gaps
  // is read only as a boolean by upcoming-matches-panel.tsx, so the fall-through
  // is latent rather than live — registering them here is what stops it becoming
  // live the first time any surface renders that array as text.
  "staking_under_operator_override",
  "staking_suppressed_by_risk_guard",
];

/**
 * The exact fall-through `describeEvidenceCode` uses when a code has no copy.
 *
 * ⚠️ THIS REPLICA IS THE WHOLE GUARD. Asserting on the *shape* of the rendered
 * string cannot work here, and this test asserted exactly that from the day it
 * was written until 2026-09-20 (docs/DEBT.md item 117): `titleCaseCode` opens
 * with `.replaceAll("_", " ")`, so its output can never contain an underscore
 * and can never match `/_diff$/`, `/_ratio$/` or `/^MODEL_/`. Every assertion
 * was structurally unfailable — deleting the long-registered `ppda_ratio` entry
 * from EVIDENCE_CODE_COPY left all 23 tests green. Verified by execution, not
 * by reading the code.
 *
 * Comparing against the fall-through instead asks the only question that
 * matters: does this code have real copy, or is it falling through?
 *
 * Kept in sync by `test_fall_through_replica_matches_the_real_implementation`
 * below — a replica that drifts from the original is a guard that lies.
 */
function titleCaseCodeReplica(code: string): string {
  return code
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

describe("Evidence copy contract", () => {
  test.each(BACKEND_EMITTED_CODES)(
    "describeEvidenceCode('%s') returns consumer-safe copy",
    (code: string) => {
      const result = describeEvidenceCode(code);

      // Must return a non-empty string
      expect(typeof result).toBe("string");
      expect(result.length).toBeGreaterThan(0);

      // Must not be the raw code itself
      expect(result).not.toBe(code);

      // THE ASSERTION THAT BITES: the code must have real copy, not the
      // title-cased fall-through. A shape check cannot express this, because
      // the fall-through already produces underscore-free Title Case.
      expect(result).not.toBe(titleCaseCodeReplica(code));

      // Belt-and-braces: no raw identifier residue survived the mapped copy.
      expect(result).not.toContain("_");
    }
  );

  test("fall-through replica matches the real implementation", () => {
    // A replica that drifts from titleCaseCode() would make every assertion
    // above vacuously true again — the exact failure this rewrite fixes.
    // Codes chosen to exercise each transform: separators, casing, digits.
    for (const code of ["ppda_ratio", "MODEL_GENERATION_UNCERTIFIED", "set_piece_xg_diff", "causal_analysis"]) {
      expect(describeEvidenceCode(`__unmapped__${code}`)).toBe(
        titleCaseCodeReplica(`__unmapped__${code}`)
      );
    }
  });

  test("an unregistered code is detectably falling through", () => {
    // Guard the guard: prove the assertion above can actually fail, rather
    // than trusting that it can. If this ever passes, the check is inert.
    const unmapped = "definitely_not_a_registered_gap_code";
    expect(describeEvidenceCode(unmapped)).toBe(titleCaseCodeReplica(unmapped));
  });
});
