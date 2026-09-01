# SabiScore Deployment Guide

Last verified against the repository: 2026-09-01.

Production entrypoints are `backend/src/api/main.py` and `apps/web`. Do not deploy
the archived `frontend/` or reintroduce `apps/api/`.

## 1. Pre-deployment gates

From a clean release checkout:

```powershell
python scripts/check-codex-skills.py
python backend/scripts/verify_active_artifacts.py
node apps/scraper/src/cli.mjs registry validate
docker compose -f docker-compose.prod.yml config --quiet
pnpm --filter @sabiscore/web lint
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
pnpm --filter @sabiscore/web build
```

Run backend Ruff, mypy, full pytest with branch coverage, OpenAPI verification,
Gitleaks, Alembic upgrade/check against PostgreSQL, scraper validation/tests,
web lint/typecheck/unit tests/build, and Playwright smoke plus Tier 1-4 desktop
and mobile gates using the exact commands in current CI/Makefile. Default CI
keeps `PROVIDER_LIVE_TESTS=false`.

If the evidence-acquisition worker is part of a release, also validate scraper
parsers and source policy before enabling cron execution:

```powershell
pnpm --filter @sabiscore/scraper test
node apps/scraper/src/cli.mjs registry validate
```

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

`DATABASE_URL` must be PostgreSQL with TLS. Production `REDIS_URL` must be a
complete `rediss://` URL; plaintext `redis://` is local-development only. Provider keys and `SECRET_KEY` are
server-only. Never expose them as `NEXT_PUBLIC_*` values.

Alembic revision `0011_user_identity_dev_platform` creates the user-state,
developer-key, analytics, and notification tables. Its revision identifier is
intentionally at most 32 characters to fit the existing
`alembic_version.version_num` column. A release must exercise the complete chain
on PostgreSQL; SQLite does not enforce that length and cannot prove this gate.

`REVALIDATE_SECRET` is a separate server-only secret shared by the backend and
Vercel. Configure the same non-empty value in both secret stores before relying
on on-demand page invalidation. When it is absent, `/api/revalidate` returns a
structured `503` and the backend skips the request; it never falls back to a
predictable development token.

For the open Render Redis incident, operators must complete and record this exact
sequence without copying credentials into tickets or logs:

1. provision a replacement Redis instance/credential with TLS required;
2. set the complete `rediss://` value in the protected Render `REDIS_URL` secret;
3. verify TLS connectivity and require `/health/ready` to report the external cache available;
4. revoke the old credential after the replacement is serving;
5. redeploy the reviewed backend SHA and verify startup/runtime logs are redacted;
6. retain provider-side rotation/revocation evidence in the private incident record.

In-memory fallback can preserve liveness, but it never satisfies production cache readiness.

## 3. Backend on Render

`render.yaml` is authoritative. Its build installs requirements and verifies the
active artifact pairs. Startup applies `alembic upgrade head` and then launches
Uvicorn; `/health/ready` is the deployment gate.

The canonical backend production install surface is
`backend/requirements.runtime.txt`, not the broader local-development
`backend/requirements.txt`. Runtime-only builds must stay off the optional
research, browser-automation, Kafka, and experiment-tracking dependency tree
unless a reviewed production change explicitly requires it.

The Render blueprint also includes a disabled-by-default scraper cron service
(`sabiscore-evidence-acquisition`). Its desired evidence-storage configuration is
the existing private bucket `sabiscore-artifacts-prod-uswest2` in `us-west-2`, using
the standard regional endpoint, virtual-host addressing, and SSE-S3 `AES256`.
Credentials remain Render secrets supplied through the AWS SDK credential chain.
Keep `SCRAPER_PRODUCTION_ENABLED=false` until the controls in
`docs/S3_EVIDENCE_STORAGE_RUNBOOK.md` are directly verified, the immutable storage
probe and one bounded acquisition succeed, and database ingestion is confirmed.

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

Build `apps/web` with pnpm. Configure `SABISCORE_BACKEND_URL` and
`REVALIDATE_SECRET` as server-only values. Do not configure provider keys in
Vercel.

After CI succeeds:

1. create the Vercel deployment from the reviewed release SHA;
2. wait for `READY`;
3. explicitly promote it to production;
4. verify `/api/health` and the public aliases;
5. confirm frontend and backend report the expected release SHAs;
6. exercise homepage fixture selection and one verified full-analysis flow on
   desktop and mobile.

Also exercise registration/login/logout, anonymous-state merge, dashboard CRUD,
developer-key create/list/revoke, analytics ingestion, notification subscription
and read state, calibration rendering, share-card generation, and sitemap/JSON-LD
output. Notification delivery scheduling and live fixture sitemap discovery are
not release-ready until their production callers are implemented and observed.

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
