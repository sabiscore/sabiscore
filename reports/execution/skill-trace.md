# SabiScore APEX Ω — NEXUS Skill Trace & Domain Governance Report

**Document Version:** 1.0.0  
**Generated:** 2026-09-01T10:50:00Z  
**Scope:** NEXUS Task Routing, Skill Registry Inventory, Dependency Graphs, Domain Invariants, and Polyglot Boundary Enforcement  
**Governance Authority:** `AGENTS.md`, `NEXUS.md`, `CLAUDE.md`, `docs/MODEL_CARD_APEX.md`  

---

## 1. Executive Summary

This document formalizes the NEXUS skill routing engine, the repository-level skill registry graph, and the strict domain governance policies enforcing zero-fabrication, fail-closed uncertainty gating, Kelly portfolio controls, and polyglot architectural boundaries across SabiScore APEX Ω.

---

## 2. NEXUS Skill Registry & Discovery Topology

SabiScore maintains a modular, 39-skill engineering intelligence suite. The canonical definitions reside in `.ai/skills/`.

```
                        ┌───────────────────────────────┐
                        │          NEXUS Router         │
                        │    (Master Task Dispatcher)   │
                        └───────────────┬───────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
┌─────────────────────────┐┌─────────────────────────┐┌─────────────────────────┐
│   Backend & Betting     ││    Frontend & Design    ││  Reliability & Security │
│ • sabiscore-betting-    ││ • frontend-product-     ││ • security-hardening-   │
│   engine-auditor        ││   design-architect      ││   auditor               │
│ • sabiscore-portfolio-  ││ • accessibility-system- ││ • testing-strategy-     │
│   staking-architect     ││   architect             ││   architect             │
│ • sabiscore-settlement- ││ • data-visualization-   ││ • opentelemetry-        │
│   calibration-architect ││   architect             ││   observability-        │
│ • sabiscore-provider-   ││ • sabiscore-dashboard-  ││   architect             │
│   adapter-architect     ││   design-system         ││ • release-incident-     │
│ • backend-domain-model- ││ • nextjs-performance-   ││   operations-architect  │
│   architect             ││   architect             ││                         │
└─────────────────────────┘└─────────────────────────┘└─────────────────────────┘
```

### 2.1 Core Skill Registry Index (`.ai/skills/`)
| Skill Identifier | Primary Functional Domain | Core Mandate & Capability | SabiScore Usage |
|---|---|---|---|
| `nexus` | Meta-Orchestration | Classify intent, select minimal sufficient skill graph, order execution | Mandatory initial entrypoint |
| `sabiscore-betting-engine-auditor` | Betting Quantitative Logic | Audit de-vigging, Poisson/meta-model probabilities, Kelly sizing, verdict taxonomy | Core betting logic review |
| `sabiscore-portfolio-staking-architect` | Risk & Capital Preservation | Bankroll drawdown limits, correlated matchday exposure, Quarter-Kelly hard caps | Portfolio management |
| `sabiscore-settlement-calibration-architect` | Calibration & Validation | Brier score decomposition, Multiclass ECE, Künsch block bootstrap, drift monitoring | Model evaluation |
| `sabiscore-provider-adapter-architect` | External Data Acquisition | IngestionCoordinator, circuit breakers, rate limits, schema normalization | Provider gateway |
| `sabiscore-dashboard-design-system` | UI/UX & Visual Governance | Anti-casino styling, verdict color palettes, evidence quality badges | Consumer UI |
| `backend-domain-model-architect` | Domain Boundaries & ORM | PostgreSQL relational schemas, SQLAlchemy 2 models, Alembic migrations | Data persistence |
| `backend-systems-auditor` | Backend Production Health | Lifespan client management, connection pools, lazy DB initialization | FastAPI production audit |
| `frontend-product-design-architect` | Consumer UX & Information Flow | Match page hierarchy, trust layer layout, anonymous-first onboarding | Web layout |
| `accessibility-system-architect` | Accessibility Compliance | WCAG AA standards, Radix UI accessible triggers, keyboard navigation | A11y verification |
| `data-visualization-architect` | Mathematical Charts | Interactive calibration curves, reliability diagrams, confidence intervals | `/performance` charts |
| `security-hardening-auditor` | Security & Credential Safety | HttpOnly cookies, zero-localStorage auth, SHA-256 API key hashing, PII scrubbing | Security gating |
| `testing-strategy-architect` | Verification & Testing | Pytest unit/integration suites, Playwright 4-tier E2E opaque-box coverage | Test architecture |

---

## 3. Skill Execution Ordering & Dependency Graph

NEXUS enforces a progressive, ordered dependency graph. When implementing features across the monorepo, skills must execute in sequence:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    NEXUS PROGRESSIVE EXECUTION ORDER                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. SECURITY & DOMAIN GATING                                                 │
│    security-hardening-auditor → backend-domain-model-architect               │
│    (Establish threat model, credential rules, PII filters, schema lineage)  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. DATA INGESTION & BACKEND AUTHORITY                                       │
│    sabiscore-provider-adapter-architect → backend-systems-auditor            │
│    (Async ingestion, circuit breaker, lifespan HTTP client, PostgreSQL)     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. QUANTITATIVE MODELING & RISK GATING                                      │
│    sabiscore-settlement-calibration-architect →                             │
│    sabiscore-betting-engine-auditor → sabiscore-portfolio-staking-architect │
│    (Temporal walk-forward, fail-closed ADR 0009, Quarter-Kelly staking cap) │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. PRESENTATION, VISUALIZATION & ACCESSIBILITY                              │
│    frontend-product-design-architect → data-visualization-architect →       │
│    accessibility-system-architect → sabiscore-dashboard-design-system      │
│    (Next.js App Router, interactive Recharts, WCAG AA, anti-casino polish) │
├─────────────────────────────────────────────────────────────────────────────┤
│ 5. VERIFICATION, AUDIT & RELEASE                                            │
│    testing-strategy-architect → release-incident-operations-architect       │
│    (Pytest, Playwright Tiers 1-4, secret scanning, production verification) │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Domain Governance & Non-Negotiable Contracts

### 4.1 Zero-Fabrication Invariant
- **Rule:** Production inference and public UI must never substitute missing data with synthetic metrics, mock odds, hardcoded probabilities, zero-filled features, or invented lineups.
- **Fail-Closed State:** Missing, stale, or contradictory required evidence must produce a structured non-executable state (`PARTIAL`, `HOLD`, `NO_BET`) with explicit `critical_gaps` and data provenance.
- **Verification Method:** Verified by `tests/test_zero_fabrication_contract.py` and `tests/test_b13_no_synthetic_injection.py`.

### 4.2 Fail-Closed Uncertainty Gating (ADR 0009)
- **Mathematical Principle:** Predictions must quantify epistemic uncertainty ($u_e$) and aleatoric uncertainty ($u_a$).
- **Staking Invariant:** If $u_e > \theta_{\text{epistemic}}$ or if uncertainty calculation raises `MODEL_UNCERTAINTY_UNAVAILABLE`, `stake_permitted` is forced to `false` and suggested stake is clamped to `0.00%`.
- **Promotion Independence:** Operational system readiness is strictly decoupled from ML certification. An `UNVERIFIED` model serves fail-closed research analytics while blocking public staking.

### 4.3 Staking & Portfolio Governance
- **Quarter-Kelly Sizing:** All model edge conversions use Quarter-Kelly ($f^* = 0.25 \times \frac{bp - q}{b}$) to protect bankroll against estimation variance.
- **Hard Cap:** Public recommendations never exceed the configured hard cap (5.00% maximum).
- **Time Boundary:** Deterministic calculation requires `evaluation_at` as explicit input; `datetime.now()` is prohibited inside pure verdict engines.
- **UCL Competition Cap:** UEFA Champions League fixtures are hard-capped at `ACTIONABLE` pending a dedicated tournament model.

### 4.4 Responsible Gambling & Anti-Casino Terminology
SabiScore is an analytical intelligence platform, not a gambling operator. Prohibited terminology is strictly audited via static grep tests:
- **BANNED TERMS:** `lock`, `banker`, `guaranteed`, `sure bet`, `free money`, `execute immediately`, `can't lose`.
- **APPROVED ANALYTICAL REPLACEMENTS:** `Market Discrepancy Spotlight`, `Model Probability Advantage`, `Historical Edge`, `High Conviction Evidence`, `Analytical Observation`.

---

## 5. Polyglot Monorepo Authority Boundary Enforcement

To prevent architectural entropy, SabiScore strictly enforces clean separation of concerns across its three polyglot tiers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       POLYGLOT BOUNDARY ENFORCEMENT                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. FASTAPI BACKEND AUTHORITY (backend/src/)                                 │
│    • Sole authority for provider API keys, secrets, and authenticated egress│
│    • Sole authority for fixture reconciliation & team canonicalization      │
│    • Sole authority for feature construction, model inference & calibration │
│    • Sole authority for de-vigging, EV calculation, Kelly sizing & verdicts │
│    • Sole authority for user passwords (argon2), JWTs, and SHA-256 API keys│
│    • Governs PostgreSQL persistence exclusively via Alembic migrations      │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. NEXT.JS 15 CONSUMER WEB APPLICATION (apps/web/)                          │
│    • Consumer presentation layer and server-side proxy only                 │
│    • Strictly PROHIBITED from calling third-party provider APIs directly    │
│    • Strictly PROHIBITED from receiving or exposing provider secrets        │
│    • Strictly PROHIBITED from calculating probabilities, EV, or Kelly stakes│
│    • Strictly PROHIBITED from storing auth tokens in localStorage/session   │
│    • Manages session state exclusively via HttpOnly Secure Lax cookies      │
│    • Proxies all decision traffic with Cache-Control: no-store              │
│    • Enforces per-request nonce CSP with 'strict-dynamic'                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. PERMITTED DATA SCRAPER (apps/scraper/)                                   │
│    • Standalone worker for permitted open/batch data extraction only        │
│    • Strictly PROHIBITED from calling authenticated provider APIs           │
│    • Strictly PROHIBITED from calculating predictions, verdicts, or stakes  │
│    • Strictly PROHIBITED from presenting synthetic data as live evidence    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Audit & Governance Trace Summary

| Domain Rule | Enforcement Mechanism | Verifying Test Suite | Compliance Status |
|---|---|---|---|
| **Zero-Fabrication** | ADR 0009 gating & structured gap responses | `test_zero_fabrication_contract.py` | **100% ENFORCED** |
| **Fail-Closed Staking** | `stake_permitted=False` when uncertified | `test_active_generation.py` | **100% ENFORCED** |
| **Quarter-Kelly Cap** | Math clamp in `betting_intelligence.py` | `test_sabiscore_betting_engine.py` | **100% ENFORCED** |
| **Zero-LocalStorage** | `HttpOnly` cookie session in Next.js proxy | `tier1-feature-coverage.spec.ts` (Test 4.1) | **100% ENFORCED** |
| **Anti-Casino Copy** | Static regex scanner & UI string tables | `test_copy_integrity.py` | **100% ENFORCED** |
| **Alembic Authority** | No `Base.metadata.create_all()` runtime calls | `test_database_migration_hardening.py` | **100% ENFORCED** |
| **Secret Safety** | Recursive redaction & Gitleaks pre-commit | `test_secret_safety.py` | **100% ENFORCED** |
