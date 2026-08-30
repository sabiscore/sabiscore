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

## Follow-up — 2026-08-30T09:41:40Z

Working directory: c:\Users\UBEC-DC-ANAMBRA\Documents\sabiscore
Integrity mode: development
Requested team: Full agent team — split across parallel workstreams

# SabiScore — Production Finishing Directive v5 — Production Mastery & Predictive Improvement

**Successor to** `docs/PRODUCTION_FINISHING_DIRECTIVE.md` (2026-08-30), the `APEX`
execution-directive wrapper, and v4. This is the authoritative execution prompt for
finishing, validating, improving, and certifying SabiScore without rewriting the platform. **Merges and corrects both** against a live re-grep of
`sabiscore-master__3_.zip` in this session — every claim below is tagged with the
evidence bar it cleared (per `sabiscore-settlement-calibration-architect`'s four-bar
standard: **built → wired → called → running**), not carried forward from either
source doc uncritically.

**v4 change note:** adds §8 (advanced models, CLV surface, parlay engine, UI, resourcing)
and **corrects a v3 error found while building it** — §3.6 previously claimed portfolio
correlation/exposure caps were undefined in code; `core/portfolio_exposure.py` already
implements them. Fixed in place, not patched over.

| Signal | v2 claimed | Re-verified this session |
|---|---|---|
| Backend / Web suites | 1764/0 · 248/0 | not re-run (static repo only — **run §6 before trusting**) |
| Critical gaps | 2 | unchanged in code |
| Advisory gaps, live EPL fixture | **9** (header) vs **10** (screenshot decision card) vs **12** (screenshot breakdown: 5 other + 4 tactical + 2 team-strength + 1 combined) | **three numbers, one fixture, same minute** — see §4 |
| Providers | "5 configured · 5 enabled" | live per-provider table: **1 `LIVE_VERIFIED`, 1 `DEGRADED`, 3 `UNKNOWN`** — see §4 |
| MIN_ACTIONABLE_EDGE | 0.042 (4.2pp) | **confirmed identical** in both `betting_intelligence.py:56` and `core_engine.py:37` (`CORE_` prefix) |

| v5 execution priority | v4 mixed product/model finish | **ordered M0→M10 program: metrics → parity → real features → ensemble → calibration → uncertainty → market/CLV → shadow → certification** |

---

## §0 — Re-verify before acting

```bash
git rev-parse --short=7 origin/master
curl -s .../health                | jq '{sha, status}'
curl -s <vercel-alias>/api/health | jq '{sha, backendStatus}'
curl -s .../api/v1/model-performance | jq '{settled_predictions, walk_forward:{rps_overall}, clv}'
curl -s .../metrics | jq '.production.counters | with_entries(select(.key|test("market|elo|clv|abstention")))'
curl -s ".../api/v1/matches/upcoming/<id>/full-analysis?league=<CANONICAL>" \
  | jq '{critical:.evidence_quality.critical_gaps, advisory:(.evidence_quality.advisory_gaps|length)}'
```
A backend SHA behind `master` is usually correct (`render.yaml rootDir: backend`) — diff
before calling it an incident. Never judge a gate through `| tail` — it masks `$?`.

---

## §1 — Mutation authority

| Class | Scope | Authority |
|---|---|---|
| **A** | Probes, greps, measurement | Autonomous |
| **B** | Code + tests, defect-fixing or additive, green CI, no gate touched | Autonomous |
| **C** | Loosens a gate, changes a certification threshold, touches `MIN_ACTIONABLE_EDGE`/Kelly caps/Brier gate, mutates prod data, adds a schema | **Explicit authorization + dry-run manifest** |

Every item in §3 is tagged **A/B/C**.

---

## §2 — Already enforced — run it, don't re-audit

All eight files below **exist and were confirmed present** this session (not assumed):

| Invariant | Guard |
|---|---|
| `critical_gaps` force PARTIAL; advisory never blocks | `test_betting_intelligence_engine.py` |
| Zero-fabrication / no synthetic-vector predictions | `backend/tests/test_zero_fabrication_contract.py` |
| No prohibited betting copy | `apps/web/src/lib/copy-contract.test.ts` |
| League normalization | `apps/web/src/lib/league-contract.test.ts` |
| No model-provenance leak | `apps/web/src/lib/model-identity-contract.test.ts` |
| Container-parity (4 things) | `apps/web/src/components/loading/match-loading-experience.test.tsx` |
| Feature-contract freshness | `backend/scripts/verify_active_artifacts.py` |
| Secrets absent | `gitleaks detect --no-git` |

```bash
cd backend && python -m pytest tests/ -k "advisory or conflicting or zero_fabrication" -q
cd .. && pnpm --filter @sabiscore/web test
```
If green, report green in one line. Re-doing these by hand is the largest waste-of-session
pattern across prior passes.

---

## §3 — Actual open work

### 3.1 Blocked on a decision (Class C — do not resolve autonomously)

**Decision 1 — staking gate.** `UncertaintyService.decompose_measured()`
(`backend/src/services/uncertainty_service.py:125,131`) short-circuits whenever
`self._bnn_model is None or torch is None` — confirmed, both conditions true (`torch`
absent from every `requirements*.txt`, no trained artifact). Certifying the model
**will not** enable staking; `stake_permitted` needs `not partial`, and this gap is
permanent-critical until resolved. Options unchanged from v2: ship torch + artifact,
reclassify to advisory (Class C, authorized only), or keep research-only as a recorded
decision.

**Decision 2 — Brier convention.** v2 attributes a mean/sum docstring-vs-code mismatch
to a function `_brier_score()` against a `0.220` gate. **This session could not
re-locate that exact name or constant** — the closest matches are
`_calculate_brier_score` (×3 services), `_compute_brier_multiclass`
(`models/calibration.py:148`), `brier_score_decomposition`
(`models/evaluation/metrics.py:52`). Treat v2's specific claim as **unconfirmed, not
false** — re-grep `certification_policy.py` and the calibration module for the actual
BNN gate constant before touching anything. Do not carry the "market scores 0.5787"
figure forward without re-deriving it from `get_settled_predictions()` output per
`sabiscore-settlement-calibration-architect`'s zero-fabrication rule.

### 3.2 Blocked on data volume (Class A — re-probe only)

| Floor | Was | Action |
|---|---|---|
| `rps_overall ≤ 0.21` | 0.243 @ 16 settled | re-probe |
| CLV summary ≥10 joined | n=3 | re-probe |
| `no_league_regression`/`market_baseline` 6/6 | 3/6, 0/6 | re-probe |
| Drift monitor baseline ≥1,000 settled | far off | **do not wire a caller** |
| Portfolio-exposure calibration (DEBT 9) ≥1 same-league/matchday settled round | — | worth a direct re-check |

**Settlement pipeline — corrected status.** `sabiscore-settlement-calibration-architect`'s
generic example list calls `get_settled_predictions()`, `walk_forward_validate()`, and
`ScrapedTeamFormStore` "built, tested, no caller." **That is stale for this repo.** Confirmed
this session:
- `get_settled_predictions()` — called from `services/settlement_service.py` **and**
  a live route, `api/endpoints/performance.py`.
- `walk_forward_validate()` — same two call sites, plus `certification_policy.py`.
- `settlement_service.run_settlement_pass` — imported at `api/main.py:160` (a real
  startup hook, not a script).
- `ScrapedTeamFormStore` — instantiated inside `upcoming_match_feature_service.py`,
  which nine other modules import including `api/endpoints/full_analysis.py`.
- `monitoring/drift.py` — **zero callers anywhere.** Genuinitely unwired. Per the volume
  floor above, this is *correctly* deferred, not a gap to close.

Clears **built + wired + called-in-production**. It does **not** clear **running**
(logs/DB rows showing it executed against real settled data) from a static checkout —
that needs a live probe:
```bash
curl -s .../metrics | jq '.production.counters.settlement_pass_runs'
```
Until that returns >0 against real fixtures, do not report the Phase-2 gate as cleared —
report it as "wiring confirmed, execution unconfirmed."

### 3.3 Genuinely open code (Class B unless noted)

**Evidence-copy leak — corrected fix.** `describeEvidenceCode()`
(`full-analysis-contract.ts:427`) still falls through to `titleCaseCode()`. v2's proposed
diff writes new entries as capitalized standalone sentences; **the existing map's
convention is lowercase clause fragments** interpolated after an em-dash (`` `Not enough
verified data — ${describeEvidenceCode(code)}.` ``, line 482). Match it:
```diff
  const EVIDENCE_CODE_COPY: Record<string, string> = {
    // …existing entries unchanged…
+   ppda_ratio: "pressing-intensity data is not published for this match",
+   progressive_carry_diff: "ball-carrying data is not published for this match",
+   set_piece_xg_diff: "set-piece chance quality is not available yet",
+   elo_league_adjusted: "the cross-league strength adjustment is unavailable",
+   causal_analysis: "driver analysis is not available for this match",
  };
```
**Guard-test correction:** v2's proposed test parses `feature_contract.json` as the
source of truth. That file (`backend/models/feature_contract.json`) is the **ML
feature-schema contract**, not a gap-code registry — it will not contain
`causal_analysis`, `MODEL_GENERATION_UNCERTIFIED`, or any of the other hand-appended
codes at `full_analysis.py`'s ~9 `critical_gaps.append("LITERAL")` sites. Two of those
sites append a **variable**, not a literal (`policy_gap` from `_effective_kelly_cap()`),
so a pure static/AST scrape has a blind spot there too — it's already covered by the
existing `LEAGUE_POLICY_UNAVAILABLE` entry, but say so in the test comment rather than
silently relying on luck. Ship the guard as a hand-maintained code list cross-checked
against both `full_analysis.py` and `upcoming_match_service.py` at review time, not an
auto-discovering test on day one — an honest B-effort fix beats a C-effort test that
silently misses half its inputs.

**Casing drift, worth a direct check (not yet confirmed as a live bug):**
`full_analysis.py` appends `MODEL_GENERATION_UNCERTIFIED` / `REQUIRED_MODEL_INPUTS_UNAVAILABLE`
(uppercase); `upcoming_match_service.py` appends `model_generation_uncertified` /
`required_model_inputs_unavailable` (lowercase) for the same semantic gap. `EVIDENCE_CODE_COPY`
lookup is exact-key. If both code paths ever render through `describeEvidenceCode()`, the
lowercase variant fails the lookup even though its uppercase sibling has copy. Confirmed
`describeEvidenceCode` is called from `betting-intelligence-dashboard.tsx` and
`full-analysis-dashboard.tsx`; **not confirmed** which endpoint feeds which component this
session — check before assuming either the bug or its absence.

**Precedent to reuse, not reinvent:** `apps/web/src/lib/evidence-state.ts` already solved
the adjacent problem (raw `DATA_GAP`/`STALE`/`CONFLICTING` *state* tokens, fixed 2026-08-26,
per the in-repo `CHANGELOG.md`'s "Unreleased" entry) with a fail-closed `{label, tone}`
descriptor and a neutral default ("Status unavailable") for unrecognised tokens, pinned by
`evidence-state.test.ts`. Mirror that shape for `EVIDENCE_CODE_COPY` for consistency across
the two mapping layers, rather than a bare string map.

**Hydration mismatch — corrected scope.** v2 claims five open sites. Re-grepped:

| Site | `formatLagosTimestamp` swap | Remaining `Date.now()`-in-render |
|---|---|---|
| `full-analysis-dashboard.tsx:483-486` | **already done** | still open — `ageSecs` computed synchronously |
| `value-bet-scanner.tsx:83,155` | **already done** | still open — same pattern |
| `performance-page-client.tsx:200,230` | N/A — this is `settled.toLocaleString()` on an **integer count**, a locale-digit-grouping issue, not a timestamp bug | different defect class; don't fold into this sweep |
| `team/[slug]/page.tsx` | no `toLocaleString`/`Date.now()` match found at all | **v2's claim appears stale — re-verify before touching this file** |

Only two real sites remain, and only the numeric half:
```diff
- const ageSecs = Math.round((Date.now() - generatedMs) / 1000);
+ const [ageSecs, setAgeSecs] = useState<number | null>(null);
+ useEffect(() => {
+   setAgeSecs(Math.round((Date.now() - generatedMs) / 1000));
+ }, [generatedMs]);
```

**Focus-visible token** — confirmed absent from `globals.css`. Ship as v2 specified
(one rule, shared layer). Class B, ~20 min.

**New this session — Phase 8 registry, undocumented in either source directive.**
`feature_registry.py` defines `APEX_FEATURES_89` / `PHASE8_FEATURES_21`
(68 Phase-7 + 21 Phase-8), backed by `features/phase8_historical.py`, referenced by
`scripts/train_on_real_matches.py`, and exposed at `api/endpoints/phase8_features.py`.
Neither directive mentions it. Before any Phase-2 modeling work, confirm via the
promotion ladder which generation is actually certified/serving — do not assume 68
is still the only live schema.

### 3.4 The advanced-metrics / value-bet proposal — verdict per component

A separate "System Architecture & Integration Strategy" doc proposed a
`RefereeProfile`/`MatchContext` Prisma schema, an `AdvancedMetricsEngine`
(PPDA, PSxG, xT), and a `MarketIntelligence.detect_value_edge()`. Audited against
`sabiscore-betting-engine-auditor` (dual-engine rule) and the built/wired/called bars:

| Component | Verdict | Why |
|---|---|---|
| Prisma schema for `RefereeProfile`/`MatchContext` | **Reject as written** | No `schema.prisma`, no Prisma anywhere in this repo; schema authority is 9 Alembic migrations, head `0009_quarantine_post_kickoff_closings`. A new migration is fine — as SQLAlchemy/Alembic, Class C. |
| `AdvancedMetricsEngine.calculate_ppda()` | **Reject as written** | `ppda_ratio` and `progressive_carry_diff` **already exist** — built, wired, and called (`data/enrichment/statsbomb_aggregator.py`, `scripts/build_statsbomb_cache.py`, consumed in `upcoming_match_feature_service.py`), and are two of the exact codes leaking raw in §3.3. The real gap is copy + the permanent `PHASE7_FEATURES_ALWAYS_DATA_GAP` slot they occupy — not a second computation engine. Building one duplicates the dual-engine failure mode this suite otherwise polices. |
| `evaluate_shot_stopping()` (PSxG) | **Blocked, not rejected** | No PSxG function exists anywhere (`understat_xg.py` only computes pre-shot xG). This needs a verified on-target/shot-placement data source first — do not derive a formula against data that isn't scraped yet. |
| `MarketIntelligence.detect_value_edge()`, 4.5% threshold | **Reject as written — Class C conflict** | The live, dual-engine-enforced threshold is `MIN_ACTIONABLE_EDGE = 0.042` (4.2pp), identical in both `betting_intelligence.py` and `core_engine.py`. A parallel 4.5% implementation is a second, uncoordinated edge engine. Any new endpoint must call the existing policy layer (`get_verdict_policy()`), never reimplement implied-probability/edge math. |
| `RefereeProfile` behavioral data (strictness, cards) | **Net-new, viable** | Only a bare `referee: Optional[str]` name field exists today (`schemas/match.py`). A full profile is a legitimate addition — but per the zero-paid-API constraint, it must be sourced via `apps/scraper`, not fabricated, and gated exactly like weather (advisory-only until a review step exists). |
| `AdvancedInsightsPanel.tsx` | **Reject as written** | Uses raw `bg-slate-900`/`text-emerald-400` classes. The repo's real verdict/signal tokens (`globals.css`) are `--conviction-{high,actionable,speculative,hold,partial}` and `--signal-{positive,warning,danger,stale,data-gap}`. A green "Value Edge" badge on ungapped, PARTIAL-Kelly, unshipped metrics also overstates certainty the underlying data doesn't have — the same violation this suite forbids for verdict badges generally. |

### 3.5 Firecrawl integration — approve the scraper placement

Workspace structure confirmed (`pnpm-workspace.yaml`: `apps/web`, `apps/scraper`,
`apps/ws`, `packages/*`). The recommendation to install into `apps/scraper` rather than
`apps/web/src/lib/server/firecrawl.ts` is correct and matches the zero-paid-API,
provider-abstraction posture already governing the platform. One addition: the
directive's own warning against piping scraped text directly into an LLM to produce a
probability is the right instinct — no `anthropic`/`openai` import exists anywhere in
`backend/src` today, so there is no precedent to follow for narrative generation
(`intelligence_synthesizer.py`'s `_compose_narrative()` is deterministic Python). If a
future summarization/classification step is added on top of Firecrawl evidence, use
structured output (Zod/Pydantic-validated extraction), never freeform text feeding a
numeric feature — and diff any scraped team/referee/venue name against the canonical
identity map before use. The historical failure mode here is concrete: a prior pass
invented provider spellings ("Ein Frankfurt", "Stade Brestois 29") and got 7 of 14 pairs
wrong. Firecrawl output is subject to the same discipline.

### 3.6 Portfolio staking — self-correction

CLV is already tracked per position (`clv_service.py`, surfaced via
`api/endpoints/performance.py`'s `get_clv_records`) — say so plainly rather than treating
"no settlement history yet" as "no signal at all," per `sabiscore-portfolio-staking-architect`.

**Correction to this directive's own prior claim.** The line that stood here previously —
"aggregate exposure caps and correlation-group sizing are not defined in code" — **was
wrong**, found by a deeper grep this session, not by new work landing. `core/
portfolio_exposure.py` already implements exactly this: same-`(league, UTC day)`
correlation grouping with a floored stake haircut, an aggregate cap at
`3.0 × max(league kelly_cap)` (constant `AGGREGATE_CAP_MULTIPLIER`), and a drawdown
status stub that returns `"insufficient_settled_predictions"` rather than a fabricated
`0.0`. It's labelled `DEFAULT_PENDING_CALIBRATION` and cites `docs/DEBT.md` item 9 for
the same floor already named in §3.2. It is strictly advisory — flags and haircuts,
never suppresses or resizes a recommendation. Full detail and the genuine remaining gap
(parlay-specific joint-probability math, which this module doesn't attempt) — §8.3.

### 3.7 Operator-only (no code path)

Redis old-credential revocation; two historical Gitleaks fingerprints
(`backend/.env.example` @ `d604c13`, `67ed0ab`); a fresh Docker image build (6–8 GB VM).
Custom domain deprioritized — Vercel alias is canonical.

---

## §8 — New this session: quantitative models, CLV surface, parlay engine, UI, resourcing

Requested as a fresh build-out. Two of five items are corrections to a false premise
(something assumed missing that already exists); building those from scratch would have
reintroduced the exact dual-implementation risk §3.4 exists to catch. Ordered by
dependency.

### 8.1 xT / PPDA / PSxG — one redirect, one blocked, one genuinely new (Class varies)

- **PPDA / progressive-carry** — not a new model, see §3.4. Redirect effort to the
  evidence-copy fix in §3.3; the computation already exists.
- **Expected Threat (xT)** — re-confirmed zero function defs anywhere in `backend/src`.
  Genuinely net-new, **Class C**: it needs its own `feature_schema_version` for the same
  reason weather does (Pillar 2.3 of the prior pass) — a signal that resolves for history
  but not for an unplayed fixture teaches the model something serving can't supply.
  `data/enrichment/statsbomb_aggregator.py` already ingests StatsBomb-shaped possession
  events for PPDA; extending it to also emit a start-zone→end-zone xT value per chain is
  the correct integration point — not a new scraper. **Do not build this ahead of the
  StatsBomb corpus regeneration in DEBT item 13** — it would join
  `PHASE7_FEATURES_ALWAYS_DATA_GAP` on day one.
- **PSxG** — unchanged from §3.4, still blocked. `connectors/opta.py` is confirmed a
  **mock stub** (`_mock_xg_data()`, no live credential path) and Opta itself is a paid
  provider — do not wire it; it would violate the zero-paid-API constraint even if it
  were real. PSxG needs a free/scraped shot-map source, verified the way Open-Meteo was
  for weather, before any formula is written.

**Redis caching — reuse `core/cache.py`, don't add a second client (Class B).**
`cache_manager` is already a circuit-broken, best-effort two-tier cache (in-memory +
Upstash Redis), already imported by `services/prediction.py`. Any future feature step
caches through the same object rather than forking its stampede protection:
```python
from ..core.cache import cache_manager

async def get_xt_for_match(match_id: str) -> Optional[dict]:
    key = f"xt:v1:{match_id}"
    if (hit := await cache_manager.get(key)) is not None:
        return hit
    value = _compute_xt(match_id)          # not implemented — blocked, see above
    await cache_manager.set(key, value, ttl=6 * 3600)
    return value
```

### 8.2 Closing Line Value — the premise was wrong, the surface is what's missing (Class B)

`clv_service.py` already exists, is wired into `performance.py`, and its own docstring
draws a hard line: *"Read-only: never feeds `EXECUTE_BET` (doesn't exist), never computes
ROI (no stake is ever placed). See `docs/adr/0004-clv-capture.md`, Addendum 2."* (The ADR
file itself wasn't present in this zip export — cite the ID, read it directly in the live
repo before extending anything it governs.) A new "CLV Tracker" backend would duplicate
this and risk drifting past that boundary. The real gap is a **frontend panel** —
`compute_clv_summary()`'s output has no dedicated surface today, only a nested field
inside `/model-performance`. Component spec is in §8.4; it must inherit the same
read-only, no-ROI framing in its copy, not just its data source.

### 8.3 Parlay Correlation Engine — genuinely new, advisory-only (Class B; Class C if it ever sizes a stake)

Push back before building: a parlay's expected value is worse than its legs taken singly
whenever any dependence exists between them, and this platform has never placed a stake
or executed a bet by design. Build **an explainer that discourages naive stacking**, not
a bet-slip combiner — matching `sabiscore-portfolio-staking-architect`'s hard boundary
(advisory only, never execution) and `SPECULATIVE` legs carrying zero real stake by
construction.

`core/portfolio_exposure.py` already does the adjacent job (§3.6) but doesn't attempt
joint-probability math for a user-selected leg set — it sizes independently-recommended
single bets, not a combined price. New module, reusing the existing grouping key rather
than reforking it:

```python
# backend/src/core/parlay_correlation.py — new, Class B
"""Advisory-only. Computes what a combined price WOULD imply; never suggests placing
one. SPECULATIVE/NO_BET/PARTIAL legs are excluded by construction."""
from __future__ import annotations
from typing import Any, Dict, List
from .portfolio_exposure import _group_key  # reuse, don't refork the correlation key

def parlay_probability(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    eligible = [l for l in eligible if l.get("verdict") not in ("SPECULATIVE", "NO_BET", "PARTIAL")]
    excluded = len(legs) - len(eligible)
    groups = {_group_key(l) for l in eligible}
    naive_joint = 1.0
    for l in eligible:
        naive_joint *= float(l["model_probability"])
    shares_group = len(groups) < len(eligible)
    return {
        "legs_considered": len(eligible),
        "legs_excluded_ineligible": excluded,          # never silently dropped
        "distinct_correlation_groups": len(groups),
        "shares_a_correlation_group": shares_group,
        "naive_independent_probability": round(naive_joint, 6),
        "advisory": (
            "Legs share a league/matchday — treat this as an upper bound, not a real "
            "probability; correlated-provider, referee, or weather risk isn't modeled."
            if shares_group else "No shared league/matchday detected across these legs."
        ),
        "stake_recommendation": None,  # this surface never sizes or recommends a stake
    }
```
Explicit non-goals: no combined-odds-to-payout calculator, no "best parlay" ranking, no
UI affordance that reads as an invitation to combine legs. A bet-slip-style combiner is a
Class C product decision — flag it, don't build it speculatively.

### 8.4 Two UI components — extend the system, don't invent a second visual language

Per `design:design-system`'s extend template; both use the real tokens from
`apps/web/src/app/globals.css` (`--conviction-{high,actionable,speculative,hold,partial}`,
`--signal-{positive,warning,danger,stale,data-gap}`) — no new hex values.

**Value Bet Matrix**

| | |
|---|---|
| Problem | A slate's value bets are only visible one fixture at a time today. |
| Existing pattern | `value-bet-scanner.tsx` is a list, not a scannable grid — not enough for a full matchday. |
| Proposed | Rows = fixtures, columns = HOME/DRAW/AWAY, cell = `edge_pct` colored by `--conviction-*`; a small dot renders when §8.3's `shares_a_correlation_group` is true for that leg. |
| States | No coherent market → `--signal-data-gap`, never a blank cell. `SPECULATIVE` → `--conviction-speculative`, and is excluded from any parlay affordance per §8.3's non-goals. |
| Accessibility | Edge value always in cell text (e.g. `+4.6%`), never color-only — WCAG 1.4.1, same rule already enforced for verdict badges elsewhere. |
| Open question | Does the correlation dot need its own legend entry, or does it read as noise at matrix density — needs a design pass with real data, not decided here. |

**Implied-Probability Converter**

| | |
|---|---|
| Problem | Users manually convert bookmaker decimal odds to a probability to sanity-check the model. |
| Existing pattern | The correct de-vigged formula already lives in `betting_intelligence.py`/`core_engine.py` — this component must not reimplement it as a third copy. |
| Proposed | Client-only input (decimal odds → de-vigged fair probability), explicitly labelled as a raw-odds utility, **not** a call into the backend verdict/edge policy — avoids the exact two-engines confusion flagged in §3.4. |
| Tokens | `--surface-card`, `--border-subtle`, `--text-muted` for the shell; **no** conviction token — this component makes no verdict claim. |
| Open question | Should it sit behind the same evidence gates as the rest of the app, or is a stateless math utility exempt? Flag for product. |

### 8.5 Resourcing — two are already solved; one is a scrape, not an API

- **Weather** — shipped (`providers/open_meteo.py`). Do not re-source or re-evaluate
  providers; the choice is already made and live-verified.
- **Live odds** — 5 providers already configured; only The Odds API is `LIVE_VERIFIED`
  today (§4). That's a provider-health task, not a sourcing gap.
- **Referee statistics** — no reliable free/structured API exists at this scope for
  strictness/card-rate profiles. Per the zero-paid-API constraint this is a scraper job
  for `apps/scraper` against public referee-appointment/match-report pages — a Tier-1
  source in the same sense Firecrawl's own doc already uses for injury/suspension pages
  (§3.5), not a new provider adapter. Starts at `DATA_GAP` until real coverage exists;
  do not seed a strictness index from priors.

---

## §4 — Visual analysis, applied (not theoretical)

Ten screenshots of the live Vercel deployment were checked against the falsifiability
protocol. Two concrete hits, both the exact "contradicting surfaces" defect class this
suite already names generically:

1. **Provider count vs. provider state.** Header banner: "5 configured · 5 enabled."
   Per-provider table on the same screen: `The Odds API = LIVE_VERIFIED`,
   `Football-Data.org = DEGRADED`, `API-Football / Sportmonks / ESPN = UNKNOWN`. Only
   1 of 5 has ever cleared a live probe. "Configured" and "verified" are being shown as
   if they're the same claim; they aren't, and the panel's own caption says so
   ("Configuration and live validation are separate... live validation appears only
   after an explicit operator probe") — the banner chip doesn't reflect that distinction.
2. **Advisory-gap count, three ways, one fixture, one session.** Header table: 9.
   Decision card: 10. Data-gap breakdown: 12 (5+4+2+1). This is the checkpoint-decay
   problem made literal — even the *authoring pass itself* couldn't hold one number
   still. Fix: pick one source of truth (`evidence_quality.advisory_gaps.length`) and
   render every surface from it, not from independently-maintained copy.

No neutral-default-as-measurement or provenance leak was visible in the captured frames
(the Elo panel correctly shows "—" with an explanatory sentence rather than a fabricated
`1500`). Not exhaustive — only 10 static frames were available.

---

## §5 — Evidence discipline (unchanged, kept short)

Never invent an external system's string — a prior pass fabricated provider team-name
spellings and got half of them wrong. A guard you haven't watched fail isn't a guard:
revert, confirm red, restore. A counter showing `resolved == total` alongside a `null`
payload is a discard bug, not missing data — read the counter, make one request, read it
again.

---

## §6 — Gates before every PR

```bash
cd backend

../.venv/Scripts/python.exe -m ruff check src/
../.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly   # v2 says ~9 min, v0 says ~12 — re-time it, don't guess
../.venv/Scripts/python.exe scripts/check_mypy_ceiling.py        # ≤784, no new in touched files
../.venv/Scripts/python.exe scripts/verify_active_artifacts.py
cd .. && pnpm --filter @sabiscore/web lint typecheck test
NODE_ENV=production pnpm --filter @sabiscore/web build
```
Dual-OS notes: `.venv/Scripts/python.exe` explicitly, bare `python` hits the system
interpreter. Stale `.mypy_cache` false-fails the ceiling gate — rerun `--no-incremental`.
Git Bash `/tmp` ≠ Windows Python `/tmp` — use repo-relative scratch paths.
`NODE_ENV=development` breaks `next build` at `/404` with a misleading `<Html>` error —
always pin `production`. Clear `.next` after deleting a route/layout. Merge only via PR,
green + approval, squash — no `--admin`.

---

## §7 — Reporting format (use this; three worked examples below)

```
ITEM · Class    STATE                          EVIDENCE                              CHANGE / NEXT
```

- **Evidence-copy leak · B** — `VERIFIED OPEN` — `describeEvidenceCode()` falls through
  to `titleCaseCode()` at `full-analysis-contract.ts:428`, confirmed live — **fix**:
  5-entry map addition matching the existing lowercase-fragment convention (§3.3); guard
  test hand-maintained, not auto-derived from `feature_contract.json`.
- **Settlement/Phase-2 gate · A** — `WIRED, EXECUTION UNCONFIRMED` — `get_settled_predictions`/
  `walk_forward_validate` reachable from `api/main.py` startup + `performance.py` routes,
  contradicting the generic "unwired" assumption — **next**: probe
  `production.counters.settlement_pass_runs` live before reporting this gate cleared.
- **PPDA duplication risk · —** — `REJECTED` — `AdvancedMetricsEngine.calculate_ppda()`
  would duplicate `statsbomb_aggregator.py`'s already-built `ppda_ratio` — **change**:
  none; redirect that proposal's effort to the copy-map fix above.
- **Portfolio exposure/correlation · A** — `SELF-CORRECTED` — this directive's own v3
  claimed the capability was undefined; `core/portfolio_exposure.py` already implements
  same-day/league haircuts and an aggregate cap — **change**: §3.6 rewritten in place,
  new work redirected to the genuine gap (§8.3's joint-probability parlay math).

---

## Appendix — Prisma scope (reconfirmed)

No `schema.prisma`, no `prisma/`, no `PrismaClient` anywhere. `prisma.config.ts` is the
agent-skills sync tool, unrelated. Schema authority is 9 Alembic migrations. `apps/web`
holds no DB client; backend runs `--workers 1`, one pool — PgBouncer adds a hop, solves
nothing at this scale.
---

## §9 — v5 execution contract: finish the product, improve the forecaster, prove the evidence

### 9.1 Mission

Operate as the **Staff Full-Stack Engineer, Staff ML Engineer, ML Evaluation Owner, SRE/Observability Owner, Product UI Engineer, and Production Release Owner** for the existing SabiScore monorepo.

The objective is not to produce another design document. The objective is to leave the repository in a **working, testable, visually cohesive, evidence-backed production state**, while preserving the existing fail-closed betting boundaries.

Execute the work directly in the repository when write access exists. When a connected repository tool is read-only, produce the exact patch/commit-ready changes locally and report the write limitation rather than claiming that code was deployed.

### 9.2 Non-negotiable operating principles

1. **Evidence before assertions.** For every consequential claim, use the four-bar standard:
   `BUILT → WIRED → CALLED → RUNNING`. Static code presence is not runtime proof.

2. **No silent policy changes.** Do not alter certification thresholds, `MIN_ACTIONABLE_EDGE`, Kelly caps, uncertainty criticality, market-baseline gates, or other safety gates merely because a candidate fails. Gate changes are Class C.

3. **One authority per concept.** No duplicate feature engines, odds engines, verdict engines, cache clients, schema definitions, calibration implementations, or metric implementations.

4. **Train/serve parity is mandatory.** A feature is not eligible for a production model unless the exact same semantic feature can be resolved at serving time for an unplayed fixture.

5. **Opening vs closing market discipline.**
   - Opening/pre-kickoff prices may be model inputs only when they are available at the actual forecast timestamp.
   - Intermediate prices are for temporal market-evolution analysis and optional feature research.
   - Closing prices are evaluation/CLV evidence unless the serving timestamp demonstrably occurs after the closing snapshot.
   - Never leak closing information into training for a forecast that is meant to exist before close.

6. **Real data only.** Never create predictive features from the target label, target-derived transforms, synthetic outcomes, random placeholders, zeros standing for unknowns, or model-generated pseudo-truth.

7. **Abstention is a valid outcome.** When required evidence, uncertainty, identity, market coherence, or feature coverage is insufficient, return the existing non-executable state rather than forcing a prediction or stake.

8. **Do not confuse predictive accuracy with betting edge.** A model can improve classification while adding no market value; a model can have modest accuracy while creating useful calibrated price discrepancies. Measure both.

9. **Consumer truthfulness.** Product surfaces must communicate capability, evidence quality, and confidence without exposing internal model provenance identifiers or overstating value.

10. **Preserve the current architecture.** This is an incremental hardening and improvement program, not a rewrite of Next.js, FastAPI, PostgreSQL, Redis, provider boundaries, or artifact promotion.

---

## §10 — Reconcile the current state before any model-changing work

### 10.1 Latest known runtime evidence

Treat these as the current operational facts until a live probe supersedes them:

```text
21 settled predictions
accuracy_overall = 0.40
baseline_accuracy = 0.333333...
rps_overall = 0.243560...
rps_std = 0.062271...
5 walk-forward folds
CLV joined sample = 6
CLV summary threshold = 10
database = healthy
redis = healthy
model artifacts = available
memory = healthy
settlement failures = 0
```

Interpretation:

- Runtime and settlement are healthy.
- The current live sample is too small to certify predictive superiority.
- The CLV sample is below the current calculation floor.
- The observed 40% accuracy is encouraging relative to the displayed baseline but is not evidence of a durable edge.
- Do not tune the model against these 21 observations.
- Use the real historical corpus for model development and use live settled predictions for longitudinal shadow-production confirmation.

### 10.2 Re-probe exact live state

Run, capture, and persist the results:

```bash
git rev-parse --short=7 HEAD
git rev-parse --short=7 origin/master

curl -fsS .../health
curl -fsS .../metrics
curl -fsS .../api/v1/model-performance
curl -fsS ".../api/v1/matches/upcoming/<id>/full-analysis?league=<CANONICAL>"
```

For each endpoint, preserve HTTP status, timestamp, SHA/version, and the exact JSON fields used for gate decisions.

Do not use `tail`, unguarded pipelines, or grep-only evidence for pass/fail conclusions.

---

## §11 — Milestone ladder

Execute in order. Do not start a later milestone while an earlier milestone has a known blocker that contaminates its evidence.

### M0 — Measurement integrity

**Class B unless a frozen policy/threshold must change.**

Deliver:

- one canonical multiclass Brier implementation and documented convention;
- one canonical RPS implementation;
- log loss as a first-class metric;
- accuracy plus per-class precision/recall;
- calibration error with explicit sample count;
- block/temporal confidence intervals for model-vs-baseline comparisons;
- explicit metric version in every evaluation artifact;
- baseline leaderboard:
  `uniform`, `league prior`, `home-bias`, `Elo`, `structural score model`, `market`, `incumbent`, `candidate`.

Required artifact:

```text
backend/reports/evaluation/metric-contract.json
```

Example shape:

```json
{
  "metric_contract_version": "1.0.0",
  "classification": "3-way 1X2",
  "primary_metric": "rps",
  "secondary_metrics": ["log_loss", "multiclass_brier", "accuracy", "ece"],
  "brier_aggregation": "mean",
  "probability_requirements": {
    "finite": true,
    "bounded": true,
    "sum_to_one": true
  }
}
```

Do not alter the existing certification policy simply to make a metric pass. If the implemented convention differs from the policy, create a Class C decision record that states the old convention, new convention, impact, tests, and policy/version hash.

**Exit gate:**

```text
metric implementation = single-source
metric semantics = documented
unit convention = unambiguous
confidence intervals = present
all baseline forecasts = reproducible
```

---

### M1 — Train/serve feature-contract closure

**Class B.**

The known candidate state includes train/serve positional mismatches and default-heavy feature slots. Close those before adding model complexity.

Deliver:

1. One authoritative feature contract consumed by:
   - historical training;
   - validation;
   - serving;
   - artifact metadata;
   - feature-availability reporting.

2. Zero positional schema mismatch.

3. Zero silently-defaulted training features.

4. Explicit feature status:
   ```text
   RESOLVED
   ADVISORY_GAP
   UNRESOLVED
   ```

5. Exact train/serve test:
   - same feature names;
   - same order;
   - same dtype;
   - same transformations;
   - same default/missingness semantics;
   - same units.

6. Per-feature lineage:
   ```text
   source
   extraction timestamp
   freshness rule
   availability at forecast time
   missingness
   variability
   train/serve parity
   ```

Required gates:

```text
serving_schema_misaligned_slots == 0
training_defaulted_slots == 0
required feature contract present
artifact contract hash == runtime contract hash
```

---

### M2 — Build the real predictive signal matrix

Do not add features indiscriminately. Implement feature families and evaluate them through temporal ablation.

#### Family A — Strength and recency

Use real, pre-kickoff values for:

```text
Elo
home-adjusted Elo
Elo difference
recent Elo trend
opponent-adjusted strength
season-start prior
EWMA form
```

Evaluate:

```text
5-match
10-match
20-match
time-decayed
```

for goals, xG, xGA, shots, shots-on-target, points, pressing and territory where available.

Use recency as an explicit decay mechanism rather than allowing long historical windows to have equal influence.

#### Family B — xG / chance quality

Prefer:

```text
xG for
xG against
xG differential
xG per shot
xGA per shot
recent xG EWMA
recent xGA EWMA
```

with opponent adjustment where the underlying data permits it.

Do not encode unknown xG as zero.

#### Family C — tactical performance

Reuse existing implementations where they already exist:

```text
PPDA
progressive-carry differential
field/territorial control
shot volume
shots on target
set-piece chance quality
```

Do not create a second PPDA engine.

#### Family D — player availability

Where verified data exists:

```text
minutes unavailable
weighted attack absence
weighted defense absence
goalkeeper absence
starting-XI stability
key-player role impact
suspension impact
```

The weighting must come from observed contribution, not hard-coded “star player” labels.

#### Family E — weather

Weather is already acquired. Do not re-source it.

Before model inclusion:

```text
verified team → location mapping
archive backfill
forecast-path parity
persistent historical evidence
feature-schema version
ablation
```

Weather remains advisory unless coverage is demonstrated for both historical training and future serving.

#### Family F — referee context

Only use observed referee/appointment data.

Do not seed referee strictness/card rates from priors or model guesses.

Start as advisory evidence. Promote to a feature only after measurable coverage and temporal availability are demonstrated.

---

### M2 feature-ablation protocol

Every feature family must answer:

```text
Does it improve out-of-sample RPS?
Does it improve log loss?
Does it improve Brier?
Does it improve calibration?
Does it reduce performance variance?
Does it improve market-relative performance?
Does it remain available at serving time?
```

Evaluate at least:

```text
BASE
BASE + ELO
BASE + FORM/EWMA
BASE + XG/XGA
BASE + PLAYER
BASE + TACTICAL
BASE + MARKET
FULL
```

No feature family becomes production-authoritative solely because a tree model reports high feature importance.

---

## §13 — M3 structural + ML forecasting stack

Build a deliberately diversified candidate stack.

### Required candidate components

```text
A — Elo / rating baseline
B — Dixon-Coles / Poisson-style score model
C — XGBoost multiclass
D — LightGBM multiclass
E — CatBoost shadow candidate where the runtime supports it
```

CatBoost is optional infrastructure, not a promotion requirement. It supports multiclass objectives/metrics, but its inclusion must be justified by out-of-sample evidence rather than library availability. Use `MultiClass`/appropriate probabilistic objectives when evaluating it.

The structural model exists to model latent scoring strength; the tree ensemble exists to capture nonlinear feature interactions; the ensemble should exploit error diversity rather than duplicate the same forecast.

### Ensemble requirements

Measure:

```text
per-model RPS
per-model log loss
per-model Brier
per-model ECE
pairwise prediction correlation
error overlap
ensemble RPS
ensemble log loss
```

Use independent random seeds for component hyperparameter searches.

A tuned model that becomes nearly identical to another component should not be assumed to improve ensemble diversity.

---

## §14 — M4 temporal model selection and tuning

### 13.1 Time-aware validation

Never use random train/test splitting for the production forecast task.

Use expanding chronological training with future test windows:

```text
TRAIN → TEST
TRAIN+TEST1 → TEST2
TRAIN+TEST1+TEST2 → TEST3
...
```

The final season must remain untouched until the candidate is frozen.

Each evaluation record must include:

```text
training_end
validation_start
validation_end
sample_count
feature_schema
model hash
calibration hash
market snapshot policy
```

### 13.2 Hyperparameter optimization

Optuna TPE may be used after M1 passes.

Search only inside the training/validation region. Never expose calibration or final holdout data to the optimizer.

Optimize:

```text
primary = RPS
secondary = log loss
diagnostic = Brier + calibration
```

Use independent sampler seeds for XGBoost and LightGBM.

Do not use a single optimization seed for all learners when diversity is part of the ensemble objective.

### 13.3 Minimum dataset floors

Respect the frozen code policy. At minimum, enforce the repository's current documented floors for:

```text
core training
calibration
holdout
walk-forward
Brier decomposition
CLV
```

If a proposed stronger floor is desired, record it as an authorized Class C policy decision rather than editing thresholds opportunistically.

---

## §15 — M5 probability calibration

The output of the predictive stack is not production-ready until the probability distribution is calibrated.

Pipeline:

```text
chronological training
      ↓
out-of-fold base predictions
      ↓
stack/blend
      ↓
later calibration slice
      ↓
temperature scaling candidate
      ↓
untouched final evaluation
```

Compare calibration methods without leakage.

Preferred first candidate:

```text
temperature scaling
```

Consider isotonic calibration only when the calibration sample size is large enough to avoid overfitting.

Report:

```text
RPS
log loss
Brier
ECE
reliability curve
sharpness
per-class calibration
```

Calibration must never use final holdout outcomes.

---

## §16 — M6 uncertainty and abstention

### 15.1 BNN

The previous label-derived BNN artifact is invalid and must never be reused.

Delete any stale local artifact that could accidentally load:

```text
backend/models/bnn_ensemble.pt
```

unless and until it has been replaced by a real-corpus, leakage-tested artifact.

If production uncertainty is required for staking:

1. install the runtime dependency explicitly and reproducibly;
2. train only on real features/outcomes;
3. enforce chronological train/validation/test;
4. prove no target-derived feature generation;
5. validate uncertainty coverage/calibration;
6. verify train/serve feature parity;
7. commit/hash the artifact according to the current promotion authority;
8. smoke the production runtime;
9. verify the public stake gate remains fail-closed when uncertainty is absent.

### 15.2 Abstention

Add/maintain explicit abstention inputs:

```text
feature coverage
identity confidence
market coherence
prediction entropy
ensemble disagreement
calibration uncertainty
data freshness
uncertainty availability
critical/advisory gaps
```

A low-quality forecast must become an explicit hold/no-action state, not a silently degraded “confident” prediction.

---

## §17 — M7 market-relative prediction and CLV evidence

### 16.1 Market benchmark

For each forecast snapshot, persist:

```text
fixture_id
forecast_timestamp
bookmaker
opening odds
intermediate odds
closing odds
de-vig probabilities
model probabilities
```

Respect the single coherent bookmaker snapshot rule.

### 16.2 CLV

Use closing prices only for evaluation/CLV unless the forecast occurs after close.

Track:

```text
CLV per selection
mean CLV
median CLV
positive-CLV rate
CLV by league
CLV by market state
CLV by confidence bucket
CLV by edge bucket
```

Current `n < 10` is insufficient even to generate the existing summary. Do not interpret a tiny positive CLV sample as evidence of edge.

Use evidence tiers:

```text
<10       unavailable
10–49     diagnostic
50–199    preliminary
200–499   meaningful
500+      strong longitudinal evidence
```

These are operational evidence tiers, not universal statistical guarantees.

### 16.3 Critical market question

Every promoted candidate must answer:

> Does SabiScore improve out-of-sample probabilistic forecasts against the coherent market baseline, or merely reproduce the market?

If the model does not beat the market benchmark, it is not a demonstrated betting-edge model even if it improves an internal classification metric.

---

## §18 — M8 production observation and drift

Do not wire the current drift monitor simply because it exists. Wait until its evidence prerequisites are satisfied.

When activated, track:

```text prediction distribution drift
feature distribution drift
missingness drift
provider coverage drift
market availability drift
RPS drift
log-loss drift
Brier drift
ECE drift
CLV drift
abstention rate
```

Use an established training baseline and document the reference window.

Never compute a drift alarm from an unrepresentative tiny production sample.

---

## §19 — M9 product/UI completion

### 18.1 Evidence truth

Create exactly one backend-authoritative evidence summary.

Every frontend surface must consume:

```text evidence_quality.advisory_gaps.length
```

rather than independently maintained counts.

### 18.2 Provider truth

Do not display:

```text 5 configured · 5 enabled
```

as if that means five providers are live verified.

Display distinct states:

```text CONFIGURED
LIVE_VERIFIED
DEGRADED
UNKNOWN
```

and summarize the actual verified count.

### 18.3 Value Bet Matrix

Build only as a read-only analytical surface:

```text rows = fixtures
columns = HOME / DRAW / AWAY
cell = edge
supporting text = model probability + market probability
state = conviction/signal token
```

Rules:

- no color-only meaning;
- no unsupported “value” claim when evidence is incomplete;
- no stake size generated in the component;
- use existing design tokens;
- no new raw hex palette;
- preserve keyboard/focus accessibility.

### 18.4 CLV dashboard

Expose:

```text CLV sample size
coverage %
mean / median CLV
positive CLV %
opening → closing movement
```

with explicit language:

```text “read-only evaluation evidence”
```

Never imply that CLV itself authorizes a stake.

### 18.5 Implied-probability converter

Keep this as a stateless client utility.

It must not implement a second backend verdict/edge engine.

---

## §20 — M10 portfolio/parlay safety

Retain the existing portfolio exposure implementation.

Do not create another exposure/correlation system.

A new parlay explainer may:

```text identify shared correlation groups
show naive independence probability
exclude NO_BET / PARTIAL / SPECULATIVE legs
warn that naive multiplication is an upper bound
```

It must never:

```text place a bet
size a bet
rank a “best parlay”
hide excluded legs
convert uncertainty into a stake
```

Any future combined-stake capability is Class C.

---

## §21 — Research-to-production promotion policy

A candidate is eligible for promotion only when all required gates pass.

### Technical gates

```text
probability simplex valid
feature contract valid
train/serve parity = exact
no silent training defaults
artifact hashes verified
runtime loader passes
rollback metadata present
```

### Predictive gates

```textpositive mean RPS improvement over incumbent
no league regression
market-relative improvement
calibration not materially worse
log loss not materially worse
```

### Data gates

```textchronological evidence
sufficient calibration sample
sufficient holdout sample
real market joins
CLV evidence
feature coverage
```

### Runtime gates

```textbackend healthy
database healthy
cache healthy
settlement healthy
no recurring failures
production counters show execution
```

### Safety gates

```textcritical gaps remain fail-closed
uncertainty unavailable => no stake
unverified market => no stake
unverified fixture => no stake
invalid probabilities => unavailable
stale/conflicted evidence => non-executable
```

Do not promote because one headline metric looks good.

---

## §22 — Recommended concrete target board

Use this board in every finishing pass:

| Board | Required condition | Status source |
|---|---|---|
| Operational | health + DB + cache + models healthy | live probe |
| Settlement | real settlement pass executed | metrics + DB |
| Metrics | canonical RPS/Brier/log-loss contract | code + tests |
| Feature parity | 0 schema mismatches | matrix + tests |
| Feature quality | no silent defaults | matrix |
| Historical data | real corpus only | manifest |
| Model candidate | temporal OOS evidence | training report |
| Calibration | later-slice calibration verified | report |
| Market baseline | candidate beats declared benchmark | comparison report |
| CLV | sufficient joined market outcomes | CLV report |
| Uncertainty | real, non-leaky artifact | artifact manifest |
| UI truth | no contradictory counts/states | Playwright + visual QA |
| Safety | all fail-closed gates green | integration tests |
| Release | CI + build + smoke + rollback | release record |

---

## §23 — Exact implementation workflow

Execute this loop for each milestone:

```text
1. INSPECT
   Read the relevant current code, tests, schema, artifact manifest, and docs.

2. MEASURE
   Run a focused probe before changing anything.

3. PATCH
   Make the smallest production-safe change that closes the identified gap.

4. TEST
   Add or update the narrow regression test first where practical.

5. RUN
   Exercise the real code path, not merely import the module.

6. VERIFY
   Re-run the metric/probe that motivated the change.

7. RECORD
   Update the evidence/report/ledger with exact commit, artifact hash, sample count,
   timestamp, and gate result.

8. PROMOTE OR HOLD
   Promotion is allowed only when the relevant gates are all green.

9. STOP
   If a Class C decision is encountered, stop at that boundary and produce the
   dry-run manifest; never infer authorization.
```

---

## §24 — Required scripts/reports to add or maintain

The repository should converge on these machine-readable artifacts:

```text
backend/reports/evaluation/metric-contract.json
backend/reports/evaluation/baseline-leaderboard.json
backend/reports/evaluation/ablation-report.json
backend/reports/evaluation/walk-forward-report.json
backend/reports/evaluation/calibration-report.json
backend/reports/evaluation/market-comparison.json
backend/reports/evaluation/clv-report.json
backend/reports/evaluation/drift-report.json
backend/reports/features/availability-matrix.json
backend/reports/features/train-serve-parity.json
backend/reports/certification/candidate-manifest.json
```

Each report must include:

```text
generated_at
git_sha
policy_version
policy_hash
feature_schema_version
model_version
artifact_hashes
sample_counts
date ranges
metric definitions
gate decisions
```

Never generate a certification report without reproducible provenance.

---

## §25 — Verification commands

### Backend

```bash
cd backend

../.venv/Scripts/python.exe -m ruff check src/
../.venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly
../.venv/Scripts/python.exe scripts/check_mypy_ceiling.py
../.venv/Scripts/python.exe scripts/verify_active_artifacts.py
```

### Focused ML/evaluation

```bash
../.venv/Scripts/python.exe -m pytest \
  tests/test_zero_fabrication_contract.py \
  tests/test_certification_policy.py \
  -q
```

Run the repository's existing evaluation/training commands for the specific candidate only after M0/M1 pass.

### Web

```bash
cd ..

pnpm --filter @sabiscore/web lint
pnpm --filter @sabiscore/web typecheck
pnpm --filter @sabiscore/web test
NODE_ENV=production pnpm --filter @sabiscore/web build
```

### Security

```bash
gitleaks detect --no-git
```

### Runtime

Probe:

```text
/health
/metrics
/api/v1/model-performance
/model-status
/full-analysis
```

and preserve machine-readable outputs.

---

## §26 — Final release gates

SabiScore is **not “world-class” or “ready for production betting”** merely because the application renders, CI is green, or the incumbent model is available.

### READY FOR GENERAL PRODUCT USE

Requires:

```text
platform healthy
API healthy
UI healthy
database healthy
cache healthy
model artifacts load
settlement running
provider states truthful
evidence counts consistent
no unresolved critical UI/security defects
```

### READY FOR SHADOW PREDICTION

Requires everything above plus:

```text
metric contract frozen
feature contract valid
temporal evaluation valid
candidate artifacts reproducible
calibration pipeline valid
```

### READY FOR LIMITED BETTING INSIGHT

Requires everything above plus:

```text
uncertainty available and validated
market evidence coherent
CLV evidence sufficient
candidate beats incumbent
candidate does not regress by league
candidate demonstrates market-relative improvement
all Class C decisions explicitly authorized
```

### READY FOR FULL PRODUCTION BETTING

Requires everything above plus:

```textlongitudinal shadow evidence
stable calibration
stable CLV
stable production drift
rollback proven
no unresolved critical gaps
stake/exposure policy explicitly authorized
```

No stage may silently inherit the authority of a higher stage.

---

## §27 — Research basis and implementation references

Use the following current references to validate implementation choices; do not treat any external article as a reason to override the repository's frozen safety policy.

- scikit-learn calibration and time-aware validation documentation:
  `https://scikit-learn.org/stable/modules/calibration.html`
  `https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html`
- scikit-learn permutation importance:
  `https://scikit-learn.org/stable/modules/permutation_importance`
- CatBoost multiclass objectives/metrics:
  `https://catboost.ai/docs/en/concepts/loss-functions-multiclassification`
- Football-Data historical results, statistics and odds:
  `https://www.football-data.co.uk/data`
- Football-Data odds timing/data notes:
  `https://www.football-data.co.uk/downloadm.php`
- Dixon–Coles football score modelling:
  use the peer-reviewed paper/reference already cited in the engineering research record; do not substitute a blog summary for the methodological source.

External references inform model design. They do not authorize a production promotion, a betting-policy change, a new paid provider, or a new schema.

---

## §28 — Operator completion report

At the end of every execution pass, report exactly:

```text
SABISCORE FINISHING REPORT
COMMIT:
ENVIRONMENT:
ACTIVE MODEL:
FEATURE SCHEMA:
POLICY VERSION/HASH:

M0 METRICS:
M1 FEATURE PARITY:
M2 FEATURE SIGNALS:
M3 MODEL STACK:
M4 TEMPORAL VALIDATION:
M5 CALIBRATION:
M6 UNCERTAINTY:
M7 MARKET/CLV:
M8 DRIFT:
M9 UI:
M10 PORTFOLIO SAFETY:

SETTLED PREDICTIONS:
WALK-FORWARD N:
RPS:
LOG LOSS:
BRIER:
ECE:
MARKET BASELINE:
CLV JOINED:
CLV STATUS:

CRITICAL GAPS:
ADVISORY GAPS:

PROMOTION:
STAKE PERMITTED:
ROLLBACK:

BLOCKERS:
NEXT AUTHORIZED ACTION:
```

Every `PASS`, `GREEN`, `VERIFIED`, or `READY` label must point to actual evidence.

Never report “complete” where the evidence bar is only `BUILT`, `WIRED`, or `CALLED`.

---

## §29 — Final directive

**Do not rebuild SabiScore. Finish it surgically.**

Prioritize, in order:

```text
measurement integrity
→ train/serve feature parity
→ real feature quality
→ structural + ML ensemble
→ temporal tuning
→ probability calibration
→ real uncertainty
→ market baseline
→ CLV evidence
→ shadow production
→ certification
→ limited production activation
```

The immediate objective is not to make SabiScore produce more predictions.

The immediate objective is to make every prediction **measurable, reproducible, temporally honest, calibrated, market-aware, uncertainty-aware, and operationally auditable**.

Only after those foundations are green should additional complexity such as xT, PSxG, referee intelligence, weather features, or parlay analytics graduate from research/advisory status into production predictive features.

**Never trade evidence quality for feature count. Never trade safety for a green dashboard. Never promote an attractive number whose provenance cannot be reproduced.**
