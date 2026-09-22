# SabiScore Upgraded Execution Directive

Date: 2026-09-22  
Scope: Final production-readiness push aligned to the original project mandate and current repository evidence.

## 1) Mission and Constraint Baseline

This directive operationalizes the original request to deliver a fully functional, visually cohesive, intelligent, consumer-ready, prediction-ready SabiScore platform while preserving:

- Zero fabrication and fail-closed evidence behavior.
- Existing architecture authority (FastAPI, Next.js, PostgreSQL, Redis, scraper).
- No payments/subscriptions/affiliate monetization.
- No automated betting execution.

## 2) Current-State Truth (as of this snapshot)

Use the current blocker map and debt ledger as authoritative:

- Active blocker split: docs/certification/blocker-matrix-2026-09-21.md
- Debt ledger: docs/DEBT.md
- Production execution governance: docs/PRODUCTION_EXECUTIVE_DIRECTIVE.md
- Data intelligence governance: docs/DATA_INTELLIGENCE_DIRECTIVE.md
- Ops standards: docs/PLATFORM_OPERATIONS_STANDARDS.md

Practical consequence:

- There is no remaining high-severity immediate code-only blocker in the current sweep.
- Remaining blockers are concentrated in operator-only and data/research-gated classes.

## 3) Mapping to Original Prompt (R1-R5)

### R1. Data / Provider Foundation & ML Parity

Required completion path:

1. Operator closure of external platform blockers:
   - Item 28 (S3 IAM 403)
   - Item 16 (credential and infra residual proofs)
2. Data/research closure for certification evidence:
   - Item 124 (served generation reproducibility binding)
   - Item 114 (candidate-vs-incumbent re-verification with artifacts)
   - Item 50 (uncertainty inversion research outcome)
3. Maintain strict fail-closed uncertainty and no synthetic confidence.

### R2. Trust, Performance, User Identity

Current status:

- Frontend observability (item 67) is closed on frontend and accepted backend-side.
- Remaining trust gap is disclosure-surface policy, not instrumentation code.

Required decision:

- Item 118 (operator decision): whether to expose prediction-backed per-fixture staking disclosure by default on the fixtures panel.

### R3. Retention, Sharing, SEO, Visual Cohesion

Current status:

- Core UX/product surfaces are operational.
- Remaining release blockers are not primarily design-system defects.

Required action:

- Keep this axis in maintenance mode unless new user-facing regressions appear.

### R4. Developer Platform & Constraints

Current status:

- No monetization activation is required for this milestone.

Required action:

- Preserve FREE-only runtime behavior and entitlement groundwork without enabling paid flows.

### R5. UX Integrity & Empty-State Honesty

Current status:

- Governance and tests enforce no fabricated predictions/confidence.

Required action:

- Continue contract and copy guards; no policy loosening to force promotional messaging.

## 4) Gate-Clearing Plan (Execution-Ordered)

## Phase A — Operator Gating Closure (Highest Leverage)

Goal: remove non-code blockers that prevent evidence from accumulating or being publishable.

Checklist:

1. Resolve item 28 (S3 IAM) and verify successful evidence storage writes.
2. Resolve item 16 (credential revocation proof + release infra residuals).
3. Re-validate item 85 closure evidence in current production state and keep alias fallback documented.
4. Decide item 118 (fixtures-panel disclosure default):
   - Option A: keep current bounded DB-read panel behavior (no default predictions).
   - Option B: authorize prediction-backed default panel and accept increased inference cost.

Exit criteria:

- All operator decisions recorded in docs/DEBT.md with evidence links.

## Phase B — Reproducibility and Candidate Evidence Integrity

Goal: close model-lineage and candidate-comparison credibility gaps.

Checklist:

1. Item 124:
   - Produce a new generation with full provenance binding emitted at train time.
   - Validate with audit_release_identity evidence.
2. Item 114:
   - Ensure candidate artifacts are available for re-verification in fresh checkout context, or rerun full retrain/eval pipeline and commit evidence artifacts.
3. Regenerate candidate comparison evidence and restate gate outcomes using current corpus.

Exit criteria:

- Release identity marked complete for the served generation lineage.
- Candidate-vs-incumbent verdict reproducible from repository artifacts.

## Phase C — Certification Evidence Completion

Goal: convert remaining gate statuses from unknown/blocked where technically possible.

Checklist:

1. Recompute calibration and scoring evidence on current settled set:
   - G11, G12, G14, G15 evidence refresh
2. Continue uncertainty program (item 50):
   - Publish next tested hypothesis outcome (pass/fail/inconclusive) with reproducible method.
3. Market baseline gate (G18):
   - Keep method-correct baseline and report decision transparently (no threshold drift).

Exit criteria:

- Certification dossier updated with clear PASS/FAIL/UNVERIFIED rationale per gate.

## Phase D — Final Production Readiness Declaration

Goal: issue an auditable release posture, not a narrative claim.

Deliverables:

1. Updated blocker matrix with all remaining items in operator/data classes or closed.
2. Updated certification report with explicit final decision.
3. Release note summarizing what changed, what remains blocked, and why.

Decision outcomes allowed:

- PROMOTE
- PROMOTE_RESEARCH_ONLY
- HOLD

No fourth outcome and no implicit promotion.

## 5) Immediate Next Milestone (Do First)

Execute Phase A item 118 decision package plus item 28 status package in one operator-ready bundle.

Why first:

- It removes the largest non-code uncertainty in customer disclosure behavior and evidence infrastructure.
- It unblocks later technical work from policy ambiguity.

Execution support artifact:

- One-page operator checklist: docs/certification/operator-action-pack-118-28-16-85-2026-09-22.md

## 6) Verification Contract for This Directive

For each completed sub-phase:

1. Update docs/DEBT.md with evidence-backed state change.
2. Update CHANGELOG.md with shipped scope and validation commands.
3. Re-run only the minimal relevant validation stack first, then broader suites if touched scope requires it.

No state transitions are accepted without written evidence.
