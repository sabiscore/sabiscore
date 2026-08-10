# SabiScore Production Setup Guide

Last updated: 2026-08-10

This is the authoritative setup and deployment guide for the finalized production shape.

## Canonical Services

| Surface | Path | Role |
|---|---|---|
| Backend | `backend/src/api/main.py` | FastAPI authority for evidence, providers, analysis, verdicts, EV, and Kelly sizing |
| Web | `apps/web` | Next.js public frontend and backend proxy routes |
| Scraper | `apps/scraper` | Permitted batch acquisition, raw snapshots, processed files, manifests, parser validation |

`apps/api` and `frontend/` are legacy-only and must not be referenced by production scripts, deploy configuration, or runbooks.

## Safe Defaults

Production and template defaults must remain fail-closed:

```env
DEBUG=false
MOCK_MODE=false
ENABLE_LEGACY_INFERENCE=false
SCRAPER_ALLOW_INSECURE_FALLBACK=false
ALLOW_SQLITE_FALLBACK=false
SABISCORE_ALLOW_INSECURE_FALLBACK=false
PROVIDER_LIVE_TESTS=false
```

Database tables are created by Alembic only. App import/startup does not call `Base.metadata.create_all()` or `Base.metadata.drop_all()`.

SQLite fallback is permitted only for isolated tests or an explicit local development opt-in with `SABISCORE_ALLOW_INSECURE_FALLBACK=true` and a non-production `APP_ENV`. Production rejects SQLite fallback.

## Environment Matrix

Backend-only provider keys:

| Variable | Required | Notes |
|---|---:|---|
| `FOOTBALL_DATA_API_KEY` | Optional | Official fixture/standing provider |
| `API_FOOTBALL_API_KEY` | Optional | Authenticated enrichment provider; legacy alias `API_FOOTBALL_KEY` is still accepted |
| `SPORTMONKS_API_TOKEN` | Optional | Authenticated enrichment provider; legacy alias `SPORTMONKS_API_KEY` is still accepted |
| `THE_ODDS_API_KEY` | Optional | Current market snapshots; legacy alias `ODDS_API_KEY` is still accepted |

Frontend/server variables:

| Variable | Scope | Notes |
|---|---|---|
| `SABISCORE_DATABASE_URL` | Docker Compose backend | Optional compose override; defaults to the `postgres` service DNS name |
| `SABISCORE_REDIS_URL` | Docker Compose backend | Optional compose override; defaults to the `redis` service DNS name |
| `SABISCORE_BACKEND_URL` | Next.js server | Backend origin for proxy routes |
| `NEXT_PUBLIC_APP_URL` | Browser-safe | Public app URL only |
| `NEXT_PUBLIC_CURRENCY` | Browser-safe | Display currency |
| `NEXT_PUBLIC_CURRENCY_SYMBOL` | Browser-safe | Display label |
| `NEXT_PUBLIC_BASE_BANKROLL` | Browser-safe | UI default only |

ESPN is keyless. Any previously exposed provider key must be rotated in the provider/platform console after repo sanitization.

The backend loads the project-root `.env` first and `backend/.env` second, so
put backend-only provider secrets in the backend template or `backend/.env`
rather than the browser-safe templates.

Credential safety:

- Keep `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `DB_PASSWORD`, and provider keys blank in committed templates.
- Do not create `NEXT_PUBLIC_*` provider keys.
- Rotate any provider key that ever appeared in historical documentation. The current tree is redacted; `.gitleaksignore` only suppresses known legacy fingerprints until a reviewed history rewrite is scheduled.
- Run the focused safety gate before release:

```bash
cd backend
python -m pytest tests/test_secret_safety.py tests/test_database_migration_hardening.py tests/test_providers_gateway.py -q --no-cov
```

- CI runs Gitleaks with redacted output and full Git history before test jobs in `.github/workflows/ci.yml`.
- Local release scans should use the installed Gitleaks binary before committing:

```bash
gitleaks detect --source . --redact --verbose
```

## Install

Production is Python 3.11: `.python-version` pins 3.11.13, Render requests
3.11.9, and backend Docker images use Python 3.11. On that dependency branch,
`backend/requirements*.txt` installs FastAPI 0.104.1, Uvicorn 0.24.0,
Pydantic 2.9.2, and SQLAlchemy 2.0.23. Python 3.14 is a supported local
compatibility path with newer wheel-backed packages, including FastAPI 0.115.x;
it is not the active Render runtime. Optional training/experiment packages such
as CatBoost, SHAP, MLflow, and Great Expectations remain Python <3.14 extras
because they are not required for API boot or provider intelligence.

Create the research environment separately. Python 3.12 selects newer binary
wheels for CatBoost, SHAP, and scikit-learn while Python 3.11 retains the validated
production-era pins:

```powershell
py -3.12 -m venv .venv-ml
.\.venv-ml\Scripts\python.exe -m pip install --upgrade pip
.\.venv-ml\Scripts\python.exe -m pip install -r backend\requirements-training.txt
.\.venv-ml\Scripts\python.exe backend\scripts\verify_training_stack.py
```

The verifier certifies imports only. Do not configure MLflow in the API runtime or
interpret successful installation as model certification. Model-changing work
requires non-zero real settlement evidence and production promotion requires the
reviewed active-generation manifest release.

Kafka clients and browser automation packages are optional worker dependencies on Python 3.14/Windows and are not part of the canonical API/provider-gateway boot path. Install them in a Python 3.11-3.13 worker environment if Kafka or dynamic browser scraping is explicitly enabled.

Use Node 22 through 24 and pnpm 8 through 11 with the committed `pnpm-lock.yaml`. On Windows, skip `corepack enable` unless running an elevated shell; a user-scoped pnpm install is sufficient.

Windows PowerShell:

```powershell
pnpm install --frozen-lockfile

py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

Linux/macOS:

```bash
pnpm install --frozen-lockfile

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt
```

## Run Locally

```bash
cd backend
alembic upgrade head
python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

```bash
pnpm --filter @sabiscore/web dev
```

```bash
pnpm --filter @sabiscore/scraper doctor
pnpm --filter @sabiscore/scraper test
```

## Provider Gateway

All provider traffic goes through `backend/src/providers/`.

Provider responsibilities:

| Provider | Trust tier | Use |
|---|---|---|
| ESPN | `UNOFFICIAL_PUBLIC` | Keyless supplementary discovery/readiness only |
| football-data.org | `OFFICIAL_AUTHENTICATED` | Fixtures and standings |
| API-Football | `OFFICIAL_AUTHENTICATED` | Enrichment, lineups, injuries, stats, odds where licensed |
| Sportmonks | `OFFICIAL_AUTHENTICATED` | Optional enrichment where licensed |
| The Odds API | `OFFICIAL_AUTHENTICATED` | Coherent current 1X2 market snapshots |

CLI:

```bash
cd backend
python -m src.cli providers status       # one-line health summary per provider
python -m src.cli providers doctor
python -m src.cli providers capabilities
python -m src.cli providers quota
```

`providers status` and `providers doctor` are safe offline/configuration commands
by default. Their public report shape is intentionally limited to `provider` and
one of `configured`, `missing`, `invalid`, `quota_exhausted`, or
`temporarily_unavailable`. Live validation is opt-in only with
`providers doctor --validate-live`; startup and default CI must not spend
free-tier provider quota.

API:

```text
GET /api/v1/providers
GET /api/v1/providers/health
GET /api/v1/providers/capabilities
GET /api/v1/providers/quota
```

Provider output is redacted and returned in a standard envelope with trust tier, status, quota, warnings, snapshot hash, and acquired timestamp.

Provider health distinguishes configuration from verification. With live provider probes disabled, enabled providers return `CONFIGURED_UNVERIFIED`, not `VERIFIED`. A provider reaches `VERIFIED` only after a provider-specific live probe or successful live data operation validates the upstream path.

The provider registry and its shared `httpx.AsyncClient` are created once in the FastAPI lifespan (`app.state.provider_registry`, `app.state.http_client`) and injected into every request via `Depends(get_provider_registry)` â€” never instantiated per request. CLI tools and tests may still call `build_provider_registry()` directly without a client; providers fall back to an ad-hoc per-call client in that case.

## Intelligence Flow

Fixture workflow:

```text
GET  /api/v1/fixtures/upcoming
GET  /api/v1/fixtures/{fixture_id}
GET  /api/v1/fixtures/{fixture_id}/evidence
POST /api/v1/fixtures/{fixture_id}/refresh
GET  /api/v1/fixtures/{fixture_id}/odds-snapshots
POST /api/v1/fixtures/{fixture_id}/odds-snapshot
POST /api/v1/fixtures/{fixture_id}/analyze
```

The strict betting engine remains the only source of verdict, expected value,
edge, and Quarter-Kelly stake sizing. UCL fixtures cannot become
`HIGH_CONVICTION`. Raw Kelly math is internal audit detail and is not returned by
public backend schemas or frontend TypeScript contracts.

Only critical gaps force a `PARTIAL` verdict: missing/invalid required model probabilities, unresolved fixture identity, missing coherent 1X2 market data for value analysis, or stale required inputs. Advisory gaps and risks such as provisional lineups, optional injury context, or low-confidence contextual signals may reduce confidence or hold promotion, but they do not trigger `PARTIAL` by themselves. Conflicting source evidence remains fail-closed and is reported separately from critical gaps.

The unified full-analysis route has a typed Pydantic/OpenAPI response. Consumers
must use `prediction_status`, `prediction_source`, `probabilities_available`,
`evidence_quality`, `effective_kelly_cap`, and `stake_permitted`. The legacy
`data_gaps` field remains an alias of `evidence_quality.all_gaps`, and
`ensemble.confidence` remains a deprecated alias of
`ensemble.top_outcome_probability`. Diagnostic/default-vector baselines are
never official probabilities and cannot produce edge or stake output.

Effective public stake caps are resolved from `LeaguePolicy`: 4% for the five
calibrated domestic leagues, 2.5% for pending-calibration Eredivisie, and 2% for
UCL, all beneath the 5% global ceiling. Public sizing remains Quarter-Kelly.

Market rules:

- Analysis uses one bookmaker's coherent 1X2 snapshot.
- Manual odds require explicit user confirmation and one bookmaker.
- Cross-bookmaker comparison is display-only.
- Missing or conflicting evidence returns a pass/partial state.

## Web

`apps/web` must not call provider hosts directly and must not import TensorFlow.js for production inference/training. Next.js server routes proxy the backend using `SABISCORE_BACKEND_URL`. The browser-side TensorFlow.js modules (`lib/ml/`) and their unreachable demo components have been removed from the tree entirely â€” `/dev/train-tfjs` is a static disabled-state page with no client-side model code behind it.

The `/intelligence` UI includes competition selection, team autocomplete, date filtering, fixture cards, readiness rail, odds auto-fill candidates, manual fallback, decision card, model-vs-market comparison, evidence passport, price window, source comparison drawer, and outage states.

Language must remain quiet and analytical. Do not add promotional betting copy.

The certified match dashboard renders backend-returned probabilities, edge,
expected value, Quarter-Kelly sizing, critical gaps, advisory gaps, conflicts,
and decision identifiers. It must not recompute official verdicts, expected
value, or stake sizing in the browser. Do not expose `NEXT_PUBLIC_KELLY_FRACTION`
or any provider credential to the web bundle.

Match-analysis proxies wait at most 25 seconds upstream. Clients use a 28-second
total budget with one infrastructure retry, then require manual retry. HTTP 500
is classified as `backend_internal_error`; cold-start copy is reserved for
explicit cold-start responses or recognized 502/503/504 wake-up conditions.
Readiness and provider configuration/enabled/live states share one platform
health view model. Freshness failures render `UNAVAILABLE`, `FETCH_FAILED`, or
`UNKNOWN` rather than an empty list or inferred percentage.

## Scraper Boundaries

`apps/scraper` may acquire permitted open/batch data, write immutable raw snapshots, produce processed files, write manifests, and validate parsers. It must not calculate predictions, verdicts, EV, Kelly stakes, or user-facing decisions.

## Release Gates

```bash
make verify
```

The target runs:

- secret/public-provider scans and database migration hardening checks;
- provider gateway tests;
- backend regression tests;
- provider CLI doctor;
- scraper tests;
- web lint;
- web typecheck;
- web tests;
- web build.

Additional deployment gates:

- Alembic upgrade against a fresh database;
- OpenAPI validation;
- Docker Compose config/build validation;
- Playwright desktop/mobile `/intelligence` smoke where browser tooling is available.

Canonical Linux CI execution (required before release decision):

```powershell
pwsh -File scripts/run-canonical-ci.ps1 -Branch master
```

This invokes and watches `.github/workflows/ci.yml` end to end. Treat any non-`success` conclusion as a hard release blocker.

Readiness probe behavior:

- `GET /health/ready` fails closed on core dependencies only: database, Alembic head, external-cache readiness policy, and strict model load.
- The capability probe is additive and now runs only after those core checks are green. A `503` readiness response no longer triggers odds-provider reads or prediction-path warmups.
- The root route now accepts both `GET /` and `HEAD /` so platform probes do not generate avoidable `405 Method Not Allowed` noise during startup.

Latest local Phase 1-2 evidence on 2026-07-05:
- `python -m src.cli providers doctor` and `providers status` passed in offline
  mode with the five-state public contract and no credential values printed.
- `..\.venv\Scripts\python.exe -m pytest tests/test_zero_fabrication_contract.py tests/unit/test_feature_transformer.py -q --no-cov`
  passed (`7 passed`). `FeatureTransformer` now fails closed by default in
  production inference and raises `DataUnavailableError` for missing required
  feature evidence; legacy defaults require explicit `allow_legacy_defaults=True`
  in training/backcompat callers.
- `..\.venv\Scripts\python.exe -m pytest tests/test_betting_intelligence_engine.py tests/test_core_engine.py -q --no-cov`
  passed (`82 passed`).
- `pnpm --filter @sabiscore/web typecheck` passed.
- `pnpm --filter @sabiscore/web lint` passed.
- `pnpm --filter @sabiscore/web test` passed outside the sandbox (`11 passed`)
  after the sandboxed run failed with esbuild `spawn EPERM`.
- `pnpm --filter @sabiscore/web build` passed outside the sandbox after the
  sandboxed run failed with Next worker `spawn EPERM`.
- `PYTHONPATH=. python scripts/verify_openapi.py` passed with 78 paths.
- `docker compose -f docker-compose.prod.yml config --quiet` passed. Docker
  image builds were retried outside the sandbox; Buildx lock access was resolved,
  but backend/web image builds are still blocked by Docker daemon DNS failures
  while fetching Debian/Alpine packages.
- `pnpm exec playwright test` ran outside the sandbox with `16 passed, 6 failed`;
  failures were backend-dependent tests because the local backend health endpoint
  returned `degraded` under host memory pressure. The release-relevant targeted
  `/intelligence` smoke passed: `pnpm exec playwright test tests/e2e/intelligence.spec.ts`
  (`4 passed`, chromium + mobile-chrome).
- `alembic upgrade head` and `alembic check` are still blocked until a valid
  PostgreSQL `DATABASE_URL` is available in the release environment.
- Branch cleanup is blocked: PR #4 from `codex/final-production-certification`
  to `master` is open, unmerged, and not mergeable. Bundle backups for all
  non-master remote branches were created under
  `artifacts/branch-backups/20260705-000338/`.

Do not merge a certification branch directly if it is stale against `master` or
contains unrelated broad churn. Port verified fixes onto current `master`, then
run the full release matrix before tagging the release.

## Rollback

1. Disable optional provider flags first.
2. Keep the backend up so the web app can render fail-closed outage states.
3. Roll back database schema only with reviewed Alembic downgrade or forward-fix migration.
4. Re-run `python -m src.cli providers doctor` and `make verify` before restoring traffic.

## vΩ.33 Identity deploy, capability readiness, season calendar (2026-08-04)

Backend data-truth release. Verdict, Kelly, edge, EV, and evidence-gating logic
are unchanged. Requires a backend redeploy (Alembic `0004_normalize_match_season`).

### Deploy verification is now a required step, not an assumption

The full WP-0/1/1.0/2/3.1 identity campaign was complete, tested, and committed
while `origin/master` was four commits behind — production ran pre-fix code and
every live probe still reproduced the original defect. Before concluding that a
reported bug is unfixed, confirm what is actually deployed:

```bash
git rev-list --left-right --count origin/master...master   # expect 0<TAB>0
curl -fsS "$BACKEND_PROD_URL/health/ready" \
  | python -c "import json,sys;d=json.load(sys.stdin);print(d['checks']['migrations']['head'])"
curl -fsS https://web-git-master-oversabis-projects.vercel.app/api/health \
  | python -c "import json,sys;print(json.load(sys.stdin)['sha'])"
curl -fsS https://web-lac-theta-42.vercel.app/api/health \
  | python -c "import json,sys;print(json.load(sys.stdin)['sha'])"
```

The two Vercel SHAs must match each other and local HEAD. **The production alias
does not auto-promote** — when the branch alias is ahead, promote the latest
READY deployment in the Vercel dashboard, or production keeps serving old code.

### Readiness now carries a capability probe

`GET /health/ready` returns a `capability` object alongside `checks`:

```json
"capability": {
  "status": "verified | unverified_no_fixtures | failed",
  "message": "...", "match_id": "...", "league": "...",
  "checked_at": "...", "cache_hit": true
}
```

`checks` remains pure component liveness (database, migrations, cache, models).
`capability` runs the real pipeline (`get_full_analysis()`) against the next
upcoming fixture in a required league, cached 15 minutes so keepalive traffic
does not re-run inference. It is intentionally **excluded** from `status` and
from the HTTP 503 decision: a model-path failure on the single free-tier dyno
must not remove the service from rotation.

Operationally, `unverified_no_fixtures` is a normal state — it means no required
league has a fixture inside the 7-day horizon (off-season, or only unsupported
competitions synced). It is not an outage and the UI must not render it as one.

### Season-start dates come from one provider-verified table

`backend/src/core/season_calendar.py` is the single source of truth, verified
against football-data.org `GET /v4/competitions/{code}` → `currentSeason.startDate`.
`upcoming_matches.py`, `leagues.py`, and `offseason.py` all import it. Do not
add a local copy — the three previous copies drifted up to 14 days early:

| League | Was | Verified 2026-08-04 |
|---|---|---|
| EPL | 2026-08-08 | 2026-08-21 |
| La Liga | 2026-08-15 | 2026-08-16 |
| Bundesliga | 2026-08-21 | 2026-08-28 |
| Serie A | 2026-08-23 | 2026-08-23 |
| Ligue 1 | 2026-08-08 | 2026-08-22 |
| Eredivisie | 2026-08-07 | 2026-08-07 |
| UCL | 2026-09-15 | estimate — 2026/27 unpublished |

Re-verify at the start of each season with:

```bash
curl -H "X-Auth-Token: $FOOTBALL_DATA_API_KEY" \
  https://api.football-data.org/v4/competitions/PL \
  | python -c "import json,sys;print(json.load(sys.stdin)['currentSeason']['startDate'])"
```

Free tier is **10 requests/minute** — probing all seven competitions twice in
one script will trip HTTP 429.

### Fixture-sync coverage caveat

`sync_upcoming_fixtures` requests a 7-day window across all seven competitions
and truncates to 50 by kickoff order. Ahead of a staggered season opening, only
the earliest-starting competition has fixtures, so `teams` is seeded for that
league alone and matchups typed for other leagues cannot resolve identity yet.
That is honest fail-closed behaviour, not a defect — the remaining leagues seed
themselves as their windows open. Confirm with:

```bash
curl -fsS "$BACKEND_PROD_URL/api/v1/fixtures/upcoming?limit=200" \
  | python -c "import json,sys,collections;d=json.load(sys.stdin);print(collections.Counter(f['competition'] for f in d['fixtures']))"
```

## vΩ.31 Loading/results parity and unverified-claim scrub (2026-07-30)

Presentation layer only. No provider, model, verdict, Kelly, evidence-gating, or
migration behaviour changed, so no backend redeploy is required by this release.

- The match loading interstitial no longer applies `p-4` on top of the root
  `<main>`'s `px-4 py-5 sm:px-6 lg:px-8`. Loading content previously sat 16px
  narrower per side than the results page and jumped wider on load. Container
  parity is now **four** things that must agree: the live container, the SSR
  skeleton, the `match-selector.tsx` overlay wrapper (the one usage site with no
  `<main>` ancestor, which therefore keeps its own `py-4`), and whatever padding
  the parent already supplies.
- The match selector footer no longer asserts **Live Data · 5 Providers
  Configured**. It reads the same `derivePlatformHealth` source the header pill
  uses and reports real `N of M providers enabled`, amber unless all configured
  providers are enabled. Operators verifying activation should now see identical
  counts in the header and the selector footer — a mismatch means a stale
  deployment, not two different measurements.
- The ensemble card no longer pairs "Diagnostic baseline values are not
  displayed" with a description of that suppressed value's shape.
- Team dropdowns now exclude the team already chosen on the other side.
- Executed checks: web lint 0, typecheck 0, **78 Vitest tests**,
  `NODE_ENV=production` build passed, prohibited-copy scan 0 real hits. Route
  weights unchanged (`/match` 208 kB, `/match/[id]` 158 kB).

Release decision remains **`NOT SAFE FOR PRODUCTION`** — unchanged by this
release and still gated on the operator items listed under Known Limitations.

## vΩ.30 Readiness clarity and build-path recovery (2026-07-29)

- The web readiness ring now says **Core ready**, **Core partial**, or **Core
  unavailable**. It measures only the backend's four infrastructure checks:
  database, migrations, cache, and model artifacts. It is not a claim that the
  real-data provider pipeline is active.
- The provider pill now shows `N of M enabled` and stays amber unless every
  configured provider is enabled. This preserves the distinction between
  configuration, enablement, and quota-aware live verification.
- The production backend Docker stage no longer copies the development stage.
  It copies `src/` and performs the one full requirements installation that
  production actually needs; the local development stage is unchanged.
- Executed checks for this checkpoint: health-status regression suite 14/14,
  web lint/typecheck, 72 Vitest tests, the production build, and `docker build
  --check` with no Dockerfile warnings. `CachedLogo` no longer forwards the
  unsupported `fetchPriority` prop to a raw image, removing the React warning
  previously emitted by the loading-layout test.
- Current live status remains **2 enabled / 5 configured**, both Vercel aliases
  are aligned at `43058a6`, and `sabiscore.com` DNS is unresolved. These are
  external activation conditions, not code fallbacks.

Release decision remains **`NOT SAFE FOR PRODUCTION`** until the existing
operator-controlled activation and release gates have direct evidence.

## vΩ.29 Certification Recovery (2026-07-28)

- `ModelRegistry.walk_forward_validate()` now passes an integer outcome to the
  RPS metric and validates outcome/probability inputs before scoring. The result
  schema is unchanged. Six isolated synthetic regression tests pass.
- A live walk-forward result is not certified yet. It requires completed
  in-season predictions plus a reviewed join from `MatchPredictionLog` to final
  match scores. Until then the live gate is explicitly waived/conditional, not
  represented as validated.
- Live infrastructure after warm-up: Render readiness `ok`; database,
  migration, cache, and Phase 7 model checks ready; both Vercel aliases at
  `f33b5ab`.
- Provider activation is incomplete: ESPN and football-data.org are enabled;
  API-Football, Sportmonks, and The Odds API remain configured but disabled
  until the Render Blueprint environment sync is approved. Probe
  `/api/v1/providers/health`; `/api/v1/providers/status` is not a current
  backend route and returns 404.
- `sabiscore.com` is attached to the Vercel `web` project. The registrar must
  set the apex `A` record to `76.76.21.21`; domain verification and HTTPS remain
  pending until DNS propagates.
- Upstash Redis rotation and the Render non-sleeping-plan upgrade are mandatory
  operator gates. Do not run new credential-dependent production probes or
  declare production readiness until both are confirmed.
- Docker Desktop and Kubernetes recovered, but the VM currently exposes about
  4 GB RAM. Production Compose validation passes, and a disposable local
  PostgreSQL database upgrades to `0003_team_reconciliation` with no Alembic
  drift. Both production image builds timed out after 15 minutes: the backend
  verify tag remained an older 2026-07-15 image, and no web verify image was
  created. Increase Docker Desktop to the supplied 6–8 GB recommendation and
  rerun both image gates.
- Current local release evidence: Ruff 0; focused RPS 6/6; full backend
  972 passed / 13 skipped; web lint 0, typecheck 0, Vitest 70/70, production
  build passed; prohibited-copy scan 0; Gitleaks clean; targeted Playwright
  4/4; scraper tests 6/6 with manifest validation `ok:true`.
- GitHub Actions is still not executing jobs. Canonical CI, secret scan,
  large-file, and scheduled keep-alive runs complete as failures with zero
  steps and no runner log. Treat local evidence as the only executed evidence
  until the account-level Actions block is cleared.

Release decision at this checkpoint: **`NOT SAFE FOR PRODUCTION`**.

## vΩ.28 Changes (2026-07-28)

- **Training-data figure corrected from "10.7k+" to 1,752 (zero-fabrication).**
  The authoritative source is each artifact's own
  `model_metadata.training_samples`, not any document: EPL 380, La Liga 380,
  Serie A 380, Bundesliga 306, Ligue 1 306. Those are exactly one season per
  league. Re-derive this number from the artifacts if it ever needs restating —
  never copy it forward from a doc or a previous UI string.
- **Two unverifiable refresh cadences removed.** "Predictions refresh every 3
  hours" (`best-bet-spotlight.tsx`) had no matching Celery beat entry and
  contradicted the component's own 5-minute `staleTime`; "Live enrichment every
  180 s" (docs page) matched nothing in `apps/web`. Both replaced with claims
  the code actually supports. The unsourced "(industry avg ~0.23)" comparative
  was dropped; the `<=0.21` RPS gate itself is real and retained.
- **`RLCard` no longer prints a reward decomposition for an unsized stake.**
  On an abstention the backend emits all-zero reward components plus a constant
  `R_abs`, and the existing `.slice(0, 4)` truncated away that one non-zero
  term. Grid is now gated on `!rec.abstain && stakePermitted`.
- **`OffseasonDataAvailability` now matches the backend.** The interface, both
  `lib/api.ts` fallback literals, and the route's `unknownFallback()` used five
  field names with zero overlap against
  `backend/src/api/endpoints/offseason.py` `_data_availability()`. Corrected to
  the real eight (`historical_data`, `live_odds`, `live_standings`,
  `live_form`, `pi_ratings`, `berrar_ratings`, `market_drift`,
  `match_context`), fallbacks unified to all-`false`.
- **Beginner-friendly explainers added to the match dashboard**, reusing the
  existing `KellyTooltip`/`EdgeTooltip`/`Tooltip` components and, for the
  uncertainty terms, `uncertainty-display.tsx`'s existing copy verbatim.
- **Shared `Tooltip` is now keyboard-reachable** (`onFocus`/`onBlur`,
  `tabIndex`, `role="tooltip"`, `aria-describedby`), fixing WCAG 2.2 SC 1.4.13
  for every caller at once.
- **Gates:** ruff 0 · pytest 966 passed / 13 skipped · web lint 0 · typecheck 0
  · Vitest 70/70 · `NODE_ENV=production` build ✓ · copy scan clean.
- **Still operator-blocked:** Render blueprint env sync for the three disabled
  providers, Upstash Redis credential rotation, and `sabiscore.com` DNS.

## vΩ.27 Changes (2026-07-28)

- **Off-season context now surfaces before submission on the match selector.**
  `match-selector.tsx` previously let a user submit any hypothetical matchup
  and only learn it was off-season from the full-analysis page's "4 critical
  gaps / No bet" teardown. It now renders the existing `LeagueOffseasonNotice`
  above the Home/Away inputs, scoped to the currently selected league, as soon
  as a new `useQuery` (`getOffseasonStatus(canonicalLeagueId(league) ?? league)`)
  reports `season_status: "OFF_SEASON"`. Non-blocking — silent during
  loading/error/in-season/unknown-league. No backend or `handleSubmit` changes;
  no new component.
- **First production caller of `getOffseasonStatus`, so it was live-verified.**
  The function had zero callers before this change. All three probes returned
  correct, distinct per-league dates: `EPL` → `2026-08-08` (11 days),
  `LA_LIGA` → `2026-08-15` (18 days), `UCL` → `2026-09-15` (49 days). Canonical
  and display vocabularies both resolve (the backend `_normalise_league` folds
  either), but canonical is sent per the vΩ.26 boundary rule. Cold first
  request took 21–30s (cold Vercel function + cold Render dyno), 0.8s once the
  1h edge cache was warm.
- **Why this endpoint over the fixtures list.** `/api/offseason/[league]` is
  edge-cached 1h and does zero prediction work; `/api/upcoming` defaults
  `include_predictions=true` and would compute a prediction for one fixture
  just to read a boolean, on every league switch once the season resumes.
- **Pre-existing type drift flagged, not fixed.** `OffseasonDataAvailability`
  in `lib/api.ts` does not match the live backend response shape
  (`historical_results/elo_ratings/...` vs `historical_data/live_odds/...`);
  reading `data_availability.*` returns `undefined` while TS claims `boolean`.
  This change does not read that field — correct the interface before anything
  does.
- **`make verify` gate 9 now pins `NODE_ENV=production`.** The recipe ran a
  bare `pnpm --filter @sabiscore/web build`, so it inherited whatever
  `NODE_ENV` the caller's shell exported. With `NODE_ENV=development` set,
  `next build` fails at the `/404` prerender with the misleading
  `<Html> should not be imported outside of pages/_document` error — the
  footgun already documented in `CLAUDE.md`, but which the release gate itself
  did not defend against. This made `make verify` fail spuriously on a clean
  tree, which matters more than usual right now: with GitHub Actions
  billing-locked, `make verify` is the only enforced gate. Standalone
  `NODE_ENV=production pnpm --filter @sabiscore/web build` was green
  throughout.
- **⚠️ Never judge a gate through `| tail`.** The first `make verify` run this
  session was piped to `tail -40`, which reported exit code 0 while the run had
  actually failed at gate 9 — the same pipe-masking trap recorded for the
  Docker gate in vΩ.15. Redirect to a file and check `$?` instead.
- **Verification.** Backend regression check: ruff 0, pytest 966 passed / 13
  skipped (unchanged). Web lint 0, typecheck 0, Vitest 62/62,
  `NODE_ENV=production` build ✓ (`/match` bundle unchanged at 207 kB),
  Playwright 4/4, copy scan 0 new hits, Gitleaks clean.
- **Operator checklist re-verified.** GitHub Actions billing lock (vΩ.20) is
  still active — `gh run list` shows the last 5 runs, including all recent
  "Keep-alive ping" schedules, completing as failures in 4–10s (a runner that
  never boots, not a real execution). This explains an observed
  `FUNCTION_INVOCATION_TIMEOUT` on the first `/api/upcoming` request of the
  session (cold Vercel function + cold Render backend, since the automated
  warm-up isn't running); every request after the first succeeded in
  1.8–3.9s. Render provider flags unchanged: `api_football`/`sportmonks`/
  `the_odds_api` remain `configured:true, enabled:false` pending operator
  approval of the blueprint env sync in the Render dashboard.

## vΩ.26 Changes (2026-07-27)

- **League vocabulary unified — every non-EPL match page was returning HTTP 400.**
  `/match/<matchup>?league=La Liga` rendered "Intelligence unavailable — A valid
  matchId and league are required". Two league vocabularies coexist in `apps/web`
  and both are load-bearing: the display form (`"La Liga"`, `"Serie A"`,
  `"Ligue 1"`) keys the team lists, logo resolver, and colour maps, while the
  canonical form (`LA_LIGA`, `SERIE_A`, `LIGUE_1`) is what the sidebar and the
  proxy schemas speak. The match selector emitted the display form; the
  full-analysis proxy's enum accepted only the canonical form and rejected the
  request before it reached the backend. The backend was never at fault — its
  `canonical_league_id` already accepts either spelling.
- **EPL masked the defect.** It is the one league both vocabularies spell
  identically, so all prior EPL-based verification passed. When validating any
  league-related change, test a non-EPL league.
- **`apps/web/src/lib/league.ts`** provides `canonicalLeagueId()`, mirroring
  `backend/src/core/league_policy.py` rule-for-rule so the two cannot drift. It
  is applied at the proxy boundary (`full-analysis`, `insights`,
  `phase8-features`) — which also rescues links already in circulation and
  backend-supplied league values — and at the source (match selector navigation,
  `/match/[id]` search params). Unsupported leagues still fail closed with 400;
  the supplementary `phase8-features` panel degrades to EPL instead.
- **Validation.** Verified against the live backend: `?league=La Liga` went
  400 → 200 with `effective_kelly_cap: 0.04` (the correct calibrated-league
  policy). Web lint 0, typecheck 0, Vitest 62/62, `NODE_ENV=production` build ✓,
  Playwright 4/4, Gitleaks clean. Backend untouched.

## vΩ.25 Changes (2026-07-27)

- **Loading interstitial matches the results container.** The `/match/[id]` loading
  screen rendered at 672 px while the results page uses `max-w-6xl` (1152 px), so
  the layout snapped ~480 px wider when the analysis landed. The interstitial now
  uses `max-w-6xl` and splits into a two-column grid above the `lg` breakpoint so
  the extra width carries the engagement cards instead of stretching one column.
  The SSR skeleton and the `match-selector` overlay wrapper were updated to match —
  all three must stay in sync or the screen shifts at hydration.
- **Retry no longer reloads the document.** "Retry now" on the match page called
  `window.location.reload()`, which discarded the 6-layer analysis and Phase 8
  sections that load independently and were rendering correctly. It now calls
  `router.refresh()` inside a transition, re-running only the page's server
  components while the sibling sections stay mounted.
- **Dead surface removed.** `apps/web/src/components/MatchDashboard.tsx` (369 lines,
  zero importers) rendered the superseded `CertifiedMatchAnalysis` contract replaced
  by `full-analysis-dashboard.tsx` in vΩ.18. The `analyzeCertifiedPrediction` client
  helper in `lib/api.ts` is now unused but retained deliberately: it wraps the live
  `/api/v1/predictions/analyze` endpoint, so its removal is a separate decision
  about that endpoint's status.
- **`/match` first-load JS 214 kB → 207 kB** by loading the interstitial through
  `next/dynamic` (`ssr: false`); it only renders after a matchup is submitted.
- **Validation.** Web lint 0, typecheck 0, Vitest 58/58, `NODE_ENV=production`
  build ✓, Playwright 4/4, Gitleaks clean. Backend untouched.
- **Operational note.** A `backendStatus: unavailable` reading during this session
  was a Render free-tier cold start (11.5 s to `/health/ready`), not a fault. The
  14-minute GitHub Actions keepalive remains dark under the billing lock, so first
  request after idle will continue to pay that cost until an external pinger is
  configured.

## vΩ.24 Changes (2026-07-27)

- **Reduced-evidence surfaces no longer display neutral defaults as measurements.**
  The match dashboard rendered `Home Elo 1500 / Away Elo 1500 / Elo Diff +0` and a
  `CI [0.0%, 0.2%]` credible interval for fixtures whose analysis was an explicit
  reduced-evidence baseline with no probabilities. Those figures are backend
  placeholders (`_elo_from_features` defaults to 1500), not observations. Both now
  render `—` with a short reason. Epistemic/aleatoric uncertainty remains visible,
  since 100% epistemic is a meaningful statement about evidence.
- **Freshness copy disambiguated.** The prediction-age indicator said "Fresh" next
  to an evidence-freshness pill reading "Unknown". It now says "Analyzed just now" /
  "Analyzed {n}m ago", making clear it describes the analysis, not the data.
- **`/performance` first-load JS reduced 232 kB → 127 kB** by loading
  `RollingAccuracyChart` (recharts) via `next/dynamic` with `ssr: false`. This closes
  the deferred bundle item from the vΩ.17 backlog. Use the same pattern for any new
  chart surface.
- **Validation.** Web lint 0, typecheck 0, Vitest 52/52, `NODE_ENV=production`
  build ✓, Playwright 4/4. Backend untouched.

## vΩ.23 Changes (2026-07-27)

- **Phase-7 insights now fail closed.** `POST /api/v1/insights` previously returned
  HTTP 200 with fabricated probabilities, a fabricated 1X2 book, and an uncapped
  35%-of-bankroll Kelly stake whenever required evidence was absent — the
  off-season default. `FeatureTransformer` raised `DataUnavailableError` correctly,
  but `insights/engine.py` swallowed it and substituted a `FEATURE_DEFAULTS`
  vector. The engine now re-raises, and the endpoint returns **HTTP 422 with
  `error_code: INSUFFICIENT_EVIDENCE`**, matching the `predictions.py` precedent.
  Operators should expect 422 from this endpoint for any fixture without verified
  form, head-to-head, and market evidence — including throughout the summer break.
- **Insights Kelly sizing is now policy-capped.** `value_analysis.bets[].kelly_stake`
  is a bankroll **fraction** (Quarter-Kelly, capped by `LeaguePolicy.kelly_cap`:
  4% for the five calibrated domestic leagues, 2.5% Eredivisie, 2% UCL) and is
  schema-bounded at `le=0.05`. It was previously a currency amount computed at
  half-Kelly against a hardcoded 100-unit bankroll with no cap.
- **No default odds book.** `data/aggregator.py` and the engine's fallback match
  data no longer substitute `{2.0, 3.2, 3.5}` when a market cannot be fetched; they
  return an empty book and value analysis is skipped, consistent with the
  full-analysis surface's "market unavailable" behaviour.
- **`/match/[id]` insights panel repaired.** The page had never rendered insights in
  production: its server component fetched the relative path `/api/insights`, which
  a Node server component cannot resolve, and the resulting error was misclassified
  as `unknown` ("We hit a snag"). The fetch moved to a server-only module that calls
  the backend directly via `SABISCORE_BACKEND_URL`. A new `insufficient_evidence`
  error state renders the 422 case as an amber, non-alarming card with no retry
  action.
- **Providers health pill.** The header no longer reports an `X/Y live` count.
  `VERIFIED` requires `PROVIDER_LIVE_TESTS=true`, which production keeps false, so
  the count was structurally always zero and displayed a permanent false outage. It
  now reads `N enabled · M configured`.
- **Validation.** Backend pytest 966 passed / 13 skipped / 0 failed, ruff 0. Web
  lint 0, typecheck 0, Vitest 49/49, `NODE_ENV=production` build ✓, Playwright
  `/intelligence` 4/4 (chromium + mobile-chrome), Gitleaks filesystem scan clean.

## vΩ.22 Changes (2026-07-25)

- **Insights panel timestamp coherence.** `apps/web/src/components/insights-display.tsx`
  formatted its two "Generated" timestamps with bare browser-local
  `toLocaleString()` — no timezone, no semantic markup — while the canonical
  full-analysis footer already used `<time dateTime=…>` + an Africa/Lagos (WAT)
  absolute. Both insights sites now reuse the exported `formatLagosTimestamp()`
  and render `<time dateTime={…}>… WAT</time>`. This closes the one live
  cross-surface timestamp drift on `/match/[id]`; it adds no helper and no
  dependency.
- **Production-finalization re-verification (no code change beyond the above).**
  The CODEX finalization directive's 14 defect hypotheses were re-checked against
  HEAD; 13 were already implemented in vΩ.17/vΩ.18 and were **not** re-built.
  Two hypotheses were verified as *incorrect for this codebase* and deliberately
  left unchanged:
  - The Phase-7 insights `confidence` field is the model's confidence scalar (or a
    `0.50` baseline sentinel), **not** max-class-probability
    (`backend/src/insights/engine.py` `_forecast_match_outcome`). Relabelling it
    "Top probability" would have been a regression. The screenshots' 33.4%
    "confidence" came from the full-analysis fallback `max(h,d,a)`, already
    relabelled "Top outcome probability" in vΩ.18. Off-season the insights
    endpoint returns HTTP 422 (zero-fab guard), so the confident tile is not
    rendered at all.
  - `MAX_KELLY = 0.025` does not exist in `apps/web`. The RL gauge scales to
    `0.05` (`settings.rl_max_kelly_cap`, distinct from the value-bet league caps)
    and the canonical Kelly gauge reads the backend `effectiveKellyCap`.
- **Validation.** Web lint 0, typecheck 0, Vitest 47/47, responsible-gambling
  copy scan 0 hits, `NODE_ENV=production` build ✓. Backend untouched (ruff 0,
  pytest 962/962, gitleaks clean earlier the same cycle). Live probes: backend
  `/health/ready` `status: ok`; `/api/v1/upcoming/matches` `offseason: true`,
  `total: 0`, `next_season_start: 2026-08-08`.

## vΩ.21 Changes (2026-07-24)

- **Full-analysis contract null-parse fix (the real `/match` error).** The web
  match page showed "We hit a snag" + "Intelligence unavailable — The backend
  returned an invalid full-analysis contract" for hand-typed off-season matchups.
  Live-first diagnosis proved this was **not** a stale deployment (the preview was
  at HEAD `25bafbe`) and **not** a backend fault (HTTP 200, well-formed
  `REDUCED_EVIDENCE_BASELINE` contract). The frontend Zod schema
  (`apps/web/src/lib/full-analysis-contract.ts`) typed `phase9_shadow_only` as
  `.optional()` (rejects `null`), while the backend legitimately returns `null`
  for that field whenever phase9 is inactive — the production default. One field's
  `null` failed the whole parse. Fixed to `.nullable().optional()` to match the
  backend's `Optional[bool] = None` and the already-correct sibling
  `phase9_candidate_features`. Regression test added; web vitest 47/47, typecheck
  and lint clean; the captured live response now parses cleanly. This affected
  every analysis while phase9 is off, not only the off-season break.
- **CI copy-scan self-match fixed.** `.github/workflows/ci.yml`'s responsible
  gambling copy scan now excludes `*.test.*`/`*.spec.*` files, so it no longer
  flags `copy-contract.test.ts`'s own prohibited-term regex literal — a latent
  `web-quality` failure that would fire once the Actions billing lock clears.
- **CORS regex staleness noted, not changed.** `render.yaml` `CORS_ORIGIN_REGEX`
  still targets the deleted `sabiscore*` project prefix. It is moot for production
  (same-origin proxying; no browser-side direct-to-backend fetch is mounted) and
  was deliberately left alone; fix it to a `web*` pattern only when such a fetch is
  activated.

## vΩ.20 Changes (2026-07-24)

- **Production cutover verified.** A fresh Vercel production deploy of `master`
  (`web-7zrnnpsbk`, aliased `https://web-lac-theta-42.vercel.app`) is live and
  supersedes the stale `web-15ykeatxv` snapshot behind the vΩ.19 screenshots.
  Live `/api/health` returns `"sha": "fd4949e"` (the deploy-parity stamp works),
  `backendStatus: ok`, and all four readiness checks ready. Stale-deployment
  bugs are now diagnosable in a single `/api/health` probe.
- **Legacy Vercel projects decommissioned.** `sabiscore` (the pre-vΩ.8
  `sabiscore-d37gxx4gs` UI) and `sabiscore-web` were permanently deleted via
  `vercel project rm`. `web` is the sole remaining Vercel project.
- **Keepalive cron downgraded; a warm-up workflow already exists.** Vercel Hobby
  rejects sub-daily crons at deploy time, so the vΩ.19 `*/10 * * * *` schedule
  **blocked every production deploy**; `vercel.json` is now `0 9 * * *` (daily).
  The sub-15-minute warm-up is the pre-existing `.github/workflows/keep_alive.yml`
  (every 14 min → `scripts/keep_alive.py` → `BACKEND_URL/health/ready` with
  latency telemetry) — no new workflow was needed.
- **⚠️ BLOCKER — GitHub Actions account billing lock.** Every recent Actions run
  (`CI - Canonical Platform`, `Secret Scan`, `Block large files`, `Keep-alive
  ping`) fails to start with *"The job was not started because your account is
  locked due to a billing issue."* The runner never boots. Consequently **no CI
  gate has actually executed on recent pushes and the keepalive does not run.**
  Operator actions, in order:
  1. Resolve the GitHub billing issue (unlocks CI + keepalive together).
  2. Set repo secret `BACKEND_URL=https://sabiscore-api-bav1.onrender.com`
     (server-side; the `keep_alive.py` script reads it).
  3. Billing-independent fallback: point a free external pinger (cron-job.org /
     UptimeRobot) at `https://sabiscore-api-bav1.onrender.com/health/ready` every
     10–14 minutes.
  Until the lock clears, local `make verify` is the only enforced gate.
- **CORS regex wired + production origins.** `backend/src/api/middleware.py` now
  passes `allow_origin_regex=settings.cors_origin_regex or None` to
  `CORSMiddleware`; the `CORS_ORIGIN_REGEX` value was configured but never
  applied, so Vercel preview URLs failed CORS. `render.yaml` `CORS_ORIGINS` adds
  `https://sabiscore.com` and `https://web-lac-theta-42.vercel.app`.
- **Reloading results page — manual retry only.** `insights-error-state.tsx`
  dropped its dead auto-reload countdown (`MAX_AUTO_RELOADS = 0` since vΩ.18 made
  it unreachable). The card no longer flashes a contradictory "Auto-retrying…" →
  "Auto-retry paused" sequence; recovery is an explicit "Retry now" button.
- **Loading screen sizing.** `match-loading-experience.tsx` widened from a fixed
  `max-w-lg` to `w-full max-w-lg sm:max-w-xl lg:max-w-2xl` (main card and SSR
  skeleton) so the interstitial no longer renders as a narrow strip that snaps to
  the `max-w-6xl` results layout. The unreachable `onExperienceComplete`
  completion effect was removed. `match-selector.tsx` corrected an unverifiable
  "Updated Every 5min" footer to "Fetched fresh per request".
- **Verification.** Web lint 0, typecheck clean, Vitest 46/46,
  `NODE_ENV=production` Next.js build ✓; Ruff clean on `middleware.py`; live
  probes: backend `/health/ready` 200 `ok`, web `/api/health` 200 `healthy` with
  the parity SHA.

## vΩ.19 Changes (2026-07-24)

- **Vercel keepalive cron registered.** `vercel.json` now declares
  `"crons": [{ "path": "/api/cron/ping-backend", "schedule": "*/10 * * * *" }]`.
  The route handler (`apps/web/src/app/api/cron/ping-backend/route.ts`, Edge
  runtime, 30 s timeout, GETs `BACKEND_URL/health/ready`) already existed; only
  the scheduler registration was missing. This keeps the Render free-tier
  backend warm, eliminating the 15-minute cold-start spindown that surfaces on
  first request as the "Engine Warming Up" retry state. **Operator action:** set
  `BACKEND_URL=https://sabiscore-api-bav1.onrender.com` (server-side, never
  `NEXT_PUBLIC_`) in the Vercel dashboard — distinct from `SABISCORE_BACKEND_URL`
  used by the proxy routes. *(Superseded in vΩ.20: the cron is now daily and the
  10-minute warm-up runs from GitHub Actions.)*
- **No UI/backend code change.** A live-first diagnostic (2026-07-24) confirmed
  the reported "errors" were a stale Vercel deployment (`web-15ykeatxv-…`,
  predating vΩ.17/vΩ.18) plus correct off-season fail-closed states
  (`offseason: true`, `total: 0`, `next_season_start: 2026-08-08`). Live backend
  `status: ok`, all four readiness checks ready. The loading screen (vΩ.14) and
  compact no-loop error state (vΩ.18) are already the fixed versions on `master`.

## vΩ.17 Changes (2026-07-20)

- **Readiness is infrastructure-backed.** The web `/api/health` route accepts the
  backend statuses `ok`, `ready`, and `healthy`; its global header ring aggregates
  database, migrations, cache, and models. Provider/source freshness remains a
  match/evidence concern and is not used as a global platform-readiness score.
- **Live performance is pending.** Public web surfaces do not advertise static
  accuracy, average-edge, completed live walk-forward, or Phase 8 production
  claims. Historical numbers are artifact benchmarks only. Live accuracy, Brier,
  ROI, and promotion claims remain pending until sufficient labelled results
  exist. Phase 8 stays shadow-only.
- **Fail-closed rollback.** Keep `PROVIDER_STRICT_QUOTA_MODE=true` and
  `PROVIDER_FAIL_CLOSED=true`. Diagnose with `/health/ready`,
  `/api/v1/providers/health`, and redacted service logs. If one provider is the
  fault domain, disable only its `ENABLE_*_PROVIDER` switch and restart; never
  relax the global fail-closed policy.

### Staged provider activation checkpoint

The Blueprint already declares the provider switches and secret names. Do not add
another adapter or duplicate environment wiring. The Render dashboard is the
operator checkpoint because this checkout has no Render CLI/API credentials.

1. Rotate the PostgreSQL password disclosed outside the secret store before any
   production or release-gate use. Update local and hosted secret stores without
   committing or logging the replacement.
2. Activate in order: API-Football, Sportmonks, then The Odds API.
3. Before each toggle, set an account-appropriate hard quota and retain
   `PROVIDER_STRICT_QUOTA_MODE=true` and `PROVIDER_FAIL_CLOSED=true`.
4. Restart, then call only the non-live `GET /api/v1/providers/health` endpoint.
   `enabled: true`, `configured: true`, and `CONFIGURED_UNVERIFIED` is the
   expected stage-one state. Do not spend live quota for off-season validation.
5. If the state is unexpected, disable only that provider and inspect redacted
   logs before continuing to the next stage.

### Verification evidence and deferred backlog

On 2026-07-20, web lint/typecheck passed, Vitest passed 30/30, the production
Next.js 15.5.19 build passed, and the desktop/mobile `/intelligence` Playwright
smoke passed 4/4. Focused backend provider/source tests passed 75/75. Live Render
reported `status: ok` with database, migrations, cache, and models ready; provider
health remained offline-safe; upcoming matches correctly returned `total: 0`,
`offseason: true`, and `next_season_start: 2026-08-08`.

Gitleaks filesystem mode passed with no current-tree leaks. Full-history mode
still reports two redacted legacy findings in historical `backend/.env.example`
commits; do not rewrite shared history as part of this maintenance release.

`make verify-core` is currently blocked in this Windows shell by missing `jq` and
POSIX `PYTHONPATH` recipe semantics. Full `make verify` additionally awaits the
newly rotated PostgreSQL credential; SQLite fallback and the disclosed credential
must not be used. Deferred work: the 232 kB `/performance` first-load bundle,
internal legacy `90%+` comments, and Phase 9 source-registry freshness plumbing.

## vΩ.14 Changes (2026-07-14)

- **`make verify` now uses the repo venv on Windows.** `verify-core`/`verify` invoked bare `python` and `alembic`, which in `make`'s bash subshell resolve to the system `C:\Python314` (missing numpy/pandas/email-validator) or fail `command not found` — never the project virtualenv. `PYTHON_BIN` now auto-detects `.venv/bin/python` (Unix) or `.venv/Scripts/python.exe` (Windows) and is `$(CURDIR)`-prefixed so the `cd backend &&` in recipes cannot break the relative path. Gates 1→3 pass locally (secret scan; 6/6 deterministic core; 945 backend tests, 13 skipped). Gate 4 (`alembic upgrade head && alembic check`) now resolves and invokes alembic — the remaining failure is the documented **needs a valid `DATABASE_URL`** limitation (set `DATABASE_URL`/`SABISCORE_DATABASE_URL` to the running Postgres before gate 4). Gates 5–14 still need Docker + browsers.
- **Transition/loading screen no longer spills over.** The `/match/[id]` route loading screen (`MatchLoadingExperience`, the default under `PREDICTION_INTERSTITIAL_V2`) self-imposed a `max-h-[calc(100vh-4rem)] overflow-y-auto` internal scroller keyed to a hardcoded 4rem header offset. The root shell actually stacks a sticky ~65px header + backend-status banner + `<main>` padding, so the card began ~85px down but was sized to nearly the full viewport — cutting off its footer/poll/swipe cards below the fold. Root `<main>` already scrolls with the window, so the trap was wrong and redundant; removed it (and from the SSR skeleton) so the screen flows like every other page. The in-page `match-selector` overlay still bounds the same component via its own outer `max-h-[calc(100vh-2rem)] overflow-y-auto`. Also removed an erroneous `useScrollLock` from the dormant `MatchLoadingInterstitial` fallback (it locked body scroll for an inline, non-modal route-loading component). Lint 0 / typecheck clean / `NODE_ENV=production` build ✓.

## vΩ.13 Changes (2026-07-14)

- **asyncpg naive/aware datetime sweep (live web paths).** `Match.match_date` is a naive `TIMESTAMP WITHOUT TIME ZONE` column, so asyncpg rejects a tz-aware `datetime.now(timezone.utc)` bound at bind time (`DataError: can't subtract offset-naive and offset-aware datetimes`) — even with an empty table. This was flooding the Render logs on `/api/v1/upcoming/matches` and `/api/v1/value-bet-scan`. Fixed the three **live, async, web-reachable** query sites by stripping tz with `.replace(tzinfo=None)` (the same convention `fixtures.py` + the vΩ.6 fixture-sync insert already use):
  - `services/upcoming_match_service.py` `_get_upcoming_matches_from_db()` (root of the log flood; its prediction-path exception fallback dict also now includes `avg_edge_pct`/`source` so it can't cascade a secondary Pydantic `ValidationError`);
  - `api/endpoints/matches.py` `/api/v1/matches/upcoming`;
  - `services/upcoming_match_feature_service.py` `project_match_features()` — the incoming `match_date` param is normalized at entry, covering the internal form/goals sequence queries that fire once real (tz-aware) API fixtures return in-season.
- **Deferred (same class, not in the deployed web `startCommand`):** `services/data_ingestion.py` (5 async sites, only started via `cli/start_ingestion.py`) and the sync-`SessionLocal()` Celery tasks in `tasks/background.py` (psycopg2, not asyncpg). Adopt the strip when that ingestion/worker deployable is next shipped.
- **Verification:** Ruff clean on edited files; `tests/unit/test_fixture_sync.py` + `tests/test_providers_gateway.py` → 15 passed; all edited files `py_compile` OK.

## vΩ.8 Changes (2026-07-13)

- **⚠️ DEPLOY BLOCKER — Render service suspended.** *(Resolved in vΩ.11: replaced by the live `sabiscore-api-bav1.onrender.com` service — see vΩ.11 section above.)* `https://sabiscore-api.onrender.com` returns an HTML "This service has been suspended" page (503) on every endpoint. All Vercel proxy 503s are downstream of this. Resume the service in the Render dashboard, then verify `GET /health/ready` → 200. Independently, `SABISCORE_BACKEND_URL` must be set in the Vercel project dashboard (proxies default to `http://localhost:8000` without it).
- **CSP `frame-src` added** — `middleware.ts` CSP now includes `frame-src 'self' https://vercel.live` so the Vercel preview toolbar iframe loads. `frame-ancestors 'none'` unchanged.
- **Transition screen zero-fabrication cleanup** — the match loading screens no longer invent data: fabricated per-team form/GF/GA/table-position cards replaced with labeled evidence-sync skeletons; fake poll community percentages removed (user's own pick only); fabricated "AI Confidence 77%" line removed; promotional profit/ROI facts removed; footer claim corrected. `LOADING_FACTS`/`FUN_FACTS` deduped into `apps/web/src/components/loading/loading-facts.ts`.
- **Loading screen a11y** — `useReducedMotion` disables infinite pulse/shimmer/particle animations; progress bars expose `role="progressbar"` with live `aria-valuenow`.
- **Bounded match-analysis retry policy** — general queries retain the shared React Query policy, while match analysis uses a strict 25-second upstream proxy timeout and 28-second total client budget. It performs one automatic retry only for recognized infrastructure failures, then requires manual retry. HTTP 500 is `backend_internal_error`; cold-start copy is reserved for explicit cold-start/readiness evidence or recognized 502/503/504 wake-up conditions.

## vΩ.9 Changes (2026-07-14)

- **Single app shell — duplicate `/match` chrome removed.** `app/match/layout.tsx` was deleted: it rendered a second `<Header/>` (the `PremiumHeader` hero) and a nested `<main>` inside the root `app/layout.tsx` shell, producing two competing `sticky top-0` headers that overlapped the match analysis. All routes now use the single root shell (fixed LEAGUES sidebar + "Live workspace" header). `components/header.tsx` was deleted as dead code (its only importer was the removed match layout).
- **Sidebar is the sole, complete nav.** The root sidebar gained a "Workspace" group (Intelligence, Matches, Performance, Monitoring, Docs) so `/performance` and `/monitoring` — previously reachable only through the broken header — are navigable again.
- **Match landing copy corrected** — "⅛ Kelly" → "Quarter Kelly" (matches the certified Quarter-Kelly 0.25 contract) and the fabricated "Updated every 15s" cadence → "Fetched fresh per request" (the match detail page is `force-dynamic`; there is no 15s polling loop).
- ⚠️ **Ops note:** after deleting a route `layout.tsx`, clear `apps/web/.next` before `tsc --noEmit` — Next's generated `.next/types/validator.ts` keeps a stale import to the removed layout and fails typecheck otherwise.

## vΩ.12 Changes (2026-07-14)

- **Off-season is expected, not a fault.** In mid-July the top-five European leagues are on summer break. The live backend `GET /api/v1/upcoming/matches` correctly returns `offseason: true`, `next_season_start: "2026-08-08"`, `total: 0`, and the web app renders the off-season notice with a restart countdown. An empty fixtures list and a 33/33/33 baseline for a hand-typed matchup are **correct fail-closed behaviour** during the break; real fixtures and predictions return automatically once the season resumes (≈8 Aug 2026). Do not attempt to force fixtures during the break.
- **All five providers are now declarable on Render.** The live `/api/v1/providers/health` showed only `espn` and `football_data_org` enabled — the other three were `provider_disabled` because `render.yaml` never declared them. `render.yaml` now ships `ENABLE_API_FOOTBALL_PROVIDER` / `ENABLE_SPORTMONKS_PROVIDER` / `ENABLE_THE_ODDS_API_PROVIDER = true` plus `API_FOOTBALL_API_KEY` / `SPORTMONKS_API_TOKEN` / `THE_ODDS_API_KEY` (`sync: false`). **Operator action:** paste those three keys into the Render dashboard → all five providers light up. Until a key is present the provider reports "needs key" (never a crash — the gateway handles the unconfigured state).

### Provider enablement runbook (Render dashboard)

1. Open the `sabiscore-api` service → **Environment**.
2. Set the provider keys (the service already reads `FOOTBALL_DATA_API_KEY`):
   `API_FOOTBALL_API_KEY`, `SPORTMONKS_API_TOKEN`, `THE_ODDS_API_KEY`.
3. Save — Render redeploys automatically (`autoDeploy: true` on `master`).
4. Verify: `GET /api/v1/providers/health` → each configured provider shows `configured: true`; after a live probe (or first real fetch) status advances toward `VERIFIED`.
5. `SABISCORE_BACKEND_URL` in the **Vercel** dashboard must be `https://sabiscore-api-bav1.onrender.com`.

> **Security:** any credential ever pasted into a chat, terminal log, or shared document is compromised and must be rotated in its provider console. `.env*` is gitignored and no real secret is tracked in the repo.

## vΩ.11 Changes (2026-07-14)

- **🟢 GATE 1 UNBLOCKED — backend live at a new Render URL.** The suspended `sabiscore-api.onrender.com` service was replaced by **`https://sabiscore-api-bav1.onrender.com`** (service `srv-d95kkffaqgkc73f8003g`; Render kept the blueprint name `sabiscore-api` but assigned the unique `-bav1` subdomain). `GET /health/ready` → 200 with database connected, Alembic at head `0003_team_reconciliation`, cache connected, and all 5 league models loaded (`v5_phase7`, 18 artifacts). Set `SABISCORE_BACKEND_URL=https://sabiscore-api-bav1.onrender.com` in the Vercel dashboard.
- **URL references updated to bav1** — `vercel.json` rewrites (`/api/v1/health`, `/api/v1/:path*`): these are load-bearing because the browser-side `ultra-api-client.ts` intentionally fetches relative `/api/v1/ultra/*` so requests stay same-origin and ride the rewrite; with the old suspended host they returned 503 HTML. Also `render.yaml` `ALLOWED_HOSTS` and the 5 root ops scripts (`verify-deployment.ps1`, `test_production.ps1`, `test_production_smoke.ps1`, `monitor_deployment.ps1`, `diagnose_deployment.ps1`). Stale `vercel.json.backup` deleted.
- **Match page reload loop removed.** `insights-error-state.tsx` is a compact card that leaves any available analysis visible. The analysis client performs the single bounded infrastructure retry; after that, recovery is manual. There is no timed page reload or session retry counter.
- **Reduced-evidence honesty.** `DataGapBanner` collapses >8 gaps under a native `<details>` with a plain-language summary (previously a 67-item text wall); `EnsembleCard` shows an amber "Baseline output — not a tradable signal" note when the backend reports a fallback model version; the Phase 8 disabled notice no longer prints backend env-var instructions to end users.
- **Verification:** lint 0 errors, `tsc --noEmit` clean, Vitest 16/16, `NODE_ENV=production next build` ✓, prohibited-term + ⅛-Kelly greps clean.

## vΩ.10 Changes (2026-07-14)

Frontend-only session. No backend files, Alembic, or betting-engine changes.

- **Backend availability banner (GATE A)** — `apps/web/src/components/backend-status-banner.tsx` shares the platform-health query with readiness/provider consumers. When readiness is unavailable, a slim amber bar states that live readiness and provider status cannot be verified; it does not infer a cold start from a generic failure. The banner dismisses when authoritative health recovers.

- **Mobile navigation (GATE E)** — `apps/web/src/components/mobile-nav.tsx` provides a hamburger button + full-screen overlay drawer (`lg:hidden`) exposing all WORKSPACE_LINKS and LEAGUES. ESC key, backdrop click, and link click all close the drawer. Wired into the root sticky header. Previously the sidebar (`hidden lg:block`) had zero mobile navigation fallback.

- **LEAGUE_COLORS extracted (GATE E)** — `apps/web/src/lib/league-colors.ts` — 7-league colour map was copy-pasted identically in `upcoming-matches-panel.tsx` and `best-bet-spotlight.tsx`. Both now import from the shared module.

- **Homepage plain-language copy (GATE B)** — `apps/web/src/app/page.tsx`: HERO_STATS detail text updated to plain English; "RPS Gate" label → "Model Precision Gate"; TRUST_BADGES "Phase 8 features" → "ML features validated"; primary CTA "Open Intelligence" → "See today's value picks" (both `PremiumHome` and `LegacyHome`); LegacyHome badge de-jargoned; PIPELINE_STEPS technical `detail` text wrapped in `<details><summary>Technical detail ▸</summary></details>` so the plain-English step label leads.

- **/intelligence metric glosses + gap collapse (GATE C)** — `betting-intelligence-dashboard.tsx` inline style block gains `.bi-gloss` + `.bi-gap-summary`. `<em className="bi-gloss">` spans added to Edge / Expected Value / Stake metric labels and Fair market / Edge / EV table column headers. `data_gaps.length > 5` now collapses under a native `<details>` (zero JS).

- **Loading screen pipeline alignment (GATE D)** — `loading-facts.ts` LOADING_FACTS reordered: entries 1–5 now explicitly mirror the 5 homepage pipeline steps (Collect → Validate → Calibrate → Compare → Surface); `ProgressiveConfidenceMeter` milestone labels changed from `Data | Models | Confidence | Ready` → `Collect | Calibrate | Compare | Ready`; a 15-second cold-start hint appears via `AnimatePresence` if analysis is still loading (respects `useReducedMotion`).

- **⅛ Kelly contract sweep** — four frontend files still showing ⅛ Kelly labels fixed: `insights-display.tsx`, `OneClickBetSlip.tsx`, `performance-page-client.tsx` (UI copy → ¼), `currency.ts` (JSDoc comment → 0.25 = ¼). `grep -rni "⅛" apps/web/src` → 0 matches.

- **Verification gate:** lint 0 errors, `tsc --noEmit` clean, Vitest 16/16, `NODE_ENV=production next build` ✓, prohibited-term grep 0 actionable hits.

## vΩ.5 Changes (2026-07-06)

- **`datetime.utcnow()` purged — entire backend/src** (except `database.py` SQLAlchemy column callable defaults, which require a dedicated SQLAlchemy migration). All 30 remaining non-canonical files (`cli/`, `connectors/`, `data/loaders/`, `models/`, `scrapers/`, `services/`) updated to `datetime.now(timezone.utc)`. `grep -rn "datetime\.utcnow" backend/src --include="*.py" | grep -v database.py` → 0 matches. CI zero-fab scan now enforces this on canonical paths (`src/api`, `src/services`, `src/providers/espn`, `src/models/orchestrator.py`, `src/core/security.py`).
- **Ultra service Kelly cap reads `LeaguePolicy.kelly_cap`** — `services/ultra_prediction_service.py` `_detect_value_bets()` now calls `get_league_policy(league_key)` with fallback to `0.04` on `LeaguePolicyUnavailableError`. League model files (`premier_league.py`, `la_liga.py`, `ligue_1.py`, `serie_a.py`) use `_KELLY_CAP` module constant from `get_league_policy()`. `grep -rn "min(kelly_fraction, 0.04)" backend/src` → 0 matches.
- **`render.yaml` metadata corrected** — `MODEL_VERSION: v5_phase7` (was `3.0`), `FEATURES_COUNT: 86` (was `220`).
- **Pydantic v2 migration complete** — `ultra_predictions.py` `UltraMatchFeatures` migrated from `class Config:` to `model_config = ConfigDict(...)`. `grep -rn "class Config:" backend/src` → 0 matches. All production schemas on Pydantic v2 API.
- **Duplicate globals removed from `main.py`** — second `model_instance`/`model_load_in_progress` declaration block removed.

## vΩ.4 Changes (2026-07-05)

- **Quarter-Kelly full sweep** — all `kelly_fraction=0.125` (⅛-Kelly) defaults changed to `0.25` across `schemas/prediction.py`, `schemas/value_bet.py`, `models/edge_detector.py`, `services/ultra_prediction.py`, `services/ultra_prediction_service.py`. League model inline Kelly post-multipliers (`* 0.125`) replaced with policy-cap pattern in `premier_league.py`, `la_liga.py`, `ligue_1.py`, `serie_a.py`. `grep -rn "kelly_fraction.*0\.125" backend/src` → 0 matches.
- **Orchestrator stale accuracy strings removed** — `models/orchestrator.py` `_get_accuracy_target()` hardcoded 76.2%/74.8% etc. removed; method returns `""` with walk-forward note.
- **Integration test gate fixed** — `tests/test_prediction_pipeline.py` gated purely on `RUN_INTEGRATION_TESTS=1`. `tests/integration/test_end_to_end.py::test_feature_transformation` asserts fail-closed `DataUnavailableError` contract. Both files green: 18 passed, 9 skipped, 0 failed.
- **`CalibratedEnsemble cv="prefit"`** — `models/enhanced_training.py` prevents re-fitting a trained `StackingClassifier` via k-fold (data leakage). Regression guard in `test_zero_fabrication_contract.py`.
- **Pydantic v2 partial migration** — All 7 production schema classes in `backend/src/schemas/` migrated.
- **Ruff zero-issue** — All bare `except:` fixed, E402 annotated, E701/E741 resolved.
- **ws service Dockerfile** — `production` target added, port aligned to `WS_PORT=8001`, `# syntax` directive dropped. Duplicate `Dockerfile.ws` deleted. CORS `allow_credentials=False`.

## vΩ.3 Changes (2026-07-05)

- **SECURITY — Upstash Redis credential purged.** A live Upstash token (`known-amoeba-10186.upstash.io`) had been committed as an env default across 10 tracked files (`apps/ws/main.py`, `apps/api/ingestion/redis_client.py`, `start_backend.bat`, and 6 docs). All occurrences removed: code/scripts now default to inert `redis://localhost:6379/0`, docs to a `<UPSTASH_REDIS_TOKEN>` placeholder. **Action required: rotate this token in the Upstash console** — it stays in Git history until a reviewed history rewrite is scheduled.
- `apps/ws/Dockerfile` gained the `production` build target that `docker-compose.prod.yml` references (previously only `base` existed, so `docker compose build ws` would fail), aligned the exposed/served port to compose `WS_PORT=8001`, and dropped the `# syntax` directive (offline-build footgun). The stale duplicate `apps/ws/Dockerfile.ws` was deleted.
- `apps/ws/main.py` CORS corrected: `allow_credentials=False` with the open-origin default (browsers reject wildcard-origin + credentials); origins overridable via `WS_ALLOWED_ORIGINS`.
- Provider circuit breakers confirmed already wired for all five providers — the four non-ESPN adapters inherit breaker protection through `BaseProvider._get_json`; no per-adapter change was needed.
- `Makefile` zero-fabrication scan output: fixed double-encoded `✗` glyphs (mojibake) in three echo lines.
- Earlier vΩ.3 pass (commit `1006485`): CI Kelly-fraction scan is now fatal (no `|| true`); `UltraPredictionService` has a zero-fabrication guard; homepage "Live" dot is backed by a real `/api/health` fetch; `performance.py` returns `503 METRICS_UNAVAILABLE` instead of false-zero stats; both engines share the `epistemic ≤ 0.05` HIGH_CONVICTION threshold; `verified_provider_count=None` now maps to 0 → PARTIAL; Eredivisie aligned to SOFT; `docker-compose.prod.yml` secrets are fail-fast required vars.

## vÎ©.2 Changes (2026-07-04)

- CI workflows (`ci.yml`, `secret-scan.yml`) now trigger on `master` branch â€” previously only fired on `main`/`develop`.
- `nginx.conf` created at repo root; `docker-compose.prod.yml` nginx mount now valid. `./ssl/` certs still required for TLS.
- All three Docker healthcheck paths aligned to `/api/v1/health/live`.
- `PREMIUM_VISUAL_HIERARCHY` flag enabled by default; premium homepage now shown to all users.
- Test deps (`pytest`, `pytest-asyncio`, `respx`) moved from `requirements.txt` to `requirements-dev.txt`; Render deployments no longer install test packages.
- Dev postgres aligned to `postgres:16-alpine` (matches prod compose).
- `datetime.utcnow()` deprecated calls replaced with `datetime.now(timezone.utc)` in `model_registry.py`.
- `render.yaml` now deploys from `master` (was `main` â€” autoDeploy never fired) and no longer sets the dead `KELLY_FRACTION=0.125` env var (read by nothing; engines hardcode Quarter-Kelly 0.25).
- `backend/src/utils/currency.py` deleted â€” dead module (zero importers) carrying a stale â…›-Kelly constant that contradicted the certified Quarter-Kelly contract.
- Sportmonks `probe()` now calls `/leagues` (cheapest call valid on every plan). Live-verified: bare `/sidelined` 404s in the subscribed API shape, so the old probe could never verify a valid token. All five providers report `configured` via `providers status`.
- `docs/Public-ESPN-API-main/` (vendored read-only reference repo) is now gitignored.

## Known Limitations

- Live provider tests are opt-in with `PROVIDER_LIVE_TESTS=false` by default.
- Provider quotas are observed and exposed but require provider-specific headers for exact remaining/reset values.
- Legacy code remains for compatibility, but production entrypoints are canonicalized to `backend`, `apps/web`, and `apps/scraper`.
- Full production readiness remains blocked until `make verify`, Docker image
  builds, Alembic upgrade/check, frontend tests/build, and Playwright smoke tests
  are run successfully in an environment with those dependencies.
- Do not delete non-master branches until open PRs are merged or closed, branch
  backups are retained, and the full release gate is green.
