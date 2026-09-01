# SabiScore API

Last verified against the repository: 2026-09-01.

The FastAPI application at `backend/src/api/main.py` is the production authority.
Its generated OpenAPI document is the field-level contract; this guide describes
the supported route families and the safety rules clients must preserve.

Local base URL:

```text
http://localhost:8000/api/v1
```

The committed contract is generated and checked with
`backend/scripts/verify_openapi.py`.

## Authentication and identity

SabiScore supports authenticated users and anonymous browser state. The Next.js
proxy stores session and anonymous identifiers in `HttpOnly`, `Secure`,
`SameSite=Lax` cookies; browser code must not place credentials in local storage.

```text
POST /auth/register
POST /auth/login
POST /auth/cookie-login
POST /auth/logout
GET  /auth/me
POST /auth/token

GET    /users/favorites
POST   /users/favorites
DELETE /users/favorites/{favorite_id}
GET    /users/saved-matches
POST   /users/saved-matches
DELETE /users/saved-matches/{match_id}
GET    /users/preferences
PUT    /users/preferences
POST   /users/merge-anonymous
```

Registration and login attempts use a dedicated bounded rate limit. Developer
API quotas are separate; there is no single global rate limit for every route.

## Provider and evidence routes

```text
GET /providers
GET /providers/health
GET /providers/evidence
GET /providers/capabilities
GET /providers/quota

GET  /fixtures/upcoming
GET  /fixtures/{fixture_id}/evidence
POST /fixtures/{fixture_id}/refresh
GET  /fixtures/{fixture_id}/odds-snapshots
POST /fixtures/{fixture_id}/odds-snapshot
POST /fixtures/{fixture_id}/analyze
```

Provider responses carry redacted state, trust tier, warnings, quota, and
acquisition timestamps. ESPN is keyless and supplementary; it cannot establish
executable market, lineup, injury, or model evidence by itself.

Manual and legacy odds routes are research-only. A coherent executable 1X2
market must come from one provider event and one bookmaker snapshot. Never merge
home, draw, and away prices across books into a synthetic market.

## Match discovery and analysis

```text
GET  /matches/upcoming
GET  /matches/search
GET  /matches/{match_id}
GET  /matches/league/{league_name}
GET  /upcoming/matches
GET  /upcoming/all
GET  /matches/upcoming/{match_id}/full-analysis
GET  /matches/{match_id}/advanced-insights
POST /insights
POST /core-engine/analyze
POST /betting-intelligence/analyze
```

Full analysis is the consumer product authority. Missing identity, evidence,
uncertainty, coherent odds, model metadata, or certification returns an explicit
reduced/unavailable state with zero public stake. It never substitutes a neutral
probability and presents it as a measured forecast.

Caller-supplied probabilities are external input, not certified model output.
They remain non-executable unless the backend independently satisfies every
identity, evidence, model, uncertainty, league-policy, and staking gate.

Supported competition identifiers are:

```text
EPL
LA_LIGA
BUNDESLIGA
SERIE_A
LIGUE_1
EREDIVISIE
UCL
```

UCL cannot reach `HIGH_CONVICTION`. `SPECULATIVE` is watchlist-only. Only
critical gaps and conflicts force `PARTIAL`; advisory gaps reduce confidence but
do not independently block an otherwise valid analysis.

Public stake sizing is Quarter-Kelly and remains bounded by the applicable
league policy and hard cap. Do not infer a stake from a probability response in
client code.

## Model performance and provenance

```text
GET /models/status
GET /model-performance
GET /model-performance/summary
GET /model-performance/calibration
GET /model-performance/calibration-curve
GET /calibration-stats
GET /explain/{match_id}
GET /{match_id}/uncertainty
```

`/models/status` exposes internal artifact provenance for developer/admin use.
Raw generation names, hashes, feature-schema identifiers, served-head names, and
promotion states must not be rendered directly on consumer surfaces. The web
application maps them through `apps/web/src/lib/model-identity.ts`.

Performance routes derive metrics from settled predictions and return explicit
insufficient-data states below their configured sample floors. They do not fill
missing calibration, RPS, Brier, CLV, or accuracy values with demonstration
numbers.

## Personalization and notifications

```text
GET    /notifications/preferences
PUT    /notifications/preferences
POST   /notifications/subscriptions/matches
DELETE /notifications/subscriptions/matches/{match_id}
GET    /notifications/in-app
POST   /notifications/in-app/{notification_id}/read
POST   /notifications/in-app/read-all
```

Notification preferences accept IANA timezone names. Match subscriptions support
kickoff reminders and probability-swing alerts. In-app notification reads are
scoped to the authenticated user or anonymous session.

## First-party analytics

```text
POST /analytics/events
```

The endpoint accepts a bounded batch from the typed web analytics client and
returns `202 Accepted`. The backend recursively removes credential and PII-like
fields before persistence. Analytics data is never a model input or evidence
source.

## Developer platform

```text
POST   /developer/keys
GET    /developer/keys
DELETE /developer/keys/{key_id}
GET    /developer/usage
```

Raw keys use the `sbk_live_` prefix, are returned only at creation, and are stored
as SHA-256 hashes. `GET /developer/usage` requires `X-API-Key` and reports the
key's current limits and counters. Current entitlement defaults are:

| Tier | Per minute | Per day |
| --- | ---: | ---: |
| `FREE` | 10 | 100 |
| `PRO` | 60 | 5,000 |

These are technical entitlement tiers only. The product has no billing,
checkout, or payment API.

## Health and operations

Health routes are intentionally split by purpose:

```text
GET /health
GET /health/live
GET /health/ready
GET /metrics
```

Liveness answers whether the process is serving. Readiness separately reports
database, migration, cache, model, Elo, and prediction-capability state. A
healthy process does not certify a prediction or authorize staking.

## Errors and cache policy

FastAPI validation errors use the framework's structured `detail` response.
Domain endpoints may add stable error codes such as `INSUFFICIENT_EVIDENCE`,
`FIXTURE_IDENTITY_REQUIRED`, or `SERVICE_UNAVAILABLE`. Clients must branch on
HTTP status and machine-readable code where present, not on human prose.

Evidence and decision endpoints are served with `Cache-Control: no-store` through
the Next.js proxy. Public metadata and season-status routes may use bounded cache
policies when their route implementation declares one.

## Deprecated compatibility surface

The `/odds` namespace and selected legacy prediction/insights routes remain for
compatibility and research. Their presence does not make them production betting
authority. New clients should use fixture evidence, full analysis, model status,
and model-performance routes.