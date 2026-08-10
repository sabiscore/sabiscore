# SabiScore Deployment Guide

Last verified against the repository: 2026-08-10.

Production entrypoints are `backend/src/api/main.py` and `apps/web`. Do not deploy
the archived `frontend/` or reintroduce `apps/api/`.

## 1. Pre-deployment gates

From a clean release checkout:

```powershell
python scripts/check-codex-skills.py
python backend/scripts/verify_active_artifacts.py
docker compose -f docker-compose.prod.yml config --quiet
pnpm --filter @sabiscore/web lint
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

Run backend Ruff, mypy, full pytest, OpenAPI verification, Gitleaks, Alembic
upgrade/check against staging PostgreSQL, sequential backend/web image builds, and
Playwright desktop/mobile gates using the exact commands in current CI/Makefile.
Default CI keeps `PROVIDER_LIVE_TESTS=false`.

Do not promote an artifact whose candidate manifest says
`promotion_permitted: false`.

## 2. Secrets and environment

Store secrets in Render/Vercel/provider secret stores, never in files or command
output. Required production defaults include:

```env
DEBUG=false
MOCK_MODE=false
ENABLE_LEGACY_INFERENCE=false
ALLOW_SQLITE_FALLBACK=false
PROVIDER_LIVE_TESTS=false
USE_PHASE9_CANDIDATE_FEATURES=false
PHASE9_SHADOW_ONLY=true
```

`DATABASE_URL` must be PostgreSQL with TLS. `REDIS_URL` must be a complete
`redis://` or preferably `rediss://` URL. Provider keys and `SECRET_KEY` are
server-only. Never expose them as `NEXT_PUBLIC_*` values.

For a credential incident: create replacement, update the platform secret, verify
TLS/application behavior, revoke the exposed credential, and scan redacted logs.

## 3. Backend on Render

`render.yaml` is authoritative. Its build installs requirements and verifies the
active artifact pairs. Startup applies `alembic upgrade head` and then launches
Uvicorn; `/health/ready` is the deployment gate.

Before promotion, verify these endpoints without printing credentials or raw
provider payloads:

```text
GET /health/ready
GET /api/v1/providers/health
GET /api/v1/upcoming/all
GET /models/status
GET /matches/upcoming/{verified_fixture_id}/full-analysis
```

Record the `sha` returned by health. A fail-closed `No bet` is a valid product
result; a fabricated probability or stake is not.

## 4. Frontend on Vercel

Build `apps/web` with pnpm. Configure `SABISCORE_BACKEND_URL` as a server-only
value. Do not configure provider keys in Vercel.

After CI succeeds:

1. create the Vercel deployment from the reviewed release SHA;
2. wait for `READY`;
3. explicitly promote it to production;
4. verify `/api/health` and the public aliases;
5. confirm frontend and backend report the expected release SHAs;
6. exercise homepage fixture selection and one verified full-analysis flow on
   desktop and mobile.

## 5. Database and models

Alembic alone manages schema. Never run `Base.metadata.create_all()` or legacy
`init_db.py` as a production migration substitute.

Model promotion switches a complete hashed manifest atomically. Keep the prior
manifest and artifacts. `/models/status` must agree with the promoted manifest and
must report the exact served head, feature schema/count, training window,
calibration/validation state, artifact type, and hash.

## 6. Activation window and rollback

Run controlled live-provider checks only after offline gates pass. Verify one real
fixture through identity, evidence acquisition, forecast or explicit abstention,
persistence, and eventual settlement/CLV join. No forced probability or bet is
required.

Exercise rollback once before declaring production readiness: restore the prior
artifact manifest and backend/frontend deployments, verify readiness and SHAs, then
re-promote the reviewed release. Follow [rollback.md](rollback.md); never force-push
or rewrite protected history.

## 7. Release decision

Use exactly one status:

- `NOT SAFE FOR PRODUCTION` if any P0/P1, credential rotation, CI, migration,
  Docker, provider, live probe, or deployment proof is blocked.
- `READY WITH DOCUMENTED LIMITATIONS` only when safely deployed and live model
  performance is truthfully pending.
- `PRODUCTION READY` only when no material limitation remains.
