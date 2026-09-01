# Project: SabiScore Football Intelligence Platform

## Architecture
SabiScore is an evidence-backed football intelligence and predictive modeling platform adhering to strict zero-fabrication, fail-closed uncertainty gating, and responsible analytical positioning.

### Polyglot Monorepo Structure
- **Backend (`backend/`)**: FastAPI application authority for provider gateways, identity reconciliation, evidence criticality, feature engineering, model inference, calibration, de-vigging, Kelly sizing, user identity, developer platform, notifications, and first-party analytics.
- **Web (`apps/web/`)**: Next.js 15, React 18.3.1, Tailwind CSS v4 consumer-facing web application and backend proxy routes. Strictly no direct external provider calls, no auth tokens in localStorage, no client-side probability or Kelly calculation.
- **Database & Storage**: PostgreSQL 16+ (Alembic schema authority only, `Base.metadata.create_all()` prohibited) and Redis 7+ (ephemeral caching, sliding-window rate limiting, distributed leases).

```
                      ┌───────────────────────────────────────────────┐
                      │              Web Client (Next.js)             │
                      │  - Anonymous & Auth UX (httpOnly cookies)     │
                      │  - Consumer Dashboard (/dashboard)           │
                      │  - Public Trust Layer (/performance)          │
                      │  - Developer Hub (/developer - No Billing)    │
                      │  - Dynamic OG Cards, Schema.org SEO, A11y AA  │
                      └──────────────────────┬────────────────────────┘
                                             │ HTTP (Proxy / Cache-Control: no-store)
                                             ▼
                      ┌───────────────────────────────────────────────┐
                      │            FastAPI Backend Authority          │
                      │  - Async Provider Ingestion Coordinator       │
                      │  - Zero-Fabrication & ADR 0009 Gating         │
                      │  - Auth & Anonymous State Merging             │
                      │  - Developer Keys & Redis Rate Limiter        │
                      │  - Typed Analytics with PII Scrubbing         │
                      │  - Timezone-Aware Notification Engine         │
                      └──────────────┬─────────────────┬──────────────┘
                                     │                 │
                                     ▼                 ▼
                          ┌──────────────────┐  ┌─────────────┐
                          │ PostgreSQL (v16) │  │ Redis (v7)  │
                          │ Alembic Migrated │  │ Multi-tier  │
                          └──────────────────┘  └─────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Unified Provider Ingestion | Asynchronous multi-provider coordinator with dynamic quota budgeting for Sportmonks, The Odds API, API-Football, Football-Data.org | M1 | R1 |
| 2 | Candidate Model Shadow Validation | Reproducible candidate training pipeline, walk-forward temporal evaluation, shadow comparison CLI | M1 | R1 |
| 3 | Enterprise Schema Lineage (Alembic 0011) | New schema for user favorites, saved matches, preferences, API keys, analytics events, notifications | M1 | R1, R2, R4 |
| 4 | Anonymous-First User Identity & Auth | Secure session management using httpOnly cookies, seamless anonymous-to-auth state merging, zero tokens in localStorage | M2 | R2 |
| 5 | Consumer Personalization & Dashboard | Saved matches, team favorites, custom preference management on `/dashboard` | M2 | R2 |
| 6 | Public Trust & Interactive Calibration | Reliability diagrams / calibration curves with Künsch bootstrap CIs, Murphy Brier decomposition, walk-forward methodology on `/performance` & `/docs` | M2 | R2 |
| 7 | Developer Platform & Entitlements | API key generation (SHA-256 hashed), Redis sliding-window rate limiting (FREE/PRO), usage metering, strictly NO billing/checkout UX | M2 | R4 |
| 8 | First-Party Privacy-Preserving Analytics | Strictly typed event catalog, client batching tracker, backend PII and secret sanitization engine | M2 | R2 |
| 9 | Timezone-Aware Match Notifications | Opt-in kickoff reminders, significant probability delta alerts, Celery background worker, in-app notification center | M3 | R3 |
| 10 | Dynamic Social Share & Viral Loop | `next/og` OpenGraph dynamic image cards for matches/teams, Web Share API, formatted clipboard analysis export | M3 | R3 |
| 11 | Programmatic SEO & Structured Data | Dynamic `sitemap.ts` pulling live fixtures/teams/competitions, Schema.org JSON-LD (`SportsEvent`, `SportsTeam`, `BreadcrumbList`) | M3 | R3 |
| 12 | Anti-Casino Polish & WCAG AA A11y | Pure analytical terminology (`Market Discrepancy Spotlight`), full WCAG AA accessibility compliance (Radix Tooltip keyboard triggers, visible focus, semantic landmarks) | M3 | R3, R5 |
| 13 | Fail-Closed UX & Empty State Guards | Comprehensive handling of unverified/missing evidence across all new pages, zero synthetic predictions, responsible gambling language | M3 | R5 |
| 14 | Opaque-Box E2E Test Suite (Tiers 1-4) | Comprehensive requirement-driven test suite covering all features in isolation, boundaries, pairwise combinations, and real-world user journeys | E2E-Track | Acceptance Criteria |
| 15 | E2E 100% Pass & Adversarial Hardening (Tier 5) | Full verification against all E2E test tiers and white-box adversarial coverage hardening | M4 (Final) | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Suite | Requirements-driven test runner, harness, and test suites across Tiers 1-4 | none | DONE |
| M1 | Backend Schema, Ingestion & ML Foundation | Alembic migration 0011, IngestionCoordinator, candidate model shadow promotion tools, auth/dev/analytics backend services | none | DONE |
| M2 | Public Trust, Identity & Developer Platform Full-Stack | Calibration curve UI/API, httpOnly cookie auth flow, anonymous merging, /dashboard, /developer portal, typed analytics | M1 | IN_PROGRESS |
| M3 | Retention, Sharing, Programmatic SEO & A11y Polish | Notifications (in-app + workers), dynamic OG image cards, dynamic sitemaps, JSON-LD, anti-casino wording, WCAG AA compliance | M1, M2 | PLANNED |
| M4 | Final Milestone: 100% E2E Pass & Adversarial Hardening | Phase 1: 100% pass on Tiers 1-4 E2E suite; Phase 2: Tier 5 adversarial edge-case stress hardening | E2E, M1, M2, M3 | PLANNED |

## Interface Contracts

### Backend ↔ Frontend Auth Contract
- Cookie Name: `sabi_session` (JWT payload, `HttpOnly; Secure; SameSite=Lax; Path=/`)
- Anonymous Cookie: `sabi_anon_id` (UUIDv4 device identity, `HttpOnly; Secure; SameSite=Lax; Path=/`)
- Endpoints:
  - `POST /api/v1/auth/register` -> Sets session cookie, merges `sabi_anon_id` items.
  - `POST /api/v1/auth/login` -> Sets session cookie, merges `sabi_anon_id` items.
  - `POST /api/v1/auth/logout` -> Clears session cookie.
  - `GET /api/v1/auth/me` -> Returns current `UserAccount` profile and preferences.
  - `POST /api/v1/users/favorites` / `DELETE /api/v1/users/favorites/{id}`
  - `POST /api/v1/users/saved-matches` / `DELETE /api/v1/users/saved-matches/{id}`

### Developer Platform Contract (R4)
- Header: `X-API-Key: sbk_live_...`
- Endpoints:
  - `POST /api/v1/developer/keys` -> Returns `{ id, name, key: "sbk_live_...", tier: "FREE" }` (secret displayed once).
  - `GET /api/v1/developer/keys` -> Lists active keys with masked prefixes and creation dates.
  - `DELETE /api/v1/developer/keys/{id}` -> Revokes key.
  - `GET /api/v1/developer/usage` -> Returns current day/minute usage and tier limits.
- Rate limits:
  - `FREE`: 10 req/min, 100 req/day
  - `PRO`: 60 req/min, 5,000 req/day

### First-Party Analytics Contract (R2)
- Endpoint: `POST /api/v1/analytics/events`
- Request Schema:
  ```json
  {
    "events": [
      {
        "event_name": "match_viewed | prediction_inspected | share_card_generated | favorite_toggled",
        "anonymous_id": "uuid",
        "timestamp": "ISO-8601",
        "properties": { "fixture_id": 123, "surface": "match_detail" }
      }
    ]
  }
  ```
- Backend Filter: Recursively scrubs all keys matching `password`, `token`, `secret`, `email`, `authorization`, `cookie`, `key`.

### Public Trust / Calibration Contract (R2)
- Endpoint: `GET /api/v1/model-performance/calibration`
- Response Schema:
  ```json
  {
    "model_generation": "canonical_68_v2",
    "binned_probabilities": [
      { "bin_center": 0.05, "observed_frequency": 0.048, "count": 120, "ci_lower": 0.032, "ci_upper": 0.064 }
    ],
    "ece": 0.024,
    "brier_score": { "total": 0.182, "reliability": 0.008, "resolution": 0.074, "uncertainty": 0.248 },
    "rps": 0.191,
    "walk_forward_seasons": ["2023-2024", "2024-2025"]
  }
  ```

### Notifications & Reminders Contract (R3)
- Endpoints:
  - `POST /api/v1/notifications/subscribe` (match reminder / odds swing)
  - `GET /api/v1/notifications` (in-app notifications)
  - `PATCH /api/v1/notifications/{id}/read`
  - `GET /api/v1/notifications/preferences`
  - `PUT /api/v1/notifications/preferences` (timezone, delivery channels, thresholds)

## Code Layout
- `backend/alembic/versions/`: Alembic schema migrations.
- `backend/src/db/models.py`: Declarative SQLAlchemy models.
- `backend/src/api/endpoints/`: FastAPI routers (`auth.py`, `developer.py`, `analytics.py`, `performance.py`, `notifications.py`).
- `backend/src/services/`: Application business logic services.
- `backend/src/tasks/`: Celery / background synchronization tasks.
- `apps/web/src/app/`: Next.js 15 App Router pages (`/dashboard`, `/developer`, `/performance`, `/match/[id]`, `/team/[slug]`, `/sitemap.ts`, `/robots.ts`).
- `apps/web/src/app/api/`: Server-side proxy and auth route handlers (managing httpOnly cookies).
- `apps/web/src/components/`: Reusable, WCAG AA compliant React components (`CalibrationCurveChart`, `MatchShareModal`, `NotificationCenter`, `ResponsibleGamblingTooltip`).
- `apps/web/src/lib/`: Typed clients, analytics tracker, evidence contracts, and SEO helpers.
- `tests/e2e/` or `apps/web/e2e/`: Comprehensive Playwright and requirement-driven test suites.
