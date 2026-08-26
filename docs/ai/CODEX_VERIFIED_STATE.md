# Codex Verified Repository State

Last reviewed: 2026-08-26

This is a dated navigation aid, not a substitute for inspecting current code,
tests, Git history, and runtime configuration. Update it only with fresh evidence.

## SAB-22 stale-authorization verification from 2026-08-26

- A session opened holding two stacked mandates: an APEX activation directive
  carrying a pre-granted Class C authorization for the SAB-22 EPL
  participant repair (518 affected matches, manifest SHA
  `a1eae47c4d5b86fb3b0eda2bc997f219533561f0913cd584ecc49839cfa72b62`, replay
  plan SHA `9bf816061704b6c45aacdc3080eba4d25dcc0d5e007c834687f66d02d7d87bd4`
  — both recorded verbatim below under "SAB-22 manifest-v3 candidate
  evidence from 2026-08-21"), and a later, broader audit/fix-pass mandate.
- Before acting on the authorization, `docs/DEBT.md` item 34 was read
  directly rather than trusted from an earlier agent's summary. It is
  titled `RESOLVED 2026-08-25` — one day before the authorization was
  granted — and records a fresh live probe
  (`GET /api/v1/release/semantic-repair-review`) that found
  `affected_matches: 0`, corroborated independently by
  `GET /api/v1/release/data-authority` (`semantic_identity: "PASS"`,
  structural Elo invariants all zero). It states plainly: "No Class C action
  was ever taken for this item."
- **Conclusion: the authorization's own required pre-mutation step cannot
  pass.** Every Class C repair script in this codebase re-derives the
  manifest hash immediately before mutating and refuses to proceed unless it
  matches the reviewed value. A manifest computed over 0 affected rows
  cannot reproduce a hash computed over 518 affected rows. Re-running the
  dry-run today would report zero affected matches and a different hash, not
  a match to the authorized one.
- **No repair was executed. No production data was touched.** This is
  recorded so a future session does not reopen SAB-22 by trusting a pasted
  authorization's premise instead of re-deriving current state, which is
  exactly the failure mode this document's own "Verification rule" (below)
  exists to prevent.

## Phase 2 market trust-boundary audit from 2026-08-21

- GitHub `master` and the Vercel production deployment
  `dpl_3chkfNohtKgJJLjwpkBif2aFCNMJ` were at exact SHA
  `e8f5e42eef854a32267ad9ba00813c8690b1eb2d`. The canonical GitHub workflow,
  secret scan, artifact validation, large-file gate, Playwright, and SonarCloud
  Code Analysis check all completed successfully for that SHA.
- Exact production parity was not established. The canonical verifier reported
  Render and the frontend-observed backend at preceding SHA
  `a054ed908f7676ad94e44eaef5e830a0994eba66`, while GitHub and Vercel were at
  `e8f5e42eef854a32267ad9ba00813c8690b1eb2d`.
- Render readiness was HTTP 200 with PostgreSQL, external Redis, Alembic head
  `0009_quarantine_market_closings`, and strict model artifacts ready. Settlement
  and CLV loops were running without execution failures, but production still had
  only three settled predictions and zero generation-scoped CLV joins. The model
  performance endpoint correctly returned HTTP 503 `METRICS_UNAVAILABLE` with
  `Cache-Control: no-store`.
- Provider telemetry showed football-data.org `DEGRADED` with seven usable and
  seven empty competition/query contexts. The Odds API remained `STALE`: 57
  observations, 502 records, 495 coherent/executable records, 14 events, and zero
  settled records. ESPN, API-Football, and SportMonks still had no durable
  observations. This does not satisfy the Phase 2 evidence gate.
- The code audit found a separate trust-boundary defect: the provenance-blind,
  publicly writable legacy `Odds` table could be labeled `VERIFIED` by fixture
  evidence and used as a Phase-8 market-drift fallback. Branch
  `fix/phase2-market-trust-boundary` removes that fallback, forces manual and
  legacy rows to explicit research-only/non-executable states, deprecates the
  compatibility `/odds` namespace, and preserves canonical provider ownership in
  `OddsHistory` plus `MarketSnapshot`.
- Final local validation passed the full backend suite (`1564 passed, 14 skipped`),
  67 focused trust-boundary/zero-fabrication/odds/secret tests, Ruff, the mypy debt
  ceiling (`769 <= 784`), six active-artifact hash pairs, workspace web tests (208),
  scraper tests (20), lint, typecheck, production build, diff checks, and a 147.05
  MB current-tree Gitleaks scan.
- A separate full-history Gitleaks audit remains a release blocker: it found one
  historical placeholder and one non-placeholder 32-character hexadecimal value
  assigned to `API_FOOTBALL_KEY` in commit `67ed0ab`. The current tree is clean,
  but provider-side revocation/rotation is not verified and the finding must not be
  allowlisted as a substitute for rotation.
- Direct Render resource/log/SQL inspection remains blocked until the connector
  workspace is explicitly confirmed. Sentry remains unverified because no callable
  connector or local project credentials were available. No Class C mutation,
  provider quota consumption, settlement write, model promotion, or deploy occurred.
- Phase 2 remains `BLOCKED`. Model promotion, public value scanning, Kelly sizing,
  and staking remain disabled. Overall decision: `NOT SAFE FOR PRODUCTION`.

## Phase 2 post-merge verification from 2026-08-21

- PR #61 merged the generation-scoped settlement and CLV hardening as GitHub
  `master` SHA `bb76f3f947e1443f6879b2c9fc322934a4903da1`. The current Vercel
  production deployment `dpl_8ZmBDCC2pkXWWx9tLTrbFtJXuTSN` was `READY` at that
  exact SHA. Its no-store `/api/health` response reported both the Vercel SHA and
  backend release SHA as the same value.
- The deployed repository functions require an explicit non-empty model generation,
  deterministically select one prediction and closing snapshot, prevent cross-model
  pooling and join multiplication in canonical SQL, and centrally apply
  `Cache-Control: no-store` to evidence and decision responses, including errors.
- Production health observed through the Vercel backend proxy was HTTP 200 with
  PostgreSQL, external Redis, migration `0009_quarantine_market_closings`, and
  strict model loading ready. The active generation remains `UNVERIFIED` and
  pending performance evidence.
- Durable provider evidence separates transport success from data coverage.
  Football-data.org has real but uneven contextual coverage; Odds API observations
  are stale and have zero settled records; ESPN, API-Football, and SportMonks have
  no durable observations. This is not sufficient certification evidence.
- Current focused validation passed 23 generation-scope, SQL-chain, and no-store
  regression tests. PR #61's canonical GitHub checks also passed the full backend
  suite (`1560 passed, 14 skipped`), PostgreSQL migration checks, frontend checks,
  scraper checks, Playwright, secret scanning, and model-artifact validation.
- The Codex discovery path had only two plugin-managed skills and omitted `nexus`.
  Branch `fix/nexus-discovery-overlay` changes setup to a per-skill overlay. The
  active workspace now resolves all 38 canonical skills, including `nexus`, while
  preserving `neon` and `neon-postgres`; four overlay regression tests pass.
- Direct Render resource and log inspection remains pending explicit selection of
  the sole connector workspace. Direct Sentry inspection remains unavailable
  without local Sentry configuration. SonarQube has no current local scanner or
  configured project; PR #62 is separately adding Sonar Cloud CI integration.
- Phase 2 is `BLOCKED`: repeated real first/intermediate/closing/result/settlement
  evidence and generation-scoped CLV samples remain insufficient. Model promotion,
  value scanning, Kelly, and staking remain disabled. Overall decision:
  `NOT SAFE FOR PRODUCTION`.

## SAB-22 manifest-v3 candidate evidence from 2026-08-21

- The repair was developed from exact `origin/master` SHA
  `317337f61a0605afc2c3c8a95a019013c1587ace`, merged through PR #57, and
  followed by the direct-backend `Cache-Control: no-store` correction in PR #59.
  Render and Vercel both deployed final code SHA
  `06de645a2dc57d1d10dbe53d0427e463dc10ef76`; Render deploy
  `dep-da3t763l550s73dqhavg` was `live` and Vercel deployment
  `dpl_EBDaKGb4swsw6TRH4xdg7qPyj1Y8` was production `READY`. The root
  checkout's unrelated `.gitignore` modification remained untouched.
- The superseded live manifest-v2 review reported 518 affected EPL matches, 236
  repair-ready, and 282 blocked. Source rows existed for all 518. The measured
  unresolved names were West Ham, Man City, and Ipswich; these are the only
  identity cases addressed by manifest v3.
- Manifest schema v3 hashes deterministic source-linked Team creations. The
  apply service locks Team/Match/Elo tables, creates reviewed targets before
  optimistic Match updates, verifies exact counts, and retains full chronological
  Elo replay. The read-only Next.js proxy now validates the response contract.
- Fresh local evidence: focused backend identity/manifest/apply/endpoint suite
  `62 passed`; full backend suite `1551 passed, 14 skipped`; full web Vitest
  `208 passed`; scraper suite `20 passed`; `/intelligence` Playwright desktop and
  mobile smoke `4 passed`; web lint, type-check, production build, scoped Ruff,
  mypy ceiling (`769 <= 784`), OpenAPI (`81 paths`), Docker Compose syntax, and
  Gitleaks current-tree scan passed. Docker image and disposable-PostgreSQL
  Alembic gates remain unavailable locally.
- A read-only Render export of the production identity population was loaded into
  an ignored, disposable local SQLite snapshot and deleted after verification.
  That reproduction matched the subsequently deployed live review.
- Direct Render and Vercel-proxied reviews on final code SHA `06de645a` both
  returned HTTP 200 with `Cache-Control: no-store`, `read_only: true`, schema v3,
  `affected_matches: 518`, `repair_ready_matches: 518`,
  `repair_blocked_matches: 0`, `source_records_missing: 0`, and `complete: true`.
  Both reported exactly one `fdco-team-epl-west_ham` creation with 266 source
  fixture ids, 266 source-evidence hashes, and 266 participant references.
- The production repair candidate hashes are manifest
  `a1eae47c4d5b86fb3b0eda2bc997f219533561f0913cd584ecc49839cfa72b62`
  and replay plan
  `9bf816061704b6c45aacdc3080eba4d25dcc0d5e007c834687f66d02d7d87bd4`.
  They identify a candidate only and do not authorize mutation.
- Final health through the Vercel deployment returned HTTP 200 and `no-store`,
  reported backend SHA `06de645a2dc57d1d10dbe53d0427e463dc10ef76`,
  PostgreSQL and Redis ready, Alembic head/applied
  `0009_quarantine_market_closings`, and strict league models loaded. The
  provider-health proxy remained non-probing and fail-closed: all five registry
  entries were `CONFIGURED_UNVERIFIED` with `live_probe_not_run` warnings.
- No production data was mutated. The live review retained
  `production_mutation_authorized: false`. Class-C apply remains blocked until a
  fresh authorization binds both hashes, the exact targets, a backup/snapshot
  reference, rollback procedure, and authorization id.

## Integration pass evidence from 2026-08-14 (post-`e0f89ae`)

Before this pass, three side branches existed
(`feat/apex-v3-activation`, `fix/httpx-odds-api-key-log-leak`,
`fix/match-selection-window-and-feature-wiring`) but were byte-identical to
`master` at `e0f89ae` — already merged, verified via `git diff master...<branch>`
returning empty for each. The only genuinely unmerged work anywhere was one
commit, `9d56ece` "redact S3 activation probe failures", on
`feat/apex-v3-activation-finalization` (one commit ahead of `e0f89ae`). It was
cherry-picked onto `master` cleanly (auto-merged, no conflict).

Separately, a UI-truthfulness defect was found and fixed: `edge_quality_score`
(a confidence/freshness/completeness composite, never a market edge) was
presented as one in three places — `match-selector.tsx`'s celebratory
"🔥 Top Edge Today" badge, `insights-tease-strip.tsx`'s bare "High/Medium/Low
Edge" tier text, and `phase8-analytics-panel.tsx`'s literal "LIVE" freshness
label on the primary `/match/[id]` page (closing `docs/DEBT.md` item 21c's
own named trigger). Full detail in `CHANGELOG.md`.

`master` HEAD is now `237c8bf` (two commits ahead of the previously-deployed
`e0f89ae`: `db26b37` the edge-quality fix, `237c8bf` the cherry-picked S3
redaction). **Not yet pushed/deployed as of this entry** — re-verify SHA
parity against Vercel/Render `/api/health` after the push. Full local gates
re-run against this exact tree: backend `ruff` clean; mypy `766 <= 784`;
backend `pytest` `1329 passed, 13 skipped`; scraper `20/20` (was 19, +1 from
the cherry-picked redaction test); web `lint` 0 warnings; web `typecheck`
clean; web Vitest `33 files / 182 tests` passed; web production build clean.

## Apex v3 production-finalization evidence from 2026-08-14

- `master`, Vercel production, and the Render API all identify code SHA
  `e0f89ae030f7c36bcb77f929a3ca46fcc65dc3c2`. Required GitHub workflows for that
  SHA ran on named GitHub-hosted runners with non-empty successful steps: canonical
  backend, web, scraper, Playwright, secret scan, Gitleaks, model-artifact, and
  large-file checks. A new candidate SHA must repeat those gates.
- Production prediction capture is **DEPLOYED / CALLED / VERIFIED** for scheduled
  fixture `fd-558223`. Two consecutive full-analysis calls remained `PARTIAL`,
  prohibited stake, and incremented `analysis.prediction_log.duplicate` from zero
  to two, proving an existing immutable row and exact-snapshot deduplication. The
  direct database count is unavailable outside Render's private network. Settlement
  is therefore DATA-FED at zero, not persistence-blocked: `/health` reports zero
  settled predictions and no settlement failures, while `/api/v1/model-performance`
  remains a structured 503. No outcome was invented or manually settled.
- Explicit bounded local live validation passed for `football_data_org`,
  `api_football`, and `sportmonks`; it failed for keyless supplementary `espn` and
  failed with redacted 401 evidence for `the_odds_api`. Public non-live health
  correctly remains configuration-only and must not be presented as production
  liveness. The Odds API credential still requires operator rotation.
- Runtime health verifies an external tier-1 Redis connection, but neither its vendor
  nor production TLS is established by available Render evidence. Gitignored local
  environment copies currently use `redis://`, not `rediss://`; they were inspected
  structurally without printing the URL. Replacement/revocation remains an operator
  gate.
- The live immutable S3 probe reached the configured bucket but failed closed with
  403 writer authorization. Read-only bucket/control checks also returned 403, so
  ownership, versioning, encryption, public-access blocking, lifecycle, and
  least-privilege IAM are not verified. The worker remains disabled and no acquisition
  canary ran. The standalone CLI now reduces SDK failures to bounded
  `error_code`/HTTP-status JSON; its redaction regression brings scraper coverage to
  20 tests.
- The deployed homepage was measured at 12 initial and 24 expanded fixture links.
  Keyboard-operable expansion, accessible soft-coverage names, display-name-first
  league identity, UCL estimated-date wording, mobile overflow protection, and the
  compact research-market empty state are present; no frontend change was needed.
- The current Vercel deployment first returned bounded no-store 503 envelopes for
  both `/api/upcoming` and `/api/value-bet-scan` during a measured Render free-tier
  cold start; direct backend health recovered to 200 after 45.67 seconds. The next
  five proxy calls per route were all 200 (upcoming 1.08-4.87 seconds; value-bet
  scan 0.99-1.62 seconds). The retained 89 platform-timeout events ended on
  2026-08-10 and belong to an older deployment.

Release decision: **NOT SAFE FOR PRODUCTION**. Real settlement/CLV thresholds,
provider and historical-secret rotation evidence, Redis TLS/vendor confirmation,
S3 authorization/controls/canary, and the stray Render service operation remain
open.

## Apex v3 implementation evidence from 2026-08-14

- On the now-deployed Apex v3 implementation, shared prediction capture and strict
  temporal joins
  **EXIST / TESTED**. A seeded test reaches scheduled verified fixture → full
  analysis → one deduplicated `MatchPredictionLog` → finished score → settled join.
  Production is still DATA-FED at zero until a real result joins; Phases F-J/N2 and
  promotion remain closed.
- Both verdict engines now make `SPECULATIVE` watchlist-only with zero stake. The RL
  advisory API was reviewed separately because it has no matching verdict taxonomy;
  its full-analysis integration still abstains/zeroes on insufficient evidence and
  applies the effective cap.
- The upcoming list can expose all 24 fetched fixtures without filtering, resets on
  league changes, gives soft coverage a visible and accessible explanation, uses
  human league names with secondary canonical IDs, and carries the UCL estimate flag
  through FastAPI/proxy/TypeScript/off-season copy. This is TESTED and deployed-page
  VERIFIED evidence.
- Ruff's CI-blocking E402 is fixed. Mypy is pinned to 2.1.0; the local count is 766
  errors in 123 files / 236 checked files, and CI now enforces the 784 ceiling instead
  of marking the step advisory.
- S3 checksum, matching-412 replay, conflicting-412, outage continuity/redaction,
  manifest hash, and fixed-context probe behavior are mocked and TESTED (20 scraper
  tests total). The gitignored root/backend env files agree on structurally valid,
  unmasked credentials and the existing `sabiscore-artifacts-prod-uswest2` regional
  configuration; their values were compared without printing secrets. The Render
  blueprint is aligned but the live dashboard is unverified. Read-only AWS
  `HeadBucket` and `GetBucketLocation` calls both returned 403, so bucket identity,
  controls, and writer authorization are not VERIFIED. The live mutating probe was
  run once and failed 403 before writing; acquisition was not run and the worker
  remains disabled.
- Local release gates completed after the final accessibility fixes: backend
  `1329 passed, 13 skipped`; focused backend `163 passed`; Ruff clean; mypy 766
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
