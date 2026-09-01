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
