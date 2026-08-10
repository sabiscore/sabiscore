# SabiScore

SabiScore is a production football intelligence platform built around a FastAPI backend, a Next.js web app, and a bounded scraper worker.

The canonical production surfaces are:

- Backend: `backend/src/api/main.py`
- Web app: `apps/web`
- Scraper worker: `apps/scraper`

Legacy roots such as `apps/api` and `frontend/` are not production deployment targets.

## Production Contract

- FastAPI is the only authority for provider access, evidence collection, prediction analysis, verdicts, expected value, and Kelly stake sizing.
- Browser code proxies backend routes only. Provider credentials are backend-only and must never use `NEXT_PUBLIC_*`.
- ESPN is keyless, unofficial, supplementary evidence only, and never model truth.
- Coherent 1X2 market snapshots must come from one bookmaker. Cross-bookmaker comparison is display-only.
- Missing evidence, stale critical data, source conflict, missing coherent odds, or incomplete model metadata returns `PARTIAL` or pass/no-bet states instead of synthetic values.
- Database schema changes are Alembic-managed. App imports/startup do not create production tables.
- SQLite fallback is disabled by default and only allowed for isolated tests or explicit local development via `ALLOW_SQLITE_FALLBACK=true`.

## Quick Start

Python 3.11 through 3.14 is supported for the API runtime. Python 3.14 uses newer wheel-backed scientific packages; optional CatBoost, SHAP, MLflow, and Great Expectations training extras should run in a Python 3.11-3.13 training environment until their Python 3.14 wheel stacks are dependable.

For offline model research, install `backend/requirements-training.txt` in a
separate Python 3.11-3.13 virtual environment and run
`backend/scripts/verify_training_stack.py`. Importability does not certify or
promote a model; production activation is controlled by the reviewed,
hash-validated active-generation manifest.

Kafka clients and browser automation packages are treated as optional worker dependencies on Python 3.14/Windows because they otherwise require native toolchains or older `greenlet` pins. The canonical API/provider gateway does not import them at runtime.

Use Node 22 through 24 and pnpm 8 through 11 with this lockfile. Do not run `corepack enable` on Windows unless you have admin rights and intentionally want Corepack shims installed globally.

```bash
pnpm install --frozen-lockfile

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
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
