# Codex Verified Repository State

Last reviewed: 2026-08-10

This is a dated navigation aid, not a substitute for inspecting current code,
tests, Git history, and runtime configuration. Update it only with fresh evidence.

## Fresh Apex activation evidence from 2026-08-10

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
  by both loaders. The generation is `UNVERIFIED`, therefore both betting engines
  enforce a critical generation gap and zero stake.
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
- Backend: `1265 passed, 13 skipped` in the final full run. Changed-file Ruff
  passes. Mypy reports 783 errors in 127 files / 232 checked files, one below the
  accepted 784-error ceiling; no new typing debt was added. A repository-wide
  Ruff invocation that includes legacy utility scripts still exposes 33
  pre-existing script findings.
- Frontend: lint, type-check, 19 Vitest files / 123 tests, and the Next.js
  15.5.19 production build passed. Playwright passed 36/36 desktop/mobile tests,
  including route overflow, keyboard, verified-fixture, and decision-state flows.
- OpenAPI verification passed with 78 paths. Alembic has one head
  (`0006_canonical_league_ids`). Production `alembic upgrade head` timed out at
  120 seconds; `alembic check` therefore remains unexecuted. SQLite fallback was
  not used.
- `docker compose -f docker-compose.prod.yml config --quiet` passed. The Docker
  daemon responds, but backend and web image builds timed out after 604 and 304
  seconds and produced no tagged image.
- Gitleaks scanned the current worktree (~178.21 MB) with no leaks. Full Git
  history still contains exactly two `backend/.env.example` findings: an old
  `SECRET_KEY` fingerprint at `d604c13` and `API_FOOTBALL_KEY` fingerprint at
  `67ed0ab`. They were not ignored because revocation is not proven.
- The supplied Render log shows an invalid Redis URL causing the deployed server
  to crash before bind. Code now degrades safely for malformed URLs, but the
  exposed credential must still be rotated and Render must receive a valid
  `redis://` or `rediss://` secret before release.
- Live proof is not coherent. Vercel recorded 86 timeout errors in seven days on
  `/api/upcoming` and `/api/value-bet-scan`. The existing PR preview at `dd24536`
  returns a platform 504 for prediction-free upcoming, times out model status,
  and still publishes hardcoded health metrics. Production remains on frontend
  SHA `1769b13`; neither deployment proves a matching backend SHA. The supplied
  Render evidence is stale and lacks the Redis/startup fixes.
- GitHub Actions did not execute the required jobs: every locked job has
  `runner_id: 0`, no steps, and an account-billing-lock annotation. Local success
  does not replace the absent Linux security/backend/web/Playwright/model evidence.
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
