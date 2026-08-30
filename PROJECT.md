# Project: SabiScore Production Finishing & Advanced Intelligence Integration

## Architecture
- **Backend**: FastAPI (`backend/src/`), SQLAlchemy 2 + Alembic (`backend/alembic/`), Redis (`backend/src/core/cache.py`), OpenTelemetry (`backend/src/core/telemetry.py`).
- **Frontend**: Next.js 15, React 18.3.1, Tailwind CSS v4 (`apps/web/src/`).
- **Data Flow**: Match ID -> Advanced Insights Service -> (Model probabilities + Feature evidence + Advanced Metrics [PPDA/PSxG/xT] + DB Context [Referee/Weather/Fatigue] + Market Intel Provenance) -> Redis Cache -> Frontend AdvancedInsightsPanel.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| 1 | PPDA Calculation | Pure deterministic PPDA with zero-defensive-action fail-closed handling (return None) | M1 | ORIGINAL_REQUEST §R1 |
| 2 | PSxG Delta | PSxG shot-stopping delta (psxg - goals) with positive=saved convention | M1 | ORIGINAL_REQUEST §R1 |
| 3 | xT Metric Contract | Explicit unavailable/corpus-required classification without synthetic data | M1 | ORIGINAL_REQUEST §R1 |
| 4 | Market Intel Provenance | Full provenance layer re-using existing de-vigging math without stake bypass | M1 | ORIGINAL_REQUEST §R2 |
| 5 | RefereeProfile Model & Migration | Alembic migration 0010 for referee statistics with nullability distinction | M2 | ORIGINAL_REQUEST §R3 |
| 6 | MatchContext Model & Migration | Alembic migration 0010 for weather, fatigue, and advanced context | M2 | ORIGINAL_REQUEST §R3 |
| 7 | Advanced Insights Endpoint | GET /api/v1/matches/{id}/advanced-insights read layer with Redis & OTel | M3 | ORIGINAL_REQUEST §R4 |
| 8 | Consumer-Safe Evidence Copy | Gap code mapping to readable copy + negative-path test contract | M4 | ORIGINAL_REQUEST §R5 |
| 9 | Hydration & Timestamp Sweep | formatLagosTimestamp replacement across 4 identified frontend files | M4 | ORIGINAL_REQUEST §R5 |
| 10 | Frontend Advanced Insights Panel | Accessible, mobile-safe, subordinate insights panel | M4 | ORIGINAL_REQUEST §R6 |
| 11 | Production Verification & Gate Checks | Ruff, pytest, mypy, web lint, typecheck, test, and production build | M5 | ORIGINAL_REQUEST §R7 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| 0 | Survey | Full codebase exploration across backend, database, and frontend | none | DONE |
| 1 | Metrics & Market Intel | R1 (advanced_metrics.py) & R2 (market_intel.py) + tests | Survey | IN_PROGRESS |
| 2 | DB & Alembic Persistence | R3 (RefereeProfile, MatchContext models & 0010 migration) + tests | Survey | PLANNED |
| 3 | Advanced Insights API | R4 (GET /api/v1/matches/{id}/advanced-insights endpoint) + tests | M1, M2 | PLANNED |
| 4 | Evidence Copy & Frontend Panel | R5 (copy mapping, timestamp sweep) & R6 (AdvancedInsightsPanel.tsx) | M3 | PLANNED |
| 5 | Production Verification | R7 (full test suite, gate checks, verification report) | M1, M2, M3, M4 | PLANNED |

## Interface Contracts
### `services/advanced_metrics.py`
- `calculate_ppda(opponent_passes: float | int, defensive_actions: float | int) -> float | None`
- `evaluate_shot_stopping(psxg_total: float, actual_goals_conceded: float | int) -> float | None`
- `evaluate_xt(event_corpus_available: bool, event_count: int) -> MetricResult`

### `services/market_intel.py`
- `build_market_intelligence(odds, model_probabilities, provider, bookmaker, ...) -> MarketIntelligenceSummary`

### `api/endpoints/advanced_insights.py`
- `GET /api/v1/matches/{id}/advanced-insights` -> `AdvancedMatchInsightsResponse`

## Code Layout
- `backend/src/services/advanced_metrics.py` (M1)
- `backend/src/services/market_intel.py` (M1)
- `backend/src/db/models.py` & `backend/src/core/database.py` (M2)
- `backend/alembic/versions/0010_referee_and_match_context.py` (M2)
- `backend/src/schemas/advanced_insights.py` (M3)
- `backend/src/api/endpoints/advanced_insights.py` (M3)
- `backend/src/api/endpoints/__init__.py` (M3 route registration)
- `apps/web/src/lib/evidence-state.ts` & `apps/web/src/lib/evidence-copy-contract.test.ts` (M4)
- `apps/web/src/components/match/AdvancedInsightsPanel.tsx` (M4)
- `apps/web/src/components/` & `apps/web/src/app/` (M4 hydration sweep)
- `backend/tests/` & `apps/web/src/` (Tests across M1-M5)
