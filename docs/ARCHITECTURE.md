# SabiScore Architecture

Last verified against the repository: 2026-09-01.

## Production boundaries

```text
Browser
  -> apps/web (Next.js 15, React 18; UI and validated proxy routes)
   -> HttpOnly session/anonymous cookies; no browser token persistence
   -> dashboard, developer keys, notifications, analytics, share/SEO UI
       -> backend/src/api/main.py (FastAPI authority)
            -> provider registry + one lifespan httpx.AsyncClient
            -> one request-scoped evidence snapshot
            -> feature projection -> active model -> evidence/stake gates
            -> PostgreSQL (Alembic schema authority)
            -> Redis (cache, leases, and developer rate limits; explicit degraded state)

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

### Training corpus authority

`backend/data/cache/fd_*.csv` — 12,765 real matches across six leagues,
2019-09 to 2026-05 — is the canonical corpus, and every trainer reads it:
`train_on_real_matches.py` for the ensemble generations and `train_bnn.py` for
the uncertainty member. Feature construction is centralised in
`build_dataset()`, which walks forward in time so a match never sees its own
result, and computes each feature group through the same shared
`feature_registry` helpers that live serving uses.

`data/processed/*_training.csv` is legacy and is retained only for reproducing
older runs. It holds 2,058 rows, leaves the xG and Elo columns zero in 85% of
them, and its Eredivisie slice is synthesised by
`scripts/generate_eredivisie_data.py`. Nothing in the serving path reads it.

The schema a trainer targets follows the **active generation**, resolved through
`active_feature_schema_version()`, never a hardcoded preference. `build_dataset`
emits both an Apex vector and a canonical/incumbent one; because
`uncertainty_service` aligns the served feature dict to the `feature_cols`
stored in a checkpoint and raises when one is missing, training against the
block that serving does not build fails closed at request time.

## Public product flow

The homepage begins with upcoming verified fixtures. Full analysis is the only
match-page authority for forecast, evidence state, betting verdict, and staking.
Hypothetical selection is secondary and visibly non-executable. Infrastructure,
provider, model, and prediction capability are separate indicators; none certifies
an individual prediction.

The API uses `Cache-Control: no-store` for evidence and decision traffic. The web
proxy validates parameters and bodies and uses `SABISCORE_BACKEND_URL`. The CSP is
generated per request with a nonce and `strict-dynamic`.

User identity, favorites, saved matches, preferences, developer keys, first-party
analytics events, notification subscriptions, and in-app notification logs are
durable PostgreSQL state introduced by Alembic revision
`0011_user_identity_dev_platform`. Browser auth is mediated by Next.js route
handlers and `HttpOnly` cookies. Raw developer keys are shown once and persisted
only as hashes.

Notification persistence and UI are implemented, but scheduled kickoff and
probability-swing generation have no production caller yet. The sitemap includes
core routes, supported league filters, a bounded team catalogue, and sample
fixture routes; it does not yet query live fixture identity. These distinctions
are operational gaps, not reasons to invent delivery or indexing claims.

## Persistence and observation

Alembic is the only schema authority. Existing prediction logs, settled matches,
and market snapshots support immutable prediction-to-result and CLV joins.
Operational metrics cover provider outcome/latency, cache tier, circuit state,
schema rejection, evidence completeness, prediction availability, abstention,
calibration state, analysis latency, settlement coverage, RPS, Brier, and CLV.

See [ADR 0007](adr/0007-evidence-authority-and-apex-promotion.md),
[deployment guide](DEPLOYMENT_GUIDE.md), and [rollback instructions](rollback.md).
