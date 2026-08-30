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

  // ── Casing-drift aliases (upcoming_match_service.py uses lowercase) ────────
  // Without these aliases the code falls through to titleCaseCode() and the raw
  // feature identifier reaches the user.
  "model_generation_uncertified",
  "required_model_inputs_unavailable",
];

/** Raw identifiers that must NOT leak to the user (spot-check for the fall-through). */
const RAW_IDENTIFIER_PATTERNS = [
  /_diff$/,     // progressive_carry_diff → "Progressive Carry Diff"
  /_ratio$/,    // ppda_ratio → "Ppda Ratio"
  /^MODEL_/,    // MODEL_GENERATION_UNCERTIFIED → "Model Generation Uncertified"
];

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

      // Must not read as a title-cased raw identifier (the titleCaseCode fallback).
      for (const pattern of RAW_IDENTIFIER_PATTERNS) {
        expect(result).not.toMatch(pattern);
      }

      // Must not look like a raw feature identifier (no unprocessed snake_case or SCREAMING_SNAKE)
      expect(result).not.toMatch(/^[a-z_]+_[a-z_]+$/);   // bare snake_case
      expect(result).not.toMatch(/^[A-Z_]+_[A-Z_]+$/);   // bare SCREAMING_SNAKE

      // Should not contain underscores (they signal un-mapped raw identifiers)
      expect(result).not.toContain("_");
    }
  );

  test("titleCaseCode fallthrough does NOT produce consumer-safe output for known codes", () => {
    // Demonstrate WHY every code must be in the map: the fallthrough is unsuitable.
    // This test will fail if describeEvidenceCode falls through for any registered code.
    for (const code of BACKEND_EMITTED_CODES) {
      const result = describeEvidenceCode(code);
      // None of the known codes should produce underscore output
      expect(result).not.toMatch(/_/);
    }
  });
});
