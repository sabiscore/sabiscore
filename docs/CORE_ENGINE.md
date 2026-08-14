# SabiScore Core Engine v2.1

The Core Engine is the deterministic betting-intelligence layer exposed at:

```text
POST /api/v1/core-engine/analyze
```

It transforms verified pre-match inputs into auditable betting decisions. It does not fetch live data, infer missing values, substitute league averages, or call legacy value-bet helpers that can inject defaults.

## Implementation Map

| Concern | File |
|---|---|
| FastAPI route | `backend/src/api/endpoints/core_engine.py` |
| Request/response schemas | `backend/src/schemas/core_engine.py` |
| Deterministic evaluator | `backend/src/services/core_engine.py` |
| Regression tests | `backend/tests/test_core_engine.py` |

The route is registered through `backend/src/api/endpoints/__init__.py`, so it is mounted under the normal `/api/v1` prefix.

## Supported Competitions

| Code | Coverage |
|---|---|
| `EPL` | Tier 1 |
| `LA_LIGA` | Tier 1 |
| `SERIE_A` | Tier 1 |
| `BUNDESLIGA` | Tier 1 |
| `LIGUE_1` | Tier 1 |
| `EREDIVISIE` | Tier 1 |
| `UCL` | Soft coverage |

UCL soft coverage is deliberately conservative: UCL fixtures can reach `ACTIONABLE`, but they cannot reach `HIGH_CONVICTION` unless a future dedicated validated UCL model variant is added and explicitly wired into the evaluator.

## Runtime Constants

| Setting | Value |
|---|---:|
| Minimum actionable edge | `0.042` |
| Fractional Kelly multiplier | `0.125` |
| Maximum Kelly cap | `0.025` |
| Speculative public stake | `0.0` (watchlist-only) |
| Minimum market overround | `> 1.0` |
| Maximum market overround | `<= 1.25` |
| Probability sum tolerance | `+/- 0.005` |
| Fresh market threshold | `<= 900s` |
| Recent market threshold | `<= 3600s` |
| High-conviction epistemic max | `0.05` |

## Input Contract

The request body is:

```json
{
  "matches": [
    {
      "match_id": "string",
      "home_team": "string",
      "away_team": "string",
      "competition": "EPL",
      "kickoff_utc": "2026-08-15T15:00:00Z",
      "model": {
        "home_probability": 0.55,
        "draw_probability": 0.25,
        "away_probability": 0.20,
        "model_version": "core-v1",
        "calibration_method": "isotonic",
        "calibration_validated": true,
        "epistemic_uncertainty": 0.05,
        "aleatoric_uncertainty": 0.12,
        "confidence_tier": "OK"
      },
      "market": {
        "bookmaker": "ExampleBook",
        "market_type": "1X2",
        "home_odds": 2.1,
        "draw_odds": 3.4,
        "away_odds": 4.5,
        "captured_at": "2026-08-15T13:45:00Z"
      },
      "signals": {
        "lineup_status": "CONFIRMED",
        "sharp_market_signal": "CONFIRMING",
        "confirmed_absences": []
      },
      "freshness": {
        "model_features_seconds": 300,
        "market_seconds": 120,
        "injury_news_seconds": 400,
        "lineup_seconds": 180
      },
      "source_status": {
        "model": "VERIFIED",
        "market": "VERIFIED",
        "team_metrics": "VERIFIED",
        "availability": "VERIFIED"
      }
    }
  ]
}
```

The schema keeps fields optional at parse time so the evaluator can preserve nulls and return `PARTIAL` with explicit `data_gaps` instead of rejecting early with a generic 422 for incomplete operational envelopes.

## Validation Flow

Each match is evaluated independently.

1. Required fields are checked for nulls.
2. Source statuses are scanned for `DATA_GAP`, `STALE`, and `CONFLICTING`.
3. Model probabilities must each be in `[0, 1]` and sum to `1.0 +/- 0.005`.
4. Odds must be decimal values greater than `1.0`.
5. Market overround must be `> 1.0` and `<= 1.25`.
6. Freshness state is derived from freshness seconds and source status.
7. If any critical gap exists, the match returns `PARTIAL`.

Under `PARTIAL`, the following fields are locked to `null`:

- `best_market`
- `edge`
- `edge_percentage_points`
- `expected_value`
- `minimum_acceptable_odds`

The stake is always `pass` and `stake_fraction` is always `0.0`.

## Market Calculus

For each supported 1X2 outcome:

```text
q_i = 1 / odds_i
overround = q_home + q_draw + q_away
fair_probability_i = q_i / overround
edge_i = model_probability_i - fair_probability_i
expected_value_i = (model_probability_i * odds_i) - 1
full_kelly_i = expected_value_i / (odds_i - 1)
recommended_kelly_i = min(max(full_kelly_i, 0) * 0.125, 0.025)
```

The evaluator only supports:

- `HOME_ML`
- `DRAW_ML`
- `AWAY_ML`

It does not infer secondary-market edges.

## Candidate Ranking

Candidates are ranked by confidence-adjusted value:

```text
max(EV, 0)
  * uncertainty_factor
  * freshness_factor
  * completeness_factor
  * market_stability_factor
```

The batch-level `top_opportunities` list includes at most three match IDs and only includes matches with `HIGH_CONVICTION` or `ACTIONABLE` verdicts. `SPECULATIVE` is returned only through the watchlist surface.

Tie breakers are deterministic:

1. Highest confidence-adjusted value.
2. Highest expected value.
3. Lowest epistemic uncertainty.
4. Freshest market data.
5. Alphanumeric `match_id`.

## Verdict Semantics

| Verdict | Meaning |
|---|---|
| `PARTIAL` | Critical input is missing, stale, conflicting, or invalid. No bet fields are emitted. |
| `NO_BET` | Inputs are valid, but no candidate has both positive edge and positive EV. |
| `HOLD` | Positive value exists, but edge/gating restrictions require inaction. |
| `SPECULATIVE` | Positive EV exists below actionable edge with confirming signals; watchlist-only with public stake fixed at `0.0`. |
| `ACTIONABLE` | Positive EV, edge >= `0.042`, validated calibration, OK confidence, fresh/recent market. |
| `HIGH_CONVICTION` | Actionable plus very low epistemic uncertainty and confirmed lineup; never for UCL. |

`PARTIAL`, `NO_BET`, and `HOLD` are successful executions. They preserve capital by returning `stake: "pass"` and `stake_fraction: 0.0`.

## Invalidation Conditions

Actionable outputs include falsifiable invalidation conditions. The minimum acceptable odds value is:

```text
1 / (model_probability - 0.042)
```

It is emitted only when the denominator is positive. Any critical source status changing to `STALE`, `CONFLICTING`, or `DATA_GAP` invalidates the decision and should trigger re-analysis.

## Verification

Focused tests cover:

- null preservation under `PARTIAL`;
- invalid overround downgrade;
- clean Tier 1 `HIGH_CONVICTION`;
- UCL cap at `ACTIONABLE`;
- `NO_BET` on non-positive value;
- `top_opportunities` filtering and deterministic ranking.

Run:

```powershell
$env:DEBUG='false'
..\.venv\Scripts\python.exe -m pytest tests\test_core_engine.py -q --no-cov
```
