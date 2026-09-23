# SabiScore (APEX Generation v5_phase7)

SabiScore is a football intelligence platform built around a FastAPI backend, a Next.js web app,
and a bounded scraper worker. It currently runs in **Research Mode**: forecasts are served, and
staking is fail-closed.

The predictive engine runs APEX generation `v5_phase7`. That generation's manifest
(`backend/models/active_generation.json`) declares `certification_state: UNVERIFIED` and
`promotion_state: ACTIVE_FAIL_CLOSED`, so `stake_permitted` is `false` platform-wide and no Kelly
stake is sized for a user. Certification gates G11/G27 are **measured, not passed** — see
`docs/DEBT.md` for the open items and `backend/src/models/certification_policy.py` for the
promotion gates themselves.

Post-hoc calibration is applied **only where held-out evidence supports it**. On the current
generation that is two of six leagues (Bundesliga, Ligue 1); the other four serve their raw
meta-model output and report `calibration_applied: false`. Calibrators are accepted solely when
holdout ECE improves and holdout Brier does not degrade — a calibrator is never forced into
production because it looks good on the rows it was fitted on (`docs/DEBT.md` item 96).

The canonical production surfaces are:

- Backend: `backend/src/api/main.py`
- Web app: `apps/web`
- Scraper worker: `apps/scraper`

The legacy `apps/api/` and `frontend/` roots were removed on 2026-09-23 (OG-11,
`docs/adr/0010-remove-apps-ws.md`). Neither was ever a production deployment
target, and both were already absent from every CI, Docker and workspace
config before deletion. Do not reintroduce them.

## Production Contract

- **Zero Fabrication:** The model operates in strict fail-closed mode. Unverified data gaps, stale dependencies, or conflicts force `PARTIAL` / no-bet rather than synthetic estimates.
- **FastAPI Authority:** FastAPI exclusively handles provider access, evidence collection, prediction analysis, verdicts, expected value, and Kelly sizing.
- **Web App Boundary:** Browser code proxies backend routes only. Provider credentials are backend-only and never exposed via `NEXT_PUBLIC_*`.
- **Market Snapshot:** Coherent 1X2 market snapshots must originate from a single bookmaker. Cross-bookmaker comparison is explicitly for display-only.
- **Database Architecture:** PostgreSQL 16+ is the sole canonical persistence tier. SQLite fallback is disabled by default. Alembic governs all database schema changes.

## Quick Start (Production-Certified Env)

Python 3.11 through 3.14 is supported for the API runtime. Python 3.14 utilizes newer wheel-backed scientific packages.

For offline model research, install `backend/requirements-training.txt` in a
separate Python 3.11-3.13 virtual environment and run
`backend/scripts/verify_training_stack.py`. Importability does not certify or
promote a model; production activation is controlled by the reviewed,
hash-validated active-generation manifest.

The canonical production backend build now installs
`backend/requirements.runtime.txt`. Keep `backend/requirements.txt` for local
development and broad repository tooling; it still includes optional research,
browser-automation, Kafka, and experiment-tracking packages that the FastAPI
runtime does not need to boot.

Kafka clients and browser automation packages are treated as optional worker dependencies on Python 3.14/Windows because they otherwise require native toolchains or older `greenlet` pins. The canonical API/provider gateway does not import them at runtime.

Use Node 22 through 24 and pnpm 8 through 11 with this lockfile. Do not run `corepack enable` on Windows unless you have admin rights and intentionally want Corepack shims installed globally.

```bash
pnpm install --frozen-lockfile

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
```

Production Docker and Render builds should use:

```bash
pip install -r backend/requirements.runtime.txt
```

Run the backend:

```bash
cd backend
alembic upgrade head
python -m uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

Run the web app:

```bash
pnpm --filter @sabiscore/web dev
```

The web app reads `SABISCORE_BACKEND_URL` server-side and serves browser API calls through Next.js routes.

## Environment

The backend reads the project-root `.env` first and `backend/.env` second, so
backend-local values override shared templates.

Start from sanitized templates:

- Root template: `.env.example`
- Backend template: `backend/.env.example`
- Web template: `apps/web/.env.example`
- Production template: `.env.production.example`

Provider keys are backend-only and the canonical names live in
`backend/.env.example`:

- `FOOTBALL_DATA_API_KEY`
- `API_FOOTBALL_API_KEY` (legacy alias: `API_FOOTBALL_KEY`)
- `SPORTMONKS_API_TOKEN` (legacy alias: `SPORTMONKS_API_KEY`)
- `THE_ODDS_API_KEY`

ESPN is keyless. If a real provider key was ever committed or copied into a frontend/Vercel public variable, rotate it in the provider console.

Focused safety gate:

```bash
cd backend
python -m pytest tests/test_secret_safety.py tests/test_database_migration_hardening.py tests/test_providers_gateway.py -q --no-cov
```

## Provider Gateway

Provider discovery:

```bash
cd backend
python -m src.cli providers doctor
python -m src.cli providers capabilities
python -m src.cli providers quota
```

API routes:

- `GET /api/v1/providers`
- `GET /api/v1/providers/health`
- `GET /api/v1/providers/capabilities`
- `GET /api/v1/providers/quota`

## Intelligence Workflow

The production UI lives at `/intelligence` in `apps/web`. It provides competition filtering, team search, date filters, fixture cards, evidence readiness, source comparison, provider odds candidates, manual odds fallback, and backend-returned decision cards.

## Model Training

Two corpora exist and they are not interchangeable:

| Path | Contents | Use |
| --- | --- | --- |
| `backend/data/cache/fd_*.csv` | **12,765 real matches**, 6 leagues, 2019-09 → 2026-05, 100% with opening 1X2 odds | **Canonical.** Every trainer should read this. |
| `data/processed/*_training.csv` | 2,058 rows; `xg_differential`, `elo_difference` and the xg-diff columns are zero in 85% of rows, and the Eredivisie slice is generated synthetically by `scripts/generate_eredivisie_data.py` | Legacy. Retained for reproducing older runs only. |

Features are built by `backend/scripts/train_on_real_matches.py::build_dataset`,
which walks forward in time — a match never sees its own result — and computes
every group through the same shared `feature_registry` helpers that live serving
uses. That train/serve parity is the governing constraint: a model must only be
trained on features that are genuinely resolved at request time.

```bash
# Ensemble candidate (baseline hyperparameters)
cd backend && python scripts/train_on_real_matches.py

# …with Bayesian (Optuna TPE) hyperparameter search, ~30 trials per learner
python scripts/train_on_real_matches.py --tune 30

# Uncertainty (BNN) member — defaults to the real corpus
python scripts/train_bnn.py                     # --corpus processed for the legacy CSVs
```

`--tune` searches `n_estimators` / `max_depth` / `learning_rate` / `reg_lambda`
(plus subsample and colsample) for RandomForest, XGBoost and LightGBM. It scores
**RPS** — the metric `model_registry.compare_models` promotes on — over a
`TimeSeriesSplit` of the **training slice only**, so the calibration and holdout
seasons stay unseen and the reported holdout RPS remains out-of-sample. A
`MedianPruner` abandons weak trials after their first fold and trials run
single-threaded, which is what keeps a laptop run inside memory. Omitting
`--tune` reproduces the baseline hyperparameters exactly.

> **CatBoost is not tunable in this workspace.** It is pinned
> `python_version < "3.14"` in `requirements.txt` and has no wheel for a 3.14
> interpreter (production runs 3.11). Its parameters map onto the two
> gradient-boosted learners that are available — `depth` → `max_depth`,
> `l2_leaf_reg` → `reg_lambda`, `iterations` → `n_estimators` — so the same axes
> are searched.

### Reading the scores

Brier is reported **summed over the three classes**. On that scale the de-vigged
bookmaker market — the strongest available 1X2 forecaster — scores **0.5787**
over the corpus above, and a uniform 1/3 forecaster scores 0.6667. A model near
0.58 is at market level, not broken. See `docs/DEBT.md` item 43: `train_bnn.py`'s
`BRIER_GATE = 0.220` sits below the market's own score and no honest model can
pass it.

## Verification

```bash
make verify
```

The `verify` target runs the focused secret/provider gates, backend tests, provider CLI doctor, scraper tests, web lint/typecheck/tests, and web build.

Run the canonical Linux CI workflow from this workstation (recommended before release or merge):

```powershell
pwsh -File scripts/run-canonical-ci.ps1 -Branch master
```

This dispatches `.github/workflows/ci.yml`, waits for completion, and fails fast when the workflow conclusion is not `success`.

## Documentation

The authoritative deployment and operations guide is [docs/SABISCORE_PRODUCTION_SETUP_GUIDE.md](docs/SABISCORE_PRODUCTION_SETUP_GUIDE.md).
