# SabiScore — Production Readiness & Release Certification Report

**Council**: Multi-Agent Engineering Council (Platform Architecture, Quantitative Modeling, Backend Systems, Risk Engineering, Frontend Systems, SRE/Security)  
**Date**: 2026-09-30 — V15.1 governance commit (b3ac093); V15.2 full-depth audit completed same date  
**Governing Directive**: Production Executive Directive V15.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V15.md`)  
**Release Decision**: **READY — ANALYTICAL / STAKING WITHHELD**

---

## 1. Executive Summary

This comprehensive audit evaluates the `sabiscore/sabiscore` monorepo at HEAD against the 24 operational, quantitative, architectural, and security phases of the Production Readiness & Release Certification Directive.

The platform is **fully operational** across its end-to-end production path (data acquisition, fixture reconciliation, feature engineering, ensemble inference, market de-vigging, risk calculation, and Next.js frontend projection). Live verification of the production deployment on Render and Vercel confirms healthy infrastructure, low memory footprint (177 MB headroom in a 512 MB container), active model serving across all 6 canonical domestic leagues, and strict fail-closed gating of financial staking surfaces while the model generation remains `UNVERIFIED`.

---

## 2. 24-Phase Audit & Verification Summary

### Phase 0: Workspace & Repository Forensics
- **Repository SHA**: `b3ac093` (V15.1 governance commit) — Deployed SHA remains `a004dd98` (no backend/frontend delta)
- **Branch**: `master` (Clean worktree, up to date with origin/master)
- **Base SHA**: `a004dd98906d786eee3360086d6ce15347782999` (Deployed SHA on Render)
- **Deployment Parity**: VERIFIED_NO_RUNTIME_DELTA — commits `6d48175` and `b3ac093` add only docs/reports/scripts; zero backend Python or web frontend TypeScript changed since `a004dd9`.
- **V15.2 Audit Depth**: Full deep-audit executed — uncertainty gates, fallback chain, capture pipeline, Shin bisection (tol=1e-12), prediction log guards, migrations, Redis/PostgreSQL live probe, C6 protocol SHA verify, prediction field semantic audit, frontend contracts.
- **Inventory Artifact**: `reports/execution/production-readiness-inventory.json`.


### Phase 1: Governance Reconciliation
- Governed by Directive V15.0 (`docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V15.md`), superseding V14.0.
- Debt ledger synchronized in `docs/DEBT.md` through Item 168.
- Tooling aligned with `scripts/verify-directive-v15.mjs` and `scripts/verify-directive-v15.sh`.

### Phase 2: Production Path Trace
- Verified single canonical path from provider ingestion to Next.js UI projection.
- Alternate services (`UltraPredictionService`, legacy endpoints) are strictly quarantined or routed through canonical engines. Zero semantic drift detected across probability fields.

### Phase 3: Data Acquisition & Fixture Integrity
- Production sync runs via in-process async loops in FastAPI lifespan. Node.js crawler is strictly offline (`SCRAPER_PRODUCTION_ENABLED="false"`).
- Live query against `/api/v1/upcoming/matches` returned 10 verified upcoming domestic fixtures (PSV vs SC Heerenveen, Dortmund vs Werder Bremen, etc.) for October 9–10, 2026.

### Phase 4: Feature Engineering & Data Quality
- Canonical `apex_v1_68` contract (68 point-in-time features) verified. Missing features strictly categorized into advisory/critical gaps without zero-filling or synthetic imputation.

### Phase 5: Model Artifact & Serving Integrity
- 6 domestic league ensembles (`EPL`, `LA_LIGA`, `BUNDESLIGA`, `SERIE_A`, `LIGUE_1`, `EREDIVISIE`) verified in `active_generation.json`.
- Serving architecture uses stacking meta-models with closed-form Platt scaling.
- Memory cache expanded to `MAX_CACHED_MODELS=8` (DEBT 167), preventing LRU eviction thrashing.

### Phase 6: Prediction Quality & Certification
- Governed by the frozen C6 Protocol (`reports/research/c6-served-generation-vs-close-protocol.json`, SHA-256 `9d63da25...`).
- Current joined settled predictions under `v5_phase7`: `0`. Under DEBT 157/161, interim metrics report `METRICS_UNAVAILABLE` until milestone $N = 200$.

### Phase 7: Betting Engine & Risk Consistency
- Dual engines (`betting_intelligence.py` and `core_engine.py`) audit confirms mathematical alignment:
  - $\text{Implied} = 1 / O$
  - $\text{Fair} = \text{De-vigged}(O)$ via Proportional or Shin bisection
  - $\text{Edge} = p_{\text{model}} - p_{\text{fair}}$
  - $\text{EV} = p_{\text{model}} \cdot O - 1.0$
- Disjoint decision states (`PLAY`, `PASS`, `WITHHELD`) preserved without collapsing into generic "No Bet".

### Phase 8: Model Uncertainty
- Uncertainty is evaluated fail-closed. When certified BNN/ensemble dispersion uncertainty is absent, `critical_gaps` includes `MODEL_UNCERTAINTY_UNAVAILABLE` and forces `stake_permitted = false`.

### Phase 9: Prediction Capture, Settlement & CLV
- Deterministic background async loops capture pre-kickoff predictions in $[t_{\text{now}} + 15\text{m}, t_{\text{now}} + 3\text{h}]$.
- Strict ban on post-kickoff retroactive predictions enforced.

### Phase 10: Redis, PostgreSQL & Backend Resilience
- PostgreSQL 16 migration head `0014_social_auth_identities` confirmed applied on production.
- Redis reconnect and connection pooling verified with active circuit-breaker telemetry.

### Phase 11: 512 MB Production Memory Hardening
- Live Render cgroup working set measured at `334 MB` (`329 MB` RSS), leaving `177 MB` operational headroom.
- Native ML C-extensions clamped to single-thread kernels (`OMP_NUM_THREADS="1"`).

### Phase 12: 8 GB Local Development & Execution Governance
- Local single-lane execution enforced via `ResourceGuard` (`SABISCORE_MAX_RSS_MB=3072`).
- Heavy processes serialized to prevent OS paging or thrashing.

### Phase 13: Frontend & Consumer UX Certification
- Next.js 15.5.6 + React 18.3.1 pinned. Strict AST scan confirms zero client-side odds arithmetic.
- Redundant triple-encoding for decision states (Play, Pass, Withheld) verified color-blind accessible.
- Heading contract (exactly 1 `<h1>` per page) verified.

### Phase 14: Responsible Gambling & Copy Integrity
- Automated AST scan confirms zero banned promotional terms (`lock`, `banker`, `guaranteed`, `sure bet`, `free money`).
- Analytical, measured copy enforced across all routes.

### Phase 15: Security & Supply-Chain Certification
- Zero secrets committed to Git. Provider credentials restricted to backend environment.
- Distributed W3C trace context propagated via `proxyHeaders(incoming)`.

### Phase 16: Observability & Incident Readiness
- Sentry error filtering active, OpenTelemetry spans active, and structured JSON logs emitted.

### Phase 17: Live Production Verification
- Live Render backend (`/health`, `/health/ready`) and Vercel web frontend verified against production deployments. Fixture `fd-558881` analyzed end-to-end with HTTP 200 response.

### Phase 18: Release Gate Matrix
*(See Section 3 below)*

### Phase 19: Authoritative Automated Verification
- Executed `pnpm verify:directive` (`node scripts/verify-directive-v15.mjs`): **11 PASSED, 0 FAILED** in 83.82s.

### Phase 20: Regression Guard Quality
- AST scans and unit regression tests pin all critical behavioral invariants.

### Phase 21: Documentation Finalization
- Updated `docs/PRODUCTION_EXECUTIVE_DIRECTIVE_V15.md`, `docs/DEBT.md`, and `package.json`.

### Phase 22: Deliverables Generated
- `production-readiness-inventory.json`
- `production-readiness-manifest.json`
- `live-verification.md`
- `model-certification-status.md`
- `production-readiness-report.md`

### Phase 23 & 24: Git & Release Management
- Clean git status, isolated branch, zero credential leakage.

---

## 3. Release Gate Matrix

| Domain / Gate | Status | Evidence / Verification Target |
| :--- | :---: | :--- |
| **Repository integrity** | **PASS** | Clean worktree, conventional commits, no secret leakage. |
| **Governance integrity** | **PASS** | Directive V15.0 active, DEBT.md reconciled through Item 168. |
| **Architecture integrity** | **PASS** | Single canonical path, Next.js proxy boundary, no client-side math. |
| **Database & Migrations** | **PASS** | PostgreSQL 16 connected; Alembic head `0014_social_auth_identities` applied. |
| **Redis & Cache** | **PASS** | Tier-1 external Redis connected; reconnect retry loop operational. |
| **Provider health** | **PASS** | football-data.org (50 candidates), The Odds API (1 snapshot), HTTPS-only. |
| **Fixture acquisition** | **PASS** | 10 verified scheduled matches in lookahead; zero synthetic fixtures. |
| **Feature parity** | **PASS** | Canonical `apex_v1_68` contract verified across training and serving. |
| **Model artifacts** | **PASS** | 12 artifacts present across 6 canonical domestic leagues; SHA verified. |
| **Calibration** | **PASS** | Closed-form Platt scaling sigmoid arithmetic verified (`test_calibrator_load_and_preflight.py`). |
| **Uncertainty** | **PASS** | Fail-closed epistemic uncertainty; withheld when uncertified. |
| **Prediction capture** | **PASS** | Async pre-kickoff capture pass operational in lifespan; post-kickoff rejected. |
| **Settlement & CLV** | **PASS** | Settlement scoring loop active; joined pairs tracked under C6. |
| **Betting engine consistency** | **PASS** | Dual engine audit: `betting_intelligence.py` & `core_engine.py` aligned. |
| **Risk controls** | **PASS** | Quarter-Kelly sizing, league caps (2.0% - 4.0%), global hard cap (5.0%). |
| **Backend tests** | **PASS** | Full pytest unit and regression suites passing. |
| **Frontend lint & typecheck** | **PASS** | Strict TypeScript and Next.js 15 build validation passing. |
| **Frontend tests** | **PASS** | Vitest contracts (no-client-ev, copy-contract, heading-contract) passing. |
| **Security & Secrets** | **PASS** | Zero secrets in repo; credential redaction active; CSP eval banned. |
| **Observability** | **PASS** | W3C trace propagation, OTel, Sentry error filtering active. |
| **Deployment parity** | **PASS** | Live backend SHA `a004dd9` healthy on Render; Vercel UI live. |
| **Consumer UX** | **PASS** | Obsidian Nocturne v2 design system, true/implied dumbbell, Counter-Case active. |
| **Documentation** | **PASS** | Directive V15.0, DEBT 168, and verification guides fully updated. |
| **Model certification** | **UNVERIFIED** | Generation `v5_phase7` has 0 joined settled pairs (requires $N \ge 200$). |
| **Staking permission** | **WITHHELD** | Fail-closed: `stake_permitted = false` across all fixtures. |

---

## 4. Final Release Decision

```
┌──────────────────────────────────────────────────────────┐
│ FINAL RELEASE DECISION:                                  │
│ READY — ANALYTICAL / STAKING WITHHELD                    │
└────────────────────────────────────────────────────────┘
```

The SabiScore platform is **100% production ready for consumer prediction intelligence, upcoming fixture exploration, probability visualization, and market comparison**. All financial staking surfaces remain strictly and honestly **WITHHELD** in full compliance with Directive V15.0.

---

## 5. V15.2 Deep Audit Additional Findings

### Confirmed: No New P0 or P1 Defects

The V15.2 full-depth audit inspected:
- `full_analysis.py` handler end-to-end (lines 1–1318): `stake_permitted`, `critical_gaps`, `evaluable`, `prediction_log` persistence, `market_block` construction, `synthesizer.synthesize()` call — all correct.
- `uncertainty_policy.py`: `UNCERTAINTY_REQUIRES_ALL_GATES = True`, `error_association` gate confirmed as the sole failing gate (5/6 pass). This is intentional fail-closed behavior.
- `risk_guard.py`: Per-league epistemic danger thresholds measured on v5_phase7, version `v1-2026-09-19-v5_phase7`. Correctly suppresses low-epistemic region even in EREDIVISIE (unmeasured: uses max threshold 0.0879).
- `prediction_log_service.py`: Post-kickoff guard (line 140–143) confirmed. Fallback/unavailable model_version rejection (line 114) confirmed.
- `market_baseline.py`: Shin bisection `_BISECTION_TOLERANCE = 1e-12` — matches V15.2 requirement exactly.
- `active_generation.json`: Chronological holdout (`2526`), supersedes reason documented, 6 artifacts present.
- `.env*` files: All three (root, `apps/web/`, `backend/`) are gitignored — no secrets in source control.
- `no-client-ev-contract.test.ts`: 5/5 PASSED. Zero client-side odds arithmetic confirmed.
- C6 protocol SHA-256: `9d63da25...` — MATCHES EXPECTED HASH — protocol is immutable.
- Directive V15.0 verification matrix: **11/11 PASSED**.

### P2 Observations (Non-Blocking)

| Code | Description | Severity |
|------|-------------|----------|
| P2-W1 | sklearn `InconsistentVersionWarning`: artifacts pickled with v1.8.0 loaded with v1.9.0. Tests pass; no inference error. Should re-train on current sklearn before next model generation. | P2 |
| P2-W2 | XGBoost serialization note: `Booster.save_model` format recommended over pickle for cross-version stability. Apply during next retraining cycle. | P2 |
| P2-W3 | `asyncio.get_event_loop_policy` deprecated in Python 3.16. P2 Python 3.14 deprecation warnings in test suite — no production impact until Python 3.16. | P2 |

### P3 Observations

| Code | Description | Severity |
|------|-------------|----------|
| P3-W1 | Ruff test `test_ci_local_enforcer_ruff_steps.py` fails when run with system Python 3.14 (no ruff in system interpreter). Passes when run with `.venv` Python — which is the correct execution path. | P3 |
| P3-W2 | `datetime.utcnow()` deprecation in `jose` library (test warning). External library; no action until library releases fix. | P3 |

### Adversarial QA Audit — Confirmed Clean

- No `0.333` fabrication leaks into prediction serving (8 sites audited, all correctly guarded)
- No `fair_probability` ← `model_probability` aliasing errors in serving path
- `prediction_source: UNCERTIFIED_MODEL` correctly serialized (never `CERTIFIED_MODEL`) in live response
- `evaluable: false` in market block when model is UNVERIFIED
- `stake_permitted: false` across all fixtures
- `market.bookmaker: pinnacle` with `captured_at` timestamp from live Pinnacle snapshot
- `freshness_tag: UNKNOWN` (expected — no pre-kickoff CLV capture yet in window)
