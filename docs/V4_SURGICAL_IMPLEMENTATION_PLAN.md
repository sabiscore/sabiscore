# SabiScore V4 Final Surgical Upgrade Pack

## Executive Summary

This pack finalizes the V4/Phase 9 candidate data-source layer for SabiScore without rewriting the current Phase 8 production architecture. It keeps the existing canonical Phase 8 89-feature inference path (legacy 86-named aliases retained) intact and adds a safer, more modular source layer for advanced xG, official fixtures/results, StatsBomb Open Data experiments, and market-efficiency features.

The upgrade is intentionally **shadow-first**:

1. Add connectors and pure feature builders.
2. Backfill artifacts offline.
3. Log candidate features in metadata only.
4. Retrain/evaluate with walk-forward gates.
5. Promote by league canary only after SHAP/ablation validation.

## Final Corrections Applied

Compared with the first V4 pack, this final pack applies these corrections:

- Writes metadata/manifest files as real JSON instead of Python `str(dict)`.
- Reads `FOOTBALL_DATA_API_KEY` and `PHASE9_SOURCES_PATH` from environment by default.
- Replaces raw odds drift with log drift `ln(current/opening)` for scale-stable market movement.
- Keeps CLV null unless explicit closing odds are supplied.
- Removes brittle floating-point assertions in tests and uses `pytest.approx`.
- Adds `StatsBombOpenDataSource` for offline event/shot experiments.
- Adds `source_registry.py` for explicit, auditable source activation.
- Normalizes more Understat/soccerdata column variants.
- Adds script path bootstrapping so the backfill script works from repo root or `backend/`.

## Upgraded Files Included

| Path | Status | Purpose |
|---|---:|---|
| `backend/src/connectors/base.py` | New/replace | Async HTTP client, retries, source metadata, connector errors. |
| `backend/src/connectors/football_data_org.py` | New/replace | football-data.org v4 fixture/results connector. |
| `backend/src/connectors/understat_source.py` | New/replace | Optional soccerdata-backed Understat xG ingestion and rolling xG features. |
| `backend/src/connectors/statsbomb_open.py` | New | Local StatsBomb Open Data events/shot loader. |
| `backend/src/connectors/odds_market.py` | New/replace | Odds normalization, implied probabilities, EV, edge, log drift, true CLV helper. |
| `backend/src/connectors/source_registry.py` | New | Config-driven source registry for auditing/shadow mode. |
| `backend/src/connectors/__init__.py` | New/replace | Public exports for connector layer. |
| `backend/src/features/phase9_xg_market_features.py` | New/replace | Hybrid xG and value-market candidate feature builders. |
| `backend/scripts/backfill_v4_data_sources.py` | New/replace | Offline artifact backfill for football-data.org and Understat. |
| `backend/tests/test_connectors/test_odds_market.py` | New/replace | Unit tests for market math and CLV safety. |
| `backend/tests/test_connectors/test_phase9_xg_market_features.py` | New/replace | Unit tests for hybrid xG fallbacks and Understat rollups. |
| `.env.v4.example` | New/replace | Safe default env controls. |

## Surgical Patch Instructions

### 1. Copy files

Extract this pack at the repository root:

```bash
unzip sabiscore-v4-final-upgrade.zip -d /tmp/sabiscore-v4-final
rsync -av /tmp/sabiscore-v4-final/sabiscore-v4-final-upgrade/ ./
```

### 2. Update `backend/requirements.txt`

Append these lines first; avoid broad dependency upgrades until CI is green:

```txt
# ==============================================================================
# V4 / Phase 9 candidate data-source tooling
# ==============================================================================
soccerdata>=1.8.7
kloppy>=3.17.0
rapidfuzz>=3.9.7
```

Optional core upgrades after all tests pass:

```txt
fastapi>=0.115,<0.117
uvicorn[standard]>=0.30,<0.32
httpx>=0.27,<0.29
scikit-learn>=1.5,<1.7
```

### 3. Update `backend/src/core/config.py`

Add near API/source settings:

```py
sportmonks_api_key: Optional[str] = Field(default=None, alias="SPORTMONKS_API_KEY")
api_football_key: Optional[str] = Field(default=None, alias="API_FOOTBALL_KEY")
the_odds_api_key: Optional[str] = Field(default=None, alias="THE_ODDS_API_KEY")
```

Add near Phase 8/source-path settings:

```py
use_phase9_candidate_features: bool = Field(
    default=False,
    alias="USE_PHASE9_CANDIDATE_FEATURES",
    description="Compute V4/Phase 9 xG and odds-market candidate features in shadow mode.",
)
phase9_shadow_only: bool = Field(
    default=True,
    alias="PHASE9_SHADOW_ONLY",
    description="When true, Phase 9 features are logged/metadata only and not passed to model inference.",
)
phase9_sources_path: Path = Field(
    default_factory=lambda: _PROJECT_ROOT / "data" / "processed" / "v4_sources",
    alias="PHASE9_SOURCES_PATH",
)
```

### 4. Update `backend/src/data/aggregator.py`

Import:

```py
from ..features.phase9_xg_market_features import build_hybrid_xg_features
```

After `team_stats = self.fetch_team_stats()` succeeds/falls back and before the `data = {...}` payload:

```py
phase9_candidate_features = {}
if getattr(settings, "use_phase9_candidate_features", False):
    try:
        phase9_candidate_features = build_hybrid_xg_features(
            home_team=self.teams["home"],
            away_team=self.teams["away"],
            team_stats=team_stats,
        )
    except Exception as exc:
        logger.warning("Phase 9 candidate xG features failed for %s: %s", self.matchup, exc)
```

Inside the `metadata` object:

```py
"phase9_candidate_features": phase9_candidate_features,
"phase9_shadow_only": getattr(settings, "phase9_shadow_only", True),
```

### 5. Update `backend/src/services/prediction.py`

Import:

```py
from ..features.phase9_xg_market_features import build_value_market_features
```

After `probabilities = {...}`:

```py
phase9_market_features = {}
if getattr(settings, "use_phase9_candidate_features", False):
    phase9_market_features = build_value_market_features(
        model_probabilities=probabilities,
        current_odds=request.odds or {},
    )
```

After `metadata = self._build_metadata(...)`:

```py
if phase9_market_features:
    metadata.setdefault("phase9_candidate_features", {})["market_efficiency"] = phase9_market_features
    metadata["phase9_shadow_only"] = getattr(settings, "phase9_shadow_only", True)
```

## Validation Commands

```bash
cd backend
pip install -r requirements.txt
pytest tests/test_connectors -q
pytest tests -q
python scripts/backfill_v4_data_sources.py --league epl --season 2025 --skip-understat
```

## Rollout Checklist

1. Create branch: `git checkout -b feat/v4-phase9-source-layer`.
2. Tag rollback point: `git tag pre-v4-phase9-source-layer`.
3. Apply files and config snippets.
4. Keep `USE_PHASE9_CANDIDATE_FEATURES=false` for the first deploy.
5. Enable in staging with `USE_PHASE9_CANDIDATE_FEATURES=true` and `PHASE9_SHADOW_ONLY=true`.
6. Confirm existing API response contracts remain unchanged except optional metadata.
7. Backfill one league/season only.
8. Run walk-forward retraining separately; do not pass candidate features into production model frames until gates pass.

## Risks & Mitigation

| Risk | Mitigation |
|---|---|
| Scraping/ToS risk | Prefer official APIs. Keep Understat disabled unless policy-approved. |
| Feature leakage | CLV is null without closing odds; use pre-match odds only for training features. |
| Schema mismatch | Candidate features stay in metadata until retrained artifacts include them. |
| Dependency conflicts | Add optional dependencies first; delay core version bumps. |
| Team-name joins | Add canonical team map/rapidfuzz before multi-source production joins. |
| Backtest inflation | Use expanding-window splits and compare against current Phase 8 baseline. |
