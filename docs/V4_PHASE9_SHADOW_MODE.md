# V4 / Phase 9 Candidate Enrichment — Shadow Mode

Status: **shadow-mode, disabled by default** (`USE_PHASE9_CANDIDATE_FEATURES=false`,
`PHASE9_SHADOW_ONLY=true`). This document covers what was added, how it is
wired in, the risk/mitigation register, the test strategy, and the rollout
plan.

## 1. What this adds

Four new connector primitives under `backend/src/connectors/`:

- **`base.py`** — `AsyncJSONClient`, `ConnectorError`, `ConnectorRateLimitError`,
  `SourceMeta`. Shared async HTTP/retry/freshness primitives for new
  connectors. Independent of the legacy `opta.py` / `betfair.py` / `pinnacle.py`
  (which keep using `aiohttp` directly — untouched).
- **`football_data_org.py`** — `FootballDataOrgClient`. Official, API-first
  fixture/result/standings connector for the top-5 leagues. Reads
  `settings.football_data_api_key` (already existed; no rename needed).
- **`odds_market.py`** — pure functions: `normalize_decimal_odds`,
  `bookmaker_margin`, `implied_probabilities`, `power_method_probs`,
  `compute_market_features`. No I/O, no new dependencies.
- **`understat_source.py`** / **`statsbomb_open.py`** — offline/batch-only xG
  and event-data sources (Understat via `soccerdata`, StatsBomb open-data via
  local JSON). Never imported on the live request path.
- **`source_registry.py`** — `build_source_registry()` / `registry_summary()`,
  a config-driven catalogue of the above for health checks and logs.

One new feature module:

- **`backend/src/features/phase9_xg_market_features.py`** —
  `build_hybrid_xg_features`, `build_value_market_features`,
  `build_market_efficiency_report`. Combine Phase 8 team-stats xG with
  optional Understat rollups, and compute EV/edge/CLV/drift over supplied
  odds.

One offline script:

- **`backend/scripts/backfill_v4_data_sources.py`** — CLI backfill to Parquet
  + JSON manifest under `PHASE9_SOURCES_PATH` (default
  `data/processed/v4_sources/`). Does not touch any production artifact.

Plus a full test suite under `backend/tests/test_connectors/` (110 tests, all
passing — see §5).

## 2. How it's wired into the live path

Both integration points are guarded by
`getattr(settings, "use_phase9_candidate_features", False)` and write
**only to `metadata`**, never to the model input frame, `probabilities`, or
`value_bets`.

### `DataAggregator.fetch_match_data` (`backend/src/data/aggregator.py`)

After `team_stats = self.fetch_team_stats()`:

```python
phase9_candidate_features: Dict[str, Any] = {}
if getattr(settings, "use_phase9_candidate_features", False):
    try:
        phase9_candidate_features = {
            "hybrid_xg": build_hybrid_xg_features(
                home_team=self.teams["home"],
                away_team=self.teams["away"],
                team_stats=team_stats,
            )
        }
    except Exception as e:
        logger.warning(f"Phase 9 candidate feature computation failed: {e}")
        phase9_candidate_features = {}
```

`metadata["phase9_candidate_features"]` and `metadata["phase9_shadow_only"]`
are added to the existing `metadata` dict (alongside `metadata["freshness"]`).
`historical_stats`, `current_form`, `team_stats`, etc. are **byte-for-byte
unchanged** regardless of this flag — confirmed via `_serialize_for_cache`
round-trip (nested float dicts already supported).

### `PredictionService.predict_match` (`backend/src/services/prediction.py`)

After `metadata = self._build_metadata(...)`:

```python
if getattr(settings, "use_phase9_candidate_features", False):
    try:
        metadata["phase9_candidate_features"] = {
            "market_efficiency": build_market_efficiency_report(
                model_probabilities=probabilities,
                current_odds=request.odds or {},
            )
        }
    except Exception as exc:
        logger.warning("Phase 9 market-efficiency report failed: %s", exc)
        metadata["phase9_candidate_features"] = {}
    metadata["phase9_shadow_only"] = getattr(settings, "phase9_shadow_only", True)
```

**Design decision — `build_market_efficiency_report` over
`build_value_market_features`:** the original plan's snippet used the bare
`build_value_market_features` (a thin pass-through to `compute_market_features`,
still provided and tested). We wire the richer
`build_market_efficiency_report` instead — same pure-math cost, but nests the
raw features under `"features"` and adds `bookmaker_margin`,
`market_complete`, `market_sharpness` (`sharp`/`standard`/`unknown`), a
`value_bets` list (model EV vs. current odds with power-method "sharp"
probabilities **and a full-Kelly stake fraction per bet, sorted strongest
first**), `recommended_kelly_fraction`, and `clv_available`. This gives
materially more shadow-mode signal per request for zero extra cost.
`request.odds` is `Dict[str, float]` and defaults to `{}` in the schema, so
`request.odds or {}` is always safe; `opening_odds`/`closing_odds` are `None`
at request time (not in `MatchPredictionRequest`), so `odds_drift_*` and
`clv_*` are `null` until those are populated from a future market-snapshot
pipeline.

`PredictionResponse.metadata: Dict[str, Any]` accepts arbitrary additive keys
— no schema migration needed.

### `backend/src/connectors/__init__.py` — merge, not overwrite

The package already exported `OptaConnector`, `BetfairConnector`,
`PinnacleConnector` (used by `api/websocket.py`). The new `__init__.py`
preserves all three legacy exports and adds the V4 primitives. Verified:

```python
from src.connectors import OptaConnector, BetfairConnector, PinnacleConnector, FootballDataOrgClient, build_source_registry
# -> imports cleanly, all five symbols resolve
```

### Optional, additive operational visibility

- `backend/src/api/endpoints/monitoring.py` `/health` now includes a
  `components.v4_sources` block (`status: "informational"`,
  `registry_summary(...)`). It **never** sets `degraded=True`.
- `backend/src/api/main.py` `lifespan()` logs the V4 source registry summary
  once at startup (`logger.info("V4 source registry: %s", ...)`). Wrapped in
  `try/except`; failure here cannot abort startup (unlike the existing strict
  model-loading check).

## 3. Relationship to existing Phase 8 code (no duplication)

| Existing (Phase 8)                                   | New (Phase 9 candidate)                              | Relationship |
|-------------------------------------------------------|-------------------------------------------------------|---|
| `features/market.py::market_movement_features`        | `connectors/odds_market.py::compute_market_features`  | Different key convention (`home/draw/away` vs `home_win/draw/away_win`), different outputs (5 drift features feeding the canonical Phase 8 model vs. EV/edge/CLV/margin for metadata). No name collisions; documented in both modules' docstrings. |
| `settings.football_data_api_key` (already existed)    | `connectors/football_data_org.py`                     | Connector reads the existing setting; **no rename**. |
| `settings.statsbomb_cache_path` (Phase 8 parquet cache)| `connectors/statsbomb_open.py` (open-data JSON loader)| Distinct artifacts; loader does not read/write the Phase 8 cache path. |
| `connectors/{opta,betfair,pinnacle}.py` (aiohttp, live)| `connectors/{base,football_data_org,...}.py` (httpx, async) | Coexist in the same package via merged `__init__.py`; zero overlap in responsibilities. |
| `team_stats["home"]["xg_avg_5"/"xg_conceded_avg_5"]`   | `build_hybrid_xg_features(...)`                       | Consumes these fields as-is (confirmed present via `_create_mock_team_stats` and `fetch_team_stats`); adds `hybrid_*` / `understat_*` prefixed keys only — no collisions with the 86 canonical feature names. |

## 4. Risks & mitigations

| Risk | Mitigation |
|---|---|
| New code path throws and breaks a prediction request | Both integration points are wrapped in `try/except`, default to `{}` on failure, and only run when `USE_PHASE9_CANDIDATE_FEATURES=true` (default `false`). |
| `connectors/__init__.py` merge breaks legacy live-odds imports | Verified: `from src.connectors import OptaConnector, BetfairConnector, PinnacleConnector` still resolves; `api/websocket.py` imports unchanged. Full repo `aiohttp` dependency (already pinned `==3.9.1`) is the only requirement for package import — no new top-level deps introduced in `__init__.py`. |
| New deps (`soccerdata`, `rapidfuzz`, optional `kloppy`) bloat / break the build | `rapidfuzz` is a small pure-Python-API wheel (verified installable). `soccerdata` and `kloppy` imports are **deferred to function bodies** in `understat_source.py` / `statsbomb_open.py` — absence raises a clear `ImportError` only when that offline path is actually invoked, never at module import time. |
| Cache serialization breaks on new nested dict in `metadata` | `_serialize_for_cache` / `_deserialize_from_cache` already handle nested dicts of floats (Phase 8 `freshness` block is the same shape). No change needed; covered by existing aggregator tests. |
| `power_method_probs` produces wrong "sharp" probabilities | **Found and fixed during integration testing** (see §6, "Bug fix"). Binary-search direction was inverted, converging to a near-uniform distribution instead of the correct margin-proportional one. Fixed + regression test added (`test_favourite_gets_uplift_vs_proportional`). |
| `statsbomb-open-data` registry entry reports `enabled=true` even with no open-data clone present | Documented limitation (see §7). Low risk: this source is `request_time_safe=False` (never auto-invoked) and the registry is informational-only. Phase 9.1 follow-up: dedicated `statsbomb_open_data_root` setting. |
| football-data.org free-tier rate limits (10 req/min) | `AsyncJSONClient.get_json_with_rate_limit_backoff` honours `Retry-After` on HTTP 429 with capped sleep. Connector is offline/batch-only (`request_time_safe=False`) — never called from the live request path. |
| Existing canonical Phase 8 model accidentally retrained on new columns | Hybrid xG / market features are **not** added to `feature_frame` / `feature_vector` anywhere — only to `metadata`. The walk-forward retraining scripts remain the only path to feature-frame changes, and are not touched by this PR. |

## 5. Testing strategy

```bash
cd backend
pytest tests/test_connectors -v
```

**110/110 passing** (validated in a clean venv with the repo's pinned
`pandas==2.2.3`, `numpy==1.26.2`, `httpx==0.25.2`, `tenacity==8.2.3`,
`aiohttp==3.9.1`, plus new `rapidfuzz`, `respx==0.21.1`):

- `test_odds_market.py` (32 tests) — normalisation, margin, market
  completeness (`is_complete_market`), implied/sharp probabilities,
  EV/edge/CLV/drift, including the `test_favourite_gets_uplift_vs_proportional`
  regression guard.
- `test_phase9_xg_market_features.py` (34 tests) — `_safe_float`,
  `_latest_team_row` (casefold + `match_order` sorting), `_kelly_fraction`
  via the report, hybrid xG (Understat-priority + team-stats fallback),
  market-efficiency report (value bets, Kelly sizing + descending sort,
  sharpness gating on market completeness, CLV availability).
- `test_understat_source.py` (10 tests) — `_resolve_team_name` and
  `rolling_xg_features` chronological-sort / shift-1 anti-leakage guarantees.
- `test_source_registry.py` (15 tests) — registry shape, per-source enable
  logic, JSON-serialisability.
- `test_football_data_org.py` (7 tests, `respx`-mocked) — matches/standings
  parsing, league-code mapping, 429/backoff handling, malformed-payload
  error.
- `test_statsbomb_open.py` (16 tests) — event JSON parsing, shot/xG
  aggregation, kloppy-absent path.

Additionally end-to-end smoke-tested against the **real** repo code (not just
the new test files):

```python
agg = DataAggregator(matchup="Arsenal vs Chelsea", league="epl")
team_stats = agg._create_mock_team_stats()
build_hybrid_xg_features(home_team="Arsenal", away_team="Chelsea", team_stats=team_stats)
# -> {'hybrid_home_xg_for_5': 2.04, 'hybrid_home_xg_against_5': 1.07, ...}
```

```python
build_market_efficiency_report(
    model_probabilities={"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
    current_odds={"home_win": 2.1, "draw": 3.3, "away_win": 3.8},
)
# -> bookmaker_margin=0.042, has_value=True, value_bets=[{"outcome": "home_win", "ev": 0.155, ...}]
```

Config and import smoke tests:

```python
from src.core.config import settings
settings.use_phase9_candidate_features  # False
settings.phase9_shadow_only             # True
settings.phase9_sources_path            # .../data/processed/v4_sources

from src.connectors import OptaConnector, BetfairConnector, PinnacleConnector, FootballDataOrgClient
# -> all resolve
```

## 6. Bug fix discovered during integration

While smoke-testing `build_market_efficiency_report`'s `sharp_implied_prob`
field, the favourite's "sharp" probability (0.345) came out **lower** than
its simple proportional implied probability (0.457) — the opposite of the
expected favourite-longshot-bias correction. Root cause: the binary search in
`power_method_probs` had an inverted bisection direction
(`if total > 1.0: lo = mid else: hi = mid`, should be `hi = mid` / `lo = mid`
respectively, since `total(mid)` is monotonically increasing). This converged
`k` toward the upper bound (≈10), flattening all outcomes toward a uniform
1/3 instead of sharpening the favourite.

**Fixed** in `connectors/odds_market.py` (corrected bisection direction +
explanatory comment). **Regression-tested**: new
`test_favourite_gets_uplift_vs_proportional` asserts
`power_method_probs(odds)["home_win"] > implied_probabilities(odds)["home_win"]`
for an example overround market. All 110 tests pass with the fix.

## 6a. Refinement pass — corrections & creative enhancements

A second surgical pass added the following, each test-covered:

- **Market-completeness gating (correctness).** `bookmaker_margin` over a
  *partial* 1X2 market can return a negative "margin", which the old
  `market_sharpness = "sharp" if margin < 0.04 else "standard"` rule would
  mislabel as `sharp`. Added `is_complete_market(odds)` to
  `connectors/odds_market.py`; `build_market_efficiency_report` now emits
  `market_complete` and classifies `market_sharpness` as `"unknown"` whenever
  the market is incomplete.
- **Kelly stake sizing (creative enhancement).** Each value bet now carries a
  full-Kelly `kelly_fraction` (`f* = (b·p − q)/b`, clamped to `[0, 1]`), the
  `value_bets` list is sorted strongest-first by Kelly, and the report exposes
  `recommended_kelly_fraction`. This dovetails with the repo's existing
  `RLBettingAgent` / value-bet detection and gives the shadow-mode log a
  directly actionable sizing signal at zero extra compute cost. (Full Kelly is
  the canonical quantity; consumers typically scale to half/quarter-Kelly.)
- **Understat anti-leakage hardening (correctness).**
  `UnderstatTeamXGSource.rolling_xg_features` previously trusted the input row
  order for its shift-1 rolling windows. It now sorts by a `date_col` (default
  `"date"`, stable sort) when present before assigning `match_order`, making
  the "no look-ahead leakage" guarantee robust against unsorted
  `read_schedule()` output. Falls back to input order (documented) when no date
  column exists.
- **football-data.org season parse (minor correctness).** Season-year
  extraction now tolerates a present-but-`null` `startDate`
  (`str(... or "")[:4]`) instead of yielding the string `"None"`.

## 7. Known limitations / Phase 9.1 follow-ups

- `source_registry.py`'s `statsbomb-open-data` entry gates on
  `settings.statsbomb_cache_path`, which always has a non-`None` default
  (it's the *Phase 8* cache-path setting, a different artifact). This means
  the registry currently reports this source as `enabled=true` regardless of
  whether a StatsBomb open-data clone actually exists on disk. Low risk
  (informational-only, `request_time_safe=False`). Follow-up: add a dedicated
  `statsbomb_open_data_root: Optional[Path] = None` setting.
- `sportmonks_api_key`, `api_football_key`, `the_odds_api_key` are added as
  config placeholders (per the original V4 plan) but have **no connector
  implementation yet** and are **not** registry entries. Adding them as
  registry sources is deferred to keep `build_source_registry()` at exactly 4
  sources (matches `test_source_registry.py`'s
  `test_returns_four_sources_by_default`). Phase 9.1: implement connectors,
  then expand the registry + update that test's expected count.
- `odds_drift_*` / `clv_*` features remain `null` at request time because
  `MatchPredictionRequest` has no `opening_odds`/`closing_odds` fields. A
  future market-snapshot capture job (writing opening/closing snapshots keyed
  by `match_id`) would let `PredictionService` populate these.

## 8. Rollout plan

| Stage | Action | Exit criteria |
|---|---|---|
| 0 (this PR) | Merge with `USE_PHASE9_CANDIDATE_FEATURES=false`. Zero behavioural change to existing endpoints. | CI green; 110/110 new tests pass; existing test suite unaffected. |
| 1 | Enable in staging only (`USE_PHASE9_CANDIDATE_FEATURES=true`, `PHASE9_SHADOW_ONLY=true`). Inspect `metadata.phase9_candidate_features` on a sample of real requests. | `phase9_candidate_features` populated without errors across at least one full day of staging traffic; `/health` shows `v4_sources`. |
| 2 | Enable in production, shadow-only. Begin logging `value_bets` / `hybrid_xg` for offline analysis (no behaviour change — still metadata-only). | 7-day soak with zero error-rate increase attributable to the new code path (monitor `logger.warning("Phase 9 ... failed")`). |
| 3 | Offline: run `backfill_v4_data_sources.py` for the 5 top leagues, build Understat rollups, run SHAP ablation comparing `hybrid_xg_diff` / `hybrid_total_xg_expectation` against existing `xg_diff_5`. | Ablation shows non-negative RPS impact for any feature proposed for promotion. |
| 4 | If a feature passes ablation: add it to the canonical feature list via the existing walk-forward retraining gate (separate PR, out of scope here). `PHASE9_SHADOW_ONLY` remains `true` until the retrained model is deployed. | New model artifact passes existing Phase 8 promotion checks. |
| 5 | Phase 9.1: implement SportMonks / API-Football / The Odds API connectors behind their placeholder keys; expand `source_registry` to 7 sources; add `statsbomb_open_data_root`. | New registry tests pass; `enabled_source_names()` reflects real connector availability. |
