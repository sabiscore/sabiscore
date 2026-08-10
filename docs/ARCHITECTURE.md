# SabiScore Architecture

Last verified against the repository: 2026-08-10.

## Production boundaries

```text
Browser
  -> apps/web (Next.js 15, React 18; UI and validated proxy routes)
       -> backend/src/api/main.py (FastAPI authority)
            -> provider registry + one lifespan httpx.AsyncClient
            -> one request-scoped evidence snapshot
            -> feature projection -> active model -> evidence/stake gates
            -> PostgreSQL (Alembic schema authority)
            -> Redis (cache/rate-limit acceleration; explicit degraded state)

apps/scraper -> open/batch acquisition and raw manifests only
```

The FastAPI backend is the only authority for provider credentials, identity
reconciliation, evidence provenance/freshness/conflicts, feature construction,
model inference, calibration/uncertainty, EV, Kelly sizing, verdicts, settlement,
and persistence. The web application never calls provider hosts or computes an
official probability, edge, stake, or verdict.

Legacy `frontend/` and `apps/api/` code is not a production entrypoint.

## Evidence and prediction flow

1. A stable verified fixture ID is the primary input. A matchup string remains a
   compatibility path and is explicitly hypothetical/non-executable.
2. The injected odds service obtains a coherent home/draw/away market from one
   bookmaker event snapshot. Cross-bookmaker, incomplete, stale, malformed, or
   schema-drifted records are rejected.
3. The same snapshot is reused for market features, full analysis, edge, CLV
   capture, persistence, and the evidence passport.
4. Feature projection requires explicit availability. Projection failure skips
   inference; missing inputs are never repaired with zeros, means, or placeholders.
5. Raw and calibrated probability vectors must be finite, bounded, and sum to one.
   Invalid output becomes `MODEL_PREDICTION_UNAVAILABLE`.
6. Full analysis fuses the certified model output with measured uncertainty,
   resolved Elo, market evidence, league policy, and explicit gaps/conflicts.
7. Any critical gap, conflict, unavailable uncertainty, unverified fixture, or
   closed stake gate produces a non-executable verdict and zero public stake.

Caller-supplied probabilities at `/api/v1/predictions/analyze` are external input,
not backend certification. They return `EXTERNAL_INPUT_UNVERIFIED`, `NO_BET`, and
zero stake.

## Providers and resilience

- One application-lifespan `httpx.AsyncClient` owns provider connection pooling.
- Providers are constructed by the registry and injected into services.
- HTTPS/allowlists, quota-aware caching, `Retry-After`, circuit recovery, schema
  validation, capture time, and provenance are enforced at the gateway boundary.
- ESPN is keyless, supplementary, and cannot establish executable market evidence.
- Redis failure is visible and may use bounded memory fallback; invalid URLs must
  not crash module import. Production readiness still requires a healthy configured
  cache.
- Central redaction removes URL userinfo, DSNs, bearer values, API-key query values,
  and sensitive mapping fields before logs or metrics retain them.

## Model governance

Active artifacts live in `backend/models/` and must have matching metadata.
Unverified generated files live in `backend/models/candidate/`; its manifest is the
promotion gate. A new generation requires chronological competition splits,
expanding temporal meta-model folds, a later calibration slice, an untouched final
evaluation season, exact served-head metrics, train/serve parity, hashes, versions,
and rollback metadata. Promotion is atomic and retains the last-known-good set.

`/models/status` reports the artifact facts the frontend may display. Missing
metadata is `UNKNOWN` or `UNVERIFIED`, never inferred from infrastructure health.

## Public product flow

The homepage begins with upcoming verified fixtures. Full analysis is the only
match-page authority for forecast, evidence state, betting verdict, and staking.
Hypothetical selection is secondary and visibly non-executable. Infrastructure,
provider, model, and prediction capability are separate indicators; none certifies
an individual prediction.

The API uses `Cache-Control: no-store` for evidence and decision traffic. The web
proxy validates parameters and bodies and uses `SABISCORE_BACKEND_URL`. The CSP is
generated per request with a nonce and `strict-dynamic`.

## Persistence and observation

Alembic is the only schema authority. Existing prediction logs, settled matches,
and market snapshots support immutable prediction-to-result and CLV joins.
Operational metrics cover provider outcome/latency, cache tier, circuit state,
schema rejection, evidence completeness, prediction availability, abstention,
calibration state, analysis latency, settlement coverage, RPS, Brier, and CLV.

See [ADR 0007](adr/0007-evidence-authority-and-apex-promotion.md),
[deployment guide](DEPLOYMENT_GUIDE.md), and [rollback instructions](rollback.md).
