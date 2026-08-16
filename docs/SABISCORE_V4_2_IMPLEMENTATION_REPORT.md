# SabiScore v4.2 Production Activation Report

## 1. Executive Result

```text
PRODUCTION STATUS: RELEASE CANDIDATE — full CI/deploy verification blocked in this sandbox
PREDICTION CAPABILITY: EXISTS / WIRED — fail-closed research forecasts preserved
MODEL CERTIFICATION: UNVERIFIED (active generation v5_phase7-20260808)
PUBLIC ACTIONABILITY: DISABLED until canonical certification is CERTIFIED
MARKET/CLV STATUS: existing paths preserved; current live provider/CLV state NOT VERIFIED here
DEPLOYMENT STATUS: NOT RUN — uploaded archive has no .git metadata and external package/deploy access is unavailable
```

## 2. Verified Starting State

The working copy was extracted from the supplied SabiScore archive. The archive does not contain `.git`, so no branch/HEAD assertion can be independently made from this sandbox. The previously recorded archive snapshot marker is `427c2cd53d95fc4a187e2794e001f747d097768a`; it is an archive marker, not a verified current Git SHA.

`backend/models/active_generation.json` remains the serving authority: generation `v5_phase7-20260808`, active version `v5_phase7`, feature schema `phase7_68`, served head `SoftmaxMetaModel`, certification `UNVERIFIED`, promotion state `ACTIVE_FAIL_CLOSED`, with six manifested league artifacts. UCL remains soft/generic coverage rather than a dedicated manifested UCL artifact.

Provider live validation remains opt-in; routine health must not spend provider quota. The runtime architecture remains FastAPI + PostgreSQL + Redis with Next.js/TanStack Query on the web frontend and one Render Uvicorn worker in the supplied blueprint.

## 3. Root Causes Resolved

### Provider-state truth

**Symptom:** configured but intentionally unprobed providers could render as `Partial` / `0 live`, visually implying failure.

**Root cause:** frontend readiness arithmetic treated explicit live verification as a prerequisite for configuration health.

**Correction:** provider configuration/enabled state is now distinct from negative live evidence and from explicit validation. `CONFIGURED_UNVERIFIED` is neutral. Routine health remains probe-free.

**Maturity:** EXISTS / TESTED by focused source-contract tests; full web test run BLOCKED by package-manager environment.

### Fixture freshness truth

**Symptom:** absent staleness could become `0` and render `Fresh`.

**Root cause:** null-coalescing at the UI boundary collapsed unknown evidence into the strongest freshness state.

**Correction:** a shared freshness mapper treats missing, null, malformed, negative, or explicitly unavailable age as `Unknown`; explicit measured zero is the only zero-age Fresh case.

**Maturity:** EXISTS / TESTED by new focused unit cases; full web suite BLOCKED here.

### Model provenance and schema integrity

**Symptom:** canonical `PredictionEngine` could label a dict-shaped artifact `v6_phase8` regardless of active manifest and could truncate an oversized feature vector to the model width.

**Root cause:** semantic provenance was inferred from Python serialization shape and width mismatch was treated as a compatibility path.

**Correction:** generation/version/schema/hash/certification provenance comes from the verified active-generation manifest. Both narrower and wider schema mismatches fail closed rather than pad/truncate silently.

**Maturity:** EXISTS / WIRED; immutable artifact verifier PASS; focused pytest execution BLOCKED by missing `redis` dependency in this sandbox.

### Uncertified public value/stake leakage

**Symptom:** upcoming or legacy prediction paths could derive positive value/Kelly output from a valid but `UNVERIFIED` active generation; old cached payloads could preserve pre-gate stakes.

**Root cause:** certification gating was stronger in Full Analysis than in all public prediction/value surfaces.

**Correction:** research probabilities may remain visible, but value bets and RL/Kelly stake are stripped/zeroed unless the canonical active generation is `CERTIFIED`. Cached legacy responses are re-gated on read.

**Maturity:** EXISTS / WIRED; code-level regression cases added; full pytest BLOCKED here.

### Elo identity and durability

**Symptom:** live Elo depended on a Parquet keyed by synthetic IDs and the Render filesystem was not a durable production state authority.

**Root cause:** historical/offline Elo storage was reused as live transactional state.

**Correction:** Alembic `0007_durable_elo_state` adds PostgreSQL `elo_rating_snapshots`. Serving resolves ratings by real `Team.id`; finished matches update the durable state chronologically and idempotently through the settlement flow. Historical replay is dry-run by default and mutates only with `--apply`. Parquet remains offline/backward-compatible tooling.

**Maturity:** EXISTS / WIRED. SQLAlchemy metadata smoke PASS. Production migration/backfill is NOT RUN and must be verified before DATA_FED/VERIFIED.

### Mobile operational truth and loading-state fabrication

**Symptom:** mobile status used approximate/hard-coded operational labels and the loading screen generated pseudo H2H facts from team-name hashes or implied unverified evidence was being processed.

**Root cause:** duplicate status logic and decorative loading content were not bound to evidence authority.

**Correction:** mobile and desktop share model-status/provider sources. Loading copy is conditional and no longer fabricates H2H/xG/injury/market claims.

**Maturity:** EXISTS / TESTED by source-level focused tests; full web suite BLOCKED here.

## 4. Prediction-Quality Improvements

No claim of higher RPS, Brier score, calibration, ROI, CLV, or betting accuracy is made from these engineering changes alone.

- Elo resolution change by league: **NOT MEASURED** — production DB migration/backfill not run.
- Feature availability change by league: **NOT MEASURED** in a production-equivalent dataset.
- Market availability: **NOT VERIFIED** in this sandbox.
- RPS/Brier/calibration: **NOT MEASURED**; no new production model was promoted.
- Market benchmark: **NOT MEASURED**.
- CLV sample/status: **NOT VERIFIED**.
- Candidate/incumbent result: **NO CANDIDATE PROMOTED**.

The quality improvement delivered in this patch is principally trust/integrity: schema mismatch fails closed, provenance is authoritative, real-ID durable Elo can be data-fed, and uncertified generations cannot produce public stake/value output.

## 5. UX / Trust Improvements

Provider configuration is no longer conflated with quota-consuming live validation. Missing freshness renders Unknown. Mobile status exposes active model/certification/provider configuration through shared authoritative queries. Ordinary league labels are human-readable. Full-analysis evidence/freshness handling is consolidated and redundant narrative/actionability content is reduced. Loading-state pseudo facts were removed. The existing design and data-visualization components were reused instead of adding duplicate gauges/passports/cards or unmeasured GSAP/Lenis dependencies.

## 6. Validation Matrix

| Check | Status | Evidence |
|---|---|---|
| Active artifact integrity | PASS | `python scripts/verify_active_artifacts.py` verified 6 hash-locked artifact pairs for `v5_phase7-20260808`; certification remains UNVERIFIED. |
| Python syntax compilation | PASS | `python -m compileall -q backend/src backend/scripts/replay_elo_from_db.py backend/tests`. |
| SQLAlchemy Elo metadata smoke | PASS | In-memory metadata creation included `elo_rating_snapshots`. |
| Changed TS/TSX syntax transpilation | PASS | Available global TypeScript compiler transpiled changed source/test files without syntax diagnostics. |
| Focused/full pytest | BLOCKED | Test collection fails because sandbox Python environment lacks the `redis` package. This is not recorded as a code failure or pass. |
| Ruff | BLOCKED | Ruff executable/package is not installed in the sandbox. |
| pnpm lint/typecheck/test/build | BLOCKED | pnpm is not provisioned; Corepack package retrieval cannot reach npm (`EAI_AGAIN`). |
| Alembic production migration | NOT RUN | No authorized production DB connection in this archive execution context. |
| Elo production replay | NOT RUN | Requires production DB/operator authorization after migration. |
| Live provider validation | NOT RUN | Intentionally quota-consuming and not required for routine health. |
| Render/Vercel deployment | NOT RUN | Archive lacks `.git`; deployment/network authority unavailable. |

## 7. Model Promotion Evidence

```text
generation: v5_phase7-20260808
active_version: v5_phase7
manifest_sha256: verified by canonical artifact verifier; exact runtime deployment value not independently observed here
dataset_hash: NOT RECOMPUTED
feature_schema: phase7_68
training_window: unchanged / see committed model metadata
calibration_window: unchanged / see committed model metadata
evaluation_window: unchanged / see committed model metadata
per_league_metrics: NOT RE-RUN
market_baseline: NOT RE-RUN
calibration_status: UNVERIFIED for public certification
feature_availability: NOT RE-MEASURED production-wide
promotion_permitted: NO
certification_state: UNVERIFIED
```

No Phase-8 model was promoted. The directive now recognizes the registry-authoritative Phase-8 candidate width as 89 while retaining legacy `CANONICAL_FEATURES_86` identifiers only as compatibility aliases.

## 8. Runtime / Deployment Evidence

- Render API: NOT DEPLOYED/VERIFIED from this sandbox.
- Vercel web: NOT DEPLOYED/VERIFIED from this sandbox.
- PostgreSQL: schema code/migration exists; target production migration NOT RUN.
- Redis: required by application/test environment, but the sandbox Python package is unavailable; production connection state NOT VERIFIED here.
- OpenTelemetry: existing architecture preserved; no second tracing stack introduced.
- Background jobs: fixture/settlement/CLV architecture preserved. Elo advancement is coupled to settlement rather than adding a competing independent scheduler.
- Provider states: configuration semantics corrected; current quota-consuming live states NOT PROBED.
- Elo durability: code authority is PostgreSQL after migration; production row coverage NOT YET VERIFIED.
- Model generation: committed active manifest remains `v5_phase7-20260808`, UNVERIFIED.

## 9. Remaining Debt

| Severity | Impact | Maturity | Owner type | Trigger / next action |
|---|---|---|---|---|
| High | Full release confidence | BLOCKED | Release operator / CI | Run canonical backend + web CI with dependencies, including Ruff, pytest, lint, typecheck, Vitest, production build, Alembic check, and Playwright. |
| High | Elo feature availability | WIRED | DB/operator | `alembic upgrade head`, dry-run replay, explicit apply, then verify row/team coverage and real fixture resolution. |
| High | Public betting actionability | UNVERIFIED | ML/governance | Keep public staking disabled until canonical certification gates pass on real evaluation evidence. |
| Medium | Tactical/StatsBomb features | DATA_GAP | Data/ML | Regenerate real-ID, point-in-time-correct tactical evidence only if measured incremental value justifies the work. |
| Medium | Live market/CLV | NOT VERIFIED | Provider/operator | Run explicit provider validation under quota controls, then observe coherent market + settlement/CLV joins. |
| Medium | Elo concurrent worker evolution | ACCEPTED current single-worker topology | Platform | If background work is extracted/horizontally scaled, add a DB/advisory/distributed lock or durable outbox worker contract around Elo advancement. |
| Low | Legacy Phase-8 `86` identifiers | COMPATIBILITY | Backend/ML | Rename only in a controlled compatibility migration; current runtime/docs should use registry-derived 89 count. |

## 10. Operator Actions

On an authorized checkout/environment with production credentials:

```bash
# 1. Install canonical dependencies and run the full release gates first.
pnpm install --frozen-lockfile
cd backend
python -m pip install -r requirements.txt -r requirements-dev.txt
ruff check src --select E4,E7,E9,F
python scripts/check_mypy_ceiling.py --ceiling 784
pytest tests -q
python scripts/verify_active_artifacts.py

# 2. Point DATABASE_URL at the intended Postgres and migrate.
alembic upgrade head
alembic check

# 3. Audit Elo before mutation, then explicitly backfill.
python scripts/replay_elo_from_db.py --dry-run
python scripts/replay_elo_from_db.py --apply

# 4. Return to workspace and run frontend/scraper gates.
cd ..
pnpm --filter @sabiscore/scraper validate
pnpm --filter @sabiscore/scraper test
pnpm --filter @sabiscore/web lint
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

After deployment, inspect the intended Render/Vercel build identities, API live/ready/detailed health, Alembic head, Redis status, Elo readiness (`authority=postgres` plus real row/team coverage), active generation/certification, and one verified upcoming fixture. Run provider live validation separately only when quota spend is authorized.

## 11. Git / Release State

```text
branch: NOT VERIFIABLE — supplied archive has no .git metadata
commit(s): NONE CREATED in this sandbox
pushed: no
production_deployed: no
rollback: apply/revert the generated patch from the original supplied archive; migration 0007 has an explicit downgrade but production downgrade requires normal change control
working_tree: upgraded archive prepared; full canonical CI remains BLOCKED in this sandbox
```
