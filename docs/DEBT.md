# SabiScore Debt Ledger

## 24. Rescheduled fixtures wedged the whole fixture-sync tick; mitigation shipped, identity-hash root cause deferred

**Tier:** mitigation = `FIXED` this session. Root cause = `NEXT` — a
kickoff-independent canonical fixture identity key, not a one-line change.
**Found:** 2026-08-16, in a fresh Render deploy log: `fixture_sync: unhandled
error — continuing without fixture data`, traceback ending in
`canonical_identity_service.ensure_canonical_fixture` raising `ValueError:
provider event conflicts with an existing canonical fixture`.

**Root cause.** `ensure_canonical_fixture`'s `fixture_id` is
`_stable_id("fixture", competition_id, kickoff_utc.isoformat(), home_name,
away_name)` — a hash that includes the exact kickoff timestamp. A legitimate
reschedule (broadcaster/league moves the kickoff time, which happens
routinely) changes `kickoff_utc` on the next sync for the same
`provider_event_id`, recomputes a different `fixture_id`, and
`ensure_canonical_fixture` correctly refuses to silently repoint the
existing `ProviderEventMapping` to a new fixture. That refusal is right in
isolation, but `sync_upcoming_fixtures()` called it with no per-fixture
try/except inside its loop, and the loop's single `session.commit()` sits
after the loop — so the raised exception propagated out before commit,
losing every fixture in that tick's batch, not just the rescheduled one.
Same failure shape as item 23 (Elo self-play), found the same day.

**Mitigation shipped (`35ca7bb`):** `sync_upcoming_fixtures()` now catches
`ValueError` around the `ensure_canonical_fixture` call, logs a warning with
the `match_id`/team names, increments `fixture_sync.identity_conflicts`, and
continues to the next fixture. The conflicting fixture's raw `Match` row
(already flushed earlier in the same loop iteration) still commits — only
canonical-identity reconciliation is skipped for that one fixture. Regression
test: `test_canonical_identity_conflict_does_not_wedge_the_batch`
(`backend/tests/unit/test_fixture_sync.py`) — seeds a fixture, resyncs it
with a different kickoff time alongside an unrelated new fixture, and asserts
the second fixture still commits.

**Not done — deliberately deferred.** The identity hash still includes
`kickoff_utc`, so a rescheduled fixture's canonical identity stays
unreconciled indefinitely (not just once) until a kickoff-independent key is
adopted — most likely `(competition_id, season, home_name, away_name)`,
which stays stable across a reschedule for SabiScore's supported
competitions (each is round-robin — at most one home/away meeting per
season pair — so this remains disambiguating; UCL's occasional
same-pairing-twice edge case was judged too rare to design around here).
Changing the hash affects new canonical-identity generation broadly, not
just the conflict path, so it's out of scope for a same-session defensive
fix.

**Blast radius:** was every fixture in whichever sync tick happened to
include a rescheduled fixture (all of them, not just the reschedule) — now
scoped to just that one fixture's canonical-identity reconciliation staying
incomplete (its `Match` row and scheduling data are unaffected).
**Cost:** mitigation, done. Root-cause fix: change `_stable_id`'s inputs in
`canonical_identity_service.py`, re-verify no existing dependents assume
kickoff-derived IDs, size small-to-medium.
**Priority:** medium — reschedules are routine in football, so this will
recur regularly until the identity key changes, but the mitigation means it
no longer costs an entire sync tick's fixtures each time.

---

## 23. 26 matches record a team playing itself — wedged the Elo backfill; code mitigation shipped, data fix deferred

**Tier:** mitigation = `FIXED` this session. Root-cause data fix = `NEXT` — no
operator credential needed, but requires investigating the team-alias
resolution path, not a one-line change.
**Found:** 2026-08-16, via a live `/health/ready` baseline check ahead of the
Elo Postgres backfill runbook in item 13 — `checks.elo` showed `rows: 0` and
`components.settlement` showed `outcome: "error"`, `last_success_at: null`,
hours after migration `0007_durable_elo_state` deployed.

**Root cause, confirmed via read-only production queries.** 26 rows in
`matches` have `home_team_id == away_team_id` — a team recorded as playing
itself. All 26 belong to exactly two clubs, one occurrence roughly every
season since 2019/2020: `fd-team-serie_a:fc_internazionale_milano` (16 rows)
and `fd-team-la_liga:rcd_espanyol_de_barcelona` (10 rows). The exact failing
insert:

```text
duplicate key value violates unique constraint "uq_elo_rating_match_team"
DETAIL: Key (match_id, team_id)=(fdco-3d01b70f3b802e7b, fd-team-serie_a:fc_internazionale_milano) already exists.
```

`sync_elo_from_finished_matches` processes matches oldest-first; the earliest
self-play row (Inter Milan, 2019-09-21) sits ahead of most of the corpus, so
every hourly settlement tick reached the same poison record, and
`apply_finished_match_to_elo`'s bulk insert of `[home_row, away_row]`
collided with itself on `(match_id, team_id)`. The failed flush aborted the
whole session — not just that one match — so `elo_rating_snapshots` stayed
at exactly 0 rows through every single tick since the migration deployed.
This is the "one poison record blocks the whole batch" failure class the
roadmap document's dead-letter-queue rationale names, and the same shape as
the 2026-08-08 fixture-sync 429-on-first-competition incident.

**Mitigation shipped (`291c06a`):** `apply_finished_match_to_elo` now checks
`home_team_id == away_team_id` before attempting the insert, logs a warning,
increments `elo.update.skipped_self_play`, and returns `False` instead of
crashing. `sync_elo_from_finished_matches` now returns a `skipped` count
alongside `processed`, surfaced through `settlement_service`'s existing
`/health` wiring with no new plumbing. Regression tests:
`test_self_play_match_is_skipped_not_crashed`,
`test_sync_skips_self_play_match_and_still_processes_the_rest`
(`backend/tests/unit/test_durable_elo_state.py`) — the second proves a good
match in the same batch as a self-play match still gets its snapshots
committed, i.e. the batch is no longer wedge-able by this bug.

**Not done — deliberately deferred.** The 26 corrupt `matches` rows
themselves are untouched; this fix only stops them from blocking everything
else. Root cause is unconfirmed — most likely a team-alias/name-resolution
bug specific to these two clubs in the historical CSV ingestion path
(`historical_backfill_service.py` / `providers/reconciliation.py`), given it
recurs almost exactly once per season for the same two teams rather than
being randomly distributed. Needs investigation before either correcting the
26 rows in place or re-ingesting them correctly; a same-session data mutation
was explicitly out of scope (production data fix, not authorized this turn).

**Blast radius:** was 100% of the durable-Elo backfill (item 13) — now
scoped down to exactly these 26 matches' own Elo history staying an honest
data gap (`home_resolved`/`away_resolved` correctly `False` for them; INV-01
unaffected — no fabricated rating is ever produced for a self-play match).
**Cost:** mitigation, done. Root-cause fix: investigation + a targeted data
correction, no credential/operator dependency, size unknown until the
alias-resolution bug is found.
**Priority:** high for the root-cause investigation — every future season
these two clubs play will add another one of these rows if the ingestion bug
isn't fixed, even though the mitigation means it won't wedge anything again.

---

## 22. `the_odds_api` API key leaked in production logs (fixed) + confirmed invalid (401, operator action required)

**Tier:** log leak = `FIXED` this session. Key validity = `FIX-NOW` / P0 —
operator-only, blocks CLV capture (item 6) and any market-benchmark work.
**Found:** 2026-08-13/14, from an operator-supplied Render deploy log
(2026-08-13T23:22–23:26 UTC) pasted into a chat session.

Two findings from the same log excerpt:

**(a) Log leak, fixed.** Every `the_odds_api` request logged its full URL,
including `?apiKey=<key>` in cleartext, at INFO level:

```text
httpx - INFO - HTTP Request: GET https://api.the-odds-api.com/v4/sports/soccer_spain_la_liga/odds?apiKey=<redacted>&regions=uk%2Ceu&markets=h2h&oddsFormat=decimal "HTTP/1.1 401 Unauthorized"
```

Root cause: `backend/src/api/main.py`'s `logging.basicConfig(level=logging.INFO, ...)`
sets the root logger level with no per-logger override, so the third-party
`httpx` package's own request-line logger (which httpx never redacts)
propagates straight to stdout/Render logs on every call. `core/logging.py`'s
`configure_logging()` already suppresses `uvicorn.access` the identical way
but is never called by `main.py` (a separate, pre-existing duplication — not
fixed this session). Only `the_odds_api` was exposed: `api_football` and
`football_data_org` use header auth (`x-apisports-key` / `X-Auth-Token`),
which httpx's INFO log line never includes (method/url/status only, never
headers); ESPN is keyless. Fixed with one line in `main.py`:
`logging.getLogger("httpx").setLevel(logging.WARNING)`, mirroring the
existing `uvicorn.access` precedent.

**(b) Key confirmed invalid — first real evidence, not code-fixable.** Every
request in the same log excerpt returned `401 Unauthorized`. The auth
mechanism in `the_odds_api.py` is correct (query-param `apiKey` is
the-odds-api.com's only scheme; `config.py`'s `AliasChoices` accepts both
`THE_ODDS_API_KEY`/`ODDS_API_KEY`; no truncation or mis-naming anywhere in
the request path). CLAUDE.md's "5 of 5 [providers] enabled" /
`CONFIGURED_UNVERIFIED` framing (vΩ.43) only ever meant the enable flag was
on and a non-empty key string was present — `PROVIDER_LIVE_TESTS=false`
means it was never actually probed end-to-end. This is the first live
confirmation, and it's negative. This is why `clv_capture` reads
`outcome:"never_run"` (item 6) — a second, more specific blocker than the
previously-documented Blueprint-sync story.

**Operator action required:** rotate the key at the-odds-api.com's dashboard,
then update `THE_ODDS_API_KEY`/`ODDS_API_KEY` in Render's environment
variables and redeploy. Treat the value visible in the pre-fix logs as
compromised regardless of root cause — it was both in Render's log retention
and pasted into a chat session.

**Blast radius:** (a) none going forward — fixed; historical log lines
already written are unaffected by this fix. (b) CLV capture (item 6) and any
Phase I market-benchmark work stay blocked until the key is rotated.
**Cost:** (a) done. (b) a few minutes across two dashboards, operator-only.
**Priority:** (a) closed. (b) high — it's the only remaining DATA-FED
prerequisite for CLV/market-comparison work.

---

## 20. A Render service builds the monorepo at root and is not in `render.yaml`

**Tier:** `FIX-NOW` / P0 — it crash-loops on every push to master.
**Found:** 2026-08-12, from an operator-supplied Render deploy log for commit
`5de6228`.

A Render web service clones the repo **at root** (no `rootDir`), runs
`pnpm install --frozen-lockfile; pnpm run build` on Node 24.14.1, builds
`@sabiscore/web` + `@sabiscore/scraper` successfully — then dies:

```text
==> Running 'pnpm run start'
 ERR_PNPM_NO_SCRIPT_OR_SERVER  Missing script start or file server.js
==> Exited with status 1
==> No open ports detected, continuing to scan...
```

`render.yaml` declares only two services: `sabiscore-api`
(`rootDir: backend`, pip + `alembic upgrade head && uvicorn`) and the
`sabiscore-evidence-acquisition` cron. **Neither matches this log.** The
service is therefore dashboard-created and outside blueprint management —
the same drift class as the operator-managed `DATABASE_URL` recorded above,
and consistent with the Blueprint-sync approval that has been outstanding
since vΩ.12.

**Immediate half fixed (2026-08-12):** root `package.json` had no `start`
script at all (only `apps/web/package.json` did), so the service could never
boot regardless of configuration. Added
`"start": "pnpm --filter @sabiscore/web start"`. Verified locally that
`PORT=4123 pnpm run start` binds to `$PORT` and serves `GET /api/health` →
200, which is exactly the port-binding contract Render's "No open ports
detected" scan was failing.

**Operator decision still required — do not skip this.** Adding the script
stops the crash loop, but it does **not** answer whether this service should
exist. `CLAUDE.md`'s canonical production shape puts `apps/web` on **Vercel**
and only `backend/` on Render. A second, blueprint-invisible copy of the
frontend on Render is either:

1. an intentional migration off Vercel — in which case it belongs in
   `render.yaml` with an explicit `startCommand`, and the Vercel project's
   role must be restated; or
2. a stale experiment that should be deleted, because it rebuilds the whole
   monorepo on every master push and its failures look identical to a
   backend outage in the dashboard.

⚠️ **CORRECTED 2026-08-12, same session.** An earlier version of this entry
claimed the crash loop "also explains why `sabiscore-api-bav1.onrender.com`
still reports `sha: 229efbc`". **That was wrong.** The backend subsequently
reached `5de6228` — and stayed healthy — while still running code that did
*not* contain the root `start` script, proving the API service was never
blocked by it. The two services are independent: `sabiscore-api` was simply
slow (free-tier `pip install` of the full runtime set takes many minutes),
and I read a slow deploy as a failed one. The real lesson is narrower than
the one first written here: **before attributing a stale `sha` to a specific
cause, confirm the timeline — a Render free-tier deploy can legitimately take
10–15 minutes, so "not yet" and "failed" look identical for a long window.**
Check the deploy log for that service, not a sibling's.

**Update 2026-08-13 — new symptom, decision made.** An operator-supplied
Render deploy log shows the `384f9f4` root `start` script fix holds — the
service now binds `$PORT` and boots cleanly (`Ready in 3.3s`) — but it still
dies roughly 4 minutes later (`ELIFECYCLE Command failed`), with no further
detail captured in the log excerpt. This is a **different failure** from the
original "no start script" crash, and it was not investigated further this
session: `render.yaml` still declares only `sabiscore-api` (Python) and the
`sabiscore-evidence-acquisition` cron, and `apps/web` is confirmed live and
correct on Vercel (production alias `sabiscore.com`, `vercel --prod` output
this session shows `Aliased https://sabiscore.com`, and
`web-lac-theta-42.vercel.app/api/health` independently reports `sha` matching
current `master` HEAD). With Vercel already canonical and healthy, the
decision is **suspend → verify → delete**, not further diagnosis of the
Render copy's runtime crash.

**Operator checklist (dashboard-only — no code change can execute this):**

1. In the Render dashboard, find the web service that is **not**
   `sabiscore-api` and **not** the `sabiscore-evidence-acquisition` cron.
2. Confirm its build/deploy log matches the signature already captured here:
   `pnpm install --frozen-lockfile`, `pnpm run build` building
   `@sabiscore/web` + `@sabiscore/scraper`, then `pnpm run start` →
   `next start`.
3. Record (privately, values not needed) whether it carries any of
   `REDIS_URL`, `DATABASE_URL`, `API_FOOTBALL_API_KEY`,
   `UPSTASH_REDIS_URL` — if the exposed Redis Cloud credential (item 15) was
   ever pasted into this service specifically, note that before touching
   item 15's revocation step.
4. **Suspend** the service (not delete yet).
5. Re-check `https://sabiscore.com` and
   `https://web-lac-theta-42.vercel.app` both still serve normally — they
   should be completely unaffected, since neither depends on this service.
6. Only after confirming step 5, **delete** the service and remove it from
   the Render dashboard's service list.

This item stays open until an operator actually performs steps 1–6 above —
adding the start script only stopped the crash-on-boot symptom, it did not
answer whether the service should exist, and code cannot make a dashboard
deletion.

**Blast radius:** every push to master triggers a failing build; the live
backend silently stays on the previous commit.
**Cost:** small for the script (done); the architectural decision is made
(suspend/delete) — remaining cost is five minutes in the Render dashboard.
**Priority:** P0 for the decision — until it is made, no push to master
reliably reaches production.

Format per entry: **Tier** (`FIX-NOW` / `NEXT` — named trigger / `ARCH-DEBT` — needs an
ADR / `ACCEPTED` — rationale + review date), owner, blast radius, engineering cost,
user impact, priority. An entry without a trigger is not `NEXT`, it's `ACCEPTED` in
disguise — say so honestly.

---

## 21. Frontend residuals left deliberately after the 2026-08-13 truthfulness pass

**Tier:** `ACCEPTED` (a and b) / **CLOSED 2026-08-14** (c — see below).
**Found:** 2026-08-13, while fixing the `LIVE`-badge, page-title, mobile-overflow
and selection-UI defects recorded in `CHANGELOG.md` for that date.

Three things were found and understood; (a) and (b) were deliberately left
unchanged, (c) was fixed the next day once its own named trigger fired.
Recording all three so a future session does not re-derive the context.

**(a) `BigMatchesCarousel` fetches while collapsed.** On the homepage the match
selector is wrapped in a native `<details>` (`app/page.tsx`, the
"Explore a manual matchup" accordion). React mounts `<MatchSelector />`
unconditionally and the browser merely hides it via the UA stylesheet, so the
carousel's `useQuery(["big-matches-carousel"])` issues its
`getUpcomingMatches()` request on every homepage load whether or not the user
ever expands the section. It is one bounded, cached (`staleTime` 5 min) request
that React Query dedupes, so the cost is small and it is **not** a correctness
or truthfulness issue — but it is avoidable. The fix is to gate the fetch on the
`<details>` open state (or lazy-mount the selector), which needs the accordion to
become a controlled component. Not worth the added state today.

**(b) `monitoring-dashboard.tsx` / `performance-dashboard.tsx` are orphaned.**
Neither is imported anywhere in `apps/web/src` (repo-wide grep), and
`app/monitoring/page.tsx` is a pure `redirect("/performance")`. They also fetch
endpoint shapes (`/api/metrics`, `/api/drift`) that no longer match the
`/api/model-performance*` surface `/performance` actually uses. Dead code, not
user-reachable, so deleting them is safe but is a separate cleanup with its own
review — bundling it into a UI-truthfulness commit would have obscured that diff.

**(c) `phase8-analytics-panel.tsx` still labels a tier `"Live"` — CLOSED
2026-08-14.** The named trigger fired: `Phase8AnalyticsSection` renders this
panel unconditionally as a full `<section>` on the primary `/match/[id]`
result page (no collapse/accordion gating it), which is exactly "promoted out
of diagnostics into a primary user surface." A separate audit the same session
also found a second live instance of the identical `edge_quality_score`
mislabeling class in `match-selector.tsx`/`insights-tease-strip.tsx` — three
occurrences total, matching this entry's own "or a third copy of this helper
appears" trigger. Fixed by renaming `freshnessLabel()`'s `"Live"` →
`"Fresh"` and `groupFreshnessChip()`'s `"LIVE"` → `"FRESH"` (pure string
rename, thresholds/colors unchanged) — **not** a cross-file helper extraction;
the three freshness implementations have different return shapes for
different purposes, and unifying them is a larger refactor than this
truthfulness fix required. Both helpers are now exported and pinned by
`phase8-analytics-panel.test.tsx`. See `CHANGELOG.md` (2026-08-14) for the
full three-file fix.

**Blast radius:** (a) one redundant request per homepage load; (b) none — dead
code; (c) none remaining — fixed.
**Cost:** (a) small but needs a controlled accordion; (b) trivial deletion,
separate review; (c) done.
**Priority:** low for (a)/(b); none remaining for (c).

---

## 17. Offline ML research environment is only partially installed

**Tier:** `NEXT` — trigger: reliable package-index access on a Python 3.11-3.13
host. **Verified:** 2026-08-10.

`backend/requirements-training.txt` now defines the isolated research stack and
`backend/scripts/verify_training_stack.py` distinguishes importability from model
certification. CatBoost 1.2.8 and SHAP 0.49.1 import in the local Python 3.12
environment. MLflow, Evidently, Great Expectations, XGBoost, LightGBM, and Optuna
did not complete installation within the bounded network attempts. The environment
was reconciled to the committed scikit-learn 1.5.2 pin and `pip check` reports no
broken requirements, but the full requirements set is not yet installed.

**Release impact:** none for the API runtime, which does not require or eagerly
import this stack. **Model impact:** candidate research, SHAP validation, drift
work, and MLflow experiment capture remain blocked locally. Installing these
packages does not permit model promotion; the real-settlement and active-generation
gates in item 14 still apply.

## 18. Scraper production cron is wired but intentionally inactive

**Tier:** `NEXT` — trigger: approved source-policy + storage credential
provisioning + retention controls documented in deployment record.
**Verified:** 2026-08-10.

`render.yaml` now defines `sabiscore-evidence-acquisition` (Docker cron) and
worker runtime assets exist in `apps/scraper/`, but
`SCRAPER_PRODUCTION_ENABLED=false` keeps execution fail-closed by default.
Code readiness exists; operational approval and secrets enablement do not.

**Release impact:** none for current API runtime while disabled.
**Risk if prematurely enabled:** unapproved source ingestion and uncontrolled
artifact retention/cost.

## 14. Apex candidate artifacts are quarantined and not certified

**Tier:** `FIX-NOW` before model promotion. **Found:** 2026-08-09.

Generated v5-named binaries were written over the active artifact paths before a
qualifying promotion decision. The active binaries have been restored and the
generated files moved to `backend/models/candidate/` with an explicit
`UNVERIFIED_CANDIDATE` manifest.

The required chronological run is now executed: training ends in 2023/24,
calibration is 2024/25, and the untouched evaluation season is 2025/26. The exact
stacked served head passed probability-simplex, input-responsiveness, coherent
price-perturbation, and positive mean RPS-improvement gates. Promotion still
fails three hard gates:

- RPS regressed in Bundesliga, EPL, and Ligue 1 (candidate won only 3/6 leagues);
- the candidate beat the coherent market baseline in 0/6 evaluated league rows;
- serving availability fails with 11 schema-misaligned positions and four
  always-data-gap slots; 24/68 training slots were defaulted/non-variable.

Evidence is versioned in `training_report_real.json`, `comparison_report.json`,
and `feature_availability_matrix.json`. Eredivisie remains pooled fallback; UCL
remains generic and capped at `ACTIONABLE`.

**Release rule:** candidate promotion is forbidden while
`promotion_permitted=false`. Do not rename or copy candidate files into the active
directory to make deployment pass. The active v5 generation is hash-locked but
formally `UNVERIFIED`; until it is certified, both verdict engines must keep every
public stake at zero and the distinct RL advisory integration must equivalently
abstain/zero its public recommendation.

## 15. Redis credential incident and Render configuration are operator-blocked

**Tier:** `FIX-NOW` / P0. **Found:** 2026-08-09. **Second call site found and
fixed:** 2026-08-10.

A supplied Render log contained a complete Redis URI. A later Render build log
shows `REDIS_URL` is not a valid `redis://`, `rediss://`, or `unix://` URL and the
deployed process exits during import. Central redaction and malformed-URL safe
degradation in `core/cache.py`'s tiered `RedisCache` were already in place, but a
live 2026-08-10T14:22 Render crash log traced a second, independent, unguarded
call site: `ModelOrchestrator.__init__` (`models/orchestrator.py`) called
`redis.from_url(redis_url, decode_responses=True)` directly, with no try/except.
Because `models/__init__.py` imports `ModelOrchestrator` eagerly, and
`ModelOrchestrator` is instantiated as a module-level singleton
(`orchestrator = ModelOrchestrator()`), any import of `src.models` — including
every request-path import of `models.feature_registry` — crashed the whole
process the instant `REDIS_URL` was invalid or unconfigured. Fixed the same way
as `cache.py`: the connection attempt is wrapped in
`(RedisError, ConnectionError, TimeoutError, ValueError)`, degrading to a minimal
`_InMemoryRedisAdapter` (get/setex/lpush/ltrim/llen/lrange — the only methods the
league models' prediction cache actually calls) instead of raising. Regression
tests in `backend/tests/unit/test_model_orchestrator_redis_fallback.py`. Code
cannot rotate the provider credential or modify the protected Render secret.

**Required operator sequence:** provision replacement Redis; set a complete
`rediss://` Render secret without printing it; prove TLS connectivity and external
cache readiness; revoke the exposed credential; redeploy; then prove current logs
remain redacted. Record provider-side replacement and revocation evidence privately.
Production remains blocked until every step is recorded.

**Update 2026-08-13 — verified runbook, migration not yet proven.** An
operator-supplied transcript worked through migrating to Upstash. Its
technical claims were checked against real code this session and hold:
`backend/src/core/config.py:174-175` does raise
`"production Redis requires a rediss:// URL"` when
`app_env == "production"` and the URL isn't `rediss://`, and
`backend/src/core/cache.py:189` does log
`"Redis (tier-1) connection established successfully"` only after a real
`PING` — the transcript's diagnostic advice is grounded, not guessed.
Superseding the freeform transcript with the corrected sequence:

1. Locally, clear the process env var by its **correct** name — `REDIS_URL`,
   not a mis-escaped `REDIS\_URL` (a real mistake caught mid-transcript;
   PowerShell doesn't need underscore escaping in a string).
2. Confirm which Render service is being edited before touching anything —
   it must be `sabiscore-api` (Python/FastAPI, `rootDir: backend`), **never**
   the undeclared Node service tracked in item 20. A pasted deploy log this
   session was from that other service and was initially misread as this
   one — see item 20's 2026-08-13 update.
3. Set the new Upstash `rediss://` URL as `sabiscore-api`'s `REDIS_URL` in
   the Render dashboard, keep `REDIS_ENABLED=true`, choose **Save and
   deploy** (not "Save only" — that only stores the value for a future
   deploy).
4. Watch the deploy log for the confirmed-real line
   `"Redis (tier-1) connection established successfully"`. Its absence, or
   `"production Redis requires a rediss:// URL"` appearing instead, means
   the guard rejected the value — fix the URL scheme, don't bypass the guard.
5. Re-run `/health/ready` and read `components.cache.metrics`' tier-1 flags
   specifically — **not** just the top-level `cache: "Connected"` string,
   which the 2026-08-12 CLAUDE.md ground-truth entry already documents as
   insufficient on its own (it read "Connected" once even while Redis was
   genuinely absent).
6. Only after step 5 confirms tier-1 is live, revoke the old Redis Cloud
   credential in its own console, then strip the stale `REDIS_URL` line from
   the local `backend/.env` (`Select-String` to confirm no match remains).
7. **Local re-test footgun:** `Settings.model_config.env_file` in
   `config.py` is `(project_root/.env, backend/.env)` — the second entry is
   cwd-relative, so `REDIS_URL` can resolve differently depending on whether
   a local script runs from the repo root or from `backend/`. Confirm from
   both cwds after editing, don't trust one.

Local Upstash connectivity (TLS, PING, write/read/delete) was reported PASS
in the transcript but is **not independently verified here** — this session
had no Upstash credential to test against. `sabiscore-api`'s `REDIS_URL` has
**not** been confirmed migrated as of this entry; a live probe
(2026-08-13, ~18:4x UTC) found `sabiscore-api-bav1.onrender.com` returning
`503` on `/health`, `/health/ready`, and `/api/v1/providers/health` alike —
consistent with either an in-progress redeploy from exactly this migration,
or an unrelated cold start/crash. Re-probe before concluding either way; see
the dated entry in CLAUDE.md for the exact snapshot.

A user-supplied screenshot of the Redis Cloud console (`cloud.redis.io`,
database `sabiscore-database`, ID `13753214` — the *old* provider being
migrated away from, not Upstash) confirms **Transport layer security (TLS)
is Off** and **CIDR allow list is Off** on that instance. This is exactly
why `sabiscore-api`'s production guard rejects it
(`config.py:174-175`, `"production Redis requires a rediss:// URL"` — a
non-TLS Redis Cloud endpoint is `redis://`, never `rediss://`). Confirms the
diagnosis; does not change the runbook above.

## 16. Release infrastructure and historical-secret gates remain partially closed

**Tier:** `FIX-NOW` / P0 before merge or deployment. **Verified:** 2026-08-10.

- Current-tree Gitleaks passes. Full-history Gitleaks still reports exactly two
  historical `backend/.env.example` fingerprints: `generic-api-key:17` at
  `d604c13` and `generic-api-key:10` at `67ed0ab`. Neither may be waived until
  the credential owner supplies dated revocation evidence for that exact value.
- Historical required-job runs still include `runner_id: 0` entries with the
  annotation `The job was not started because your account is locked due to a
  billing issue.` That dispatch blocker has now cleared: canonical Linux CI run
  `31437373215` (head `fe46d97`) completed with all five jobs green
  (Secret Scan, Backend Lint/Typecheck/Tests, Scraper Validate/Tests,
  Web Lint/Typecheck/Build, Playwright Smoke). Keep this item open only for the
  remaining infra/deploy proofs below.
- **Update 2026-08-14:** the current deployed SHA `e0f89ae` has genuine successful
  runs for canonical CI, backend, web, scraper, Playwright, Secret Scan, Gitleaks,
  model artifacts, and large-file checks on named runners with real steps. Billing
  dispatch is closed for this SHA. This does not prove CI for a new candidate SHA,
  nor revoke either historical credential.
- Docker Compose configuration passes. Fresh backend and web image retries ran
  for more than five and three minutes respectively without producing a current
  image. The only `sabiscore-backend:verify` tag is dated 2026-07-15 and
  `sabiscore-web:verify` does not exist.
- The backend production install surface is now trimmed to
  `backend/requirements.runtime.txt` in both `render.yaml` and the production
  Docker stage, removing optional research/browser/Kafka packages from the API
  boot path. This reduces build surface area but does **not** by itself prove a
  fresh backend/web image build; the image-proof gate remains open until new
  tags exist from the current release candidate.
- Alembic reports one head (`0006_canonical_league_ids`), but the production
  `upgrade head` connection attempt timed out after 120 seconds, so `check` and
  migration-head proof remain absent.
- The canonical `make verify` cannot execute faithfully on this Windows host
  because its recipe assumes POSIX shell syntax and `jq`. Use canonical Linux CI
  via `.github/workflows/ci.yml` (or `scripts/run-canonical-ci.ps1`) as the
  source of truth for merge/release gates.

**Release rule:** keep PR #5 unmerged and do not activate Render or promote a
Vercel deployment while any item above remains unproven.

## 12. Certified artifacts were trained on synthetic data — RESOLVED, with a residual

**Tier:** `ACCEPTED` — root cause fixed 2026-08-08 (retrain). Kept as the incident
record; the residual feature-coverage gap is tracked as item 13 below.
**Found:** 2026-08-08. **Resolved:** 2026-08-08, same day.

**Cause.** `backend/data/processed/*_training.csv` — the corpus behind every
committed `*_ensemble_v5_phase7.pkl` — is 500 rows of `np.random.randn()` noise
under 236 columns (`form_0`, `xg_7`, `fatigue_3`) that appear nowhere in the
canonical feature registry. The models therefore responded to only 4 of 68 inputs,
and the two enrichment parquets feeding those 4 are keyed by synthetic placeholder
team ids that never join to a real fixture — so every live fixture received a
byte-identical prediction (`0.4162 / 0.4155 / 0.1683`). Scored on real held-out
fixtures the incumbents landed at 0.20–0.41 accuracy, at or below always
predicting the home side. The "51% accuracy" in the artifact metadata was measured
against noise.

**Fix.** Retrained on the 12,765 real matches committed under
`backend/data/cache/fd_*.csv` via `backend/scripts/train_on_real_matches.py`,
computing only the features serving actually resolves (through the same shared
helpers, replicating `_get_team_stats`'s window semantics), with strictly forward
history accumulation and a most-recent-season temporal holdout. Candidate beat
incumbent on RPS in **5 of 5** leagues (mean +0.0453); responsive inputs
4/68 → 21–22/68. Eredivisie, which has one season and no holdout, uses a pooled
all-league model annotated as such. Reproducible via
`scripts/compare_candidate_vs_incumbent.py`. Pinned by
`tests/unit/test_model_differentiates_fixtures.py`.

**What this does NOT fix** — see item 13. The model is now sound, but several
canonical evidence families still remain unavailable at prediction time. The
previous note that market features were absent is stale: serving now fetches one
coherent 1X2 market, projects `derive_market_features(...)`, and marks
`MARKET_FEATURES_14` resolved. Head-to-head, venue, and Elo/tactical evidence
remain incomplete, so the artifact still holds those slots at registry defaults
by design and cannot lean on them yet.

---

## 13. Serving still has an unresolved canonical feature family — tactical remains; durable Elo code is ready for runtime backfill

**Tier:** `NEXT` — head-to-head and home venue resolved 2026-08-11; the Elo code path was corrected 2026-08-16 and now awaits production migration/backfill verification. Tactical/StatsBomb remains unresolved.
**Owner:** unassigned.
**Found:** 2026-08-08, while establishing the retrain's feature set.

The prior version of this item claimed the 14 canonical market fields were still
absent and reused a stale served-feature count. That is no longer accurate.
`UpcomingMatchFeatureProjector.project_match_features()` now calls
`derive_market_features(...)` and marks `MARKET_FEATURES_14` resolved, with the
contract pinned by `backend/tests/test_staleness_and_market_wiring.py`,
`backend/tests/test_feature_gap_detection.py`, and
`backend/tests/unit/test_feature_registry.py`. Re-derive any exact
served-feature count from code before using this item in retrain planning.

**Update 2026-08-11:** head-to-head and home venue are also now resolved.
`UpcomingMatchFeatureProjector._get_h2h_stats()` and `._get_home_venue_stats()`
(`backend/src/services/upcoming_match_feature_service.py`) query `Match` history
directly and are wired into `project_match_features()`; formulas were cross-checked
against `backend/src/data/transformers.py` for train/serve parity. Covered by
value-asserting tests in `backend/tests/test_feature_gap_detection.py`
(`test_get_h2h_stats_returns_computed_values_for_seeded_meeting`,
`test_get_home_venue_stats_returns_computed_rates`, plus a none-with-no-history
guard for h2h). Four cross-signal features also resolve incidentally once their
inputs are available: `h2h_market_agreement`, `venue_market_combo`,
`form_market_agreement_home`, `form_market_disagreement`.

The remaining missing family of genuine football evidence is:

| Family | Count | Why it is absent |
|---|---|---|
| ~~Head-to-head~~ | ~~5~~ | **Resolved 2026-08-11** — see above. |
| ~~Home venue record~~ | ~~4~~ | **Resolved 2026-08-11** — see above. |
| Elo | 4 | **Code-fixed 2026-08-16** — live serving now reads durable real-`Team.id` snapshots from PostgreSQL; production migration/backfill is still an operator verification gate. |
| Tactical / StatsBomb | 4 | Still backed by the stale/synthetic offline cache; requires a separate corpus regeneration and point-in-time parity review. |

**2026-08-16 update:** production Elo no longer depends on the local Parquet as its
serving authority. Migration `0007_durable_elo_state` adds `elo_rating_snapshots`;
`elo_state_service.py` reads/writes ratings by real `Team.id`; settlement applies
newly finished matches idempotently and chronologically; and
`replay_elo_from_db.py` now requires explicit `--apply` (default `--dry-run`) for
historical backfill. The Parquet engine remains offline/backward-compatible tooling.

**2026-08-16 update (2):** the backfill wasn't merely awaiting verification —
it was permanently wedged at 0 rows by a data-integrity bug. See item 23 for
the full diagnosis and the shipped mitigation. With that fix in, the hourly
settlement-coupled trickle (`sync_elo_from_finished_matches`, 500/tick) can
make real forward progress against the ~12,760 good matches; full coverage
is expected in roughly a day of background operation, no operator `--apply`
required unless faster coverage is wanted. Re-check `checks.elo.rows` in
`/health/ready` before treating this item as resolved — it was still
unverified as of this update.

**Blast radius:** prediction quality. Once migration + backfill are verified in the
target DB, the four Elo features can resolve from durable real identity. Tactical /
StatsBomb remains the residual family.
**Cost:** production operator action: migrate, dry-run, apply backfill, then inspect
readiness/Elo resolution. StatsBomb regeneration is separate.
**Impact:** moderate until DATA_FED/VERIFIED in production; no fabrication because
unresolved Elo remains a data gap.
**Priority:** high for production backfill verification; medium/low for tactical
regeneration depending on measured incremental value.

---

## 0. Canonical league_id storage — `_LEAGUE_META` stored fd.org codes

**Tier:** `ACCEPTED` — fixed 2026-08-08 (WP-A). Kept as incident record per convention.
**Found:** 2026-08-08, live probe of Eredivisie (9 DB rows, all `LEAGUE_POLICY_UNAVAILABLE`).
**Fixed:** `fixture_sync_service.py:_LEAGUE_META` tuple[1] changed from fd.org code
(`"DED"`, `"PL"`, `"PD"`, `"BL1"`, `"SA"`, `"FL1"`, `"CL"`) to canonical SabiScore ID
(`"EREDIVISIE"`, `"EPL"`, `"LA_LIGA"`, `"BUNDESLIGA"`, `"SERIE_A"`, `"LIGUE_1"`, `"UCL"`).
Alembic migration `0006_canonical_league_ids` renames existing League rows in the live DB
and cascades to `teams.league_id`, `matches.league_id`, `league_standings.league`.
`clv_capture_service._fd_code_to_canonical()` updated to an identity map (was a translation;
now `_LEAGUE_META` already stores canonical IDs directly). Test: `test_synced_league_id_is_canonical`.
**Root effect:** Eredivisie capability probe now returns `unverified_no_fixtures` → `verified`
once `get_next_upcoming_fixture()` can match canonical IDs; EPL/La Liga unblocked as their
sync windows open. Blast radius was every prediction path via `get_league_policy()` and
`full_analysis.py`'s model artifact lookup.

---

## 10. Offline Elo / StatsBomb artifacts were frozen at 2024-06-02 and synthetically keyed

**Tier:** `NEXT` — **Elo code path fixed 2026-08-16; production migration/backfill not yet independently verified.** StatsBomb remains offline debt. The historical incident below is retained because the legacy Parquet files still exist for offline/backward-compatible tooling.
**Owner:** unassigned.
**Found:** 2026-08-08, tracing why STALE_REQUIRED_EVIDENCE fired on 100% of fixtures.

**⚠️ Correction (2026-08-08, later same day): staleness was never the main defect.**
Both parquets are keyed by **synthetic placeholder team ids** — `bundesliga_home_0`,
`bundesliga_team_3` — not real `Team.id` values. `EloEngine.get_context()` and
`StatsBombAggregator.get_team_features()` therefore find zero rows for every real
fixture and silently return the neutral 1500/1500 baseline. The 2024-06-02 end date
is real but secondary: even a perfectly fresh artifact with these ids would join to
nothing. A regeneration run must re-key by `Team.id`, not merely extend the dates.

Two related fixes landed the same day: `elo_parquet_path`/`statsbomb_cache_path` were
resolving relative to the CWD and so weren't loading **at all** locally (item 12), and
`EloContext` now carries `home_resolved`/`away_resolved` so an unresolved rating is
reported as a `data_gap` instead of publishing 1500/1500 as an observation
(`backend/tests/unit/test_elo_context_resolution.py`).

`data/processed/statsbomb_features_cache.parquet` (2,058 rows) and
`data/processed/elo_ratings.parquet` (4,116 rows) both end **2024-06-02** — the whole
offline artifact set was frozen at the end of the 2023/24 season. Consequences:

- StatsBomb supplies 2 of the 65 live features (`home_pressing_intensity`,
  `progressive_carry_diff`); both are additionally forced to DATA_GAP because
  `statsbomb_staleness_max_days` is exceeded. `shot_quality_diff` is a permanent
  DATA_GAP by design (`PHASE7_FEATURES_ALWAYS_DATA_GAP`), unrelated to this.
- The 4 Elo features come from `EloEngine`, which reads the parquet — so the Elo
  context card and `elo_difference` are computed against ratings ~2 years stale.

vΩ.44 stopped this from *blocking* every analysis (the staleness gate now
distinguishes enrichment age from model-input age — see CHANGELOG), so the impact is
now degraded enrichment rather than total abstention. But it is still real signal
loss on 6 of 65 features.

`EloEngine.update_after_match()` already exists and persists post-match updates, and
as of vΩ.44 there are 12,765 real completed matches in the database to replay — so
regenerating Elo is now a scripted replay rather than a data-sourcing problem.
Regenerating StatsBomb needs the open-data corpus re-cloned (offline, large).

**2026-08-16 durable-Elo correction:** live feature serving has been moved to the
PostgreSQL `elo_rating_snapshots` authority rather than relying on this Parquet.
Settlement now advances Elo from newly finished matches with match/team idempotency,
and the historical replay script persists the same real-ID state only when
`--apply` is explicitly supplied. This reaches **EXISTS/WIRED** in this snapshot;
production `alembic upgrade head`, replay, row coverage, and live fixture resolution
must still be observed before marking it DATA_FED/VERIFIED. The stale StatsBomb
portion of this item remains unchanged.

**2026-08-08 correction — blast radius was wider than "6 of 65 degraded" for one
path.** `GET /api/v1/upcoming/matches` (the endpoint behind the homepage fixture
list) built its feature vector via the bare `project_match_features()`, which by
design never calls `EloEngine`/`StatsBombAggregator` at all — so on that specific
path these 6 features (plus the whole Phase-8 block) weren't just stale, they were
completely absent *and* invisibly excluded from `data_gaps` (the bare method's own
`_CALLER_RESOLVED_FEATURES` exclusion assumes a caller-side merge that never ran).
Same-valued near-default feature vectors across different fixtures were the direct,
visible symptom (every homepage fixture card showing an identical edge figure).
Fixed by switching that call site to `build_live_feature_vector()`, the wrapper
every other prediction surface already used — the upcoming-fixtures path now
surfaces and honestly gaps Elo/StatsBomb exactly like `full_analysis.py` does. This
does not close this item: the underlying parquets are still frozen at 2024-06-02.

**Blast radius:** 6 of 65 features degraded; no fabrication — every affected feature
is honestly reported as a gap (previously true only off the upcoming-fixtures path;
now true everywhere, see correction above).
**Cost:** Elo replay is small now that history exists. StatsBomb is a separate,
larger offline job.
**Impact:** moderate — reduces evidence quality, does not block predictions.
**Priority:** medium for the Elo half (cheap, and history now exists); low for
StatsBomb.

---

## 11. Eleven upcoming fixtures still have no history — lower-division clubs in cup ties

**Tier:** `ACCEPTED` — correct fail-closed behaviour; recorded so it is not
re-diagnosed as a bug.
**Found:** 2026-08-08, measuring backfill coverage.

38 of 49 upcoming fixtures resolve real history on both sides. The other 11 involve
clubs genuinely absent from the six top-flight divisions the backfill covers —
Coventry City, Hull City (Championship), Málaga, Deportivo La Coruña, Racing
Santander (Segunda), ADO Den Haag, Cambuur, Willem II (Eerste Divisie), Le Mans
(Ligue 2). They appear in the fixture feed because football-data.org's competition
endpoints include cup ties.

Those fixtures correctly return reduced evidence rather than a prediction built on a
club the system has never seen. Loading second divisions would fix it but would put
matches outside the seven-competition closed set into `matches`, with no canonical
`league_id` to hold them — a deliberate boundary, not an oversight.

**Blast radius:** those fixtures show no prediction.
**Cost:** would require a decision on representing non-supported competitions.
**Impact:** low — correct behaviour, just not maximal coverage.
**Priority:** low.

---

## 1. Base-58 feature block is silently defaulted on every live prediction

**Tier:** `NEXT` → **CLOSED 2026-08-07 (WP-18)** — see below.
**Owner:** unassigned.
**Found:** 2026-08-04, verifying the WP-0/WP-1/WP-2 identity + gap-detection campaign.
**Updated:** 2026-08-05 — WP-10.1 shipped (caller wired), WP-10.2 semantics pinned
(evidence below). WP-10.3 was still open at that point; it later shipped as WP-18
on 2026-08-07, as recorded in the closure note below.

**Closed 2026-08-07 (WP-18).** The `R4/INV-14` approval gate this entry described
("operator go/no-go... approval required, not autonomous, never execute-then-ask")
referenced an external campaign document's own numbering — `docs/RISK_REGISTER.md`
is empty and `INV-14`/`R4`/`GATE-10` are not defined anywhere else in this repo
(confirmed via repo-wide grep), so no formal, enforced gate (CI check, populated
registry) existed to satisfy mechanically. The substantive requirement — a human
with repository authority explicitly signing off on this exact schema-semantics
change before it landed — **was** satisfied: the operator reviewed a written plan
naming this precise change ("fix the confirmed home/away collision... wire the
existing (already-live-elsewhere) canonical remap... prefer real scraped
wins/draws/losses over the cruder estimate where available") and explicitly
approved it before any code was touched, via this session's plan-review flow.
Implementation matches WP-10.1/WP-10.2's semantics exactly, plus the D8b prefix
fix landed atomically as this entry required, plus the `feature_defaulted_ratio`
before/after proof (regression-test-backed, not a one-off manual number). Full
detail in `CLAUDE.md`'s WP-18 ground-truth entry and `CHANGELOG.md` vΩ.41.

`_get_team_stats()` (`backend/src/services/upcoming_match_feature_service.py:705-805`)
computes ~12 stats (`home_form_5`, `home_win_rate_5`, `home_goals_per_match_5`, …) that
share no name with any `CANONICAL_FEATURES_58` entry
(`backend/src/models/feature_registry.py:6-65` — e.g. the canonical name is
`home_form_last5_home`). The WP-2 gap-detection fix already flags this honestly as an
advisory gap rather than fabricating a value (`data_gaps` computed via
`_CALLER_RESOLVED_FEATURES` set-membership, not a value check) — this is **not** a
zero-fabrication violation. It is a prediction-*quality* gap: the model receives real
signal for at most ~28 of 86 features (Elo/StatsBomb/Phase8 block) on every request.

**Second, independent bug in the same function**: `_get_team_stats()` hardcodes the
`"home_"` prefix on every key it returns, regardless of which team it's called for —
`project_match_features()` calls it once for the home team and once for the away team
with identical output-key shapes (`upcoming_match_feature_service.py:140-141`), so
`away_stats` silently overwrites `home_stats` under the same dict keys before
`features_dict.update(...)`. Currently inert (neither key is canonical, so the
collision has no live effect), but a real remap must add an `is_home`/prefix parameter
or it will trade "honestly defaulted" for "silently swapped between home and away."

**WP-10.1 shipped (2026-08-05):** `ScrapedTeamFormStore` (D12 — was a zero-caller class)
now has a real caller: `UpcomingMatchFeatureProjector._apply_scraped_fallback()`
consults it only when `_get_team_stats()` returns `None` (zero DB history for that
side), and only tags the result via `data_quality["scraped_fallback"]` — never folded
into `is_synthetic` (the zero-fab publish gate in
`upcoming_match_service.py:265`, `publishable = not is_fallback and not is_synthetic`;
flipping it on a fallback whose keys are still non-canonical would have re-opened
exactly the vΩ.32 fabrication class this campaign already closed once). Still fully
inert on the canonical feature vector, deliberately — that's WP-10.3, below. Tests:
`backend/tests/test_feature_gap_detection.py`
(`test_scraped_fallback_used_when_db_has_no_history_but_stays_inert`,
`test_scraped_fallback_absent_leaves_prior_behaviour_unchanged`).

**WP-10.2 semantics pinned (2026-08-05, no assumption):** the canonical remap this item
needs is not undiscovered — it already exists, live, in a *sibling* pipeline.
`backend/src/data/transformers.py`'s `FeatureTransformer.engineer_features()`
(lines 328–339) computes the exact canonical names from the *exact same* non-canonical
keys `_get_team_stats()`/`ScrapedTeamFormStore.to_projection_stats()` both already
produce:

```text
home_form_last5_home   = home_form_5 * 3.0                      # → points/game over last 5, 0–3 scale
away_form_last5_away   = away_form_5 * 3.0
home_wins_last5_home   = round(home_win_rate_5 * 5.0)            # win RATE → win COUNT (0–5)
away_wins_last5_away   = round(away_win_rate_5 * 5.0)
home_draws_last5_home  = max(0, 5 - wins - 2)                    # ⚠ algebraic estimate, NOT a
away_draws_last5_away  = max(0, 5 - wins - 2)                    #   real draw count — assumes a
home_losses_last5_home = max(0, 5 - wins - draws)                #   fixed "2 losses" baseline
away_losses_last5_away = max(0, 5 - wins - draws)
home_goals_for_avg     = home_goals_per_match_5   (direct passthrough)
away_goals_for_avg     = away_goals_per_match_5
home_goals_against_avg = home_goals_conceded_per_match_5
away_goals_against_avg = away_goals_conceded_per_match_5
```

This is confirmed as the *training-time* semantics, not a guess: `models/training.py`
and `models/enhanced_training.py` both import `FeatureTransformer` from this exact
module, and `backend/models/training_report.json` → `data.feature_names[0:5]` starts
`["home_form_last5_home", "home_wins_last5_home", "home_draws_last5_home",
"home_losses_last5_home", "away_form_last5_away", …]` — the real trained artifact's own
feature order. **The draws/losses estimate is itself a latent precision loss**:
`ScrapedTeamFormStore`'s `ScrapedTeamForm` already carries real `wins`/`draws`/`losses`
integers from the scraped CSV (`to_projection_stats()` currently discards them down to
the same lossy `home_`-prefixed shape as `_get_team_stats()`, matching its bug
intentionally) — a real remap has a strictly-better option than reproducing
`transformers.py`'s algebraic estimate when the scraped source is what's in play.

**Historical pre-closure rationale for WP-10.3 (wiring this remap into
`upcoming_match_feature_service.py`):** it was classified R4 under INV-14
("remapping `_get_team_stats()` output onto
canonical feature names is a feature-schema change... even though no new feature is
added — the meaning bound to each name changes") — proposal-only, approval required,
never execute-then-ask. Confidence in the semantics was high (cited to the live
training artifact, not assumed), but the operator still had to sign off because the
change altered what every live model saw and required the D8b prefix fix plus a
`feature_defaulted_ratio` before/after capture. That approval and atomic implementation
were completed by WP-18, as the 2026-08-07 closure note records.

**Historical blast radius:** every live prediction, matchup and DB-fixture path.
**Closure:** WP-18 completed the approval, D8b atomic fix, regression coverage, and
`feature_defaulted_ratio` proof. No go/no-go decision remains open for this item.

---

## 2. Settlement loop and production prediction capture shipped; real outcomes pending

**Tier:** `NEXT` → settlement loop **shipped 2026-08-05**; interactive capture fix
**DEPLOYED / VERIFIED 2026-08-14** on Apex v3.
Entry kept (annotate, don't remove, matching item 1's precedent) because production
is still DATA-FED at zero, a residual limitation and a related risk (item 5) remain.
**Owner:** unassigned.
**Updated:** 2026-08-05 — WP-10.4 shipped. New `services/settlement_service.py`
composes `sync_settled_results()` (new, `fixture_sync_service.py`) →
`get_settled_predictions()` → `walk_forward_validate()`, called hourly from a new
periodic `_background_settlement_sync()` task in `api/main.py`. `sync_settled_results`
settles matching `Match` rows via a new `FootballDataAPIClient.get_recent_results()`
provider method, looked up by the same deterministic `fd-{id}` scheme
`sync_upcoming_fixtures()` already writes — no identity re-resolution needed.
`/health` gains an informational `components.settlement` snapshot;
`/model-performance` and `/model-performance/summary` now run the real query instead
of an unconditional 503 (the still-503 `reason` also corrected from
`bet_history_aggregation_not_yet_integrated`, now false, to
`insufficient_settled_predictions`). See `docs/adr/0003-settlement-join-scheduling.md`
for the scheduling decision and rejected alternatives. **Residual, not fixed by this
change:** once a match hits `SETTLED_MATCH_STATUSES` its score is frozen — a
provider-side correction after settlement is never re-applied.

The older paragraph below the WP-10.4 closure was stale: the background settlement
caller and result sync do run. The production zero instead traced to the other side
of the join: fresh verified-fixture full analysis returned real model output without
writing `MatchPredictionLog`, so there was nothing for a later finished result to
join. The Apex v3 candidate adds one shared, transactional capture path used by full
analysis and the existing prediction writers. It accepts only finite real-model
simplexes for existing scheduled fixtures strictly before kickoff, records a
deterministic input hash/provenance and `interactive_full_analysis` trigger, and
deduplicates the same match/model/input snapshot without a migration. A seeded
end-to-end test now proves scheduled fixture → full analysis → prediction log →
finished result → settled join. Persistence failure is observable but does not turn
an analytical fail-closed response into an execution claim.

Settlement and CLV selection now choose the latest eligible prediction strictly
before kickoff or closing-line capture. Two production full-analysis calls for the
same scheduled fixture incremented the duplicate counter twice, proving the existing
immutable row and deployed deduplication without creating another row. Direct row
counts remain private-network-only. The path is **DEPLOYED / CALLED / VERIFIED** but
not DATA-FED or CERTIFIED until a naturally finished fixture joins.

**Blast radius:** `/model-performance`, accuracy/RPS, CLV, and every promotion gate
that requires settled outcomes. **Residual:** production remains honestly
`503 METRICS_UNAVAILABLE` with zero settled predictions until a deployed pre-kickoff
capture later joins a real finished result. Do not retrain or promote on one row;
existing sample-size and temporal gates still apply.
**Impact:** no real accuracy telemetry exists yet even though the season is about to
generate settleable matches (Eredivisie opens 2026-08-07, EPL 2026-08-21 — see
`backend/src/core/season_calendar.py` for the provider-verified table).
**Priority:** was high as the literal Phase-1→Phase-2 gate; the *caller* is no longer
the blocker. What remains is time: `/model-performance` needs ≥10 settled, logged
Eredivisie predictions (several matchdays into the season, not the first match) before
Phase 2 can honestly begin.

---

## 3. OTel telemetry entirely unregistered; fixture-sync failures are invisible

**Tier:** `ACCEPTED` — both halves shipped; kept only as the incident record + a
pointer to the residual gap named below.
**Owner:** unassigned.
**CLOSED 2026-08-06/07 — verified against code, not carried forward from a stale
note.** `docs/adr/0006-otel-activation.md` moved from Proposed to **Accepted**;
`core/telemetry.py::setup_telemetry()` registers a real `TracerProvider` +
`BatchSpanProcessor(OTLPSpanExporter(...))` and a `MeterProvider`, called from
`api/main.py:67`, with `FastAPIInstrumentor.instrument_app()` applied at
`api/main.py:342` — both gated on `settings.enable_tracing AND
settings.otel_exporter_otlp_endpoint` both being set, so this remains a true
no-op in every environment that hasn't configured an OTLP endpoint (safe-defaults
preserved). OTLP/HTTP was chosen over gRPC specifically to avoid the `grpcio`
native-extension cost on the free-tier dyno (ADR-0006 §Cost) — no new pin needed.
The fixture-sync half is also closed: `run_fixture_sync()`
(`backend/src/services/fixture_sync_service.py`) now calls
`metrics_collector.increment("fixture_sync.failures")` +
`.record_error(...)` on its swallow path, surfaced live via the already-wired
`GET /metrics` (`api/endpoints/monitoring.py:560`,
`metrics_collector.get_summary()`) — no new endpoint needed, this task was the
one swallow site without any tracking at all. `_background_settlement_sync` and
`_background_clv_capture` were checked and did **not** need the same fix — both
already track outcome/`consecutive_failures` in an in-memory `_last_result` dict
surfaced via `/health` `components.settlement`/`components.clv_capture`
(item 2's own delivery), predating this entry.

**Blast radius:** none remaining — was every request (no tracing) and fixture
ingestion (no failure signal); both now have a signal.
**Impact:** none remaining.
**Priority:** none — revisit only if a future OTel exporter change needs a fresh
ADR.

---

## 4. Duplicate season-string writer

**Tier:** `ACCEPTED` — fixed; kept as the incident record only.
**Owner:** unassigned.
**CLOSED — verified against code 2026-08-07** (this entry's "not yet fixed"
framing was stale; the fix was already live, undocumented here until now).
`backend/src/data/loaders/football_data.py:322` calls
`season=canonical_season(match_data["match_date"])`, deriving from the match's own
date rather than re-deriving `"YYYY/YYYY"` from the source filename — there is now
exactly one season-string writer (`backend/src/utils/season.py`), matching
`fixture_sync_service.py` and `upcoming_match_feature_service.py`.

**Blast radius:** none.
**Impact:** none.
**Priority:** none.

---

## 5. Predictions with a synthetic match_id can never settle

**Tier:** `ACCEPTED` — **CLOSED 2026-08-12**. Kept as the incident record.
**Owner:** unassigned.
**Found:** 2026-08-05, while wiring the settlement join (item 2).
**Fixed:** 2026-08-12, ahead of its own trigger — closed *before* real settled
data could expose the gap, rather than waiting for a depressed
`settled_join_rate` to prove it. Eredivisie's first settleable results land
within days, so fixing it after the fact would have meant permanently
unjoinable rows already written.

`create_prediction()` (`backend/src/api/endpoints/predictions.py`) synthesized
`match_id = f"{home}_{away}_{timestamp}"` when the caller didn't supply a real one.
`get_settled_predictions()` joins `MatchPredictionLog.match_id` to `Match.id` — a
synthetic value can never equal a real `Match.id`, so such prediction rows were
permanently unjoinable no matter how correct the settlement pipeline is.

**Resolution:** the endpoint now fails closed. When no `match_id` is supplied it
raises HTTP 422 with `error_code: "FIXTURE_IDENTITY_REQUIRED"`, directing the
caller to a real fixture id from `GET /api/v1/fixtures/upcoming`, instead of
fabricating an identity that silently corrupts the settlement SLI. This is the
"rejecting the write" option named in the original cost estimate below, chosen
over back-resolving the fixture by team name + kickoff: that lookup would itself
be an identity guess, and the codebase already has a canonical answer for
whether a matchup resolves (`reconcile_team`, the `FIXTURE_IDENTITY_UNVERIFIED`
path) rather than a second, weaker heuristic in an endpoint. The DB-fixture
path, which already passes a real `match_id`, is untouched. Regression guard:
`test_prediction_endpoint_never_mints_a_synthetic_match_id` in
`backend/tests/test_zero_fabrication_contract.py` — a source-level contract
assertion in the repo's established style for this invariant class, since
importing the endpoint requires a live DB (item 7).

**Blast radius:** `settled_join_rate` (item 2's SLI) and `/model-performance`'s
`settled_predictions` count — both would have read low even once matches settled
correctly, for any share of predictions logged via this path.
**Impact:** now none for new writes. ⚠️ **Residual:** any rows already written
under a synthetic key before this fix remain unjoinable. No backfill was
attempted — `MatchPredictionLog` currently holds no settled rows at all
(`settled_predictions_total: 0`), so there is nothing to repair yet; re-check
if `settled_join_rate` reads low once real volume exists.
**Priority:** none remaining for the write path.

## 6. CLV and ROI are structurally unavailable, not merely unimplemented

**Tier:** `ACCEPTED` — ROI half unchanged/out of scope by construction; CLV half now
computed. Kept as the incident record + the ROI rationale, matching item 2/3/4's
"update in place, don't delete" precedent.
**Owner:** unassigned.
**Found:** 2026-08-05, while wiring `/performance` to the settlement join (item 2).
**Updated:** 2026-08-06 — **the CLV capture half is now shipped**, not just
proposed. `docs/adr/0004-clv-capture.md` (Accepted) landed alongside migration
`0005_clv_capture_schema` and `services/clv_capture_service.py`: a periodic
background job (`_background_clv_capture`, 5-min interval, same
handle-stored/cancel-on-shutdown shape as settlement sync) enumerates fixtures
approaching kickoff, fetches the odds board per league via
`TheOddsAPIProvider.odds()`, computes a median consensus across coherent
bookmaker records, de-vigs it (`the_odds_api.devig_probabilities`), and writes
one `MarketSnapshot(is_closing_line=True)` row. `MatchPredictionLog` gained a
nullable `closing_market_snapshot_id` FK, always NULL for now — see the ADR's
2026-08-06 addendum for why (`canonical_fixture_id`, the originally-proposed
join key, is never populated for an ordinary upcoming fixture; the job keys on
the legacy `matches.id` instead). 8 new unit tests
(`tests/unit/test_clv_capture_service.py`); backend suite 1089 passed.
**Updated 2026-08-07 — the CLV computation half now ships too.**
`repositories/fixtures.py::get_clv_records()` joins the latest logged
prediction per match to its latest captured closing line **on `match_id`, not
`canonical_fixture_id`** — both `MatchPredictionLog` write sites and the
capture job itself hardcode `canonical_fixture_id=None`, so that FK was never
a real prerequisite despite how the 2026-08-06 addendum below reads;
`match_id` is populated and indexed on both tables today, so no
identity-resolution work was needed to unblock this. `services/clv_service.py
::compute_clv_summary()` computes a mean CLV
(`model_prob[argmax] - closing_implied_prob[argmax]`) plus a positive-rate,
gated on `n >= 10` joined records (reuses `model_registry.py`'s own
`MIN_RECORDS_FOR_DECOMPOSITION` threshold rather than inventing a second magic
number in the same response), surfaced as an independent `clv` field on
`GET /model-performance` — independent of the walk-forward floor already in
that response, since a season can have enough closing lines and too few
finished matches, or the reverse. **Two things this deliberately did NOT do:**
it does not touch `MatchActionability.clv_pct`
(`services/intelligence_synthesizer.py`, `full_analysis.py:448`, still
hardcoded `None` / "Sprint 5") — that field lives in the Kelly/verdict/abstain
advisory surface, the same category as `betting_intelligence.py`/
`core_engine.py` even though it isn't literally those files, and is a
different "CLV" concept (per-recommendation, not this diagnostic aggregate);
and it does not restore the `/performance` frontend CLV card — an explicit
user scope decision this session, not a technical blocker (the computation
prerequisite the guard below names is now satisfied). **ROI is unchanged and
stays unreachable by construction** — it needs a placed stake, which this
platform never places.

`/performance` used to carry "30d CLV" and "30d ROI" stat cards. They were removed
rather than left showing an em-dash, because an em-dash means "awaiting data" and
neither figure is awaiting anything:

- **CLV** (closing line value) needs the closing price recorded beside each prediction.
  `MatchPredictionLog` (`backend/src/db/models.py:227-251`) stores probabilities,
  confidence, `model_version`, `calibration_method`, `input_hash` and a nullable
  `payload` — **no odds column of any kind**. The CLV machinery itself does exist
  (`connectors/pinnacle.py::calculate_clv`, the `clv_*` features in
  `connectors/odds_market.py`), so this is a missing *join*, not a missing capability:
  nothing links a stored prediction to the market price at the time it was made.
- **ROI** needs a realised return on a placed stake. This platform never places one —
  verdicts terminate at `NO_BET`/`HOLD`, staking is shadow-evaluation only, and the
  `EXECUTE_BET` state was explicitly rejected as a product-identity decision. There is
  no execution record for ROI to be computed from, and adding one is out of scope by
  construction rather than by backlog position.

**Blast radius:** none today — removing the cards changed no computation. The risk this
entry guards against is someone re-adding the *ROI* card as a "coming soon"
placeholder, which would be an INV-01 fabrication surface of exactly the
vΩ.24/vΩ.28 kind (a neutral default rendered where a measurement belongs). The
CLV card's own prerequisite (a real computed number) is satisfied as of
2026-08-07 — restoring it is now a scope decision, not a fabrication risk.
**Cost to actually deliver CLV:** **done, 2026-08-07** — the schema/capture job
shipped 2026-08-06, computation shipped 2026-08-07 (above). Correcting a
citation error from the previous version of this entry: the "already does this
math" reference here previously named `connectors/odds_market.py::
market_movement_features` — that function does not exist in that module at
all (`market_movement_features` lives in `features/market.py` and has no
`model_probabilities` parameter, so it cannot compute CLV under any wiring).
The function that *does* compute CLV, `connectors/odds_market.py::
compute_market_features()`, was deliberately **not** called by the shipped
implementation either — it re-derives de-vig arithmetic from raw odds that
`MarketSnapshot.*_implied_prob_devigged` already stores precomputed, so
`clv_service.py` does a direct subtraction on those columns instead. Remaining
cost, if ever wanted: wiring the diagnostic `clv` field into the `/performance`
frontend (out of scope this pass) and, separately, deciding whether/how to
populate `MatchActionability.clv_pct` from the same joined data (a
verdict-adjacent surface, not touched here).
**Cost to deliver ROI:** not applicable; it requires reversing a deliberate product
decision, not writing code.
**Impact:** `GET /model-performance` now returns an independent `clv` field
(mean CLV + positive-rate, `n >= 10` floor) alongside the walk-forward harness
output; the `/performance` frontend page is unchanged and does not render it
yet.
**Priority:** none for CLV computation (done). Low for the `/performance` card
restoration, whenever that scope is picked up. ROI: never, absent an explicit
operator decision to change what the product is.

## 7. `core/database.py` opens a connection at import time, so every offline tool needs a live DB

**Tier:** `ARCH-DEBT` — needs an ADR; do not change fail-closed semantics casually.
**Owner:** unassigned.
**Found:** 2026-08-05, diagnosing a production outage (see the operator note below).

`backend/src/core/database.py` runs `_test_connection()` and raises at **module scope**
(`:110-117`), not inside a function. Anything that imports the module therefore
requires a reachable PostgreSQL, including tooling that has no business needing one:

- `alembic/env.py:11` does `from src.core.database import Base`, so **`alembic upgrade
  head`, `alembic check`, and `alembic revision --autogenerate` all fail with a
  connection error before Alembic runs its own logic** — the failure surfaces as a raw
  traceback from an import, not as a migration error.
- `src.api.main` cannot be imported for inspection, linting or an IDE language server
  without a database.
- `make verify` gate 4 and gate 14 both need a live local PostgreSQL purely to import.

**Why this is not simply "make it lazy":** the raise is load-bearing. It is what
enforces "PostgreSQL unavailable and SQLite fallback is not explicitly allowed" — the
`ALLOW_SQLITE_FALLBACK` invariant that must never activate silently. Deferring the
check must preserve that: the correct shape is a lazy engine whose *first use* raises
the same way, not a check that is dropped.

**Blast radius:** in production it converts a recoverable dependency outage into an
un-diagnosable crash loop. `render.yaml`'s `startCommand` is
`alembic upgrade head && uvicorn …`; when the import raises, the `&&` short-circuits,
uvicorn never starts, the container exits, Render restarts it, and the only public
signal is the platform's own HTML 502. The service being down is *correct* (it cannot
serve without its database) — being unable to say why is not.
**Cost:** medium. Convert to a lazily-initialised engine plus an explicit
`verify_database_connection()` called from `lifespan()` and from Alembic's `run_
migrations_online()`, keeping the fallback gate exactly where it is.
**Impact:** developer friction today; diagnosability during an incident.
**Priority:** medium — raise it if a second outage is misdiagnosed because of this.

---

## Operator action outstanding (not code — no code change can resolve it)

**RESOLVED 2026-08-06 — new PostgreSQL instance provisioned; render.yaml corrected
to match.** The expired `sabiscore-db` (below) was replaced with a standalone
instance (`sabiscore_db_v2`) created directly in the Render dashboard, outside
blueprint management. `render.yaml` still declared `DATABASE_URL` via
`fromDatabase: {name: sabiscore-db}` and still carried a `databases:` block for
the now-dead resource — live drift that would have risked a future Blueprint
sync (e.g. the one enabling the three disabled providers) silently rebinding
`DATABASE_URL` back to a dead or freshly-empty resource. Fixed: `DATABASE_URL`
is now `sync: false` (operator-managed, matching how the replacement was
actually provisioned) and the `databases:` block is removed. No data was lost
by this correction — the old instance was already unreachable (DNS failure)
before the replacement existed, so there was nothing live to migrate.
**Still worth confirming, operator-only:** that `sabiscore_db_v2` is on a plan
that won't hit the same 30-day free-tier expiry (if it's also `plan: free`,
this will recur).

**Original entry, 2026-08-05 (kept for the incident record):**
Render PostgreSQL `sabiscore-db` no longer resolved and the API was crash-looping.
Observed in the Render logs:

```text
failed to resolve host 'dpg-d95kg3e7r5hc73eh7g6g-a': [Errno -2] Name or service not known
PostgreSQL unavailable and SQLite fallback is not explicitly allowed
==> Instance srv-d95kkffaqgkc73f8003g-nvp7j restarted
```

`render.yaml:32` wired `DATABASE_URL` via `fromDatabase: sabiscore-db`. A DNS failure
on the instance hostname meant the database instance itself was gone, not that
credentials had drifted — Render's free PostgreSQL tier expires and is deleted after
30 days.

---

## 8. `monitoring/drift.py` still has zero production callers — reference baseline cannot exist yet

**Tier:** `NEXT` — trigger: ≥1,000 score-verified settled fixtures exist (the
generator's own `--minimum-sample` default; see below). Not sooner.
**Owner:** unassigned.
**Found:** 2026-08-06, scoping a "wire drift → Slack alerting" task before starting it.

`DriftMonitor` (`backend/src/monitoring/drift.py`) and `trigger_slack_drift_alert`
(`backend/src/services/alerting.py`) are both correct and unit-tested, and
`SLACK_DRIFT_WEBHOOK_URL` now has a `render.yaml` declaration (`sync: false`,
this session). None of that makes wiring a periodic caller today a good idea —
two independent blockers, both data, not code:

1. **No reference baseline exists, and none can be generated.**
   `backend/data/reference/` holds only a `README.md` and a
   `baseline_v1.manifest.template.json` — never `baseline_v1.parquet` itself.
   `scripts/generate_reference_baseline.py` → `ReferenceBaselineGenerator`
   selects only score-verified settled fixtures and refuses to write an
   artifact below `--minimum-sample` (default 1,000) — by design, it "never
   fabricates or zero-fills a baseline." Zero fixtures are settled as of
   2026-08-06 (Eredivisie's first ball hasn't been kicked). `DriftMonitor.__init__`
   raises `DriftConfigurationError` without this file; there is nothing to
   construct a monitor from yet.
2. **No live write path stores a reconstructable feature vector for a
   "current batch."** `MatchPredictionLog.payload` is written as `None` from
   `api/endpoints/predictions.py` and as the full `MatchAnalysisResult` (not a
   raw canonical feature row) from `services/analytics.py` — neither shape
   matches the reference schema's `ordered_features` that `evaluate_batch()`
   requires. Even once (1) is satisfied, sourcing `current_batch_df` is a
   second, separate piece of work.

Building periodic-task scaffolding around either blocker now would mean
guessing at a shape with nothing real to validate it against — the same
"stacked bug behind a broad except" class this codebase has hit before
(vΩ.32). Deferred deliberately, not overlooked.

**Blast radius:** none today — `drift.py` importing cleanly and its tests
passing is the full extent of current behavior.
**Cost:** the baseline half resolves itself once real settlement volume
exists (run the generator; it either succeeds past 1,000 rows or refuses).
The current-batch half needs a real decision: either widen a write path to
log the canonical feature vector `engineer_features()` already produces, or
source batches by re-deriving it from settled `MatchPredictionLog` rows —
worth deciding once there's real data to test against, not now.
**Impact:** none — advisory monitoring, not on any serving path.
**Priority:** low until item 2's settlement volume climbs toward four figures;
revisit alongside item 2/5's own settled-data gates.

---

## 9. Portfolio-exposure haircut curve and aggregate-cap multiplier are placeholders, not calibrated values

**Tier:** `NEXT` — trigger: ≥1 fully-settled same-league/same-matchday round
exists (Eredivisie's opening weekend, 2026-08-07 onward, is the earliest
candidate). Not sooner.
**Owner:** unassigned.
**Found:** 2026-08-06, implementing WP-17 (`docs/adr/0005-portfolio-exposure-policy.md`).

`backend/src/core/portfolio_exposure.py`'s `HAIRCUT_PER_ADDITIONAL_FIXTURE` (0.10),
`HAIRCUT_FLOOR_MULTIPLIER` (0.50), and `AGGREGATE_CAP_MULTIPLIER` (3.0) are reasoned
starting points, not derived from real same-matchday settlement outcomes — none exist
yet. ADR-0005's Reversal/Trigger clause names this same gap. Marked
`PORTFOLIO_POLICY_SOURCE = "DEFAULT_PENDING_CALIBRATION"`, mirroring
`LeaguePolicy.policy_source`'s own vocabulary. Policy (c)'s drawdown-pause threshold has
no placeholder at all — it's deferred entirely (no settled positions exist to compute a
real drawdown from), never a fabricated value.

Same session also found and fixed a genuine prerequisite bug while implementing this:
`PredictionEngine.calculate_value_bets` (`backend/src/models/prediction.py`) computed
Kelly stakes with no cap at all — a 4th, independent, uncapped implementation beyond
the 3 `MAX_KELLY_CAP=0.05` literals already known (`insights/engine.py`,
`betting_intelligence.py`, `core_engine.py`). Now clamped via
`min(get_league_policy(league).kelly_cap, MAX_KELLY_CAP)`, matching the established
pattern. This was a real, live-affecting fix, not part of the placeholder gap above.

**Blast radius:** none — advisory-only, flags/haircuts a display number never read as
a gate (`EXECUTE_BET` doesn't exist).
**Cost:** recalibrate once real settled outcomes exist for ≥1 same-league/matchday
group.
**Impact:** low today; the risk is the placeholder looking more authoritative than it
is if the marker is ever dropped.
**Priority:** low until Eredivisie's opening round settles.

---

## 19. `UpcomingMatch` / `UpcomingMatchesResponse` are declared twice in `apps/web`, bridged by an unchecked cast

**Tier:** `ACCEPTED` — **CLOSED 2026-08-12**, same day it was opened. Kept as
the incident record per this ledger's convention.
**Owner:** unassigned.
**Found:** 2026-08-12, while fixing the empty fixtures panel.

**Closed 2026-08-12.** The trigger named below ("the next time either shape
changes") fired immediately: the very next change to this response shape was
the league-filter fix in the same session. Resolution: `lib/api.ts` remains the
single authority and absorbed the three fields the panel legitimately needed
and the canonical copy lacked — `data_quality`, `competition_stage`, `portfolio`
on `UpcomingMatch`, plus `portfolio_exposure` on `UpcomingMatchesResponse`. The
panel's 65-line local redeclaration and the
`as Promise<UpcomingMatchesResponse>` cast are deleted; it now imports both
types from `@/lib/api`. The prediction sub-shape disagreement noted below
(`draw_prob`/`away_win_prob` vs `draw`/`away_win`) resolved on inspection —
the panel never read those keys, only `predictions?.confidence`, so the
divergence was dead surface area rather than a live mismatch. `pnpm typecheck`
exits 0 with the cast removed, which is the proof that matters: any future
field drift is now a compile error rather than a runtime `undefined`.

`apps/web/src/lib/api.ts` exports the canonical `UpcomingMatch` /
`UpcomingMatchesResponse` interfaces used by `getUpcomingMatches()`.
`apps/web/src/components/upcoming-matches-panel.tsx` independently redeclares
both with a **different** shape, then force-casts the real client's return
value (`getUpcomingMatches(...) as Promise<UpcomingMatchesResponse>`), so
TypeScript cannot catch a genuine mismatch between what the API returns and
what the panel assumes.

The drift is real in both directions: the panel's copy carries
`data_quality`, `competition_stage`, and `portfolio`; the canonical copy
carries `venue`, `value_bets`, `source`, `edge_quality_score`, `clv_pct`,
`data_gap`, `unavailable_reasons`, and `generated_at`. The prediction sub-shapes
disagree outright — the panel spells the keys `draw_prob`/`away_win_prob`,
the canonical copy `draw`/`away_win`.

**This is no longer theoretical.** Rendering an honest "backend failed" empty
state required `data_gap`, which exists on the canonical type and on the wire
but was absent from the panel's copy — a compile error that the cast would
have hidden entirely had the field been read through it rather than declared.
`data_gap?: boolean` was added to the local copy as the minimal unblock; the
duplication itself is untouched.

**Blast radius:** any field the backend adds, renames, or removes is invisible
to the panel until it fails at runtime.
**Cost:** small but not mechanical — the two shapes must first be reconciled
(they are not a superset/subset), then the cast removed and the panel's reads
re-typechecked.
**Impact:** moderate — this is a zero-fabrication surface, and a silently
`undefined` field here renders as a missing badge or a wrong empty state
rather than an error.
**Priority:** medium. Do it as part of the next change to this response shape,
not as a standalone refactor.
