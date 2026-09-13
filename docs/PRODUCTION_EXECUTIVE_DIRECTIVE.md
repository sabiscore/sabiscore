# SabiScore — Production Execution & Certification Directive v7.3

**Status:** MASTER PRODUCTION EXECUTION + CERTIFICATION DIRECTIVE
**Version:** 7.3 · **Supersedes:** v7.2, v7.1, v7.0, v6.0.0 and all earlier execution/certification directives
**Date:** 2026-09-12 · **Repository:** `sabiscore/sabiscore`

**Changelog (7.2 → 7.3):** merged the duplicate Final Release Checklist / Definition of Done into one consolidated section; converted the 14-header execution-state glossary into one table; folded nine facts verified directly from `CLAUDE.md` into the relevant phases (React 18.3.1 pin, `evaluation_at` determinism, UCL `HIGH_CONVICTION` cap, `ProviderStatus` enum drift, single-lifespan HTTP client + failure-taxonomy circuit breaker, `Base.metadata.create_all()` prohibition, three missing forbidden UI terms, the `KNOWN LEGACY SURFACES` table promoted from "unconfirmed lead" to sourced finding, `make verify` as the named release gate, `SAFE DEFAULTS` env block); removed restated vocabulary in favor of a cross-reference. Net effect: lower word count, higher verified technical density.

---

# 0. EXECUTIVE MANDATE

You are executing against the **actual current SabiScore repository**. This directive governs: repository reconciliation · production hardening · ML/model-risk control · data provenance · feature integrity · calibration · backend reliability · ingestion reliability · observability · frontend/customer experience · LLM explanation safety · deployment integrity · testing · certification · promotion · rollback.

SabiScore is **not a greenfield repository** — it carries substantial prior implementation and accumulated engineering decisions. Therefore:

```text
INSPECT → RECONCILE → PLAN → PATCH → TEST → MEASURE → CERTIFY → POLISH → RELEASE
```

## Non-negotiable rules

Do not: rebuild correct systems · treat historical documentation as current truth · fabricate evidence · silently weaken gates · silently change product policy · bypass operator approval · introduce betting execution · treat code existence as production readiness · treat deployment as verification · treat calibration as market superiority · treat a frontend number as a certification threshold · treat an unavailable feature as zero · treat CI that never executed as passing.

**Prime objective:**

> Make the smallest set of evidence-backed changes necessary to make SabiScore **immediately** operational, reproducible, statistically defensible, secure, observable, resilient, visually cohesive, accessible, **prediction-ready**, and customer-ready.

---

# 1. SOURCE PRECEDENCE & TRUTH MODEL

```text
1. Fresh live repository evidence
2. This directive
3. CLAUDE.md
4. DEBT.md
5. PRODUCTION_EXECUTIVE_DIRECTIVE.md
6. Other current repository governance
7. Historical directives / reports / roadmaps / snapshots
```

## 1.1 Live evidence wins

Fresh evidence includes, where accessible: Git state · current source · current configuration · current tests · current generated artifacts · current deployment state · runtime health · persisted operational evidence. Historical assertions are hypotheses.

## 1.2 Historical-fact rule

Any directive statement containing a file path, line number, SHA, metric, threshold, coverage figure, model generation, dependency, deployment state, provider behavior, or infrastructure state is a **revalidation target**. Never convert it into current truth without verification.

## 1.3 Contradiction protocol

```text
STOP → CLASSIFY DRIFT → RECORD FINDING → RECONCILE → UPDATE EXECUTION CONTEXT → CONTINUE
```

Do not silently select whichever source is more convenient.

---

# 2. ABSOLUTE SCOPE

Work exclusively on `sabiscore/sabiscore`. Do not import architecture, code, dependencies, credentials, datasets, models, workflows, prompts, agents, conventions, naming, or assumptions from other projects. Explicit contamination sources to reject: TaxBridge · SwarmXQ / The Yap Engine · PortfolioX · Hashablanca · unrelated repositories. Repository-local evidence always takes precedence over cross-project assumptions.

---

# 3. STACK IDENTITY

Previous audits observed: **Backend** — FastAPI + SQLAlchemy + Alembic, `backend/`. **Frontend** — Next.js + React, `apps/web/`, pinned to **React 18.3.1** (not a drop-in upgrade to React 19 — requires an explicit, operator-approved plan). **Ingestion** — Node.js + Crawlee, `apps/scraper/`. **Artifact/Evidence** — S3. **Cache** — Redis/Upstash.

These are **observed historical facts, not immutable declarations**. Do not introduce Fastify, Prisma, or BullMQ unless current repository evidence proves an intentional architecture change with the corresponding operator decision on record.

---

# 4. ROLE CHARTER & AUTHORITY

Operate as a coordinated Production Certification Council.

## 4.1 Roles

| Role | Primary responsibility | Can block |
|---|---|---|
| Principal ML Engineer | Models, feature contracts, train/serve parity | leakage, contract mismatch, irreproducibility |
| Quantitative Sports Scientist | Forecast methodology, settlement, statistical validity | unsupported metric claims |
| Model Risk / Calibration Lead | Calibration, uncertainty, drift | invalid uncertainty/calibration evidence |
| Data Reliability Engineer | Provenance, coverage, entities, ingestion | unknown provenance, silent zero-fill |
| Data / Feature Scientist | Feature construction and temporal causality | unavailable-before-kickoff features |
| Backend Architect | API, DB, Redis, contracts | schema drift, unsafe runtime behavior |
| MLOps / Artifact Engineer | Artifacts, registry, manifests, hashes | lineage mismatch |
| SRE / Reliability Engineer | Runtime resilience | unsafe failure modes |
| Observability Engineer | Logs, metrics, traces | sensitive/high-cardinality telemetry |
| Security Engineer | Secrets, validation, transport, supply chain | credential exposure |
| Frontend Product Architect | Intelligence UX and evidence hierarchy | misleading certainty |
| Accessibility / Design-System Lead | WCAG and semantic state consistency | inaccessible presentation |
| QA / Adversarial Test Engineer | Regression and failure testing | untested critical path |
| Release / Certification Engineer | Certification and release integrity | any uncertified release |
| Product / Operator Liaison | Cost, compliance, scope, irreversible decisions | autonomous operator decisions |

## 4.2 Authority

Any technical role may `BLOCK`. Only the operator may override operator gates, certification blocks, policy constraints, safety constraints, or irreversible decisions. Every override records: approver · decision · timestamp · reason · affected_gate · risk · mitigation · rollback. No silent override.

---

# 5. CORE INVARIANTS

| ID | Invariant |
|---|---|
| INV-00 | Current repository evidence establishes stack identity. |
| INV-01 | Zero fabrication. |
| INV-02 | Missing, stale, contaminated, or unverifiable evidence fails closed. |
| INV-03 | Related betting-intelligence/core-engine changes remain synchronized — verify with `git diff --name-only \| grep -E "betting_intelligence\|core_engine"`; both files must appear. |
| INV-04 | Promotion ladder cannot be skipped. |
| INV-05 | Capability maturity must be explicit. |
| INV-06 | `DEBT.md` is append-only. |
| INV-07 | Prefer surgical patches; rewrites require justification. |
| INV-08 | Local execution respects the 8 GB resource ceiling unless explicitly offloaded. |
| INV-09 | Research Mode remains the current customer posture unless explicitly changed. |
| INV-10 | No certainty/gambling language. |
| INV-11 | Alembic is the sole production schema authority — never `Base.metadata.create_all()` at startup or in migrations. |
| INV-12 | Never automatically loosen safety, provenance, coverage, or certification constraints. |
| INV-13 | Prediction features must be available before prediction time. |
| INV-14 | Artifact lineage must be cryptographically verifiable. |
| INV-15 | Certification evidence must be reproducible. |
| INV-16 | Historical/reanalysis data cannot masquerade as forecast evidence. |
| INV-17 | CI blocked/unexecuted is not CI pass. |
| INV-18 | Frontend/backend contracts cannot silently diverge. |
| INV-19 | Customer-facing confidence cannot exceed verified evidence. |
| INV-20 | Production policy changes are versioned, hashed, tested, and attributable. |
| INV-21 | `evaluation_at` is required by every verdict calculation; pure betting logic must never read the system clock directly. |

---

# 6. PRODUCT SAFETY VOCABULARY

**Approved:** Research mode · Verified · Limited evidence · Potential value · No verified edge · Insufficient verified data · Model unavailable · Market unavailable · Data delayed · Maintenance

**Forbidden:** Guaranteed · Sure Bet · Lock · Certain · Risk-free · Can't lose · Guaranteed winner · Banker · Free money · Execute immediately

Do not bypass this prohibition through equivalent phrasing.

---

# 7. MATURITY & PROMOTION MODELS

## 7.1 Capability maturity

```text
EXISTS → TESTED → WIRED → CALLED → DEPLOYED → VERIFIED
```

Do not claim `EXISTS` = production-ready, `WIRED` = operational, or `DEPLOYED` = verified.

## 7.2 Model promotion

```text
UNVERIFIED → OFFLINE_VALIDATED → SHADOW → FORECAST_ONLY → ACTIONABLE_CERTIFIED
```

No promotion may skip a rung. Research-serving may use `PROMOTE_RESEARCH_ONLY`, which does not imply betting certification.

---

# 8. OPERATOR GATES

| Gate | Decision |
|---|---|
| OG-01 | recurring infrastructure / Render plan change |
| OG-02 | build or remove `apps/ws` |
| OG-03 | odds-update cadence |
| OG-04 | production scraper activation |
| OG-05 | scraper cadence increase |
| OG-06 | certification-policy threshold/policy change |
| OG-07 | promotion beyond `FORECAST_ONLY` |
| OG-08 | override of FAIL/BLOCKED certification |
| OG-09 | production data-source policy |
| OG-10 | new recurring infrastructure cost |
| OG-11 | irreversible architecture deletion |
| OG-12 | customer-facing risk-semantics change |

The agent may prepare evidence and implementation. It must not silently approve these decisions.

---

# 9. EXECUTION-STATUS PROTOCOL

Execution status is a first-class control. Every implementation response must contain both `NEXUS` and `EXECUTION STATUS` (§10).

## 9.1 / 9.2 Mandatory execution states and their meanings

| State | Meaning |
|---|---|
| `INIT` | Task received but not yet inspected. |
| `ORIENTING` | Scope, phase, files, risks and dependencies are being established. |
| `VERIFYING` | Current repository evidence is being inspected. |
| `PLANNING` | Smallest safe implementation path is being selected. |
| `GATED` | Pre-implementation controls are being evaluated. |
| `IMPLEMENTING` | Approved autonomous implementation is occurring. |
| `TESTING` | Targeted and broader validation is executing. |
| `MEASURING` | Objective metrics/evidence are being produced. |
| `CERTIFYING` | Evidence is being evaluated against the authoritative certification policy. |
| `WAITING_OPERATOR` | Implementation may be prepared, but progress requires an operator decision. |
| `BLOCKED` | A technical, evidence, security, policy, or dependency condition prevents safe continuation. |
| `HOLD` | Not promotable, but no active implementation failure necessarily exists. |
| `COMPLETE` | Task completed at its verified maturity rung. |
| `FAILED` | Execution attempted but produced an implementation or validation failure requiring remediation. |

## 9.3 Status transitions

```text
Normal:            INIT → ORIENTING → VERIFYING → PLANNING → GATED → IMPLEMENTING → TESTING → MEASURING → CERTIFYING → COMPLETE
Operator-gated:     GATED → WAITING_OPERATOR → GATED → IMPLEMENTING
Evidence-blocked:   VERIFYING / MEASURING / CERTIFYING → BLOCKED → VERIFYING
Release hold:       CERTIFYING → HOLD
Unrecoverable:      IMPLEMENTING / TESTING → FAILED
```

## 9.4 Forbidden transitions

Never: `INIT → COMPLETE` · `VERIFYING → CERTIFYING` without evidence · `BLOCKED → COMPLETE` · `WAITING_OPERATOR → IMPLEMENTING` without approval · `TESTING → COMPLETE` when required tests failed · `CERTIFYING → PROMOTE` when required gates are unverified.

---

# 10. MANDATORY RESPONSE HEADER

Every implementation response begins:

```text
┌─ NEXUS ─────────────────────────────────────────────────────┐
│ Task:       [intent classification]                         │
│ Phase:      [P# / task]                                     │
│ Rung:       [maturity rung]                                 │
│ Roles:      [responsible roles]                             │
│ Skills:     [minimal skill chain]                           │
│ Order:      [dependency-aware sequence]                     │
│ Invariants: [INV-*]                                         │
│ Gate:       [AUTONOMOUS | OPERATOR_APPROVAL_REQUIRED]        │
│ Evidence:   [required evidence]                              │
│ Risk:       [critical risks]                                │
└─────────────────────────────────────────────────────────────┘

EXECUTION STATUS
State:        [STATE]
Phase status: [NOT_STARTED | ACTIVE | COMPLETE | BLOCKED | HOLD]
Gate status:  [CLEAR | PENDING | BLOCKED | FAILED]
Evidence:     [VERIFIED | PARTIAL | MISSING]
Next action:  [one concrete action]
```

The response must never hide a blocker inside prose.

---

# 11. NEXUS ROUTING

```text
CLASSIFY → SCOPE → DEPENDENCY RESOLUTION → ROLE ASSIGNMENT → SKILL SELECTION
→ INVARIANT CHECK → EVIDENCE PLAN → IMPLEMENTATION PLAN → VALIDATION PLAN → ROLLBACK PLAN
```

Never load every skill blindly. Use only repository-available skills.

```text
ML:        ai-feature-architect → sabiscore-settlement-calibration-architect
Backend:   backend-systems-auditor → security-hardening-auditor → opentelemetry-observability-architect
Frontend:  sabiscore-dashboard-design-system → frontend-design-auditor
Release:   engineering:deploy-checklist → engineering:documentation
```

---

# 12. UNIVERSAL TASK EXECUTION LOOP

Every implementation unit follows a loop that maps directly onto §9.1's core rungs (ORIENTING…CERTIFYING), with two extra steps for feedback and reporting:

```text
ORIENT → VERIFY → PLAN → μ-GATE → IMPLEMENT → TEST → MEASURE → REFLECT → CERTIFY → EMIT
```

- **ORIENT** — phase, task, affected files, dependencies, roles, invariants, operator gates, blast radius, rollback.
- **VERIFY** — read current files; re-run relevant historical claims.
- **PLAN** — choose the smallest safe diff.
- **μ-GATE** — evaluate invariants, gates, resource constraints, CI constraints, rollback.
- **IMPLEMENT** — modify only required files.
- **TEST** — targeted tests first, broader tests second.
- **MEASURE** — capture objective evidence.
- **REFLECT** — recheck against the §1 precedence sources.
- **CERTIFY** — record affected gate evidence.
- **EMIT** — report result, tests, evidence, changed files, maturity rung, gate status, remaining risk, next action.

---

# 13. PHASE MAP — SINGLE AUTHORITATIVE NUMBERING

Exactly **19 phases: P0–P18.** No other phase numbering may be used.

| Phase | Name | Purpose |
|---|---|---|
| P0 | Ground Truth | Establish current state |
| P1 | Architecture Reconciliation | Map actual system and classify work |
| P2 | Data Provenance & Entity Integrity | Validate source and identity integrity |
| P3 | Feature & Weather Integrity | Validate temporal/feature correctness |
| P4 | Experiment & Model Governance | Validate evaluation protocol |
| P5 | Calibration & Uncertainty | Validate probabilistic outputs |
| P6 | Certification Policy & Metrics | Establish statistical policy authority |
| P7 | Drift & Monitoring | Make monitoring operational |
| P8 | Model Comparison & Market Diagnostics | Evaluate candidate/incumbent and market |
| P9 | Betting Safety | Preserve default-deny research posture |
| P10 | Ingestion & Scraper Reliability | Harden evidence acquisition |
| P11 | Infrastructure & Runtime | Validate infrastructure, cron, WebSocket decisions |
| P12 | Backend, DB & Redis | Harden application runtime |
| P13 | Observability & Security | Validate operational telemetry/security |
| P14 | Frontend Intelligence UX | Make customer-facing evidence coherent |
| P15 | LLM Explanation Safety | Govern AI explanations |
| P16 | Deployment & CI Integrity | Verify release identity |
| P17 | Testing & Customer Smoke | Execute final validation |
| P18 | Certification, Promotion & Release | Produce final certification and release decision |

**Numbering rule:** never introduce alternate phase identifiers (e.g., "Phase 20," "Phase 29"). Tasks: `P0.T1 … P18.Tn`. Certification gates: `G01–G30`. Operator gates: `OG-01–OG-12`. Debt items retain their repository IDs.

---

# 14. P0 — GROUND TRUTH

**State required:** `VERIFYING`. No implementation changes.

Resolve: `CURRENT_HEAD_SHA` · `CURRENT_BRANCH` · `WORKTREE_STATE` · `REMOTE` · `DEPLOYED_BACKEND_SHA` · `DEPLOYED_FRONTEND_SHA` · `ACTIVE_MODEL_GENERATION` · `ACTIVE_SCHEMA` · `LATEST_ALEMBIC_REVISION` · `ACTIVE_CERTIFICATION_POLICY` · `POLICY_SHA256` · `SERVING_MANIFEST_HASH` · `MODEL_ARTIFACT_HASHES` · `DATASET_SNAPSHOT`.

Inspect: Git · dependencies · backend · frontend · scraper · providers · database · Redis · model registry · calibration · certification · market · weather · CI/CD · observability · security · documentation.

Produce: `KNOWN` · `VERIFIED` · `STALE` · `UNKNOWN` · `BLOCKED`.

**Exit condition:** do not enter P1 until current repository identity is established, major architecture is mapped, unknown critical facts are explicitly recorded, and no historical claim is being treated as current truth.

---

# 15. P1 — ARCHITECTURE RECONCILIATION

## 15.1 Subsystem inventory

Per subsystem: implementation · entry point · configuration · dependencies · maturity rung · tests · known defects · risk · required action.

## 15.2 Change classification

`ALREADY_CORRECT` · `NEEDS_INTEGRATION` · `NEEDS_HARDENING` · `NEEDS_REPLACEMENT` · `BLOCKED_BY_DATA` · `BLOCKED_BY_EVIDENCE` · `NOT_JUSTIFIED`. `NOT_JUSTIFIED` work must not be implemented merely because an older roadmap requests it.

## 15.3 Historical Forensic Register

Prior audits produced the findings below. Each is a **hypothesis to revalidate, not authority** — it speeds up reconnaissance, never substitutes for it. Close each out with a §15.2 classification before any related change proceeds.

**15.3.1 Certification policy.** Prior finding: an authoritative policy module already exists at `backend/src/models/certification_policy.py` with versioning, promotion gates, evidence floors, and policy hashing. Verify: file exists at that path, is imported by the live serving/certification path (not just present), and its version matches the deployed policy. Action: `RECONCILE / EXTEND` — do not duplicate. If confirmed: `ALREADY_CORRECT`.

**15.3.2 RPS promotion gate.** Prior finding: authoritative policy lives in the backend module; the RPS condition is relative; `RPS_DISPLAY_FLOOR` is display-only; `RPS_PROMOTION_GATE` was marked deprecated. Verify by grepping both aliases across backend and frontend for any live path still reading the deprecated one as authoritative. Action: finish deprecation only if still present. Never invent an absolute RPS gate.

**15.3.3 Ingestion topology.** Prior finding: `apps/scraper → S3 → Python reconciliation`; the claim that the Node scraper directly hydrates PostgreSQL was rejected as false. Verify by tracing the scraper's actual write target. Action: preserve current topology; do not redesign from stale roadmap language.

**15.3.4 Betting-engine safety.** Prior finding: default-deny controls exist, including `stake_permitted = false`; no `EXECUTE_BET` exists. Verify at every call site and search for the symbol. Action: preserve, verify, never create `EXECUTE_BET`. Weakening this is `NOT_JUSTIFIED` by default and requires OG-08.

**15.3.5 Weather provenance.** Prior finding: plausible weather-API responses may represent reanalysis rather than genuine historical forecast data. Verify the archive boundary, provenance tagging, and the regression test that would catch mislabeling. If the boundary or test is missing, classify `NEEDS_HARDENING` and treat as blocking for any weather-dependent feature.

**15.3.6 Sourced — legacy surfaces (higher confidence than a forensic hypothesis).** `CLAUDE.md`'s own `KNOWN LEGACY SURFACES` table — which outranks any prior audit directive per §1 — names: `apps/api/` (legacy API skeleton, incomplete — remove from CI/Docker/scripts) · `frontend/` (legacy Vite app — remove) · a stale npm lockfile (pnpm is canonical — delete) · `Base.metadata.create_all()` (replace with Alembic) · direct browser odds fetching (security violation — route through backend proxy) · an `ESPN_API_KEY` variable (ESPN is keyless — remove). Action: confirm each is still absent from CI/Docker/scripts; this is a live-doc-sourced fact requiring confirmation, not open-ended investigation.

**15.3.7 Genuinely unconfirmed leads.** `CLAUDE.md`'s ground-truth snapshot predates these and does not resolve them — full investigation required: the scraper resilience/circuit-breaker manager may be exported but never called at runtime; the calibrator may be unwired at inference (trace `FIT → SERIALIZED → REGISTERED → LOADED → CALLED`).

## 15.4 P1 exit condition

A change proceeds only after its subsystem inventory (§15.1) is recorded, its classification (§15.2) rests on live evidence — not the forensic register alone — and any related §15.3 finding has been explicitly revalidated.

---

# 16. P2 — DATA PROVENANCE & ENTITY INTEGRITY

Per production feature family: source · provider · provider_version · acquisition_timestamp · effective_timestamp · historical_availability · forecast_availability · entity_coverage · temporal_coverage · missingness · transformation · leakage_status · reproducibility · eligibility.

Keep independent: source reliability · historical coverage · forecast authenticity · entity coverage · feature eligibility.

Entity mappings must be auditable. Venue records: provider_id · canonical_name · normalized_name · latitude · longitude · source · verification_status · effective_from · effective_to. Never use model-recalled coordinates. Unknown entities are explicit coverage gaps.

**Evidence-tier distinction:** only `critical_gaps` may force a degraded certification status; a gap from an advisory-tier, corroboration-only source reduces confidence but never blocks promotion on its own — a missing response from such a source is at most `advisory_gap`.

**Provider status drift:** documented enum names can diverge from code (e.g., a `DEGRADED`/`SCHEMA_INVALID` naming convention rendering as different literal values in the actual `ProviderStatus` enum). Grep the live enum before writing any code that pattern-matches provider status by name.

**Exit condition:** required production data is `PROVEN` or `EXPLICITLY UNAVAILABLE/INELIGIBLE`. Never silently substitute.

---

# 17. P3 — FEATURE & WEATHER INTEGRITY

Every feature: `AVAILABLE_BEFORE_PREDICTION_TIME` AND `NO_POST_MATCH_INFORMATION`. For match `t`: `features(t) = information available strictly before kickoff(t)`. Never include current-match result/xG/shots, post-match weather, settlement data, future information, or unavailable closing information.

**Weather provenance states:** `forecast_archive` · `reanalysis` · `observed` · `unknown` (ineligible). A successful HTTP response does not establish forecast provenance. Reanalysis must never masquerade as forecast. Insufficient evidence → `FEATURE_STATUS = UNAVAILABLE`, never `FEATURE_VALUE = 0`.

Measure: whole_corpus_coverage · forecast_window_coverage · venue_coverage · archive_eligible_coverage · authentic_forecast_rate · missing_hour_rate · fetch_failure_rate.

**Exit condition:** no production feature proceeds with unresolved temporal leakage or invalid provenance.

---

# 18. P4 — EXPERIMENT & MODEL GOVERNANCE

Authoritative protocol: `TRAIN → CALIBRATE → TEST`, chronological. Never: random-split production claims · tune on final holdout · calibrate on final test · use future data · reuse a contaminated holdout · materialize post-match information into historical features.

Record per experiment: experiment_id · model_family · feature_contract · dataset_snapshot · training_window · calibration_window · holdout_window · seed · provider_versions · generation_id · metric_convention · hyperparameters · artifact_hashes · code_sha.

Candidate and incumbent share: holdout · class order · metric convention · settlement rules · eligibility · evaluation code. The incumbent retains its own declared feature contract.

---

# 19. P5 — CALIBRATION & UNCERTAINTY

Candidate methods: temperature scaling · vector scaling · beta calibration · isotonic regression. Do not force a calibrator into production. Persist: raw probabilities · calibrated probabilities · method · training/calibration/test windows · sample count · class order · metrics · confidence intervals · artifact hash.

**Serve-time calibration.** Trace `FIT → SERIALIZED → REGISTERED → LOADED → CALLED`. A calibrator that exists offline but is not applied at inference is not production-calibrated. Required regression: registered calibrator → inference → calibrated output, demonstrating the pre-fix failure where practical.

**Independent uncertainty.** Never replace measured uncertainty with a probability-derived proxy. If unavailable: `UNCERTAINTY_STATUS = UNAVAILABLE`, and any gate requiring it fails closed. Measure empirically against forecast error.

---

# 20. P6 — CERTIFICATION POLICY & METRICS

Single certification control authority. Do not create duplicate policies. The authoritative policy defines or references: policy_version · policy_sha256 · class_order · metric_conventions · thresholds · coverage_rules · drift_rules · uncertainty_rules · market_rules · artifact_rules · schema_rules · deployment_rules · security_rules · observability_rules · frontend_rules · promotion_rules. Every threshold: definition · computation · dataset/window · owner · persistence · test · pass/fail interpretation. Any threshold change requires OG-06 + policy version bump + policy hash change + regression evidence.

**Metric contract.** Freeze Brier / RPS / log-loss conventions, ECE methodology, class ordering, zero-probability handling, reliability/resolution methodology. Persist ECE binning_method, bin_count, bin_edges, sample_count, per-class and aggregate ECE. Never compare incompatible conventions.

**Phantom-threshold rule.** Every non-policy threshold is classified `POLICY_BACKED` · `DISPLAY_ONLY` · `DIAGNOSTIC` · `ORPHANED` · `UNVERIFIED`. Never promote an orphan frontend number into policy merely to make a gate appear complete.

---

# 21. P7 — DRIFT & MONITORING

PSI compares a declared reference distribution against a declared current one, with frozen reference-derived bin edges and explicit zero-bin handling. PSI measures distribution shift, not concept drift — pair it with performance/outcome monitoring. Operational thresholds live in certification policy.

Monitoring executes as: scheduler → endpoint → backend metric computation → persistence → alert/gate → certification evidence. **The backend is the statistical authority — never duplicate the mathematics in TypeScript.**

---

# 22. P8 — MODEL COMPARISON & MARKET DIAGNOSTICS

Apples-to-apples: candidate and incumbent share holdout, class order, metric convention, settlement rules, eligibility, evaluation code. Fail closed when these differ.

Market diagnostics distinguish: model_probability · market_implied_probability · fair_probability · closing_probability · edge · CLV. Never label an arbitrary market snapshot as CLV. Unavailable evidence → `MARKET_BASELINE = UNVERIFIED`. Never equate "better calibrated" with "beats market."

---

# 23. P9 — BETTING SAFETY

Research Mode remains default. Required: `stake_permitted = false` unless the repository's actual policy and certification state explicitly permit otherwise. Never create `EXECUTE_BET`; never introduce automatic betting; never expose staking controls in Research Mode. Existing default-deny machinery must not be deleted solely because it is inactive.

**UCL cap:** fixtures in the Champions League are hard-capped at `ACTIONABLE` and cannot reach `HIGH_CONVICTION` until a dedicated, certified UCL model variant exists.

---

# 24. P10 — INGESTION & SCRAPER RELIABILITY

Preserve actual topology (`apps/scraper → S3 → Python reconciliation`) without redesign absent evidence. Verify whether resilience infrastructure is genuinely called.

**Idempotency:** canonical business identity (competition + season + participants), never a mutable kickoff timestamp.
**Retry:** transient errors (timeout, 429, temporary provider failure) → capped exponential backoff + jitter.
**Poison data:** malformed/schema-invalid payload → DLQ, with metadata: originalQueue · failureReason · attemptCount · firstAttemptAt · lastAttemptAt · originalPayload/reference. Monitor DLQ depth, DLQ age, retry rate, failure rate, circuit-breaker state. Mojibake/corrupt entity names fail closed.

Production scraper activation requires OG-04; cadence change requires OG-05.

---

# 25. P11 — INFRASTRUCTURE & RUNTIME

Inspect actual deployment state: plan · resource limits · cold starts · runtime health · database lifecycle · Redis topology · cron registration · cost · expiry risk · failure behavior. Recurring infrastructure changes require OG-01 or OG-10.

**Cron:** a route in source is not evidence of production execution. Verify: route exists → registration exists → schedule valid → environment exists → handler idempotent → failure observable → retry/DLQ behavior. Never invent odds cadence.

**WebSocket:** if `apps/ws` is a stub, do not represent it as production real-time infrastructure. Evaluate build versus removal, choose the smallest architecture satisfying the product, require OG-02, and create an ADR.

---

# 26. P12 — BACKEND, DATABASE & REDIS

Hardening: strict validation · request-size limits · bounded concurrency · provider timeouts · capped retries · structured errors · deterministic response schemas · request IDs · readiness/liveness separation · graceful degradation · transaction boundaries · connection-pool limits · cleanup. **Provider gateway uses one application-lifespan async client, never instantiated per-request; the circuit breaker must distinguish network / rate-limit / authentication / client / server / schema failures.**

**Database:** Alembic is the sole schema authority (INV-11). Verify migration ordering, current revision, schema compatibility, startup behavior, transaction safety, rollback, pool behavior.

**Redis:** determine required-for-correctness versus performance-optimization. Required → readiness fails when unavailable. Optional → explicit degraded mode + tests. Use bounded TTL caches and bounded local fallback where justified. Never create unbounded local intelligence stores.

---

# 27. P13 — OBSERVABILITY & SECURITY

Instrument where applicable: HTTP · providers · database · Redis · model inference · feature generation · cache · ingestion · settlement · certification · deployment. Low-cardinality dimensions; never expose sensitive information; keep telemetry memory-bounded.

OTel terminology: SDK batch processor = bounded export buffering; collector tail sampling = tail sampling; probabilistic/head sampling = bounded non-collector alternative. Never conflate them.

Security covers: secrets · validation · CORS · transport · dependency integrity · credential scoping · unsafe input · logging exposure. Concretely: zero `NEXT_PUBLIC_*` provider keys; redact auth headers, API-key query params, DSNs, and passwords from logs/traces; rotate any credential that was ever committed.

---

# 28. P14 — FRONTEND INTELLIGENCE UX

Canonical hierarchy: `MATCH → MODEL PROBABILITY → FAIR PROBABILITY → CONFIDENCE/EVIDENCE → MARKET COMPARISON → PROBABILITY DELTA → SUPPORTING EVIDENCE → LIMITATIONS`.

Use percentage points (`Model: 58% · Market fair: 52% · Difference: +6 percentage points`) — never call that "6% edge" unless the surface explicitly defines the term.

Customer states use the approved vocabulary (§6). State must derive from backend evidence — the frontend cannot manufacture certification state. Reuse canonical verdict/confidence components; do not fork verdict logic. Research/shadow/certified states remain visually distinct and semantically accessible; do not rely on color alone.

---

# 29. P15 — LLM EXPLANATION SAFETY

LLMs may enhance NEXUS/explain/insight/narrative/summarization surfaces. They do not control classical prediction logic. Every explanation prompt defines ROLE · GOAL · CONSTRAINTS · FORMAT · NULL HANDLING. An explanation may cite only fields in the canonical prediction/API contract; missing data must be acknowledged. Never invent statistics, probabilities, market data, weather, injuries, confidence, or performance figures. Maintain fixed evaluation fixtures (normal prediction · insufficient data · missing field · market/weather unavailable · data gap · uncertainty unavailable). Version prompts and fixtures together.

---

# 30. P16 — DEPLOYMENT & CI INTEGRITY

Release identity: `Git SHA → dataset/model artifact → serving manifest → backend deployment → backend health SHA → frontend deployment → frontend compatibility → certification → promotion`. Verify source SHA, artifact hash, manifest hash, model generation, schema, migration, backend SHA, frontend SHA. Require release-time **and** runtime verification — a build-time network request alone is insufficient. Mismatch → `MAINTENANCE` or another explicit degraded state.

**Artifact integrity:** every production artifact carries artifact_sha256 · generation_id · schema_version · feature_contract · training_window · calibration_window · holdout_window · creation_sha · dataset/provider snapshot. Reject missing artifact, hash mismatch, schema mismatch, generation mismatch, feature-contract mismatch.

**CI:** if required checks did not execute, `CI_STATUS = BLOCKED` — never `PASS`. An administrative merge under override must be recorded. **Production posture must also match `CLAUDE.md`'s `SAFE DEFAULTS` env block (`DEBUG`, `MOCK_MODE`, `ENABLE_LEGACY_INFERENCE`, `ALLOW_SQLITE_FALLBACK`, `PROVIDER_LIVE_TESTS`, `PHASE9_*` flags, and any others current) — re-verify current values, do not assume they are unchanged.**

---

# 31. P17 — TESTING & CUSTOMER SMOKE

**Testing contract.** Canonical entry point (re-verify it is still current): `make verify` — secret scanning, repository secret-safety tests, backend unit/integration tests, provider gateway tests, strict-engine tests, provider CLI doctor (fixture mode), Alembic fresh-database upgrade + schema verification, OpenAPI generation/diff, scraper tests + manifest validation, web lint/typecheck/unit/build, Docker Compose + image build, Playwright desktop and mobile smoke. No gate may be bypassed with `|| true`; no live provider quota consumed by default (`PROVIDER_LIVE_TESTS=false`). Discover the actual current command set rather than trusting this list blindly; add model/certification-specific tests not covered by the above. Never weaken or delete a test to make validation pass; safety-sensitive changes require regression evidence.

**Adversarial matrix.** Exercise: healthy provider · provider timeout · provider 429 · malformed payload · missing/stale feature · invalid artifact · artifact hash mismatch · schema mismatch · Redis/database unavailable · uncertainty/market/weather unavailable · invalid venue · mojibake entity · insufficient evidence · drift breach · frontend/backend SHA mismatch · maintenance state. Each critical failure path must produce a deterministic safe state.

**Customer smoke.** Verify homepage · league discovery · match discovery · prediction · evidence · probability display · market comparison · data-gap/insufficient-data states · error boundary · maintenance · mobile · desktop · accessibility. No broken route, hydration error, critical console error, fabricated metric, certainty language, misleading CLV, raw generation ID in primary UX, layout overflow, inaccessible control, or inconsistent verdict semantics.

---

# 32. P18 — CERTIFICATION, PROMOTION & RELEASE CONTROL PLANE

The single authoritative certification section — requirements here must not be duplicated elsewhere as independent rules.

## 32.1 Gate registry

`G01_REPOSITORY_INTEGRITY` · `G02_TEST_SUITE` · `G03_STATIC_ANALYSIS` · `G04_BUILD` · `G05_SCHEMA_MIGRATION` · `G06_ARTIFACT_INTEGRITY` · `G07_FEATURE_CONTRACT` · `G08_DATA_PROVENANCE` · `G09_TEMPORAL_LEAKAGE` · `G10_COVERAGE` · `G11_CALIBRATION` · `G12_BRIER` · `G13_RPS` · `G14_LOG_LOSS` · `G15_ECE` · `G16_UNCERTAINTY` · `G17_DRIFT_PSI` · `G18_MARKET_BASELINE` · `G19_MARKET_CLV` · `G20_SECURITY` · `G21_OBSERVABILITY` · `G22_BACKEND_SMOKE` · `G23_FRONTEND_SMOKE` · `G24_DEPLOYMENT_PARITY` · `G25_CUSTOMER_UX` · `G26_INGESTION_RELIABILITY` · `G27_CALIBRATOR_SERVING_PARITY` · `G28_RELEASE_REPRODUCIBILITY` · `G29_DATASET_INTEGRITY` · `G30_ROLLBACK_READINESS`

Every gate has exactly one of `PASS` · `FAIL` · `BLOCKED` · `UNVERIFIED` · `NOT_APPLICABLE`. No required gate disappears.

## 32.2 Gate evidence contract

Per gate record: gate_id · name · status · threshold · observed · method · evidence · code_sha · generated_at · notes. Evidence identifies an actual test, report, artifact, log, endpoint, query, manifest, or reproducible computation. **A prose assertion is not evidence.**

## 32.3 Certification report

Create `artifacts/certification/certification_report_<generation>_<timestamp>.json`. The report must be machine-readable, schema-valid, versioned, hash-associated, reproducible, append-only, and human-auditable. Never overwrite historical reports.

## 32.4 Report contents

Required top-level sections: report_version · generated_at · repository · deployment · model · data · policy · metrics · gates · operator_gates · risks · changes · validation · decision.

- **repository:** name · commit_sha · branch · working_tree_clean
- **deployment:** backend_sha · frontend_sha · schema_version · migration_revision · compatibility_status
- **model:** generation_id · model_family · feature_contract · artifact_hash · schema_version · status · calibration
- **data:** dataset_snapshot · temporal_window · coverage · provenance_status · leakage_status · forecast_authenticity
- **policy:** policy_version · policy_sha256 · metric_convention · class_order
- **metrics:** brier · rps · log_loss · ece · reliability · resolution · uncertainty · psi · market
- **operator_gates:** gate_id · status · approver · decided_at · reason · notes
- **risks:** risk_id · severity · status · description · impact · mitigation · rollback · approver
- **changes:** file · action · reason · tests
- **validation:** tests · lint · typecheck · build · security · migration · integration · smoke · artifact_validation · CI status
- **decision:** status · reason · blocking_gates — allowed values `PROMOTE` · `PROMOTE_RESEARCH_ONLY` · `HOLD` · `REJECT`

---

# 33. CERTIFICATION DECISION LOGIC

Certification is determined by evidence, not implementation completeness.

**Mandatory HOLD:** required gate `UNVERIFIED` · required gate `BLOCKED` · required operator gate `PENDING` · deployment identity incompatible · required evidence missing.
**Mandatory REJECT/HOLD:** any critical gate `FAIL` — REJECT or HOLD depending on recoverability and policy.
**`PROMOTE_RESEARCH_ONLY` requires:** valid temporal evaluation · valid calibration evidence · valid artifact lineage · valid serving contract · leakage controls · correct evidence-state representation · known limitations exposed · stake controls disabled · required gates passing.
**`PROMOTE`** requires the stronger evidence defined by the authoritative certification policy — never infer it merely from "all tests passed."

---

# 34. CERTIFICATION STATUS PROTOCOL

Allowed statuses: `UNASSESSED` · `IN_PROGRESS` · `PASS` · `FAIL` · `BLOCKED` · `UNVERIFIED` · `HOLD` · `PROMOTE_RESEARCH_ONLY` · `PROMOTE` · `REJECT`.

```text
EXECUTION STATUS     = what the agent is doing
CERTIFICATION STATUS = what the evidence currently proves
RELEASE DECISION     = what may be promoted
```

Do not merge these. Example: Execution `COMPLETE`, Certification `HOLD`, Release `HOLD` — a completed coding task does not imply a certifiable release.

---

# 35. RELEASE REPRODUCIBILITY

A release must be reconstructable from: source SHA · dataset snapshot · provider versions · feature contract · model artifact · calibrator artifact · policy version/hash · evaluation configuration · serving manifest — sufficient for a future engineer to determine what was trained, on what data, with which features and code, using which calibration, evaluated on which holdout, under which policy, deployed where.

---

# 36. ROLLBACK READINESS

Document: **Application** — previous known-good SHA. **Model** — previous artifact, generation, manifest. **Database** — migration rollback/forward strategy. **Frontend/Backend** — known-compatible pair. **Certification** — never delete invalid historical evidence; write a superseding report. Rollback must be executable, not theoretical.

---

# 37. DEBT DISCIPLINE

Every newly discovered production defect becomes a `DEBT.md` entry. Never delete or renumber historical debt. Closing requires resolution + status + date + tests/evidence. A debt item is closed only when its Definition of Done is verified — never merely because code exists.

---

# 38. DOCUMENTATION DISCIPLINE

Update only documentation made inaccurate by implementation. Synchronize where applicable: `CLAUDE.md` · `DEBT.md` · ADRs · release notes/changelog · certification artifacts · model registry documentation. Never preserve stale production metrics as current; never update documentation to make a missing gate appear passed.

---

# 39. SURGICAL CHANGE POLICY

Default to the smallest safe diff. Avoid unrelated refactors; prefer narrow PRs. Do not modify generated files unless required, or delete functionality without proving obsolescence. A substantial rewrite requires technical justification, blast-radius assessment, rollback strategy, and a reviewable commit description. Operator-gated changes remain isolated.

---

# 40. PHASE EXIT CONTRACT

A phase is not complete because its code was edited — it exits only when its exit conditions are satisfied. Every phase produces: PHASE_STATUS · OUTCOME · EVIDENCE · CHANGED_FILES · OPEN_RISKS · BLOCKERS · NEXT_PHASE. Allowed phase status: `NOT_STARTED` · `ACTIVE` · `COMPLETE` · `BLOCKED` · `HOLD`. A blocked phase cannot silently advance the dependency chain.

---

# 41. MASTER EXECUTION STATE

At any moment the agent must answer: CURRENT_PHASE · CURRENT_TASK · EXECUTION_STATE · PHASE_STATUS · MATURITY_RUNG · CERTIFICATION_STATUS · OPEN_GATE · OPEN_OPERATOR_GATE · PRIMARY_BLOCKER · LAST_VERIFIED_SHA · LAST_VERIFIED_ARTIFACT · NEXT_ACTION. These are operational state variables, not narrative prose.

---

# 42. FINAL RELEASE CHECKLIST & DEFINITION OF DONE

SabiScore is complete only when every applicable item below is both **done** (checklist) and **verified** (DoD) — the two are one gate, not two.

**Repository & Engineering** — [ ] branch/SHA/working-tree/remote verified · [ ] deployment identity verified · [ ] build passes · [ ] tests pass · [ ] static analysis passes · [ ] security checks pass · [ ] backend and frontend operational · [ ] contracts deterministic.

**Architecture** — [ ] backend, frontend, scraper, provider layer, model pipeline, certification pipeline, market pipeline, weather pipeline, observability, and CI/CD all reconciled per §15.

**Data** — [ ] provenance auditable · [ ] temporal availability, entity mappings, venue mappings verified · [ ] weather archive boundary verified, reanalysis contamination blocked · [ ] missingness explicit, coverage and forecast-authenticity quantified · [ ] leakage blocked, missing evidence fails closed.

**Model** — [ ] incumbent identified, feature contract enforced · [ ] temporal split verified, holdout protected · [ ] calibration evaluated, calibrator serialized **and served** (§19) · [ ] uncertainty independently verified or explicitly unavailable · [ ] artifacts hashed and reproducible · [ ] drift governed, market diagnostics correctly labeled.

**Runtime & Operations** — [ ] provider resilience, circuit breaker, backoff/jitter, idempotency, DLQ + monitoring · [ ] backend/DB/Redis hardening, observability, security · [ ] artifacts and deployment parity verified · [ ] failure modes adversarially tested · [ ] rollback documented and executable · [ ] production dependencies appropriate to actual need.

**Product** — [ ] prediction hierarchy, evidence state, market semantics correct · [ ] Research Mode explicit, no certainty language, no misleading market claims · [ ] canonical verdict components reused, no forked logic · [ ] accessible, mobile-ready, desktop-ready, visually coherent · [ ] loading/empty/error/maintenance states polished · [ ] LLM explanation safety enforced (§29).

**Release & Certification** — [ ] CI status accurate (blocked ≠ pass) · [ ] adversarial and customer smoke passed · [ ] G01–G30 evaluated with no phantom gates and no blocked gate shown as pass · [ ] operator gates recorded and attributable · [ ] certification report generated, schema-valid, and reproducible · [ ] promotion decision derived from evidence, not from "all tests passed."

---

# 43. REQUIRED FINAL EXECUTION OUTPUT

Every **final release execution** emits exactly:

1. **Release decision:** `PROMOTE` · `PROMOTE_RESEARCH_ONLY` · `HOLD` · `REJECT`
2. **Execution status:** state, phase, phase status, certification status, maturity rung, gate status, operator-gate status, primary blocker, next action
3. **Production identity:** populate from §32.4's repository/deployment/model/policy fields (commit, backend/frontend SHA, model generation, dataset snapshot, schema, migration, certification policy + hash, serving manifest, artifact hashes)
4. **Implemented changes:** per file — file, change, reason, test/evidence, maturity rung
5. **Validation:** tests · lint · typecheck · build · security · migration · integration · artifact validation · smoke · CI, each `PASS`/`FAIL`/`BLOCKED`/`NOT_RUN` — never convert `NOT_RUN` or `BLOCKED` into `PASS`
6. **Model evidence:** Brier · RPS · log loss · ECE · reliability · resolution · uncertainty · PSI · market baseline · CLV · sample size · confidence intervals · evaluation windows · class ordering — no number without evidence context
7. **Data coverage:** overall · forecast window · venue · weather · feature family · forecast authenticity · missingness · provenance
8. **Certification gate matrix:** G01–G30 with status, observed, threshold, method, evidence, code_sha, notes
9. **Operator gates:** OG-01–OG-12 with status, approver, timestamp, decision, reason
10. **Risks:** ID, severity, status, impact, mitigation, rollback, approver
11. **Customer readiness:** homepage · discovery · prediction · evidence · market · degraded states · maintenance · mobile · desktop · accessibility · Research Mode safety · LLM explanation safety
12. **Rollback:** exact reversal steps for application, model, artifact, database, frontend/backend compatibility, certification state
13. **File manifest:** created · modified · deleted · unchanged-but-verified

---

# 44. HARD STOP CONDITIONS

Immediately enter `BLOCKED` on: unknown repository identity · unexpected stack contamination · unresolved feature leakage · artifact/schema/policy mismatch · holdout contamination · unknown provenance for a required feature · historical reanalysis represented as forecast · missing required uncertainty · incompatible frontend/backend contract · required CI unavailable · required operator approval pending · critical gate failure · unsafe resource requirement · credential exposure · unsafe schema mutation · fabricated evidence · unsupported market claim · customer certainty exceeding verified evidence.

If operator action, not technical remediation, is required: `WAITING_OPERATOR`, not `BLOCKED`.

---

# 45. FINAL OPERATING RULES

**Always:** inspect before changing · revalidate historical claims · separate facts from hypotheses · preserve correct architecture · patch surgically · test failure modes · measure objectively · evidence every claim · fail closed · separate policy from presentation, prediction from explanation, execution status from certification status, engineering authority from operator authority · keep releases reconstructable and rollback executable · keep customer confidence bounded by evidence.

**Never:** fabricate · guess · leak · zero-fill missing evidence · silently weaken constraints · treat code existence, deployment, or blocked CI as verification/pass · treat calibration as market superiority · treat frontend thresholds as policy · treat prose as evidence · treat LLM explanation as prediction logic · auto-approve operator gates · introduce betting execution · delete safety controls for convenience · rewrite working architecture without evidence.

---

# 46. FINAL COMMAND

Execute against the **actual current SabiScore repository**, in phase order:

```text
P0 GROUND TRUTH → P1 ARCHITECTURE RECONCILIATION → P2 DATA PROVENANCE & ENTITY INTEGRITY
→ P3 FEATURE & WEATHER INTEGRITY → P4 EXPERIMENT & MODEL GOVERNANCE → P5 CALIBRATION & UNCERTAINTY
→ P6 CERTIFICATION POLICY & METRICS → P7 DRIFT & MONITORING → P8 MODEL COMPARISON & MARKET DIAGNOSTICS
→ P9 BETTING SAFETY → P10 INGESTION & SCRAPER RELIABILITY → P11 INFRASTRUCTURE & RUNTIME
→ P12 BACKEND/DATABASE/REDIS → P13 OBSERVABILITY & SECURITY → P14 FRONTEND INTELLIGENCE UX
→ P15 LLM EXPLANATION SAFETY → P16 DEPLOYMENT & CI INTEGRITY → P17 TESTING & CUSTOMER SMOKE
→ P18 CERTIFICATION / PROMOTION / RELEASE
```

Do not skip a dependent phase. Do not advance through `BLOCKED` / `WAITING_OPERATOR` / `HOLD` without resolving its governing condition.

The release decision derives from **current repository evidence + versioned certification policy + reproducible validation + operator decisions** — never from historical assumptions, optimistic interpretation, stale documentation, or this directive itself.

The final SabiScore system must be: **Operational, Reproducible, Evidence-gated, Fail-closed, Statistically defensible, Observable, Secure, Resilient, Responsive, Accessible, Visually credible, Intelligently explained, Customer-ready — immediately.**

# END OF DIRECTIVE
