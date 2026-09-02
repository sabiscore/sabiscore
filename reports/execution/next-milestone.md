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
---

## Milestone executed 2026-09-02 — market-edge display integrity

### Why this outranked the alternatives

Every P0/P1 item in `prioritized-backlog.md` is now either **Done** or blocked
on something no code can move: a Docker daemon this environment does not have,
a live PostgreSQL `alembic check` (the boot-gating revision check is already
confirmed at `0012_notif_log_idempotency`), operator console access, or real
settled-match volume. The genuinely new evidence this session was the operator's
live screenshots — and one of them showed a defect.

Ranked against the alternatives:

- **Docker image proof** — environment-blocked, unchanged.
- **Firecrawl / diagnostics plans** — reconciled in `plan-reconciliation.md`
  Appendix B; net new work: none.
- **`n ≥ 30` reporting floor** — right direction, but blanks every panel at
  today's ~34 total settled predictions. Trigger recorded.
- **Edge-delta defect** — live, consumer-facing, on the highest-traffic
  product surface, a backend-authority violation, and fixable in one component.

Selected on the guiding question: the smallest change that most increases
trustworthy intelligence while reducing architectural risk.

### What shipped

`docs/DEBT.md` item 53 carries the full incident record. In short: the match
page printed **two different edges for the same market** — `EDGE DELTA` at
`+9.4% EV advantage` recomputed in the browser from `1 / market_odds` (the
vigged price), and `MARKET EDGE` directly beneath it printing the backend's
de-vigged `odds_edge.edge`. `EdgeDeltaBar` now reads the backend's own
`model_prob` and `edge` and derives the fair probability exactly as
`model_prob - edge`; the label is a probability-point gap, not "EV"; the
shared `EdgeTooltip` no longer describes edge against the vigged price.

### Evidence

| Gate | Result |
|---|---|
| New regression tests watched failing on a reverted fix | 3 failed / 12 passed |
| Same tests after the fix | 15/15 passed |
| Full web unit suite | 304/304 passed |
| Web lint | 0 errors, 0 warnings |
| Web typecheck | 0 errors |
| `NODE_ENV=production` production build | exit 0 |
| Backend | untouched — it was already correct |

⚠️ One flake observed and confirmed as unrelated: the first full-suite run had
`performance-page-client.test.tsx > distinguishes a real outage from having no
settled data` time out at 5000 ms under parallel load. It passes in isolation
and the suite is 304/304 on re-run. Not caused by this change; not fixed here.

---

## Milestone executed 2026-09-02 (second) — WEB_PUSH notification channel

### Why this, and why not the alternative offered alongside it

The operator supplied `Recommendations2.txt`, which proposes two paths and
states "Starting execution on Path A." Both were reconciled first
(`plan-reconciliation.md` Appendix C):

- **Path A (WEB_PUSH)** — accepted. It was the one product gap the prior
  session explicitly left open, it is bounded, and it closes the last half of
  `docs/DEBT.md` item 51.
- **Path B (certification thresholds)** — **rejected, deliberately.** Its first
  step is "define the exact mathematical baselines a model must hit." Those
  baselines already exist, frozen and SHA-256-hashed in
  `certification_policy.py` v1.0.0, pinned *before* the candidate was
  evaluated precisely so they could not be tuned afterwards. Redefining them
  now, having seen the candidate fail, is the exact action APEX §23 forbids
  and is Class C — an operator decision, not an agent's. Its step 4's claim
  that a parity test closes DEBT 42/49/50 is also factually wrong about all
  three; the per-item reasoning is in Appendix C.

### What shipped

Full record in `docs/DEBT.md` item 54; operator setup in
`docs/NOTIFICATION_CHANNELS.md`. Backend transport (VAPID + RFC 8291 on the
already-present `cryptography`, no new dependency), `push_devices` table +
migration `0013`, three endpoints + Next proxies, dispatch wiring, service
worker, browser enrolment helper, a third Delivery option in the subscribe
modal, and an explicit `worker-src 'self'` CSP directive.

Six specifics from the attached plan were corrected rather than followed —
BullMQ, `apps/api/`, raw SQL migration, a colliding endpoint name,
`NEXT_PUBLIC_VAPID_PUBLIC_KEY`, and `pywebpush`. Each is a repo constraint the
document could not have known.

### Evidence

| Gate | Result |
|---|---|
| RFC 8291 §5 published test vector | **byte-for-byte match** |
| Decrypt-as-a-browser round trip (independent HKDF via `cryptography`) | passes |
| `test_web_push_delivery.py` (new) | 18/18 |
| `test_push_device_registry.py` (new) | 15/15 |
| `test_notification_dispatch_service.py` (7 new/rewritten WEB_PUSH cases) | 26/26 |
| Full backend suite — CI (Linux) | **2116 passed**, 15 skipped, 2 xfailed, 0 failed |
| Full backend suite — local | 2117 passed, 17 skipped, 2 xfailed, exit 0 |
| Backend ruff | 0 |
| mypy ceiling | 771 ≤ 784 — **unchanged from baseline**, no new errors |
| Alembic `0013` upgrade → downgrade → re-upgrade | clean |
| OpenAPI | 108 paths (was 106; +2 for the push routes) |
| Artifact verifier | 6/6 hash-locked pairs |
| `web-push.test.ts` (new) | 15/15 |
| Full web suite | **319/319** (was 304) |
| Web lint / typecheck | 0 / 0 |
| `NODE_ENV=production` build | exit 0 |
| Gitleaks over the full branch range | no leaks found |
| **SonarCloud quality gate** | **OK — new-code coverage 98.0%** (was 71.0%) |
| PR #134 checks | **22/22 pass**, `mergeStateStatus: CLEAN` |

The two suite counts differ by the platform-dependent optional-ML skip set
(catboost/SHAP are unavailable on the local Python 3.14 interpreter), not by
any test outcome.

### Three CI failures on the way in

Recorded in `docs/DEBT.md` item 54 in full. In short: Gitleaks flagged an RFC
public key literal (**never run locally before pushing, though it is installed
and takes under a second**); the `pull_request`-event scan still saw the
introducing commit after the fix, so a `.gitleaksignore` fingerprint was added
per the ledger's existing precedent rather than force-pushing a rewritten
branch; and two typecheck errors were only reachable once the Gitleaks gate
stopped skipping every downstream job — **the first commit claimed a clean
typecheck that had been run before the test file existed.** Finally SonarCloud
failed on new-code coverage at 71%, backfilled to 98%.

### Deliberately not built

- A standalone push-preferences screen — the existing per-match modal is the
  only place a reader currently opts in, and a second surface would need its
  own state reconciliation.
- `render.yaml` declarations for the new env vars. The EMAIL channel set the
  precedent of dashboard-only configuration, and a `render.yaml` change forces
  a Blueprint-sync approval that has repeatedly been a blocker in this repo.
  Every variable is named in `docs/NOTIFICATION_CHANNELS.md` instead.
- Anything under Path B.
