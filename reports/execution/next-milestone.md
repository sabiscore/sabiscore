# Next Milestone

Verified against the working tree on 2026-09-01.

## Objective

Close the two remaining M3 architecture gaps and complete the two release
gates that could not run in this local environment, without weakening model,
evidence, or staking gates.

## Completed this session

1. Web unit suite (295 tests) and production build — done.
2. Backend Ruff, mypy ceiling, full pytest suite (2050 passed), artifact
   verifier, and OpenAPI verifier — done, via an isolated fail-closed test
   configuration.
3. All 328 Playwright executions (164 unique tests, Chromium + Mobile
   Chrome) — done; found and fixed one real production defect in the
   process (see `CHANGELOG.md`).
4. Gitleaks and the repository secret-safety gates — done; zero new
   findings.

## Remaining required work

1. Apply Alembic through `0011_user_identity_dev_platform` on a real
   PostgreSQL instance and run `alembic check` — no PostgreSQL server was
   reachable in this environment.
2. Build backend/web production images and validate Compose — skipped this
   session by operator choice.
3. Deploy the reviewed SHA, confirm backend/frontend SHA parity, and exercise
   the identity, dashboard, calibration, developer, analytics, notification
   CRUD, share, sitemap, and JSON-LD flows against the live deployment.

## Product gaps after validation

- Add a durable scheduled notification generator/dispatcher with idempotency,
  retry policy, observability, and tests before claiming reminders or
  probability-swing delivery is operational.
- Replace sample fixture sitemap entries with bounded, canonical live fixture
  discovery that fails closed when the backend is unavailable.

## Non-goals

- Do not certify or promote a model by changing thresholds after observing
  results.
- Do not enable public staking while model/uncertainty gates are closed.
- Do not add billing, checkout, automated bet placement, or provider calls from
  the browser.