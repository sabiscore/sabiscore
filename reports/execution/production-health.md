# Production Health Evidence

Generated 2026-09-01. Updated 2026-09-02 — see "Live evidence" below.

No live production health probe was executed *by this session* during the
2026-09-01 documentation audit. This report therefore made no claim about
current Render/Vercel SHA parity, database latency, Redis latency, provider
circuit state, migration head, or live model availability as of that date.

## Live evidence (2026-09-02, operator-supplied, not independently re-probed)

- **Backend** (`sabiscore-api-bav1.onrender.com`, Render deploy/runtime log):
  build succeeded, `alembic upgrade head` applied cleanly against real
  PostgreSQL with `Alembic schema revision verified:
  0011_user_identity_dev_platform`, all 6 league model artifacts loaded,
  `fixture_sync` seeded 16 new upcoming fixtures, and the service answered
  `GET /health/ready` → `200 OK` repeatedly after going live. This is master
  branch (`rootDir: backend`, autodeploy) — the deployed commit is presumed
  to be `master` HEAD as of that deploy (`68d8824`, PR #128) since the log's
  own "build release identity" line is a model-artifact verification hash,
  not a git SHA, and `/health`'s `sha` field (the actual deploy-parity
  stamp) was not queried in this log.
- **Frontend** (`web-f4ubx5exr-oversabis-projects.vercel.app`, a **preview**
  alias, screenshots): Intelligence/home, a real verified fixture's match
  analysis, a hypothetical non-executable matchup, the Matches listing,
  the Performance walk-forward chart, the anonymous-session Dashboard, and
  the Developers API-key platform all render correctly against a live
  backend, with evidence gates (critical vs. advisory gaps, staking-disabled
  banner, Kelly cap, withheld probabilities on unmatched fixtures) behaving
  as designed. This alias was not cross-checked against the production
  alias (`web-lac-theta-42.vercel.app`) for SHA parity.

This closes the "verify migration 0011 on real Postgres" gap from
`reports/execution/next-milestone.md` and adds real evidence for several
(not all) of the flows that document's item 3 asks for. It does **not**
close: Docker image/Compose proof, production-alias SHA-parity confirmation,
or verification of the notification-dispatch-worker branch's own code in
production (that code is not yet merged to `master`).

## Code-level health contract

- `/health/live` is process liveness.
- `/health/ready` reports dependency readiness and prediction capability.
- `/health` exposes release identity and component state.
- `/metrics` exposes available operational counters.
- Model certification and per-fixture staking remain separate from platform
  readiness.

## Local evidence from this audit

| Check | Result |
| --- | --- |
| Web lint | Pass |
| Web typecheck | Pass |
| Web tests | 295/295 passed |
| Web production build | Exit 0, 49/49 pages |
| Backend Ruff | 0 issues |
| Backend mypy ceiling | 768<=784 |
| Backend full pytest | 2050 passed / 17 skipped / 2 xfailed |
| OpenAPI verifier | 106 paths verified |
| Model artifact verifier | 6/6 hash-locked pairs verified |
| Scraper validate + tests | 20/20 passed |
| Gitleaks (working tree + full history) | 2 pre-existing historical findings only (`docs/DEBT.md` item 16); zero new |
| Playwright (Chromium + Mobile Chrome) | **328/328 passed** |
| Notification dispatch focused tests | 11/11 passed (`test_notification_dispatch_service.py` + `test_notifications_and_timezones.py`) |
| Notification dispatch ruff/mypy | ruff 0; mypy ceiling 766<=784 (no new errors attributed to touched files) |

## Required production evidence

Before a readiness conclusion, record responses from `/health`,
`/health/ready`, `/api/v1/providers/health`, `/models/status`, and one verified
fixture full-analysis flow; compare backend and frontend release SHAs; ~~verify
migration `0011` on PostgreSQL~~ (done, see above); and complete Docker
image/Compose validation. Still missing: a direct `/health` read (for the
`sha` deploy-parity stamp), `/api/v1/providers/health` and `/models/status`
reads, and production-alias (not preview-alias) SHA parity.

Current decision from this report alone: **`NOT YET SAFE FOR PRODUCTION`** —
downgraded from the 2026-09-01 wording. Migration 0011 is now proven on real
Postgres and a live backend/frontend pair were shown functioning correctly
across several core flows, so this is no longer "no live evidence exists at
all." What remains open is narrower but still real: Docker image/Compose
proof, a direct `/health` SHA-parity check on the *production* alias, and
confirmation that this branch's own (not-yet-merged) code runs correctly in
production once merged.
