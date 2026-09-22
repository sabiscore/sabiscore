# Blocker Matrix — 2026-09-21

Snapshot scope: refreshed 2026-09-22 from current `master` using live repository evidence from [docs/DEBT.md](../DEBT.md), [docs/PLATFORM_OPERATIONS_STANDARDS.md](../PLATFORM_OPERATIONS_STANDARDS.md), targeted tests, and current operator-gate probes.

Classification rule:
- `CODE-FIXABLE` means the blocker can be resolved by repository changes without external console access or waiting for new real-world data.
- `OPERATOR-ONLY` means resolution requires GitHub/Vercel/Render/AWS/credential/branch-protection actions outside repo code.
- `DATA/RESEARCH` means unblock requires elapsed settled volume, retraining artifacts, or explicit research decisions rather than immediate code edits.

## A) Code-Fixable Blockers

| ID | Blocker | Class | State | Evidence | Next Action |
|---|---|---|---|---|---|
| 126 | `requires_bash` skip condition could fail instead of skipping on broken WSL launcher | CODE-FIXABLE | RESOLVED | `docs/DEBT.md` item 126, `backend/tests/unit/test_zero_fabrication_scan_enforces.py` | Keep guard test in CI/local suite |
| 104 (script side) | Remote CI verifier previously risked stale assumptions from hardcoded required workflow names | CODE-FIXABLE | RESOLVED | `scripts/verify_remote_ci.sh`, `backend/tests/unit/test_verify_remote_ci_ruleset.py` | Keep ruleset-context query path; re-run tests on script changes |
| 67 | Frontend Sentry observability instrumentation gap | CODE-FIXABLE | RESOLVED (frontend) / ACCEPTED (backend operator-gated) | `docs/DEBT.md` item 67 | Keep current frontend coverage and revisit backend DSN policy only when operator scope opens |

## B) Operator-Only Blockers

| ID | Blocker | Class | State | Evidence | Required Operator Action |
|---|---|---|---|---|---|
| 118 | ADR-0011 per-fixture staking disclosure remains inert by product decision | OPERATOR-ONLY | OPEN | `docs/DEBT.md` item 118 (`OPEN — OPERATOR DECISION`) | Approve/decline exposing prediction-backed fixture panel by default |
| 104 (platform side) | Branch protection required-status-check policy (GitHub ruleset) | OPERATOR-ONLY | RESOLVED (this cycle) | `docs/DEBT.md` item 104 | Reconfirm contexts after any workflow rename |
| 28 | S3 evidence-storage operator gate (last credentialed signal 403) | OPERATOR-ONLY | OPEN | `docs/DEBT.md` item 28 (`NEXT`, 2026-09-22 rerun logged as non-diagnostic without bucket env) | Fix IAM policy in AWS console and rerun probe with bucket + credentials present |
| 16 | Historical secret revocation + release infra residuals | OPERATOR-ONLY | OPEN (partial) | `docs/DEBT.md` item 16 (`NEXT`, 2026-09-22 runner-backed CI success re-confirmed; historical-secret + Docker proofs still open) | Provide revocation evidence for historical fingerprints and fresh Docker image proof |
| 85 | Production alias routing inconsistency (legacy alias) | OPERATOR-ONLY | RESOLVED (monitor) | `docs/DEBT.md` item 85 (`RESOLVED`, 2026-09-22 parity probe healthy) | Keep fallback alias documented; re-probe parity after each release |

## C) Data / Research / Retrain Blockers

| ID | Blocker | Class | State | Evidence | Unblock Condition |
|---|---|---|---|---|---|
| 124 | Served generation lacks reproducibility binding (origin not recorded) | DATA/RESEARCH | OPEN | `docs/DEBT.md` item 124 (`OPEN — needs new generation`; re-verified 2026-09-22, verdict unchanged) | Produce a new generation with full manifest provenance |
| 114 | Candidate-vs-incumbent re-verification blocked by absent candidate `.pkl` artifacts in fresh checkout | DATA/RESEARCH | RESOLVED (this workspace) / re-opens on a genuinely fresh checkout | `docs/DEBT.md` item 114 (re-verified 2026-09-22: reran comparison + availability-matrix scripts against existing local artifacts, result matches prior evidence exactly, no drift) | A fresh clone with no local training run still needs a retrain first |
| 37 | Market-block mismatch deadlock moved to data-bound state | DATA/RESEARCH | BLOCKED-ON-DATA | `docs/DEBT.md` item 37 | Gather required evaluation data and rerun promotion evidence |
| 9 | Portfolio exposure constants still placeholder-calibrated | DATA/RESEARCH | NEXT | `docs/DEBT.md` item 9 | Run calibration at adequate group count and approve apply |
| 8 | Drift monitor lacks required settled reference volume | DATA/RESEARCH | NEXT | `docs/DEBT.md` item 8 | Reach settled-volume trigger and wire production caller |
| 50 | Ensemble-dispersion uncertainty inversion remains open research blocker | DATA/RESEARCH | NEXT | `docs/DEBT.md` item 50 | Resolve hypothesis through measured research outcome |

## Current Sweep Outcome

- 2026-09-22 refresh revalidated item 85 parity and item 16 runner-backed dispatch health with live probes.
- Item 28 remains operator-blocked; latest local probe result is non-diagnostic when bucket env is absent and does not supersede the prior credentialed 403 evidence.
- Remaining blockers are predominantly `OPERATOR-ONLY` or `DATA/RESEARCH` constrained; forcing code changes here would create non-evidence-based churn.
