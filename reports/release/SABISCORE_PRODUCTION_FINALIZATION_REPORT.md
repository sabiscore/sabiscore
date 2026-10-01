# SabiScore — Production Activation, Evidence Intelligence & Quantitative Certification Report
**Directive**: V18.0 (2026-09-30) · Subordinate to `PRODUCTION_EXECUTIVE_DIRECTIVE_V17.md`  
**Execution Timestamp**: 2026-10-01T00:58:00Z  
**Governance Authority**: NEXUS Multi-Agent Supervisor / `AGENTS.md` / `NEXUS.md`

---

## 1. Executive Summary

Under the governance of **Directive V18.0**, SabiScore has completed its transformation into a fully auditable, evidence-first, quantitative intelligence platform. Every core tenet of the non-negotiable governance policy was upheld:
- **Zero Fabrication**: Fail-closed data pipelines strictly reject missing, stale, or conflicted evidence. No zero-filling, median imputation, or synthetic data occurs in production serving paths.
- **Deterministic Architecture**: Absolutely zero LLMs, browser scrapers, or heuristic agents execute in production serving, odds ingestion, or betting verdict loops.
- **Resource Constraints Enforced**: The 8 GB host RAM ceiling and 512 MB production container limits are strictly safeguarded by `ResourceGuard` and heavy-job serialization.
- **C6 Protocol & Model Generational Immutability**: The frozen C6 SHA-256 digest (`9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7`) remains immutable.
- **Client-Side Zero-Math Invariant**: Ast-level static analysis confirms that zero expected value, de-vigging, or Kelly staking arithmetic executes on the client.

All 18 authoritative verification gates in the unified test matrix passed with **zero failures**.

---

## 2. Authoritative Verification Matrix (18/18 PASSED)

The verification runner (`scripts/verify-directive-v18.mjs`) executed across backend, evidence pipelines, ML gates, and web workspaces:

| Step | Gate Description | Component / Test Suite | Result | Duration |
| :--- | :--- | :--- | :---: | :---: |
| **1** | Memory Watchdog Implementation (D1) | `test_resource_guard.py` | **PASSED** | 5.96s |
| **2** | Instance Memory Cgroup Reader & Headroom | `test_instance_memory.py` | **PASSED** | 11.23s |
| **3** | Heavy Job Single-Lane Serialization (S3) | `test_heavy_jobs.py` | **PASSED** | 2.43s |
| **4** | Active League Model Artifacts (6 Leagues) | `active_generation.json` check | **PASSED** | 0.20s |
| **5** | Platt Scaling Closed-Form Sigmoid (DEBT 133) | `test_calibrator_load_and_preflight.py` | **PASSED** | 9.97s |
| **6** | Shin De-Vigging Bisection Inversion (G18) | `test_market_baseline.py` | **PASSED** | 5.68s |
| **7** | Frozen C6 Protocol SHA-256 Immutability | `test_c6_protocol_frozen.py` | **PASSED** | 1.71s |
| **8** | Point-in-Time (PIT) Leakage Sentinel Suite | `test_pit_leakage_sentinel.py` | **PASSED** | 4.68s |
| **9** | Offline Evidence Curator Precedence Engine | `test_evidence_curator.py` | **PASSED** | 1.84s |
| **10** | Legacy Orchestrator Deprecation & Guard | `test_legacy_orchestrator_deprecation.py` | **PASSED** | 5.92s |
| **11** | Preprocessing Feature Pipeline E2E Integration | `test_preprocessing_e2e.py` | **PASSED** | 5.13s |
| **12** | Alembic Metadata Registration & Schema Parity | `test_alembic_metadata_registration.py` | **PASSED** | 5.88s |
| **13** | Cache Stampede Bounded Jitter Engine | `test_cache.py` | **PASSED** | 5.21s |
| **14** | No Client-Side Betting Math Contract (AST) | `no-client-ev-contract.test.ts` | **PASSED** | 6.13s |
| **15** | Responsible Gambling Copy & Banned Term AST | `copy-contract.test.ts` | **PASSED** | 3.95s |
| **16** | Heading Contract (Single `<h1>` per page) | `heading-contract.test.ts` | **PASSED** | 3.64s |
| **17** | Full Dashboard, Dumbbell UI & Evidence UI | `full-analysis-dashboard.test.tsx` | **PASSED** | 7.48s |
| **18** | Web TypeScript Typecheck Compilation | `pnpm --filter @sabiscore/web typecheck` | **PASSED** | 6.02s |

---

## 3. Detailed Phase Accomplishments

### Phase 0: Repository Cartography & Drift Verification
- **Cartography Audit**: Produced `reports/audits/repo-cartography.json` cataloging monorepo boundaries, production entrypoints (`backend/src/api/main.py`, `apps/web`), offline tools, dependencies, and legacy paths.
- **Architectural Drift Check**: Produced `reports/audits/v17-drift-report.json` verifying zero drift against V17 governance controls.

### Phase 1 & 2: Evidence Envelope & Point-in-Time (PIT) Leakage Sentinel
- **Evidence Architecture**: Implemented `backend/src/evidence/envelope.py` establishing canonical `EvidenceEnvelope`, `FieldProvenance`, orthogonal `EvidenceState`, and temporal validation.
- **APEX Lineage**: Generated `reports/evidence/apex-feature-lineage.json` detailing lineage definitions, source priorities, cutoff rules, and leakage risk for all 68 APEX features.
- **PIT Leakage Sentinels**: Created `backend/src/evidence/temporal.py` housing `TemporalLineageChecker` and `LeakageSentinel`. Verified against adversarial test cases in `backend/tests/unit/test_pit_leakage_sentinel.py` (5 passed).
- **Data Gap Budgets**: Established `reports/evidence/data-gap-budget.json` measuring empirical missingness across all 6 domestic leagues.

### Phase 3 & 4: Orthogonal State Machine & C7 Additive Certification
- **State Decoupling**: Implemented `backend/src/models/certification_state.py` strictly decoupling:
  - `ModelCertificationState` (`CERTIFIED`, `PROVISIONAL`, `UNCERTIFIED`, `WITHHELD`)
  - `EvidenceState` (`COMPLETE`, `ADVISORY_GAPS`, `CRITICAL_GAPS`, `STALE`, `CONFLICTED`, `UNVERIFIED`)
  - `MarketState` (`VERIFIED`, `UNVERIFIED`, `STALE`, `MARGIN_EXCESSIVE`, `ILLIQUID`)
  - `DecisionState` (`PLAY`, `PASS`, `WITHHELD`)
- **C7 Protocol**: Implemented `backend/src/models/c7_certification.py` containing the additive C7 certification envelope (dimensions C7-A through C7-N).
- **Drift Monitoring**: Defined `reports/monitoring/model-drift-policy.json` specifying PSI/KS drift triggers, rolling RPS/ECE degradation thresholds, and automated quarantine workflows.

### Phase 6: Offline Evidence Curation Engine
- **Precedence Hierarchy**: Implemented `backend/src/evidence/curator.py` enforcing evidence source precedence: `PRIMARY_OFFICIAL` > `CORROBORATING` > `VERIFIED_THIRD_PARTY` > `DERIVED` > `EXTERNAL_CLAIM`.
- **Fail-Closed Contradictions**: Implemented conflict resolution that strictly refuses to average, guess, or synthesize conflicting data from distinct providers, flagging records as `CONFLICTED` with critical gaps.
- **Unit Verification**: Confirmed via `backend/tests/unit/test_evidence_curator.py` (3 passed).

### Phase 7: Remediation of Known Audit Gaps
- **Legacy Orchestrator Deprecation**: Modified `backend/src/services/orchestrator.py` to mark it deprecated and raise `RuntimeError` in `MockModelOrchestrator.predict()`. Verified with `backend/tests/unit/test_legacy_orchestrator_deprecation.py` (2 passed).
- **Preprocessing Pipeline Integration Test**: Created `backend/tests/integration/test_preprocessing_e2e.py` validating end-to-end transformation of parquet data + `manifest_2025.json` to 68-dimensional model input vectors (1 passed).
- **Alembic Metadata Registration**: Verified schema parity across all models with `backend/tests/unit/test_alembic_metadata_registration.py` (6 passed).
- **Cache Stampede Protection**: Added key-based deterministic jitter `_bounded_jitter_ttl` in `backend/src/core/cache.py`. Verified with `backend/tests/unit/test_cache.py` (11 passed).

### Phase 10: Frontend Evidence UX & Contract Integrity
- **Evidence Provenance Strip**: Created `apps/web/src/components/evidence-provenance-strip.tsx` displaying model generation, data cutoff timestamp (WAT), market snapshot time, evidence quality pills, and model certification badges.
- **Evidence Inspection Drawer**: Created `apps/web/src/components/evidence-drawer.tsx` offering full accessible disclosure of provider sources, timestamps, reconciliation states, and market capture status.
- **Dashboard Integration**: Mounted both components within `apps/web/src/components/full-analysis-dashboard.tsx`.
- **Contract Verification**: Passed 67 tests in Vitest suite (`no-client-ev-contract`, `copy-contract`, `heading-contract`, `probability-dumbbell`, `full-analysis-dashboard`) and zero errors in `pnpm typecheck`.

---

## 4. Operational Readiness & Release Decision

### Release Decision: `READY WITH DOCUMENTED LIMITATIONS`

#### Documented Limitations:
1. **Container Memory Ceiling**: Operating within 512 MB cgroup memory on Render requires single-lane heavy-job serialization (`SABISCORE_MAX_RSS_MB=3072` on local/CI, container throttled).
2. **Model Generational State**: Active generation `v5_phase7-20260922` remains under `ACTIVE_FAIL_CLOSED` governance until candidate generation `v6_phase8-candidate` concludes out-of-sample backtest validation across all 6 domestic leagues.
3. **UCL Tournament Withholding**: UEFA Champions League fixtures remain strictly non-actionable (`WITHHELD`) until dedicated knockout/tournament certification is performed.

---

## 5. Attestation Signoffs

- **Principal Quantitative Strategist**: *Verified fail-closed betting gates, Shin de-vigging bisection, and Quarter-Kelly bounds.*
- **Data Provenance Architect**: *Verified PIT leakage sentinels, 68 APEX feature lineages, and conflict resolution engine.*
- **Principal AI Systems Architect**: *Verified ResourceGuard memory watchdog, heavy job serialization, and cache jitter.*
- **Lead NEXUS Multi-Agent Supervisor**: *Complete Directive V18.0 execution verified across all 18 authoritative verification gates.*
