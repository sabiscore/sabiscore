# Original User Request

## 2026-08-31T20:32:35Z

# Teamwork Project Prompt

Transform the SabiScore platform into a fully functional, evidence-backed, consumer-ready football intelligence product. This includes real live data enrichment, robust candidate model generation, shadow production, a public trust layer, user personalization, and growth features—all while remaining 100% free for users.

Working directory: c:\Users\UBEC-DC-ANAMBRA\Documents\sabiscore
Integrity mode: demo

## Verification Resources
Use the existing test suites in the repository as the baseline for verification:
- Backend: `backend/tests/` (unit, integration, provider, engine, quota, cache, and migration tests)
- Frontend: `apps/web/tests/`, `apps/web/e2e/` (Playwright desktop and mobile smoke tests)

## Requirements

### R1. Data / Provider Foundation & ML Parity
Implement real, timestamped data enrichment using Sportmonks, The Odds API, and API-Football. Store raw evidence in PostgreSQL (using Alembic migrations) and use Redis for ephemeral caching. External provider calls must be asynchronous, not blocking the FastAPI prediction path. Generate an enriched candidate model, run temporal evaluation, and deploy in shadow production. Do not weaken existing uncertainty gates.

### R2. Trust, Performance, & User Identity
Build a public trust layer detailing model performance and methodology. Implement a secure, anonymous-first user identity system supporting saved matches, favorites, and personalization (dashboard). Integrate strict, typed first-party product analytics that do not log PII, passwords, or raw secrets.

### R3. Retention, Sharing, & SEO
Implement provider-independent notifications (opt-in, timezone-aware). Build stable match discovery pages, a share/viral loop with share cards, and programmatic SEO for matches, teams, and competitions. Redesign the homepage to emphasize "evidence-backed football intelligence" rather than a casino aesthetic. Ensure strict WCAG AA accessibility.

### R4. Developer Platform & Constraints
Create a free developer platform with API key management and usage visibility. Build underlying entitlement primitives (FREE, PRO, etc.) but **do not** introduce paid subscriptions, billing, or monetization UX. Use only the existing architecture (FastAPI, Next.js, Postgres, Redis). Do not create competing prediction engines, identity systems, or provider gateways.

### R5. UX Integrity & Empty States
Never fabricate predictions, accuracy metrics, or uncertainty when data is missing. All critical surfaces must handle empty, partial, or error states cleanly (e.g., "Unavailable", "Not enough evidence"). Use precise, responsible gambling terminology.

## Acceptance Criteria

### Data & Architecture
- [ ] Alembic migrations exist for all new schema additions; no runtime `create_all()` is used.
- [ ] Provider fetching operates asynchronously (e.g., workers/cron) and does not block FastAPI `/predict` routes.
- [ ] No new auth systems or prediction engines are duplicated; existing systems are extended.

### Machine Learning
- [ ] Candidate model generation pipeline is strictly reproducible (seeds, git commits, feature versions logged).
- [ ] Temporal evaluation is performed using a rolling-origin method without future data leakage.
- [ ] Model uncertainty remains strictly fail-closed if uncertified (no synthetic uncertainty values displayed).

### Product & UX
- [ ] A complete anonymous-to-authenticated flow works without storing auth tokens in `localStorage`.
- [ ] Automated accessibility checks (WCAG AA) pass for new components (visible focus, semantic landmarks, contrast).
- [ ] E2E tests verify core journeys: browse → analyze → signup → save match → share.

## 2026-09-01T05:39:34Z

# Teamwork Project Prompt

Working directory: c:\Users\UBEC-DC-ANAMBRA\Documents\sabiscore
Integrity mode: demo

## SABISCORE APEX Ω — AUTONOMOUS PRODUCTION EXECUTION DIRECTIVE

### ROLE
Act as the Principal Autonomous Systems Architect, Staff Platform Engineer, Senior ML Systems Engineer, Quantitative Football Analytics Engineer, Senior FastAPI/PostgreSQL Engineer, Senior Frontend/Product Engineer, Product Strategist, UX/Product Designer, Analytics Engineer, Security Engineer, SEO Engineer, SRE/Observability Owner, and Production Release Owner for:
**Repository:** `sabiscore/sabiscore`

Primary objective:
> Transform the existing SabiScore platform into a fully functional, evidence-backed, intelligent, visually cohesive, trustworthy, consumer-ready, growth-ready, retention-oriented, and production-ready football intelligence product, while remaining 100% FREE during this milestone.

Do not introduce:
* payments
* subscriptions
* checkout
* billing
* affiliate monetization
* artificial paywalls
* automated betting execution

Architect future monetization underneath the product, but do not activate it.

### 1. ABSOLUTE OPERATING PRINCIPLES
- **Inspect before modifying:** Never guess. The current repository, active artifacts, tests, migrations, etc., are authoritative.
- **Preserve the architecture:** Keep Next.js (frontend), FastAPI (backend), scraper, PostgreSQL, Redis. Extend surgically; do not create competing engines or systems.
- **Evidence outranks growth:** Never sacrifice data/model/certification integrity for growth.

### 2. CURRENT GROUND TRUTH
Reconcile all facts against the latest code before acting. FastAPI is the authority; PostgreSQL is durable state; uncertainty certification remains fail-closed; production model promotion is separate from health.

### 3. MANDATORY FIRST EXECUTION SEQUENCE
Do these steps in this exact order before implementing product features:
1. **Lock the baseline:** Produce `reports/execution/baseline.md`.
2. **Read governance:** Produce `reports/execution/skill-trace.md`.
3. **Audit architecture:** Produce `reports/execution/architecture-map.md`.
4. **Audit data and ML contracts:** Produce `reports/execution/feature-matrix.md` and `model-lineage.md`.
5. **Audit production health:** Produce `reports/execution/production-health.md`.
6. **Audit attached plans against reality:** Produce `reports/execution/plan-reconciliation.md`.
7. **Create the execution backlog:** Produce `reports/execution/prioritized-backlog.md`.
8. **Select exactly ONE first implementation target:** Produce `reports/execution/next-milestone.md`.

### 4. MILESTONE 1 — DATA + FEATURE INTEGRITY (P0)
Increase real, timestamped information (player availability, expected lineups, real xG, market movement, etc.). Use existing provider contracts via asynchronous acquisition → PostgreSQL → Redis → FastAPI.

### 5. MILESTONE 2 — TRAIN/SERVE FEATURE PARITY (P0)
Define strict train/serve parity. Hard rule: TRAINING AVAILABILITY = SERVING AVAILABILITY = TEMPORAL OBSERVABILITY.

### 6. MILESTONE 3 — FEATURE-GATE INTEGRITY (P0)
Audit feature-gate schemas and missingness policies. Do not alter certification thresholds merely to obtain PASS.

### 7. MILESTONE 4 — ENRICHED CANDIDATE MODEL (P0/P1)
Build candidates incrementally. Measure families independently (RPS, log loss, calibration, etc.). No promotion based purely on in-sample performance or feature count.

### 8. MILESTONE 5 — SHADOW PRODUCTION (P0)
Run candidate and incumbent side-by-side. Record shadow capture for durable evidence. Candidate remains non-authoritative until explicitly promoted.

### 9. MILESTONE 6 — UNCERTAINTY RESEARCH LOOP (P0/P1)
Continue research-only uncertainty measurement. Do not redefine the failing gate opportunistically.

### 10. MILESTONE 7 — EXPLAINABILITY (P1)
Add asynchronous explainability (SHAP/global importance). Consumer language must describe contribution, not causality.

### 11. MILESTONE 8 — TRUST PRODUCT (P1)
Build `/performance`, `/methodology`, `/track-record` using only auditable backend data. No fabricated metrics.

### 12. MILESTONE 9 — MATCH INTELLIGENCE PRODUCT (P1)
Make the match page the central consumer experience: fixture → probabilities → evidence passport → what changed → why → market context → decision state.

### 13. MILESTONE 10 — IDENTITY + PERSONALIZATION (P1)
Preserve anonymous-first access. Authenticated users gain saved matches, favourite teams/competitions, recent analyses, dashboard.

### 14. MILESTONE 11 — RETENTION + NOTIFICATIONS (P1)
Implement opt-in alerts for teams, matches, and kickoffs. Never block prediction requests.

### 15. MILESTONE 12 — FIRST-PARTY ANALYTICS (P1)
Create one typed analytics abstraction. Analytics failure must never break the core product.

### 16. MILESTONE 13 — SHARING + ORGANIC DISTRIBUTION (P1)
Support social sharing with dynamic images (Next.js OG generation). No hype-based claims.

### 17. MILESTONE 14 — SEO + DISCOVERY (P1)
Index genuine pages. Implement canonical URLs, metadata, sitemaps, structured data.

### 18. MILESTONE 15 — DEVELOPER PLATFORM (P2)
Provide a free `/developers` portal with API keys, rotation, usage visibility, and rate limits.

### 19. MILESTONE 16 — ENTITLEMENT READINESS (P2)
Support future tiers (FREE, PRO, etc.). Current state is FREE with all shipped capabilities.

### 20. MILESTONE 17 — VISUAL + PERFORMANCE POLISH (P1/P2)
Premium football intelligence platform design (not casino). Optimize Core Web Vitals, accessibility, and bundle size.

### 21. MILESTONE 18 — SECURITY + RELIABILITY HARDENING (P0)
Audit and harden auth, IDOR, CSRF, XSS, rate limiting, and secret leakage.

### 22. MILESTONE 19 — FINAL PRODUCTION VERIFICATION (P0)
Verify complete repository, ML pipelines, backend APIs, frontend builds, and production deployment health. Produce `reports/release/final-production-verification.md`.

### 23. REQUIRED DELIVERABLE CONTRACT
Every milestone MUST leave behind: Code, Tests, Evidence, Documentation, and a Release Record.

### 24. GIT / PR CONTRACT
Prefer small coherent commits (e.g., `feat(data): ...`, `certify(ml): ...`).

### 25. GITHUB / RENDER / VERCEL EXECUTION RULES
Use GitHub for source control, Render for backend production, and Vercel for frontend deployment.

### 26. HARD “DO NOT” RULES
Never weaken certification to pass, fabricate statistics, fake live data, expose secrets, put provider calls in the browser, or make FastAPI perform expensive ETL synchronously.

### 27. SUCCESS DEFINITION
SabiScore must provide real data, traceable evidence, reproducible models, train/serve parity, safe inference, honest uncertainty, audited performance, and excellent UX while preserving existing architectural authority.

### 28. FINAL AUTONOMOUS EXECUTION COMMAND
Inspect the repository. Establish the baseline. Produce audit artifacts. Select one highest-priority milestone. Implement, test, verify, commit, record evidence, reassess. Build the intelligence substrate first, expose what evidence supports, and make the product excellent.
