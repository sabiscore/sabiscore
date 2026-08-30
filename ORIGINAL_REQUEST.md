# Original User Request

## Initial Request — 2026-08-30T05:10:28Z

SabiScore Production Finishing & Advanced Intelligence Integration — surgical enhancement of a live football prediction platform. Add advanced analytical metrics (PPDA, PSxG, xT), market intelligence provenance, contextual match data (referee, weather), consumer-safe evidence copy, and a unified advanced-insights API and frontend panel — all integrated into an existing production-grade FastAPI + PostgreSQL/Alembic + Redis + Next.js/React architecture without duplicating or destabilizing any existing capability.

Working directory: c:\Users\UBEC-DC-ANAMBRA\Documents\sabiscore
Integrity mode: development

### Critical Repository Context

This is a **live production codebase** with mature infrastructure. The team MUST inspect existing code before creating anything new. Key existing systems that MUST NOT be duplicated:

**Backend (Python/FastAPI at `backend/src/`):**
- **Market math**: `connectors/odds_market.py` — implied probabilities, bookmaker margin, power-method de-vigging, EV, edge, CLV, market features. `features/market.py` — market drift from opening→closing odds. `services/betting_intelligence.py` — authoritative verdict engine with de-vigging, edge, EV, Quarter-Kelly.
- **Feature registry**: `models/feature_registry.py` — canonical 68-feature schema with `CANONICAL_FEATURES_58` + `PHASE7_FEATURES_10`. Phase 9 xG/market candidate features in `features/phase9_xg_market_features.py`. Train/serve parity harness.
- **Pressing/PPDA**: `pressing_intensity` exists in feature registry as a proxy (Elo-derived approximation in `data/aggregator.py`); `ppda_ratio` field exists in `data/enrichment/statsbomb_aggregator.py` but is a StatsBomb schema field, not a standalone calculable metric. **No standard PPDA calculation (opponent_passes / defensive_actions) exists yet.**
- **xT**: `connectors/opta.py` has an `expectedThreat` extractor for Opta event data. No standalone xT calculator or pitch-grid model.
- **PSxG**: **Does not exist anywhere in the codebase.** This is new work.
- **Elo/ratings**: Fully implemented (`elo_state_service.py`, `pi_ratings.py`, `berrar_ratings.py`, `form.py`).
- **Redis cache**: 3-tier architecture in `core/cache.py` (Redis Labs → Upstash → in-memory). Async client in `core/redis.py`.
- **OpenTelemetry**: `core/telemetry.py` — OTLP/HTTP, conditional on config. `FastAPIInstrumentor` wired in `api/main.py`.
- **Betting engines**: Three independent engines — `betting_intelligence.py`, `core_engine.py`, `rl_betting_agent.py` — each with distinct verdict/recommendation APIs.
- **Evidence/gap system**: `DATA_GAP`, `VERIFIED`, `STALE`, `CONFLICTING`, `DATA_UNAVAILABLE`, `RESEARCH_ONLY` tokens. Backend emits gap codes like `ppda_ratio`, `progressive_carry_diff`, `shot_quality_diff`, `elo_league_adjusted`, `set_piece_xg_diff`, `key_passes_under_pressure_diff`, `causal_analysis`.
- **Database**: SQLAlchemy 2 + Alembic. 9 migrations (0001–0009). **No Prisma** — Alembic is the only schema authority. Models in `core/database.py` and `db/models.py`.
- **API endpoints**: 24+ endpoint modules in `api/endpoints/` including `full_analysis.py`, `betting_intelligence.py`, `odds.py`, `value_bets.py`, `predictions.py`.

**Frontend (Next.js/React at `apps/web/src/`):**
- **Evidence state**: `lib/evidence-state.ts` — fail-closed token-to-label mapper.
- **Copy contract test**: `lib/copy-contract.test.ts` — checks prohibited gambling terms, but does NOT map backend gap codes to consumer-safe language.
- **Full analysis contract**: `lib/full-analysis-contract.ts` — Zod schema with verdict, ensemble, actionability, evidence schemas.
- **Accessibility**: `lib/accessibility.ts` — WCAG 2.1 AA helpers (sr-only, ARIA IDs, focus trap, live regions).
- **Timestamp**: `formatLagosTimestamp` exists and is used in several files, but `new Date(...).toLocaleString()` hydration-unsafe patterns remain in: `full-analysis-dashboard.tsx`, `value-bet-scanner.tsx`, `performance-page-client.tsx`, `team/[slug]/page.tsx`.
- **Components**: 57+ components including `full-analysis-dashboard.tsx` (71KB), `betting-intelligence-dashboard.tsx` (44KB), `insights-display.tsx`, `phase8-analytics-panel.tsx`.

**Current repository state:**
- Branch: `master`, SHA: `cd0dcdc`
- 175 backend test files
- Model generation: 5, Research mode (staking disabled)
- Postgres: Ready, 5 providers configured/enabled, 4/4 core checks passing

## Requirements

### R1. Backend Advanced Metrics Engine

Create `backend/src/services/advanced_metrics.py` containing pure, deterministic, side-effect-free, unit-testable calculation functions:

- **PPDA**: `opponent_passes / defensive_actions`. Return `None` when `defensive_actions == 0`. Reject negative inputs. Do not invert the formula.
- **PSxG shot-stopping delta**: `psxg_total - actual_goals_conceded`. Document the sign convention explicitly. Positive = saved more than expected. Treat as analytical signal, not a categorical quality verdict.
- **xT**: Only implement if event-corpus requirements can be satisfied for both training and serving. If not, classify as `UNAVAILABLE` / `ADVISORY_REQUIRES_CORPUS`. Never fabricate synthetic xT values.

All functions must be provenance-aware and explicit about missing data (return `None` or a typed unavailable marker, never `0.0` for missing). These metrics are contextual/advisory — they do NOT bypass the existing model certification, evidence, uncertainty, or staking gates.

### R2. Market Intelligence Provenance Layer

Extend the existing market math in `connectors/odds_market.py` and create `backend/src/services/market_intel.py` as an aggregation/provenance service that:

- Distinguishes raw bookmaker odds, normalized implied probability, market overround, model probability, probability edge, and expected value — using the existing de-vigging arithmetic in `betting_intelligence.py` rather than reimplementing it.
- Produces a layered result including: `model_probability`, `implied_probability`, `probability_edge`, `expected_value`, `market_overround`, `classification` (e.g. `POSITIVE_EDGE`), `stake_permitted` (always consumed from existing verdict engines, never independently calculated), `decision` (e.g. `RESEARCH_ONLY`), `source`, `observed_at`, `freshness`.
- Carries full provenance metadata: which provider, which market, which selection, observation timestamp, staleness, suspension status, market completeness, normalization method, model version, feature-schema version, uncertainty availability, fixture pre-kickoff status, certification state.
- A positive mathematical edge MUST NOT automatically imply permission to stake. The existing 4.5% threshold remains a configurable policy value.

### R3. Database Persistence (Alembic Only)

Create **only** the minimum required Alembic migration(s) for new contextual data:

- **RefereeProfile**: `id`, `name`, `avg_yellow_cards`, `avg_red_cards`, `penalties_awarded`, `strictness_index`, `sample_size`, `source`, `observed_at`, `updated_at`. Nullable fields for genuinely unavailable observations — `NULL` means no valid observation, `0.0` means a measured zero.
- **MatchContext**: `id`, `match_id` (FK), `weather_condition`, `weather_source`, `weather_observed_at`, `fatigue_index_home`, `fatigue_index_away`, `ppda_home`, `ppda_away`, `psxg_home`, `psxg_away`, source metadata, timestamps.

Design against existing SQLAlchemy models in `backend/src/core/database.py` and `backend/src/db/models.py`. Follow existing naming, metadata, relationship, indexing, and rollback conventions from the 9 existing migrations. Verify `upgrade → downgrade → upgrade` cycle.

**Do NOT introduce Prisma.** The `prisma.config.ts` files in the repo are artifacts, not active schema management.

### R4. Advanced Insights API Endpoint

Add `GET /api/v1/matches/{id}/advanced-insights` as an **aggregation/read layer** (not a second prediction engine) that composes:

- Existing model probabilities and feature evidence from `full_analysis.py` / `betting_intelligence.py`
- Advanced metrics (PPDA, PSxG, xT) from R1
- Contextual information (weather, referee, fatigue) from R3
- Market intelligence provenance from R2
- Certification state from existing `certification_policy.py`

Response schema must use existing API conventions and explicitly distinguish `AVAILABLE`, `PARTIAL`, and `UNAVAILABLE` states for each metric group. Include model identity, feature-schema version, and decision state (`research_only`, `stake_permitted`).

Add validation, provenance, freshness, error semantics, OpenTelemetry spans (using existing `core/telemetry.py`), and Redis caching (using existing `core/cache.py` — market data gets shorter TTL than static referee metadata). The endpoint must not create N+1 query paths.

### R5. Consumer-Safe Evidence Copy & UX Fixes

**Evidence-copy guard**: Create or extend a mapping from backend-emitted gap/evidence codes to consumer-safe language. Every gap code the backend emits must have reader-oriented copy — no raw feature identifiers reach users. Mapping examples:
- `ppda_ratio` → "Pressing intensity data not published for this match"
- `progressive_carry_diff` → "Ball-carrying data not published for this match"
- `set_piece_xg_diff` → "Set-piece chance quality not available yet"
- `shot_quality_diff` → "Shot-quality breakdown not available yet"
- `elo_league_adjusted` → "Cross-league strength adjustment unavailable"
- `causal_analysis` → "Driver analysis not available for this match"
- `key_passes_under_pressure_diff` → "Chance-creation-under-pressure data unavailable"

Add a test at `apps/web/src/lib/evidence-copy-contract.test.ts` that derives expected codes from the backend's registry and fails when any code lacks consumer copy. **Negative-path verification required**: remove one mapping → run test → confirm failure → restore → confirm pass.

**Timestamp/hydration sweep**: Replace remaining `new Date(...).toLocaleString()` and render-time `Date.now()` patterns with the existing `formatLagosTimestamp()` convention in: `full-analysis-dashboard.tsx`, `value-bet-scanner.tsx`, `performance-page-client.tsx`, `team/[slug]/page.tsx`.

**Container parity**: Inspect parent padding before adding any new padding. Do not add redundant `p-4`/`px-4`/`py-5`.

**Mobile overflow**: Ensure `min-width: 0` is on actual grid/flex items, not nested too deep.

### R6. Frontend Advanced Insights Panel

Create `apps/web/src/components/match/AdvancedInsightsPanel.tsx` using the existing design system (existing cards, typography, spacing, tooltip, status, responsive, focus, loading, empty-state conventions from `apps/web/src/components/`).

The component must:
- Remain visually subordinate to the primary prediction/decision display
- Distinguish measured values from unavailable values (using existing `evidence-state.ts` tokens)
- Show market freshness and source/provenance
- Never imply a stake recommendation solely from an edge
- Work at mobile widths with no horizontal overflow
- Support keyboard navigation using existing accessibility primitives
- Avoid hydration-sensitive rendering (no render-time `new Date()`)

Information hierarchy: Pressing/tactical signals → Shot-quality signals → Match conditions (weather, referee) → Market intelligence (model prob, market prob, edge/EV, freshness, decision state).

Use "Positive market edge detected" language (not aggressive betting labels) when certification is incomplete. Never display a green "Value Edge" badge unless the full value contract is satisfied.

### R7. Test Suite & Production Verification

Comprehensive test coverage for all new code:

- **Unit tests** for every analytical primitive: valid inputs, zero inputs, missing inputs, invalid inputs, boundary conditions, numerical stability, sign conventions.
- **Contract tests**: API response schema validation, evidence-code mapping, provenance, certification state, unavailable-state semantics.
- **Integration tests**: Database persistence, Redis caching, OpenTelemetry spans.
- **Regression tests**: Existing prediction endpoints, model artifacts, feature contracts, staking gates, and dashboards remain unchanged.
- **Negative-path tests**: Every new guard must be demonstrated failing when the guarded condition is violated.

All tests must pass the existing production gates:
```
cd backend && ../.venv/Scripts/python.exe -m ruff check src/
cd backend && ../.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly
cd backend && ../.venv/Scripts/python.exe scripts/check_mypy_ceiling.py
pnpm --filter @sabiscore/web lint
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
NODE_ENV=production pnpm --filter @sabiscore/web build
```

## Acceptance Criteria

### Backend Metrics & Market Intelligence
- [ ] `calculate_ppda(opponent_passes=450, defensive_actions=45)` returns `10.0`
- [ ] `calculate_ppda(opponent_passes=100, defensive_actions=0)` returns `None` (not `0.0` or `Infinity`)
- [ ] `evaluate_shot_stopping(psxg_total=2.5, actual_goals_conceded=1)` returns `1.5` (positive = saved more than expected)
- [ ] Market intelligence output includes all provenance fields: provider, market, selection, timestamp, staleness, model version, certification state
- [ ] A positive mathematical edge in market intelligence output has `stake_permitted: false` when the model is uncertified (current state)
- [ ] No new service duplicates calculations already in `connectors/odds_market.py` or `services/betting_intelligence.py`
- [ ] `ruff check src/` passes with zero errors
- [ ] `pytest tests/ -q` passes with zero failures and no decrease in test count from current baseline

### Database
- [ ] New Alembic migration(s) follow existing naming convention (`0010_*.py`)
- [ ] `alembic upgrade head` succeeds on a fresh database
- [ ] `alembic downgrade -1` then `alembic upgrade head` succeeds (reversibility)
- [ ] No Prisma schema, client, or migration is introduced
- [ ] Nullable fields correctly distinguish `NULL` (no observation) from `0.0` (measured zero)

### API
- [ ] `GET /api/v1/matches/{id}/advanced-insights` returns valid JSON with status `AVAILABLE`, `PARTIAL`, or `UNAVAILABLE`
- [ ] Each metric group (ppda, psxg, xt, weather, referee, market) has its own status field
- [ ] Response includes model identity, feature-schema version, and decision state
- [ ] Endpoint uses existing Redis cache with appropriate TTLs (shorter for market data)
- [ ] OpenTelemetry span `advanced_insights.request` is emitted when tracing is enabled
- [ ] No N+1 query patterns (verify with query count logging)

### Frontend & UX
- [ ] No raw backend feature identifiers (e.g., `ppda_ratio`, `progressive_carry_diff`) appear in any user-facing text
- [ ] Evidence-copy-contract test fails when a mapping is removed and passes when restored
- [ ] No `new Date(...).toLocaleString()` patterns remain in the 4 identified files
- [ ] `AdvancedInsightsPanel` renders correctly at 375px mobile width with no horizontal overflow
- [ ] Keyboard focus is visible on all interactive elements in the new panel
- [ ] `pnpm --filter @sabiscore/web lint` passes
- [ ] `pnpm --filter @sabiscore/web typecheck` passes
- [ ] `pnpm --filter @sabiscore/web test` passes
- [ ] `NODE_ENV=production pnpm --filter @sabiscore/web build` succeeds

### Safety & Governance
- [ ] Advanced metrics are classified as contextual/advisory — they do not feed into the active model or alter staking decisions
- [ ] No secrets, credentials, or API keys appear in source code, logs, or API responses
- [ ] Provider failures fail closed (return `UNAVAILABLE`, not crash)
- [ ] Unavailable data is never converted to `0.0`
- [ ] The existing 3 verdict engines (`betting_intelligence.py`, `core_engine.py`, `rl_betting_agent.py`) are unmodified unless explicitly required
