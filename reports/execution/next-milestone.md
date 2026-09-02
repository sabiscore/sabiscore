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
   deployment. **Partially confirmed 2026-09-02** — see "Live verification
   update" below for exactly what was and wasn't exercised. Not fully closed:
   SHA parity was not checked against the *production* alias (only a preview
   alias was observed), and the notification-dispatch-worker code on this
   branch is not yet merged to `master`, so the backend the operator's
   evidence hit is master's current head (`68d8824`, PR #128), not this
   branch's HEAD.

## Live verification update (2026-09-02)

Two independent pieces of operator-supplied evidence, not re-derived or
re-probed by this session:

- **Render deploy/runtime log** for `sabiscore-api-bav1.onrender.com`:
  confirms migration 0011 applies cleanly on real Postgres (item 1 above,
  now closed), all 6 league model artifacts load
  (`Startup: PredictionEngine cache reused 6/6 validated league models`),
  `fixture_sync` seeded 16 new upcoming fixtures, and the service reports
  live and passes repeated `/health/ready` checks. The "Verified exact build
  release identity `badab32e...`" line is a **model-artifact verification
  hash** (`scripts/verify_active_artifacts.py`), not a git commit SHA — it
  does not by itself identify which commit is deployed. `git cat-file`
  confirms that hash doesn't correspond to any local commit.
- **Six screenshots of `web-f4ubx5exr-oversabis-projects.vercel.app`** (a
  Vercel **preview** alias — not cross-checked against the production alias
  `web-lac-theta-42.vercel.app`, per the standing rule that preview and
  production aliases can serve different payloads). They show, against a
  live backend: the home/Intelligence page (`Core ready 100%`, 5 providers
  configured / 2 live-validated, Model Pulse "Generation 5 / Research mode /
  staking blocked"); a real verified fixture's match analysis (Ipswich Town
  FC vs Liverpool — 2 critical / 9 advisory gaps, correctly abstaining with
  "No bet", Elo context, RL recommendation, market-edge comparison all
  rendering); a **hypothetical, unmatched** fixture (Arsenal vs Brentford —
  correctly tagged "Hypothetical — non-executable", 6 critical / 52 advisory
  gaps, ensemble probabilities correctly withheld as "Unavailable" rather
  than shown as a fabricated diagnostic baseline); the Matches page with
  league filters and team autocomplete; the Performance page's real
  walk-forward numbers (55.7% accuracy, RPS 0.236, 35 settled predictions,
  5 chronological folds, CLV −4.2pp, "Walk-forward validated 2 Sept 2026");
  the Dashboard's anonymous-session identity state (M8); and the Developers
  API-key platform (M13, free tier, 0/10 req/min, 0/100 req/day quotas).
  **Not shown in this evidence** and therefore still unconfirmed live:
  notification CRUD/delivery UI, the analytics ingestion pipeline, the share
  flow, the sitemap, and JSON-LD output.

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