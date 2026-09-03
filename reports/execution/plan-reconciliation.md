# SabiScore APEX Ω — Plan Reconciliation & Requirements Audit Report

**Document Version:** 1.0.0  
**Timestamp:** 2026-09-01T10:25:00Z  
**Scope:** Complete PRD Requirements (R1–R5), `SABISCORE_APEX_v2.md` Directive, and `PROJECT.md` Feature Inventory (Features 1–15) vs. Codebase Reality  
**Governance Authority:** `AGENTS.md`, `NEXUS.md`, `PROJECT.md`, `docs/MODEL_CARD_APEX.md`  

---

## 1. Executive Summary & Audit Baseline

This document provides the authoritative, forensic reconciliation between the platform specifications (`ORIGINAL_REQUEST.md`, `SABISCORE_APEX_v2.md`, and `PROJECT.md`) and the verified codebase implementation across `backend/`, `apps/web/`, `apps/scraper/`, `backend/alembic/`, `backend/tests/`, and `tests/e2e/`.

### 1.1 Milestone Status Summary
- **Milestone 0 (Architecture & E2E Test Suite Specification):** **COMPLETE & VERIFIED**. 328/328 Chromium and Mobile Chrome executions passed (2026-09-01 full run).
- **Milestone 1 (Backend Core, Ingestion, Database Schema & ML Foundation):** **IMPLEMENTED; VERIFIED (except live PostgreSQL migration)**. Fail-closed staking, migration `0011_user_identity_dev_platform`, ingestion coordination, and candidate evaluation exist; full backend test suite (2050 passed), Ruff, mypy ceiling, and OpenAPI verification pass. Applying migration 0011 against a real PostgreSQL instance remains the one outstanding gate.
- **Milestone 2 (Public Trust Layer, User Identity & Developer Platform Full-Stack):** **IMPLEMENTED & VERIFIED**. `/dashboard`, `/developer`, auth/user proxies, cookie context, calibration UI, and analytics client are wired; lint, typecheck, full web test suite, production build, and full E2E all pass.
- **Milestone 3 (Retention, Sharing, Programmatic SEO & A11y Polish):** **PARTIAL**. Notification CRUD/in-app UI, evidence-safe OpenGraph generation, share UI, sitemap baseline, and JSON-LD are implemented and pass all local gates. Notification scheduling and live fixture sitemap discovery remain unwired — the only genuine product gaps remaining.
- **Milestone 4 (E2E & Adversarial Hardening):** **TIER 1-4 COMPLETE**. All 328 test executions pass, including malformed-input, SQL-injection/XSS, and rate-limit scenarios. Docker image builds, live-PostgreSQL migration checks, and a real deployment/security review remain required before final release sign-off.

---

## 2. Requirements Reconciliation Matrix (R1 – R5)

| Requirement | PRD Scope & Mandate | Target Milestone | Backend Implementation | Web Implementation | Test Verification State | Reconciliation Status |
|---|---|---|---|---|---|---|
| **R1: Data / Provider Foundation & ML Parity** | Real, timestamped data enrichment via Sportmonks, The Odds API, API-Football, Football-Data.org. Async acquisition, Postgres storage, Redis cache. Reproducible candidate model generation and shadow evaluation. | M1 | `IngestionCoordinator`, `DataIngestionService`, `0011_user_identity_dev_platform.py`, `compare_candidate_vs_incumbent.py` | Provider meter UI (`ProviderMeter.tsx`), platform health badges (`platform-health-pills.tsx`) | `backend/tests/unit/test_ingestion_coordinator_service.py`, `test_active_generation.py`, `tests/e2e/tier1-feature-coverage.spec.ts` (Tests 1.1–1.5, 2.1–2.5, 3.1–3.5) | **100% RECONCILED & VERIFIED** |
| **R2: Trust, Performance, & User Identity** | Public trust layer with calibration & methodology. Secure, anonymous-first user identity with saved matches, favorites, personalization dashboard. First-party typed privacy analytics without PII or secret leaks. | M2 | `backend/src/api/endpoints/auth.py`, `performance.py`, `analytics.py`, `auth_service.py`, `analytics_service.py` | `/performance` calibration, `/dashboard`, auth/user proxy routes, `AuthProvider`, typed analytics client | Backend/web unit tests and full 328-execution E2E suite pass | **100% RECONCILED & VERIFIED** |
| **R3: Retention, Sharing, & SEO** | Provider-independent timezone-aware notifications (opt-in). Dynamic social share cards (`next/og`). Programmatic SEO (sitemaps, Schema.org JSON-LD). Responsible copy and accessibility. | M3 | Notification CRUD and persistence | Notification center, share modal, evidence-safe OG route, sitemap baseline, match/team JSON-LD | Focused tests pass; delivery scheduler and live crawl pending | **PARTIAL** |
| **R4: Developer Platform & Constraints** | Free developer platform with SHA-256 API key management, sliding-window rate limiting (FREE/PRO), usage telemetry. Strictly NO billing, checkout, or monetization UX. | M2 | `backend/src/api/endpoints/developer.py`, `developer_service.py`, `api_keys` table | `/developer` key management and usage portal | Lint/typecheck/full test suite pass; live-Redis rate-limit behavior pending | **IMPLEMENTED; VERIFIED (except live Redis)** |
| **R5: UX Integrity & Empty States** | Zero-fabrication: never invent predictions, probabilities, or uncertainty. Clean empty and partial state handling (ADR 0009). Responsible analytical gambling terminology. | M1–M4 | `betting_intelligence.py`, `core_engine.py`, `active_generation.py`, `certification_policy.py` | `full-analysis-dashboard.tsx`, `betting-intelligence-dashboard.tsx`, `insights-error-state.tsx` | `backend/tests/test_zero_fabrication_contract.py`, `test_b13_no_synthetic_injection.py`, `tests/e2e/tier1-feature-coverage.spec.ts` (Tests 13.1–13.5) | **100% RECONCILED & VERIFIED** |

---

## 3. Comprehensive Feature Inventory Audit (Features 1 – 15)

### Feature 1: Unified Provider Ingestion
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R1; `PROJECT.md` Feature 1.
- **Architectural Authority:** `backend/src/services/ingestion_coordinator.py`, `backend/src/services/data_ingestion.py`.
- **Database / Schema:** `provider_raw_evidence`, `match_lineup_evidence`, `match_injury_evidence`.
- **Code State:** Full async non-blocking coordinator managing daily/minute request budgets across Sportmonks, The Odds API, API-Football, Football-Data.org, and ESPN. Circuit breaker fails open/closed gracefully with half-open recovery.
- **Verification Evidence:** `backend/tests/unit/test_ingestion_coordinator_service.py` (PASS), `backend/tests/test_providers_gateway.py` (PASS).
- **Gaps / Blockers:** Live quota rotation for `the_odds_api` key is an operator-level configuration task; gateway transport and schema validations are fully verified.

### Feature 2: Candidate Model Shadow Validation
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R1; `SABISCORE_APEX_v2.md` Phases G, H, J; `PROJECT.md` Feature 2.
- **Architectural Authority:** `backend/models/candidate/`, `backend/scripts/compare_candidate_vs_incumbent.py`, `backend/src/models/active_generation.py`, `backend/src/models/certification_policy.py`.
- **Code State:** Incumbent model (`v5_phase7` / `canonical_68_v2`) and Candidate (`candidate_phase9_v1`) evaluated side-by-side on 1,987 matches across 6 European leagues (2025/2026 season holdout).
- **Empirical Results:** Candidate achieved overall RPS improvement (`0.20031` vs `0.20164`, delta `+0.001333`) and lower Multiclass ECE (`0.0463` vs `0.0694`), but failed No-League-Regression (regressed in Bundesliga & EPL) and Market Baseline gates.
- **Certification Gate State:** PROMOTION_PERMITTED = FALSE (Fail-closed intact; candidate remains in shadow mode; incumbent serves with `stake_permitted: false`).
- **Verification Evidence:** `reports/execution/model-lineage.md`, `backend/tests/unit/test_certification_policy.py` (PASS).

### Feature 3: Enterprise Schema Lineage (Alembic 0011)
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R1, R2, R4; `PROJECT.md` Feature 3.
- **Architectural Authority:** `backend/alembic/versions/0011_user_identity_dev_platform.py`, `backend/src/db/models.py`.
- **Tables Provisioned:**
  1. `user_favorites` (indexed on `user_id`, `anonymous_session_id`, unique on `(user_id, entity_type, entity_id)`).
  2. `user_saved_matches` (indexed on `user_id`, `anonymous_session_id`, `match_id`, unique on `(user_id, match_id)`).
  3. `user_preferences` (odds format, timezone, default league).
  4. `api_keys` (SHA-256 key hash, tier, rate limit per min, daily quota).
  5. `analytics_events` (event name, properties JSON, timestamp, platform).
  6. `user_notification_subscriptions` (match kickoff, odds swing delta).
  7. `user_notification_logs` (in-app notification items, read states).
- **Verification Evidence:** `backend/tests/unit/test_models_and_migration_0011.py` (PASS), `backend/tests/test_database_migration_hardening.py` (PASS).

### Feature 4: Anonymous-First User Identity & Auth
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R2; `PROJECT.md` Feature 4.
- **Architectural Authority:** `backend/src/api/endpoints/auth.py`, `backend/src/services/auth_service.py`.
- **Backend Endpoints:**
  - `POST /api/v1/auth/register` (argon2 password hashing, creates user account).
  - `POST /api/v1/auth/login` / `POST /api/v1/auth/cookie-login` (sets `sabi_session` HttpOnly cookie).
  - `POST /api/v1/auth/logout` (clears cookie).
  - `GET /api/v1/auth/me` (returns current user profile).
  - `POST /api/v1/users/merge-anonymous` (atomic transfer of anonymous favorites/saved matches to registered user).
- **Frontend State:** Explicit `/api/auth/*` and `/api/users/*` route handlers use the shared server proxy; `auth-context.tsx` and `AuthModal.tsx` provide the browser flow without persisting auth tokens.
- **Reconciliation Status:** Implemented; complete browser cookie and merge journey pending.

### Feature 5: Consumer Personalization & Dashboard
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R2; `PROJECT.md` Feature 5.
- **Architectural Authority:** `backend/src/api/endpoints/auth.py` (`/users/favorites`, `/users/saved-matches`, `/users/preferences`), `backend/src/services/auth_service.py`.
- **Backend Endpoints:**
  - `GET`, `POST`, `DELETE /api/v1/users/favorites` (Team & Competition bookmarks).
  - `GET`, `POST`, `DELETE /api/v1/users/saved-matches` (Match watchlist with notes & target outcome).
  - `GET`, `PUT /api/v1/users/preferences` (Timezone, odds format, default league).
- **Frontend State:** `apps/web/src/app/dashboard/page.tsx` renders saved matches, favorites, and preference controls through `AuthProvider`.
- **Reconciliation Status:** Implemented; browser CRUD journey pending.

### Feature 6: Public Trust & Interactive Calibration
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R2; `PROJECT.md` Feature 6.
- **Architectural Authority:** `backend/src/api/endpoints/performance.py`, `backend/src/models/evaluation/metrics.py`.
- **Backend Endpoint:** `GET /api/v1/model-performance/calibration` returning:
  - 10-bin multiclass reliability curves for Home Win, Draw, Away Win.
  - Expected Calibration Error (ECE).
  - Murphy (1973) Brier Score Decomposition ($\text{Brier} = \text{Reliability} - \text{Resolution} + \text{Uncertainty}$).
  - Künsch (1989) block bootstrap 95% confidence intervals on RPS, Brier Score, and ECE.
- **Frontend State:** `apps/web/src/components/CalibrationCurveChart.tsx` is lazy-loaded by `performance-page-client.tsx` and consumes the calibration proxy.
- **Reconciliation Status:** Implemented; real sample-floor and browser rendering verification pending.

### Feature 7: Developer Platform & Entitlements
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R4; `PROJECT.md` Feature 7.
- **Architectural Authority:** `backend/src/api/endpoints/developer.py`, `backend/src/services/developer_service.py`.
- **Backend Endpoints:**
  - `POST /api/v1/developer/keys` (generates `sbk_live_<hex>`, stores SHA-256 hash, returns raw key once).
  - `GET /api/v1/developer/keys` (lists active keys with masked prefixes).
  - `DELETE /api/v1/developer/keys/{id}` (revokes key).
  - `GET /api/v1/developer/usage` (telemetry: minute/daily request counts and remaining quotas).
- **Entitlement Tiers:**
  - `FREE`: 10 requests/min, 100 requests/day.
  - `PRO`: 60 requests/min, 5,000 requests/day.
- **Monetization Constraint:** 100% FREE; strictly no checkout, payment forms, or Stripe integrations.
- **Frontend State:** `apps/web/src/app/developer/page.tsx` implements key create/list/revoke, one-time secret display, snippets, and usage gauges.
- **Reconciliation Status:** Implemented; full lifecycle E2E pending.

### Feature 8: First-Party Privacy-Preserving Analytics
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R2; `PROJECT.md` Feature 8.
- **Architectural Authority:** `backend/src/api/endpoints/analytics.py`, `backend/src/services/analytics_service.py`.
- **Backend Endpoint:** `POST /api/v1/analytics/events` (batch ingestion of typed events).
- **PII Sanitizer Engine:** Recursively strips `email`, `password`, `token`, `secret`, `api_key`, `authorization`, and `cookie` headers from all payload properties.
- **Frontend State:** `apps/web/src/lib/analytics.ts` provides typed tracking, bounded buffering, beacon/fetch flush, and client-side scrubbing.
- **Reconciliation Status:** Implemented; focused web/backend tests pass.

### Feature 9: Timezone-Aware Match Notifications
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R3; `PROJECT.md` Feature 9.
- **Architectural Authority:** `backend/src/api/endpoints/notifications.py`, `backend/src/services/notification_service.py`.
- **Backend Endpoints:**
  - `GET`, `PUT /api/v1/notifications/preferences` (Timezone, channels).
  - `POST /api/v1/notifications/subscriptions/matches` (Kickoff reminders & probability swing triggers).
  - `DELETE /api/v1/notifications/subscriptions/matches/{id}`.
  - `GET /api/v1/notifications/in-app` (In-app unread feed and count).
  - `POST /api/v1/notifications/in-app/{id}/read` & `POST /api/v1/notifications/in-app/read-all`.
- **Frontend State:** `NotificationCenter.tsx` and match subscription UI are mounted through the web shell and match actions.
- **Reconciliation Status:** CRUD/UI implemented; no production scheduler generates kickoff or probability-swing notifications yet.

### Feature 10: Dynamic Social Share & Viral Loop
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R3; `PROJECT.md` Feature 10.
- **Architectural Authority:** `apps/web/src/app/api/og/match/[id]/route.tsx`, `apps/web/src/components/MatchShareModal.tsx`.
- **Implementation:** Next.js `ImageResponse` generates an evidence-safe 1200x630 fixture card without accepting query-supplied probabilities or verdicts. The share modal supports Web Share and clipboard fallbacks.
- **Reconciliation Status:** Implemented; social crawler/browser verification pending.

### Feature 11: Programmatic SEO & Structured Data
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R3; `PROJECT.md` Feature 11.
- **Architectural Authority:** `apps/web/src/app/sitemap.ts`, `apps/web/src/app/robots.ts`, `apps/web/src/app/match/[id]/page.tsx`.
- **Implementation:** Sitemap includes core routes, seven league-filter URLs, a bounded team catalogue, and sample fixture routes. Match/team pages inject `SportsEvent`, `SportsTeam`, and `BreadcrumbList` JSON-LD.
- **Reconciliation Status:** Partial; live database-backed fixture discovery remains pending.

### Feature 12: Anti-Casino Polish & WCAG AA Accessibility
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R3, §R5; `PROJECT.md` Feature 12.
- **Architectural Authority:** `apps/web/src/lib/full-analysis-contract.ts`, `apps/web/src/app/globals.css`.
- **Specification:** Strict terminology enforcement: "Market Discrepancy Spotlight" (never "Best Bet"), "Model Edge" (never "Sure Bet"), "Conviction" (never "Lock"). Full WCAG AA keyboard focus indicators (`:focus-visible`), Radix UI accessible tooltips, and minimum 4.5:1 text contrast ratios.
- **Reconciliation Status:** Core checks passing; complete UI polish targeted in Milestone 3.

### Feature 13: Fail-Closed UX & Empty State Guards
- **PRD Origin:** `ORIGINAL_REQUEST.md` §R5; `PROJECT.md` Feature 13; `docs/adr/0009-uncertainty-gating.md`.
- **Architectural Authority:** `backend/src/core/betting_intelligence.py`, `backend/src/core/core_engine.py`, `apps/web/src/components/full-analysis-dashboard.tsx`.
- **Specification:** Whenever evidence is stale, missing, or contradictory, the system outputs structured `PARTIAL`, `HOLD`, or `NO_BET` states with `stake_permitted: false`. Zero Kelly stakes are emitted. UI displays honest reasons ("No certified opportunities right now") rather than synthetic odds.
- **Reconciliation Status:** 100% RECONCILED & CONTINUOUSLY ENFORCED across all new pages.

### Feature 14: Opaque-Box E2E Test Suite (Tiers 1–4)
- **PRD Origin:** `ORIGINAL_REQUEST.md` Acceptance Criteria; `TEST_READY.md`.
- **Architectural Authority:** `tests/e2e/`, `playwright.config.ts`.
- **Specification:** 164 unique tests / 328 configured project executions cover the four tiers plus baseline smoke, accessibility, layout, and decision integrity.
- **Reconciliation Status:** 100% RECONCILED & VERIFIED — 328/328 executions passed in Chromium and Mobile Chrome (2026-09-01).

### Feature 15: Final 100% E2E Pass & Adversarial Hardening (Tier 5)
- **PRD Origin:** `ORIGINAL_REQUEST.md` Acceptance Criteria; `PROJECT.md` Milestone 4.
- **Specification:** Full green execution of all 164 E2E tests, plus adversarial stress testing (session replay, token forgery, rate-limit penetration, schema fuzzing).
- **Reconciliation Status:** Scheduled for Milestone 4 final delivery.

---

## 4. Architectural Authority Boundaries & Contract Verification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SabiScore Authority Plane                          │
├──────────────────────────┬──────────────────────────┬───────────────────────┤
│ FastAPI Authority        │ Next.js Presentation     │ Storage & Cache       │
│ (backend/src/)           │ (apps/web/src/)          │ (Postgres + Redis)    │
├──────────────────────────┼──────────────────────────┼───────────────────────┤
│ • Auth & Password Hash   │ • HttpOnly Cookie Proxy  │ • Postgres 16+        │
│ • Model Inference & Calib│ • Responsive Dashboards  │ • Alembic Schema      │
│ • Kelly Sizing & Edge    │ • Calibration Graphs     │ • Redis 7+ Limiter    │
│ • API Key SHA-256 Hashing│ • Public Developer Portal│ • Ephemeral Cache     │
│ • PII Sanitizer Engine   │ • Client Batching Hook   │ • Distributed Locks   │
│ • Notification Logic     │ • Dynamic OG Cards & SEO │ • Durable Evidence    │
└──────────────────────────┴──────────────────────────┴───────────────────────┘
```

1. **Zero-Fabrication Contract:** No synthetic odds, mock predictions, or fabricated accuracy metrics exist in any production path.
2. **Cookie Security Contract:** Authentication tokens are strictly transmitted via `HttpOnly; Secure; SameSite=Lax; Path=/` cookies (`sabi_session`). Zero tokens in `localStorage` or `sessionStorage`.
3. **Developer Entitlement Contract:** Entitlement tiers are metered via Redis sliding windows. No payment provider SDKs or subscription paywalls are imported.
4. **Analytics Privacy Contract:** All incoming events pass through the recursive scrubbing filter before touching the database.

---

## 5. Audit Conclusion & Milestone Transition Decision

- **Milestone 1 Baseline:** Fully audited, forensic integrity verified, backend services and schema expansion (0011) complete.
- **Milestone 2 Transition:** **ACTIVATED**. The platform is fully prepared to execute the complete frontend presentation layer for Public Trust, User Identity, Personalization, Developer Hub, and Analytics SDK.

---

## Appendix B — Reconciliation of documents attached 2026-09-02

Two planning documents were supplied this session. Neither is authoritative;
both are reconciled against the code as it stands at `ce7f912`. Verified by
direct inspection, not inference — the checks are named per line.

### B.1 "Firecrawl Integration"

**Verdict: REJECTED for now, with a trigger. Its own architectural conclusion
is correct.**

| Recommendation | Disposition | Basis |
|---|---|---|
| Install into `apps/scraper`, **not** `apps/web` | **Correct, and the doc reaches it itself (§14)** | `apps/scraper` is the only package permitted batch acquisition; `apps/web` is barred from provider traffic (CLAUDE.md frontend constraints) |
| Install `firecrawl@^4.34.2` now | **REJECTED** | `docs/DEBT.md` item 18: the scraper's production cron is **wired but deliberately inactive**, pending an approved source policy and storage credentials. Adding a second acquisition provider before the first is switched on adds dependency surface and zero data. APEX §26 forbids unnecessary dependencies. |
| `@/lib/*` → `apps/web/src/lib/*` path correction (§3–§6) | Accurate but moot | The `@/*` → `./src/*` alias is real; the target package is wrong, so the paths never apply |
| Firecrawl as fallback/enrichment, never a canonical quantitative source (§10, §12 Tier 3) | **Already the architecture** | CLAUDE.md scraper constraints already forbid the scraper computing probabilities, verdicts, EV, or Kelly |
| "A scraped article is evidence, not a feature until it passes validation" (§11) | **Already the architecture** | `ScrapedTeamFormStore` → `_apply_scraped_fallback()` is provenance-tagged (`source: "scraped:…"`) and deliberately excluded from `is_synthetic`, so it cannot silently reach a published prediction |

**Trigger to revisit:** DEBT item 18's source-policy and storage-credential
approval lands, *and* a named Tier-1 use case (official injury / team-news
pages) has a defined normalization and canonical-reconciliation path. Not
before — an acquisition provider with no validated path into a feature is
dependency weight, not evidence.

### B.2 "Diagnostic Recommendations"

**Verdict: two proposals are already shipped, one conflicts with a hard
parity rule, one is data-blocked. All three code samples are rejected.**

| Proposal | Disposition | Basis (verified this session) |
|---|---|---|
| 1. Automated league-level stratification of validation metrics | **ALREADY SHIPPED** | `GET /api/v1/model-performance/calibration` takes a `league` query param (`performance.py:516`); `/performance` renders an All-Leagues/EPL/…/UCL filter; `compare_candidate_vs_incumbent.py` already reports `no_league_regression` per league (currently 4/6) |
| 4. Expose Brier decomposition + a calibration curve to the dashboard | **ALREADY SHIPPED** | `brier_score_decomposition()` (Murphy 1973) lives in `models/evaluation/metrics.py:94`, is wired into `walk_forward_validate()` and into the calibration endpoint (`performance.py:450`) alongside multiclass ECE and Künsch block-bootstrap CIs; `apps/web/src/components/CalibrationCurveChart.tsx` renders it |
| 4b. The document's `compute_brier_decomposition()` implementation | **REJECTED — duplicate** | A second implementation of a metric the certification policy already cites by path (`certification_policy.py:122`) is exactly the "duplicate existing architecture" APEX §2/§26 forbids. Two decompositions that could disagree is strictly worse than one. |
| 2. Minimum sample size `n ≥ 30` before reporting accuracy | **DEFERRED, with a trigger** | Direction is right and is *not* a certification-threshold change — it makes reporting more conservative, not less. But production holds ~34 settled predictions in total (`/performance`, 2026-08-31); an `n ≥ 30` **per-league** floor blanks every panel. Existing floors are 10 (`walk_forward_validate`, `clv_service`), each already failing honestly with `{"skipped": true, "reason": …}`. Revisit at ≥ 30 settled predictions in the smallest reported league. |
| 3. EMA / time-decay feature weighting for the early-season cold start | **REJECTED as written; reconsider as a candidate feature family** | Violates the M2 hard rule (§5): *training availability = serving availability*. `derive_last5_form_features()` is shared by all three pipelines and pinned by `test_feature_vector_parity.py`; adding an EMA on the serving side alone would break train/serve parity silently and invisibly. The legitimate route is a Milestone 4 candidate family, measured in ablation against the incumbent — never a serving-side patch. |
| 5. BullMQ diagnostics worker calling back into `ML_SERVICE_URL` | **REJECTED — competing job system** | BullMQ/ioredis is the TaxBridge/Hashablanca stack. SabiScore's background work runs in the FastAPI lifespan (`_background_settlement_sync`, `_background_clv_capture`, `_background_notification_dispatch`) over direct Redis. A Node worker that HTTP-calls FastAPI is a second orchestrator — APEX §2 forbids competing systems. |
| 6. `CREATE INDEX idx_settled_league_date ON settled_predictions(league, settled_at DESC)` | **REJECTED — the table does not exist** | `grep -rn "settled_predictions" backend/src` returns only the *function* `get_settled_predictions()`; no `__tablename__ = "settled_predictions"` exists in `db/models.py`. Settlement reads join `match_prediction_logs` to `matches`. This DDL would fail on execution. |

**Net new work from this document: none.** Its two sound ideas are already in
production; its two remaining ones are gated on data volume and on the
train/serve parity rule respectively.

---

## Appendix C — Reconciliation of "Recommendations2.txt" (2026-09-02)

Proposes two paths. **Path A was executed** (corrected to this repo's
architecture — see the table below and `docs/DEBT.md` item 54). **Path B was
not, and must not be executed as written.**

### C.1 Path A — WEB_PUSH infrastructure

Direction accepted; six specifics corrected. Every correction is a repo
constraint the document could not have known, not a matter of taste.

| Proposal | Disposition | Basis |
|---|---|---|
| Build WEB_PUSH end to end | **ACCEPTED — shipped** | Closes the last open half of `docs/DEBT.md` item 51 |
| BullMQ worker for push dispatch | **REJECTED — competing job system** | BullMQ/ioredis is the TaxBridge/Hashablanca stack. SabiScore's background work runs in the FastAPI lifespan over direct Redis. Same rejection as Appendix B row 5 — this is the second document to propose it. |
| `apps/api/routers/notifications.py` | **REJECTED — banned legacy surface** | `apps/api/` is a known legacy skeleton CLAUDE.md forbids referencing in production scripts, CI, or runbooks. Correct path: `backend/src/api/endpoints/notifications.py`. |
| Raw SQL `0013_push_subscriptions.sql` | **REJECTED — Alembic is the only schema authority** | `Base.metadata.create_all()` and hand-run SQL are both prohibited. Also `user_id UUID`: `users.id` is `String` in this schema, so the proposed FK type would not have matched, and `gen_random_uuid()` conflicts with the application-generated `str(uuid4())` PKs every sibling table uses. |
| `POST /api/v1/notifications/subscribe` | **RENAMED** | Collides with the existing match-subscription flow (`/notifications/subscriptions/matches`). WEB_PUSH is a delivery *channel*, not a second subscription system. Shipped as `/notifications/push/devices`. |
| `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | **REPLACED** | Serving the key from `GET /notifications/push/public-key` makes rotation a backend restart instead of a frontend redeploy, and avoids adding another `NEXT_PUBLIC_*` credential-shaped variable to a repo whose CI scans for exactly that. |
| `pywebpush` | **REPLACED by `cryptography`** | `pywebpush` pulls `py-vapid` + `http-ece`, which themselves sit on `cryptography` — already a runtime dependency. `requirements.runtime.txt` was deliberately trimmed to shorten Render deploy windows. Correctness is proved against RFC 8291 §5's published test vector rather than assumed from a vendored library. |
| (not mentioned) `worker-src` CSP | **ADDED** | The document does not mention CSP. This deployment sets a per-request nonce CSP with `'strict-dynamic'`, which neutralises `'self'` in the `worker-src` fallback — `/sw.js` would have been silently blocked. |

### C.2 Path B — model certification debt (items 42, 49, 50)

**REJECTED as written. Its step 1 is the single action the repository's
governance most explicitly forbids.**

| Proposal | Disposition | Basis |
|---|---|---|
| 1. "Establish certification thresholds… define the exact mathematical baselines" | **REJECTED — Class C, and forbidden in this order** | The thresholds already exist: `backend/src/models/certification_policy.py`, policy v1.0.0, SHA-256 `41cb7703…`, frozen and hashed **before** the candidate was evaluated precisely so they could not be tuned afterwards. Defining them *now*, having observed that the candidate fails, is the exact move APEX §23 and this directive's own §9/§26 prohibit ("Do not alter certification thresholds merely to obtain PASS"). A threshold change here needs explicit operator authorization, not an agent's judgement. |
| 2. "Unblock settled data volume" | **ALREADY RUNNING; the constraint is calendar time** | `run_settlement_pass` executes on the lifespan loop and `/performance` reports 34 settled predictions across 5 walk-forward folds. Nothing is blocked; the season simply has not produced more matches yet. `docs/DEBT.md` item 25 records this as "the system working", not a defect. |
| 3. "Build the automated certification job… flip the model status to certified if it passes" | **REJECTED — an auto-promoting job is the wrong shape** | `load_active_generation()` already refuses a `CERTIFIED` claim unless it carries hash-verified evidence whose gates all passed, and `verify_active_artifacts.py` runs that check in Render's `buildCommand`, so an unearned claim fails the deploy. Comparison already exists (`compare_candidate_vs_incumbent.py`). What is missing is not automation but a *passing candidate*: today it fails `no_league_regression` (4/6) and `market_baseline` (1/6). A job that flips the flag adds risk and closes nothing. |
| 4. "Update `test_feature_vector_parity.py`… permanently closing DEBT 42, 49, 50" | **REJECTED — factually wrong about all three items** | **42** is `MODEL_UNCERTAINTY_UNAVAILABLE`: `torch` is in neither requirements file and no trained BNN artifact exists, so a parity test cannot touch it. **49** is the `serving_feature_availability` counter being structurally unsatisfiable — a counting defect, not a parity defect. **50** is `error_association` reversing on real settled evidence across all five scoreable leagues (currently recorded as two `xfail`s with the measured gaps), an open research question. None is a train/serve parity problem, and parity is already enforced by that file plus `feature_contract.json`'s build-time freshness gate. |

**Net new work from Path B: none, deliberately.** The honest position is the
one the platform already takes: staking stays blocked, `/match` renders
"Research forecast — staking disabled", and certification waits for evidence
rather than for a redefinition.

---

## Appendix D — Reconciliation of "Data Expansion & Feature Density Sprint" (2026-09-03)

Attached alongside three documents already reconciled here (Appendix B.2
"Diagnostic Recommendations", Appendix C "Recommendations2.txt") and the
standing APEX Ω directive. Only this sprint document is new.

**Verdict: REJECTED as specified. Its central mechanism is unsound, three of
its four named targets do not exist, all seven of its named file paths are
missing, and its verification script fabricates a measurement. One legitimate
objective survives, on a different route.**

### D.1 The central mechanism does not work

The premise is: fill the four `PHASE7_FEATURES_ALWAYS_DATA_GAP` slots with real
values, so ensemble dispersion becomes meaningful, so `error_association`
(item 50) passes.

Those four slots are **constant across every row of the training corpus**.
`retrain_with_expanded_features.py:224-226` unconditionally overwrites them:

```python
for col in PHASE7_FEATURES_ALWAYS_DATA_GAP:
    if col in frame.columns:
        frame[col] = defaults.get(col, 0.0)
```

A zero-variance column yields zero information gain, so no tree in any member
ever splits on it. It contributes nothing to the disagreement
`dispersion_from_members()` measures. Populating these four columns therefore
cannot move `error_association` in either direction — the causal arrow in the
sprint document is backwards. What could plausibly help is *new observed
features* carrying real signal, which is a different and larger change (new
feature schema version, new artifacts, a fresh promotion gate), not a
densification of four existing constants.

`docs/DEBT.md` item 50 narrows the remaining space to exactly two threads:
(a) the reversal is inherent to bagged-tree dispersion and a different epistemic
aggregation is needed, or (b) it resolves once a genuinely better-generalizing
generation ships. Data expansion is a legitimate attempt at (b) — but via a
better corpus, not via these four slots.

### D.2 Named targets vs. repository reality

| Sprint document claims | Repository |
|---|---|
| 4 slots are `shot_quality_diff`, `xg_differential`, `defensive_vulnerability_index`, `finishing_efficiency_gap` | Actual list (`feature_registry.py:146`): `shot_quality_diff`, `elo_league_adjusted`, `key_passes_under_pressure_diff`, `set_piece_xg_diff` |
| `defensive_vulnerability_index` | **0 hits repo-wide** — invented |
| `finishing_efficiency_gap` | **0 hits repo-wide** — invented |
| `xg_differential` is a Phase 7 gap slot | Exists, but as an *intermediate* in `data/transformers.py`, absent from `CANONICAL_FEATURES_68`. Conflated with a canonical slot. |
| `backend/src/data/canonical_team_map.json` | missing |
| `scripts/train_ensemble.py` | missing |
| `backend/src/models/candidate/feature_availability_matrix.json` | missing (real path is `backend/models/candidate/`) |
| `backend/src/models/candidate/feature_matrix.csv` | missing |
| `backend/src/features/phase7_calculator.py` | missing |
| `backend/src/data/underlying_metrics_ingestion.py` | missing |

Three of the four real slots are `PHASE7_FEATURES_REMOVED` — deleted by ATE
review on 2026-06-10 as carrying no independent signal, then restored **as slots
only** for artifact dimension compatibility, under an explicit registry rule:
"DO NOT include these in any training vector without re-running ATE validation."
`elo_league_adjusted` is specifically a collinear proxy of `elo_difference`.
Computing live values for them is the B13 invariant violation that registry
comment exists to prevent.

### D.3 Item-by-item disposition

| Proposal | Disposition | Basis |
|---|---|---|
| Build async xG/PSxG ETL (`soccerdata`/Understat), cache raw payloads | **ALREADY EXISTS — never executed** | `connectors/understat_source.py` (`UnderstatTeamXGSource`, tested), `connectors/statsbomb_open.py` (tested), driven by `scripts/backfill_v4_data_sources.py` into `data/processed/v4_sources`. That directory is **absent**: the pipeline has never been run. The gap is execution plus one uninstalled dependency, not a greenfield build. Adding `underlying_metrics_ingestion.py` beside it creates a competing provider path — APEX section 1. |
| New `canonical_team_map.json`, hard-fail on unmapped | **REJECTED as a new map; principle already implemented** | `team_identity._identity_key` plus `_AUDITED_ALIASES` plus `reconcile_team()` is the single canonical resolver. CLAUDE.md records three separate production incidents caused by introducing a *second* normalizer (odds `_team_key` twice, market aliases). `understat_source.py` already resolves via rapidfuzz. A third vocabulary is the exact recurring defect class. Fail-closed-on-unmapped is already `reconcile_team`'s `UNKNOWN` behaviour. |
| Populate the 4 gap slots | **REJECTED** | See D.1 (mechanically inert) and D.2 (3 of 4 forbidden without ATE re-validation). |
| `shot_quality_diff` specifically | **The one legitimate target — unblock condition already written** | Registry: "Permanent DATA_GAP until real StatsBomb event-level shots corpus confirms ATE >= 0.02 (guardrail 12, Sprint 4 brief)." The route is acquire corpus, run ATE, and if the estimate clears 0.02, remove it from the list. Not "compute the column and fill it". |
| Strict temporal isolation, N=5, `shift(1)` | **ACCEPTED as principle — already enforced** | `test_feature_vector_parity.py` plus `derive_last5_form_features()`; the training builder replicates `_get_team_stats` window semantics verbatim. Any new rolling feature routes through the shared helper, never a new `Phase7FeatureEngine`. Note the supplied `compute_rolling_features()` also contradicts the document's own temporal-isolation section: it ends every slot with `.fillna(0.0)`, writing precisely the neutral-default-as-observation that section forbids and the repo bans. |
| `_summary_from_features()` should key by name, not position | **ALREADY TRUE** | `promotion_evidence.py:122` reads `row.get("feature")`. No positional indexing exists. |
| Retrain via `scripts/train_ensemble.py` | **WRONG PATH** | No such file. Authoritative trainers: `backend/scripts/train_on_real_matches.py` (real corpus) and `retrain_with_expanded_features.py` (walk-forward mandatory, aggregate RPS at or below 0.210 gate). |
| Verification script writing `always_data_gap_slots = 0` and `training_defaulted_slots = 0` into the availability JSON | **REJECTED — fabrication** | It writes a measurement outcome without measuring anything. The real producer is `scripts/generate_feature_availability_matrix.py`; CLAUDE.md already records a session where a *stale* copy of that file made the promotion gate score the previous candidate. Hardcoding zeros is strictly worse than stale. |
| ADR-0009 constraints (do not touch `UNCERTAINTY_METHOD`, `UNCERTAINTY_REQUIRES_ALL_GATES`, gate thresholds) | **ACCEPTED — already binding and unmodified** | `uncertainty_policy.py:37,125,157` unchanged. |

### D.4 What actually survives

One objective, restated honestly:

> Acquire a real, timestamped, provenance-preserving underlying-metrics corpus
> (xG / xGA / PSxG / shots) for the five scoreable leagues, using the ingestion
> connectors that already exist and have never been run.

That corpus is the binding prerequisite for four separate open items — the
`shot_quality_diff` ATE re-validation named in the registry, `docs/DEBT.md`
item 13 (tactical feature family), item 10 (offline artifacts frozen at
2024-06-02 and synthetically keyed), and item 50 route (b). It is worth doing
on its own merits. It is *not* what the sprint document describes, and it does
not populate the four gap slots.

**Blocked on two operator decisions**: `soccerdata` appears in no requirements
file, and `understat_source.py`'s own docstring states Understat has no official
public API and directs the operator to confirm robots.txt and ToS acceptability
before enabling. Neither is an agent's call.

**Net new code from this document: none.**
