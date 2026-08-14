# Codex Verified Repository State

Last reviewed: 2026-08-14

This is a dated navigation aid, not a substitute for inspecting current code,
tests, Git history, and runtime configuration. Update it only with fresh evidence.

## Local Apex v3 candidate evidence from 2026-08-14

- On `feat/apex-v3-activation`, shared prediction capture and strict temporal joins
  **EXIST / TESTED**. A seeded test reaches scheduled verified fixture → full
  analysis → one deduplicated `MatchPredictionLog` → finished score → settled join.
  Production is still DATA-FED at zero until this code is deployed and a real result
  joins; Phases F-J/N2 and promotion remain closed.
- Both verdict engines now make `SPECULATIVE` watchlist-only with zero stake. The RL
  advisory API was reviewed separately because it has no matching verdict taxonomy;
  its full-analysis integration still abstains/zeroes on insufficient evidence and
  applies the effective cap.
- The upcoming list can expose all 24 fetched fixtures without filtering, resets on
  league changes, gives soft coverage a visible and accessible explanation, uses
  human league names with secondary canonical IDs, and carries the UCL estimate flag
  through FastAPI/proxy/TypeScript/off-season copy. This is local TESTED evidence,
  not deployed-page measurement.
- Ruff's CI-blocking E402 is fixed. Mypy is pinned to 2.1.0; the local count is 772
  errors in 123 files / 236 checked files, and CI now enforces the 784 ceiling instead
  of marking the step advisory.
- S3 checksum, matching-412 replay, conflicting-412, outage continuity/redaction,
  manifest hash, and fixed-context probe behavior are mocked and TESTED (19 scraper
  tests total). The gitignored root/backend env files agree on structurally valid,
  unmasked credentials and the existing `sabiscore-artifacts-prod-uswest2` regional
  configuration; their values were compared without printing secrets. The Render
  blueprint is aligned but the live dashboard is unverified. Read-only AWS
  `HeadBucket` and `GetBucketLocation` calls both returned 403, so bucket identity,
  controls, and writer authorization are not VERIFIED. The mutating probe/acquisition
  was not run and the worker remains disabled.
- Local release gates completed after the final accessibility fixes: backend
  `1329 passed, 13 skipped`; focused backend `163 passed`; Ruff clean; mypy 772
  under the enforced 784 ceiling; web lint and typecheck clean; 31 Vitest files /
  178 tests; Next.js 15.5.19 production build; scraper validation and 19 tests;
  OpenAPI 78 paths; Docker Compose configuration; and 38 desktop/mobile Playwright
  tests including an axe WCAG A/AA scan. Alembic upgraded a disposable database,
  but `alembic check` still reports 11 pre-existing legacy index removals, so that
  gate is not green.
- Gitleaks found no secret in the current committed-tree snapshot or the exact
  staged candidate diff. Full history still reports the known redacted
  `backend/.env.example` findings at `d604c13f40f0fad0a72d6a83eb64f5e4fc106fd7`
  (`SECRET_KEY`) and `67ed0ab7440595b0d304ea2768c46b17d97e9adb`
  (`API_FOOTBALL_KEY`). Scan cleanliness does not prove either credential was
  rotated or revoked; dated operator evidence remains required.

## Fresh Apex v2 execution evidence from 2026-08-14

- Settlement is EXISTS / TESTED / WIRED / CALLED / DEPLOYED and its production
  query is DATA-FED at zero. `/api/v1/model-performance` returned
  `503 METRICS_UNAVAILABLE` with `settled_predictions: 0`; walk-forward, CLV
  calibration, retraining, and promotion remain unverified and gated.
- Redis tier-1 is DEPLOYED / VERIFIED as an external connection from detailed
  `/health` cache metrics (enabled, available, real hit/miss counters, zero
  errors). The evidence does not establish the vendor as Upstash, and the
  supplied Render log lacks the required connection-success line.
- The single authorized `the_odds_api` live probe returned 401 with credentials
  redacted. Football-Data.org, API-Football, Sportmonks, ESPN, and The Odds API
  each remain `CONFIGURED_UNVERIFIED` in non-live provider health; no aggregate
  provider-liveness claim is supported.
- WP-18 remains WIRED / CALLED and its focused regression coverage passes.
  Season confidence now comes from `season_calendar.py`: UCL is explicitly
  estimated, while unknown leagues return an unknown confidence state.
- Public `kickoff_utc` values are normalized to offset-aware UTC at the FastAPI
  response boundary. The strict frontend contract remains unchanged.
- The UI now states `RESEARCH FORECAST — staking disabled`, keeps model
  certification explanations visible, separates configured providers from
  live verification, and uses repository semantic variables for official
  verdict presentation. Actionable celebration and pre-certification stake
  surfaces were removed.
- S3 acquisition remains dormant. The missing bucket, endpoint, region,
  path-style, SSE, and standard credential-chain variables are scaffolded only;
  bucket/IAM provisioning and worker activation remain operator actions.
- TESTED evidence produced this session: backend `1317 passed, 13 skipped`
  (focused contract/security/season subset `53 passed`); web type-check and
  lint PASS; web `30 files / 168 tests`; Next.js 15.5.19 production build PASS;
  scraper `14 passed`; OpenAPI verification `78 paths`.
- Gate C is VERIFIED locally at 360x800, 430x932, 768x1024, 1280x800, and
  1440x900. Each viewport retained the research/no-stake frame and long club
  names without horizontal overflow. Keyboard order and visible focus,
  accessibility-tree names, reduced motion, a 200% zoom-equivalent viewport,
  and fail-closed match rendering passed. The successful live-backed `PARTIAL`
  full-analysis state was retested after its first deploy exposed legacy muted
  text and generic-element ARIA defects; the persisted production build then
  reported zero axe violations. Gradient contrast required a manual endpoint
  calculation; the worst measured ratio was 4.516:1.
- Current-source Gitleaks completed with no finding while inaccessible generated
  pytest temporary trees were excluded. The explicit staged release diff was
  scanned separately (`160.79 KB`, no finding). This is current-source evidence,
  not full-history revocation evidence.
- Deployment SHA parity is not established by these local results and must be
  verified independently after the release push.
- The active generation remains `UNVERIFIED`, and `promotion_permitted=false`.
  No candidate artifact was trained, copied, renamed, or promoted.

## Fresh Apex activation evidence from 2026-08-10

- The refined production task contract now lives in
  `docs/APEX_FINAL_PRODUCTION_ACTIVATION_DIRECTIVE.md`. It records the current
  blockers, real-settlement hard gate, isolated research-tooling rules, and
  master/deployment acceptance criteria without treating aspirations as evidence.
- `backend/requirements-training.txt` provides a Python 3.11-3.13 research stack.
  CatBoost 1.2.8 and SHAP 0.49.1 import in the isolated local Python 3.12
  environment; MLflow and ancillary packages remain incomplete after bounded
  network attempts. This is partial importability only and did not change the
  active generation.
- `ModelRegistry` no longer imports MLflow when tracking is unconfigured, never
  logs its URI, redacts registry errors, and rejects mutable local production
  promotion in favor of the active-generation release manifest.
- Upcoming fixture reads are now cache/PostgreSQL-first and provider-free on the
  public request path. Prediction-free reads have a five-second backend deadline
  and an eight-second Vercel proxy deadline with structured data gaps.
- `/value-bet-scan` no longer performs 200 synchronous analyses; it returns only
  persisted fresh gated opportunities, or an empty non-executable data gap.
- Health accuracy/RPS/edge fields are nullable and `Pending` without settled
  backend samples. Public outcome mutation and client-local performance truth are
  retired; `/api/predict` requires a persisted fixture and validates the backend
  probability simplex without zero filling.
- Active v5 artifacts are governed by one hash-validated generation manifest used
  by both loaders. The generation is `UNVERIFIED`, therefore both verdict engines
  enforce a critical generation gap and zero stake; the distinct RL advisory
  integration must equivalently abstain and expose zero public stake.
- Apex chronological evidence uses pre-2024/25 training, 2024/25 calibration, and
  untouched 2025/26 evaluation. The candidate wins 3/6 active-league RPS
  comparisons and 0/6 market-baseline comparisons. Serving availability also
  fails (11 schema-misaligned and four always-data-gap slots), so promotion stays
  closed.
- Work is isolated on `feat/market-odds-features` in a clean linked worktree.
  Dirty local `master`, the two local skill deletions, and the unrelated
  `data/cache/football_data/E0_2324.csv` modification remain untouched and must
  not enter a release commit.
- Generated model files are quarantined under `backend/models/candidate/` with
  `UNVERIFIED_CANDIDATE` status and promotion disabled. Active v5 binaries were
  restored to the checked-in generation.
- External caller probabilities, missing uncertainty/calibration/freshness, bad
  simplexes, incoherent odds, and failed feature projection now fail closed. A
  projection exception does not run inference on a zero/default vector.
- One lifespan-scoped odds service and coherent request snapshot now feed
  features, full analysis, edge, CLV capture, and provenance.
- Full analysis is the authoritative match-page contract. The legacy insights
  error was removed; uncertainty/Elo are nullable; `model_drivers` is preferred;
  verified fixture identity is required for public staking.
- The homepage prioritizes verified fixtures and renders model claims from
  `/models/status`. Hypothetical entry is visibly secondary and non-executable.
- Codex discovery validation reports 40 canonical skills and `.agents/skills`
  resolves to `.ai/skills`. A Codex/VS Code restart may be needed to refresh the
  selector after the junction is created.
- Backend: `1268 passed, 13 skipped` in the final full run. Whole-repository Ruff
  passes with zero findings after 79 legacy diagnostic, deployment, and training
  script findings were repaired. Mypy reports 781 errors in 127 files / 232
  checked files, three
  below the accepted 784-error ceiling; no new typing debt was added.
- Frontend: lint, type-check, 19 Vitest files / 123 tests, and the Next.js
  15.5.19 production build passed. Playwright passed 36/36 desktop/mobile tests,
  including route overflow, keyboard, verified-fixture, and decision-state flows.
- OpenAPI verification passed with 78 paths. Alembic has one head
  (`0006_canonical_league_ids`). Production `alembic upgrade head` timed out at
  120 seconds; `alembic check` therefore remains unexecuted. SQLite fallback was
  not used.
- `docker compose -f docker-compose.prod.yml config --quiet` passed with non-secret
  required placeholders, and the Docker 29.6.2 daemon responds. Fresh backend and
  web image retries ran for more than five and three minutes without a current
  image. The backend verify tag is an old 2026-07-15 image; no web verify tag exists.
- Gitleaks scanned the current worktree (~180.87 MB) with no leaks. The ignored
  `.venv-ml` path is excluded like `.venv` and `node_modules`; its installed
  third-party package tests are not repository content. Full Git
  history still contains exactly two `backend/.env.example` findings: an old
  `SECRET_KEY` fingerprint at `d604c13` and `API_FOOTBALL_KEY` fingerprint at
  `67ed0ab`. They were not ignored because revocation is not proven.
- The supplied Render log shows an invalid Redis URL causing the deployed server
  to crash before bind. Code now degrades safely for malformed URLs, but the
  exposed credential must still be rotated and Render must receive a valid
  `redis://` or `rediss://` secret before release.
- Vercel built READY preview `dpl_FZcdYXQ1zTi4VbQvXephkc2ncDMQ` from code SHA
  `89c1254`. Health now reports frontend SHA `89c1254`, nullable metrics,
  `performanceStatus: PENDING`, no optimistic model version, and no backend SHA.
  CSP retains a per-request nonce and `strict-dynamic` without `unsafe-eval`.
- Prediction-free upcoming no longer reaches Vercel's platform timeout: it exits
  with a no-store structured 503, `data_gap: true`, and
  `UPCOMING_PROXY_TIMEOUT`. Five preview probes took 9.13-9.49 seconds, all 503;
  therefore they do not satisfy the production requirement for successful
  probes or warm latency below two seconds. Model status also returns a bounded
  503 because the paired Render backend is stale and lacks this release.
- Production remains on frontend SHA `1769b13`. Vercel recorded 86 timeout errors
  over the preceding seven days on `/api/upcoming` and `/api/value-bet-scan`.
  No matching backend SHA, Render readiness, Redis, provider, fixture-sync, or
  real-analysis proof exists, so the preview was not promoted.
- Fresh GitHub Actions for `89c1254` did not execute the required jobs. Failed
  security/model/large-file jobs have `runner_id: 0`, no runner name, and no
  steps; dependent backend/web/Playwright jobs were skipped. The account billing
  lock must be resolved and every required job rerun. Local success does not
  replace the absent Linux evidence.
- The model-artifact workflow now validates the actual `backend/models` artifacts,
  both production loaders, fixture sensitivity, and the closed candidate promotion
  manifest instead of generating dummy models in the wrong directory.

Release decision: **NOT SAFE FOR PRODUCTION** until credential rotation, valid
Redis/PostgreSQL checks, Docker/CI gates, candidate certification (or explicit
continued use of the last known-good artifacts), live provider flow, coherent
deployment SHAs, and a rollback rehearsal are proven.

## Confirmed in the supplied control file

- Production entrypoints are `backend/src/api/main.py`, `apps/web`, and
  `apps/scraper`.
- Legacy `apps/api/` and `frontend/` must not be restored to production paths.
- The provider registry and shared lifespan HTTP client are already implemented.
- Browser TensorFlow.js inference was removed; official inference is backend-only.
- Critical and advisory evidence gaps are separated.
- Verdict/watchlist behavior is implemented in two independent engines and must stay
  aligned.
- Quarter-Kelly public sizing and the hard stake cap are already represented.
- Public Full-Kelly fields and `NEXT_PUBLIC_KELLY_FRACTION` are prohibited.
  The current backend schema and web TypeScript contracts expose only capped
  Quarter-Kelly stake fractions; raw Kelly math remains internal audit detail.
- `python -m src.cli providers doctor` and `providers status` use the same
  offline-safe five-state public contract: `configured`, `missing`, `invalid`,
  `quota_exhausted`, or `temporarily_unavailable`. Live validation remains
  explicit via `doctor --validate-live`.
- `backend/src/core/league_policy.py` supports both legacy uppercase league ids
  and canonical internal ids such as `premier_league`, `la_liga`, and `ucl`.
  Missing league policy propagates as `DATA_GAP: LEAGUE_POLICY_UNAVAILABLE`.
- The frontend CSP uses a per-request nonce in middleware.
- Playwright desktop/mobile `/intelligence` smoke coverage is present.
- Alembic-only schema management, Gitleaks, and zero-fabrication scans are release
  expectations.

## Known incomplete or environment-dependent gates in the supplied control file

- Formal walk-forward RPS validation depends on sufficient live historical data.
- Football-Data.org and Sportmonks adapters require credentialed live-contract
  verification.
- Full `make verify` requires its infrastructure dependencies, including PostgreSQL
  and Docker.
- Vercel linkage/deployment status must be verified externally.
- Full production readiness is not yet certified in this checkout until
  `make verify`, Docker builds, Alembic upgrade/check, frontend test/build, and
  Playwright smoke gates pass in the target release environment.

## Fresh local evidence from 2026-07-05

- Transformer zero-fabrication hardening:
  `backend/src/data/transformers.py` now defaults to fail-closed production
  behavior, validates required feature evidence before engineering features, and
  exposes `allow_legacy_defaults=True` only for explicit training/backcompat
  callers. Missing production evidence raises `DataUnavailableError`.
- Transformer/static contracts:
  `7 passed` for `tests/test_zero_fabrication_contract.py` and
  `tests/unit/test_feature_transformer.py`.
- Betting engines:
  `82 passed` for `tests/test_betting_intelligence_engine.py` and
  `tests/test_core_engine.py`.
- Frontend:
  `pnpm --filter @sabiscore/web typecheck` passed;
  `pnpm --filter @sabiscore/web lint` passed;
  `pnpm --filter @sabiscore/web test` passed outside the sandbox
  (`2 files`, `11 tests`) after sandboxed esbuild spawn failed with `EPERM`;
  `pnpm --filter @sabiscore/web build` passed outside the sandbox after the
  sandboxed Next worker spawn failed with `EPERM`.
- OpenAPI:
  `PYTHONPATH=. python scripts/verify_openapi.py` passed with 78 paths.
- Static scans:
  zero hits for `full_kelly_fraction`, web Full-Kelly tokens, and
  `NEXT_PUBLIC_KELLY_FRACTION`; zero hits for `FEATURE_DEFAULTS[` in
  production API/service/provider paths and `backend/src/data/transformers.py`.
- Docker:
  `docker compose -f docker-compose.prod.yml config --quiet` passed. Docker image
  builds were retried outside the sandbox; Buildx lock access was resolved, but
  backend and web image builds remain blocked by Docker daemon DNS failures when
  fetching Debian/Alpine packages.
- Alembic:
  `alembic upgrade head` and `alembic check` are blocked in this environment by
  an invalid/unavailable PostgreSQL URL. SQLite fallback was not used for the
  production migration gate.
- Playwright:
  Full `pnpm exec playwright test` ran outside the sandbox and produced
  `16 passed, 6 failed`; failures were backend-dependent checks because local
  backend health was `degraded` due host memory pressure. Targeted
  `pnpm exec playwright test tests/e2e/intelligence.spec.ts` passed 4/4
  (desktop + mobile).
- Branch/PR state:
  `master` equals `origin/master` at
  `1453b785f28d81959c7d9db99efa3b9f0edd8a68`. PR #4
  (`codex/final-production-certification` -> `master`) is open, unmerged, and
  not mergeable. Local bundle backups for all non-master remote branches are in
  `artifacts/branch-backups/20260705-000338/`. Do not delete non-master branches
  while PR #4 remains open and release gates are blocked.

## Fresh maintenance evidence from 2026-07-20

- Live Render readiness returned `status: ok`; database, migrations, cache, and
  models were all `ready`. Alembic head/applied was
  `0003_team_reconciliation`; five Phase 7 leagues and 18 artifacts were loaded.
- The non-live provider-health endpoint returned `CONFIGURED_UNVERIFIED` for ESPN
  and Football-Data.org. API-Football, Sportmonks, and The Odds API were
  configured but still disabled. Provider activation is a Render-dashboard
  operator checkpoint and did not occur in this code session.
- Render and Vercel same-origin upcoming-match probes returned `total: 0`,
  `offseason: true`, and `next_season_start: "2026-08-08"`; no fixtures were
  forced. The deployed Vercel `/api/health` still showed the pre-release
  contradiction (`backendStatus: ok` plus `status: degraded`) before this commit.
- Local web gates passed: lint, typecheck, 30/30 Vitest tests, Next.js 15.5.19
  production build, and 4/4 Playwright `/intelligence` desktop/mobile smoke.
- Focused backend provider/source coverage passed 75/75. The provider/source test
  run emitted legacy pytest-asyncio deprecation warnings but no failures.
- Static copy tests enforce zero active-source hits for `lock`, `banker`,
  `guaranteed`, `sure bet`, `free money`, `execute immediately`, and one-eighth
  Kelly variants.
- Gitleaks `--no-git` filesystem mode passed with no current-tree leaks. Full
  history still contains two redacted legacy findings from old
  `backend/.env.example` commits; history rewriting remains out of scope.
- `make verify-core` did not complete in the current Windows command-shell path:
  `jq` is unavailable and the recipe's POSIX `PYTHONPATH=.` assignment is not
  recognized. Full `make verify` was not run with the PostgreSQL password exposed
  in chat; it must be rotated and supplied through a secure secret store first.
  SQLite fallback was not used.
- Deferred without expansion: the `/performance` first-load bundle remains
  232 kB, internal legacy `90%+` comments, and Phase 9 source-registry freshness
  plumbing.

## Verification rule

Before relying on any item above, locate its current implementation and tests. If
code disagrees with this file, code and passing tests win; update this document in
the same change.
