# SabiScore — Rollback Instructions (C-25)

This document satisfies certification gate C-25 of the SABI-CORE vΩ.1 directive.

## Quick rollback (git)

```bash
# Identify the last known-good commit
git log --oneline -10

# Rollback to a specific commit (DESTRUCTIVE — loses local uncommitted changes)
# Create a reviewed revert commit; never rewrite shared or protected history.
git revert <bad-sha> --no-edit
```

## Historical examples only

The SHAs below are historical records, not current certification. Read the
last-known-good SHA from the successful deployment itself before any rollback.

```
a6c4fe6  feat: SABI-CORE production hardening — zero-fabrication, provider ceilings, league policy
```

Previous stable commit: `a5a94f9 feat: finalize production data intelligence workflow`

---

## Model artifact rollback

1. Read the active release manifest and verify its hashes before promotion.
2. Retain the prior manifest and artifacts as an immutable last-known-good set.
3. Revert the single release commit that changed the complete artifact set and
   `backend/models/active_generation.json`; do not copy individual model files
   across generations or edit hashes by hand.
4. Run `python backend/scripts/verify_active_artifacts.py` and both-loader smoke
   tests, restart the backend, and verify `/health/ready` plus `/models/status`.
5. Record the restored model version and hash, then restore the newer manifest
   only after the incident is resolved and the same gates pass.

The manifest is fail-closed: a missing file, path escape, or SHA-256 mismatch
must prevent model readiness. A rollback is incomplete until both production
loaders consume the same verified generation and `/api/v1/models/status` reports
the expected generation, manifest hash, certification state, and release SHA.

MLflow and `ModelRegistry` are research records, not deployment authorities. Do
not roll back a model by changing an MLflow stage or editing local registry
metadata. If an optional research dependency causes a workstation failure, remove
and recreate only the isolated `.venv-ml` from
`backend/requirements-training.txt`; do not change API runtime dependencies or the
active-generation manifest.

## Service-level rollback

### Backend (FastAPI)

```bash
# Railway / any PaaS
railway rollback            # rolls back to previous deploy

# Docker Compose (self-hosted)
docker compose -f docker-compose.prod.yml down
docker pull sabiscore-backend:<previous-tag>
IMAGE_TAG=<previous-tag> docker compose -f docker-compose.prod.yml up -d
```

### Frontend (Vercel)

1. Record the failing production deployment id and its source SHA.
2. Find the last green deployment whose source SHA matches the paired backend
   release and whose browser/API probes were recorded.
3. Promote that exact deployment; do not trigger a rebuild from a moving branch.
4. Verify production aliases, the custom domain, CSP, release SHAs, five bounded
   upcoming probes, and the observation-window error cluster before declaring
   rollback complete.

Do not promote a preview while GitHub release checks, backend same-SHA proof, or
the Redis operator checkpoint is incomplete.

### Database

Alembic migrations are additive and backward-compatible. A code rollback does **not** require a database rollback unless a migration added a column that the rolled-back code rejects.

To check: `alembic history` — compare against the new code's expectations.

If a downgrade is needed:

```bash
cd backend
alembic downgrade -1          # one step back
alembic downgrade <revision>  # specific revision
```

**Never** run `alembic downgrade base` in production. Alembic migrations are designed to be applied forward only in production; reserve full downgrades for staging.

---

## Environment variable rollback

### Evidence-storage worker

If S3 activation or acquisition is implicated, set
`SCRAPER_PRODUCTION_ENABLED=false`, stop the exact scraper worker, and revoke only
its scoped AWS access key. Do not delete the retained bucket or archived objects.
Local/Postgres ingestion continuity remains available while S3 is unavailable;
re-enable the worker only after the fixed-context immutable-write/checksum/conflict
probe succeeds. See `docs/S3_EVIDENCE_STORAGE_RUNBOOK.md`.

If a credential or feature flag change caused the rollback, revert only those variables in your hosting environment without redeploying code:

| Provider issue | Fix |
|---|---|
| FDO 400 errors | Rotate `FOOTBALL_DATA_API_KEY` in provider console; update env |
| API-Football quota | Set `API_FOOTBALL_DAILY_REQUEST_LIMIT` lower; or set `ENABLE_API_FOOTBALL_PROVIDER=false` |
| Odds API credit burn | Set `THE_ODDS_API_MONTHLY_CREDIT_LIMIT`; or disable with `ENABLE_THE_ODDS_API_PROVIDER=false` |
| All providers failing | Keep `PROVIDER_FAIL_CLOSED=true`; inspect `/api/v1/providers/health` and redacted backend logs, then disable only the affected provider flags while diagnosing |
| Mock data in prod | Confirm `MOCK_MODE=false` and `DEBUG=false` |

Never disable fail-closed behavior in production, including during diagnosis.
Provider isolation must use the individual `ENABLE_*_PROVIDER=false` switches;
missing evidence must continue to surface as a structured gap or `PARTIAL` state.

---

## Rollback decision matrix

| Symptom | Rollback? | Action |
|---|---|---|
| 5xx rate spikes on `/api/v1/providers/*` | Maybe | Check provider health first; may be upstream |
| Verdicts all returning PARTIAL | No | Check `verified_evidence_providers` in request payload |
| Kelly stakes suddenly 2× expected | Investigate | LeaguePolicy kelly_cap may have changed; check `league_policy.py` |
| Frontend shows all providers ✗ | No | Backend startup issue; check `/health/ready` |
| `test_no_synthetic_scrapers` fails in CI | Code rollback | Revert any scraper changes that re-introduced `_simulate_` |
| Alembic drift detected | Schema rollback | Run `alembic downgrade -1` then fix migration |

---

## Health check endpoints (production monitoring)

```
GET /health/live    → 200 if process is running
GET /health/ready   → 200 if DB + critical deps are up
GET /health         → full health JSON
GET /api/v1/providers/health  → per-provider status
```

A successful rollback should restore `/health/ready` to 200 and `/api/v1/providers/health` to show at least one provider as `VERIFIED` or `CONFIGURED_UNVERIFIED`.

---

## Post-rollback checklist

- [ ] `/health/ready` returns 200
- [ ] At least one provider returns non-`UNAVAILABLE` status
- [ ] A test verdict request returns a valid `MatchAnalysisResult` (not 500)
- [ ] Frontend loads `/intelligence` without CSP or hydration errors
- [ ] No new Gitleaks findings in the rolled-back commit
- [ ] Alembic reports no drift: `alembic check`
