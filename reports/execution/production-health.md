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
  `GET /health/ready` → `200 OK` repeatedly after going live.

  ⚠️ **CORRECTION (same day).** An earlier revision of this section claimed
  the log's `Verified exact build release identity badab32eaaaf...` line was
  "a model-artifact verification hash, not a git SHA", and inferred the
  deployed commit was `68d8824` (PR #128). **Both claims were wrong.**
  `badab32eaaaf661282576b74f161b6a0f57d10f6` is the git commit for PR #129
  (`feat(retention): wire scheduled in-app notification dispatch worker`,
  authored 09:54:38 +0100); Render began building ~60 seconds later, so that
  deploy carried the notification-dispatch-worker backend, not the commit
  before it. The claim rested on `git cat-file -e` failing for that hash —
  but that only proved **the local clone had not yet fetched the
  just-created master commit**, not that the hash was a non-commit. A SHA
  missing locally means fetch first; it is never by itself evidence about
  what the SHA is.
- **Frontend** (`web-f4ubx5exr-oversabis-projects.vercel.app`, a **preview**
  alias, screenshots): Intelligence/home, a real verified fixture's match
  analysis, a hypothetical non-executable matchup, the Matches listing,
  the Performance walk-forward chart, the anonymous-session Dashboard, and
  the Developers API-key platform all render correctly against a live
  backend, with evidence gates (critical vs. advisory gaps, staking-disabled
  banner, Kelly cap, withheld probabilities on unmatched fixtures) behaving
  as designed. This alias was not cross-checked against the production
  alias (`web-lac-theta-42.vercel.app`) for SHA parity.

## Live probe — 2026-09-02 ~13:41 UTC (direct, this session)

Probed directly rather than inferred, after PR #130 merged:

| Probe | Result |
| --- | --- |
| `GET /health` (Render) | `status: healthy`, **`sha: 59f21a1`** |
| `GET /health/ready` → `migrations` | `status: ready`, **`head`/`applied`: `0012_notif_log_idempotency`** |
| `GET /health/ready` → `database` | `ready` — Connected |
| `GET /health/ready` → `cache` | `ready` — **External Redis connected** (`external_available: true`) |
| `GET /health/ready` → `models` | `ready` — v5_phase7, 6 leagues loaded, 12 artifacts |
| `GET /health` → `components.notification_dispatch` | `outcome: ok`, 0 consecutive/total failures, last success 282s ago (≈5-min cadence, as configured) |
| `GET /api/health` (Vercel production alias `web-lac-theta-42.vercel.app`) | **`sha: 59f21a1`**, `backendSha: 59f21a10511…`, `backendStatus: ok` |

**Deploy parity is confirmed in both directions** — local `master` HEAD,
Render, and the Vercel production alias all read `59f21a1`. This is the
first time the production-alias parity check (a standing recurring item)
has been satisfied against this milestone's code.

This closes, with direct evidence:

- migration `0011` **and** the newly-added `0012_notif_log_idempotency` are
  applied on real production PostgreSQL (0012 was never verified anywhere
  but SQLite before this probe);
- the notification dispatch worker is running live on its 5-minute cadence
  with zero failures — not merely deployed, but executing;
- Redis is genuinely connected (read from the readiness cache check, which
  this repo's own history warns is not sufficient alone — but it agrees with
  `external_available: true`);
- production-alias (not preview-alias) SHA parity.

Still **not** closed: Docker image/Compose build proof (explicitly skipped
by operator decision this session), and live exercise of the notification
**delivery** path end-to-end — the worker reports `examined: 0`, meaning no
real subscription has existed to dispatch yet, so the EMAIL transport shipped
in `59f21a1` is deployed and inert, never yet observed sending.

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

~~Before a readiness conclusion, record responses from `/health`,
`/health/ready`, … compare backend and frontend release SHAs; verify
migration `0011` on PostgreSQL~~ — **all satisfied by the 2026-09-02 live
probe above**, except the two items named below.

Still missing: `/api/v1/providers/health` and `/models/status` reads, one
verified-fixture full-analysis flow exercised against the live deployment,
Docker image/Compose validation (operator-skipped), and an observed
end-to-end notification delivery (the worker has had zero subscriptions to
dispatch so far).

Current decision from this report: **`RELEASE-READY WITH DOCUMENTED
LIMITATIONS`** — upgraded from `NOT YET SAFE FOR PRODUCTION`, on evidence
rather than elapsed time. The reviewed commit `59f21a1` is live on both
Render and the Vercel production alias with full SHA parity, its migrations
(through `0012`) are applied on real PostgreSQL, all four readiness
components report `ready`, and its background worker is executing on
schedule with zero failures. The remaining gaps are verification breadth
(untried flows, no Docker proof), not known defects — and model
certification/staking remains independently and deliberately closed, which
this report does not and cannot change.
