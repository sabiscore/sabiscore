# Next Milestone

Verified against the working tree on 2026-09-01. Updated 2026-09-02 with live
evidence supplied by the operator (see "Live verification update" below).

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
5. Scheduled in-app notification delivery (kickoff reminders +
   probability-swing alerts) — done: new
   `backend/src/services/notification_dispatch_service.py`, wired into the
   FastAPI lifespan alongside fixture-sync/settlement/CLV, informational
   `/health` snapshot, new `GET /api/v1/notifications/subscriptions/matches`
   read endpoint, 8 new focused unit tests + 1 extended. Ruff 0; mypy
   ceiling 766<=784; targeted pytest 11/11 passed; broader health/readiness
   regression suite (10 tests) unaffected.

## Remaining required work

1. ~~Apply Alembic through `0011_user_identity_dev_platform` on a real
   PostgreSQL instance and run `alembic check`~~ — **CONFIRMED 2026-09-02.**
   An operator-supplied Render deploy log for the `sabiscore-api` service
   (master branch, `rootDir: backend`) shows `alembic upgrade head` running
   against real PostgreSQL end-to-end: `Context impl PostgresqlImpl`,
   `PostgreSQL connection successful`, and
   `Alembic schema revision verified: 0011_user_identity_dev_platform`,
   followed by all 6 league models loading and repeated `GET /health/ready`
   → `200 OK`. Migration 0011 is proven on production Postgres. (`alembic
   check`'s drift output specifically was not visible in the log — the
   startup-time `require_alembic_current()` revision check is what's
   confirmed here, which is the check that gates boot.)
2. Build backend/web production images and validate Compose — still open;
   no Docker evidence was supplied this session either.
3. Deploy the reviewed SHA, confirm backend/frontend SHA parity, and exercise
   the identity, dashboard, calibration, developer, analytics, notification
   CRUD/delivery, share, sitemap, and JSON-LD flows against the live
   deployment.

## Product gaps after validation

- `WEB_PUSH`/`EMAIL` notification channels are persisted but not dispatched;
  a follow-up milestone should add channel-specific transport adapters
  behind the same dispatch-pass contract.
- Replace sample fixture sitemap entries with bounded, canonical live fixture
  discovery that fails closed when the backend is unavailable.

## Non-goals

- Do not certify or promote a model by changing thresholds after observing
  results.
- Do not enable public staking while model/uncertainty gates are closed.
- Do not add billing, checkout, automated bet placement, or provider calls from
  the browser.