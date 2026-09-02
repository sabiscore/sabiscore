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

1. ~~Apply Alembic through `0012_notif_log_idempotency` on a real PostgreSQL
   instance~~ — **BOTH CONFIRMED 2026-09-02.** A direct live probe of
   `GET /health/ready` after PR #130 deployed returns
   `migrations: {status: "ready", head: "0012_notif_log_idempotency",
   applied: "0012_notif_log_idempotency"}` against production PostgreSQL.
   (Note: the revision id is `0012_notif_log_idempotency`, not
   `0012_notification_idempotency` as an earlier draft of this line said —
   it was deliberately shortened to fit `alembic_version.version_num`'s
   `VARCHAR(32)`.) `alembic check`'s drift output specifically is still not
   independently captured; what is confirmed is the startup-time
   `require_alembic_current()` revision check, which is the check that gates
   boot.
   An operator-supplied Render deploy log for the `sabiscore-api` service
   (master branch, `rootDir: backend`) shows `alembic upgrade head` running
   against real PostgreSQL end-to-end: `Context impl PostgresqlImpl`,
   `PostgreSQL connection successful`, and
   `Alembic schema revision verified: 0011_user_identity_dev_platform`,
   followed by all 6 league models loading and repeated `GET /health/ready`
   → `200 OK`. Migration 0011 is proven on production Postgres, but this
   evidence predates migration 0012. (`alembic
   check`'s drift output specifically was not visible in the log — the
   startup-time `require_alembic_current()` revision check is what's
   confirmed here, which is the check that gates boot.)
2. Build backend/web production images and validate Compose — still open;
   no Docker evidence was supplied this session either.
3. Deploy the reviewed SHA, confirm backend/frontend SHA parity, and exercise
   the identity, dashboard, calibration, developer, analytics, notification
   CRUD/delivery, share, sitemap, and JSON-LD flows against the live
   deployment. — **Deploy + SHA parity CONFIRMED 2026-09-02:** Render
   `/health` and the Vercel production alias `/api/health` both report
   `sha: 59f21a1` (= local `master` HEAD), `backendStatus: ok`, all four
   readiness components `ready`, and `components.notification_dispatch`
   `outcome: ok` executing on its 5-minute cadence with zero failures.
   **Flow exercise remains partial:** identity/dashboard/calibration/
   developer/match-analysis were verified visually against a *preview* alias
   earlier the same day; analytics, notification delivery, share, sitemap,
   and JSON-LD are still unexercised live. Notification *delivery*
   specifically cannot be observed yet — the worker reports `examined: 0`,
   i.e. no real subscription exists to dispatch, so the EMAIL transport is
   deployed and inert rather than proven.

## Product gaps after validation

- ~~`WEB_PUSH`/`EMAIL` notification channels are persisted but not
  dispatched~~ — **EMAIL closed 2026-09-02** (`docs/DEBT.md` item 51
  follow-up): stdlib SMTP adapter, config-gated, zero new dependency.
  `WEB_PUSH` remains open — it needs a new crypto dependency
  (VAPID/AES128GCM) and a frontend service worker that don't exist yet,
  materially more work than reusing what EMAIL already had available.
- ~~Replace sample fixture sitemap entries with bounded, canonical live
  fixture discovery that fails closed when the backend is unavailable~~ —
  **closed 2026-09-02** (`docs/DEBT.md` item 52).

## Non-goals

- Do not certify or promote a model by changing thresholds after observing
  results.
- Do not enable public staking while model/uncertainty gates are closed.
- Do not add billing, checkout, automated bet placement, or provider calls from
  the browser.