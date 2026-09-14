# SabiScore v7.3 — Blocked-Gate Release Report

**Repository:** `sabiscore/sabiscore`  
**Candidate HEAD:** `d20e2fa01c7dc1f5829a8ba7203c5c944f5c4c44`  
**Date:** 2026-09-14  
**Decision:** `HOLD`  
**Certification posture:** Research Mode / fail-closed  

## Executive disposition

This report records the current release boundary without converting unavailable evidence into PASS. The candidate is deployed in production, but the current HEAD has not completed a reproducible v7.3 certification cycle. No threshold has been weakened, no staking capability has been enabled, and no market-edge claim is promoted.

## Confirmed calibration-state defect

`backend/src/models/prediction.py` correctly executes the persisted stacking `meta_model`, but the current serving state labels every successful meta-model invocation as `calibration_applied=True`. The authoritative label map explicitly identifies `SoftmaxMetaModel` as `"none"`, so a successful uncalibrated Softmax head can be surfaced as calibration-applied.

Required correction:

1. Treat `SoftmaxMetaModel` as uncalibrated: `calibration_applied=False`, serving method `raw`.
2. Set `calibration_applied=True` only for explicitly recognized calibrated meta-model classes or a separately executed fitted calibrator whose application succeeds.
3. Treat unknown future meta-model classes as unverified calibration, not calibrated provenance.
4. Add regression coverage for Softmax, recognized calibrated meta-models, and unknown meta-models.
5. Regenerate calibration/serving evidence after the patch; do not infer certification from source inspection alone.

Tracked in GitHub issue #187.

## Gate state

| Gate | Status | Reason |
|---|---|---|
| G01 Repository integrity | UNVERIFIED | Current remote HEAD is known, but a local clean working-tree verification was not available in this execution environment. |
| G02 Test suite | BLOCKED | No current full test execution was available; GitHub Actions has no workflow run for candidate HEAD. |
| G03 Static analysis | BLOCKED | Current `make verify` / lint/typecheck were not executed for candidate HEAD. |
| G04 Build | BLOCKED | Current production build was not independently reproduced from candidate HEAD. |
| G05 Schema migration | UNVERIFIED | Current repository contains migration `0014_social_auth_identities`; direct live migration-head verification was not produced in this pass. |
| G06 Artifact integrity | UNVERIFIED | Existing certification evidence targets an older commit and cannot certify candidate HEAD. |
| G07 Feature contract | UNVERIFIED | Requires current artifact/serving verification. |
| G08 Data provenance | UNVERIFIED | Existing provider evidence is historical relative to this candidate certification. |
| G09 Temporal leakage | UNVERIFIED | Existing leakage tests are not a substitute for a fresh candidate run. |
| G10 Coverage | UNVERIFIED | No fresh candidate certification run. |
| G11 Calibration | FAIL | Serving contract can incorrectly report calibration-applied for an uncalibrated `SoftmaxMetaModel`. |
| G12 Brier | UNVERIFIED | No fresh candidate evaluation artifact. |
| G13 RPS | UNVERIFIED | Historical values cannot be promoted to candidate certification evidence. |
| G14 Log loss | UNVERIFIED | No fresh candidate evaluation artifact. |
| G15 ECE | UNVERIFIED | No fresh candidate calibration evaluation. |
| G16 Uncertainty | FAIL | Measured BNN uncertainty remains unavailable; a probability-derived proxy is prohibited. |
| G17 Drift PSI | NOT_APPLICABLE | Existing designed maturity floor remains applicable; not a release blocker by itself. |
| G18 Market baseline | FAIL | Latest verified evidence did not establish the required market-baseline promotion condition. |
| G19 Market CLV | UNVERIFIED | Informational evidence is not sufficient to certify current candidate state. |
| G20 Security | UNVERIFIED | No fresh candidate security verification. |
| G21 Observability | UNVERIFIED | No fresh candidate observability verification. |
| G22 Backend smoke | UNVERIFIED | Production telemetry is useful operational evidence but does not replace candidate smoke certification. |
| G23 Frontend smoke | UNVERIFIED | No fresh candidate end-to-end certification run. |
| G24 Deployment parity | UNVERIFIED | Frontend is at candidate HEAD while backend is on a different live deploy SHA; current difference is not independently proven incompatible, but parity is not certified. |
| G25 Customer UX | UNVERIFIED | Current source posture is not a substitute for candidate smoke evidence. |
| G26 Ingestion reliability | UNVERIFIED | No fresh candidate ingestion certification run. |
| G27 Calibrator serving parity | FAIL | Calibration-state provenance is currently overstated for Softmax meta-model inference. |
| G28 Release reproducibility | FAIL | Existing certification report is tied to older commit `4396d65`; no reproducible current-HEAD certification artifact exists. |
| G29 Dataset integrity | UNVERIFIED | No fresh candidate dataset integrity run. |
| G30 Rollback readiness | UNVERIFIED | Current rollback evidence was not independently regenerated in this pass. |

## CI status

GitHub Actions returned **no workflow runs for candidate HEAD `d20e2fa...`**. Under v7.3 INV-17, absence/blockage of required CI evidence is not a PASS and therefore cannot be silently cleared.

## Promotion decision

`HOLD`.

`PROMOTE_RESEARCH_ONLY` is not currently supportable because required calibration-state correctness, uncertainty evidence, market-baseline evidence, current candidate reproducibility, and CI/test evidence are unresolved. The correct behavior is to preserve fail-closed research mode rather than reinterpret missing evidence as success.

## Required exit sequence

1. Apply the calibration-state patch in `backend/src/models/prediction.py`.
2. Add the focused regression tests to `backend/tests/test_prediction_engine.py`.
3. Run the focused backend tests, then canonical `make verify`.
4. Restore/resolve the GitHub Actions billing/runner blocker and obtain green required checks.
5. Re-run artifact, feature-contract, calibration, Brier/RPS/log-loss/ECE, uncertainty, market-baseline, deployment-parity, and smoke gates against the exact candidate SHA.
6. Regenerate the machine-readable P18 certification report with hashes and exact evidence sources.
7. Only then reconsider `PROMOTE_RESEARCH_ONLY`; do not enable staking or actionable promotion merely because the calibration defect is fixed.

## Non-actions

- No certification threshold was relaxed.
- No market-baseline failure was reclassified as informational.
- No uncertainty proxy was substituted for measured uncertainty.
- No stale report was reused as current certification.
- No production staking/actionability was enabled.
