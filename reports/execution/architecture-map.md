# Architecture Map

Verified against the working tree on 2026-09-01.

## Production boundaries

```text
Browser
  -> apps/web (Next.js 15 / React 18)
       -> explicit route handlers under apps/web/src/app/api
       -> HttpOnly sabi_session and sabi_anon_id cookies
       -> no provider credentials or official prediction calculations
  -> backend/src/api/main.py (FastAPI authority)
       -> provider/evidence/identity services
       -> feature projection, model inference, uncertainty, EV, Kelly, verdicts
       -> PostgreSQL through SQLAlchemy/Alembic
       -> Redis for cache, leases, and developer rate limiting

apps/scraper -> open/batch acquisition and manifests only
```

Legacy `apps/api` and `frontend` roots are not production entrypoints.

## Current implementation inventory

- 97 FastAPI operation decorators under `backend/src/api`.
- 94 Next.js API route-handler files and 11 page files under `apps/web/src/app`.
- Alembic revision `0011_user_identity_dev_platform` creates seven tables for
  favorites, saved matches, preferences, API keys, analytics events,
  notification subscriptions, and notification logs.
- M2 web surfaces are present: auth modal/context, dashboard, calibration chart,
  developer portal, user-state proxies, and analytics tracker.
- M3 partial surfaces are present: notification CRUD/in-app UI, match share UI,
  evidence-safe OpenGraph image route, sitemap baseline, and match/team JSON-LD.

## Authority and safety

FastAPI remains the only authority for provider access, probabilities,
calibration, evidence gaps, edge, EV, Kelly, verdicts, and staking. Next.js
validates or forwards browser requests and renders backend-owned decisions.

The active model generation remains uncertified and staking remains fail-closed.
Health/readiness does not certify a prediction. Analytics events and user state
are not model inputs.

## Known architecture gaps

- No production caller schedules kickoff or probability-swing notification
  generation; only preferences, subscriptions, logs, and UI are implemented.
- The sitemap uses a bounded route/team/sample-fixture catalogue rather than live
  fixture discovery.
- Full PostgreSQL migration, Redis-backed lifecycle, Playwright, container, and
  deployment verification remain release gates.

See `docs/ARCHITECTURE.md`, `docs/API.md`, and `docs/DEPLOYMENT_GUIDE.md`.