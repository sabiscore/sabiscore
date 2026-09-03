# xG-derived feature ATE on the real Understat corpus

**Date:** 2026-09-03
**Script:** `backend/scripts/measure_xg_feature_ate.py`
**Data:** `backend/data/processed/v4_sources` — 35 league-seasons, 12,560 Understat matches
**Machine-readable:** `xg-feature-ate.json`

Reproduce:

```bash
cd backend && PYTHONPATH=. ../.venv-ml/Scripts/python.exe \
  scripts/measure_xg_feature_ate.py --out reports/evaluation/xg-feature-ate.json
```

## Why this measurement

`models/feature_registry.py` states the reason `shot_quality_diff` is a
permanent `PHASE7_FEATURES_ALWAYS_DATA_GAP` member:

> proxy ATE unreliable without real StatsBomb shot-map data. Proxy derived from
> `xg_avg_5` difference **collapses to q75=0 on synthetic training data**,
> making ATE estimates non-discriminative.

The blocking clause was *synthetic training data*. A real Understat corpus now
exists, so the proxy family can be measured against real observations for the
first time.

## Method

- 12,459 played matches (101 unplayed Ligue 1 2019/20 COVID cancellations
  dropped — `has_data=False`, never default-filled).
- Rolling window 5, `min_periods=3`, `shift(1)`, partitioned by
  (league, season) so no value crosses a season boundary and no value at match
  *M* uses information from *M* or later.
- 11,419 usable rows; 1,040 cold-start rows **dropped, not imputed** — an
  imputed value would be a fabricated observation feeding a causal estimate
  whose entire purpose is detecting real signal.
- `models/causal_selector.py::CausalFeatureSelector(practical_ate=0.02)` — the
  repo's existing estimator, carrying the registry's own threshold.

## Result

| feature | ate_win | ate_draw | p | verdict | class |
|---|---|---|---|---|---|
| `xg_differential` | **0.2464** | −0.0258 | 0.0000 | PASS | CAUSAL_DRIVER |
| `xg_attack_diff` | **0.2169** | −0.0076 | 0.0000 | PASS | CAUSAL_DRIVER |
| `xg_defense_diff` | **0.1790** | −0.0220 | 0.0000 | PASS | CAUSAL_DRIVER |
| `finishing_efficiency_gap` | 0.0082 | 0.0064 | 0.3851 | below threshold | INDEPENDENT |

The xG-differential family clears the 0.02 practical threshold by roughly 12×
on real data. The registry's "non-discriminative on synthetic data" finding does
not reproduce on real observations.

**The estimator discriminates rather than rubber-stamping.**
`finishing_efficiency_gap` — goals minus xG, a quantity that is famously
mean-reverting and should carry little predictive signal — lands at 0.0082 with
p=0.385 and is classified `INDEPENDENT`. A measurement that passed everything
would be worth distrusting; this one does not.

## What this does NOT establish

⚠️ **`shot_quality_diff` remains unmeasured and remains a permanent data gap.**
It is defined on post-shot xG (PSxG − xG). Understat publishes xG but not PSxG,
and its match frame carries no shot counts either. The registry's condition
names a "real StatsBomb event-level shots corpus", which this is not.
`defensive_vulnerability_index` is likewise unmeasurable here (needs shots
conceded).

⚠️ **`xg_differential` is not a canonical feature slot.** It exists only as an
intermediate in `data/transformers.py`. Adding it to `CANONICAL_FEATURES_68`
changes the vector width, which is precisely the 2026-06-10 incident recorded in
`feature_registry.py`: removing slots made the registry emit 65 columns against
68-column artifacts, `PredictionEngine` correctly refused to zero-pad, and
`model_version="fallback"` was served on every inference for two months.

⚠️ **This is a median-split proxy ATE, not an adjusted causal estimate.** It is
the repo's existing `CausalFeatureSelector` convention (treatment = feature ≥
median, effect = difference in outcome means), and is unadjusted for
confounders. Strong team quality drives both rolling xG and match outcome, so
some of this effect is association, not causation.

## Status

Evidence only. No gate, threshold, registry entry, or artifact was modified by
this measurement. Acting on it means introducing a new candidate feature schema
version and running it through the existing promotion gate
(`models/certification_policy.py`, policy v1.0.0) — an authorised decision, not
a unilateral edit. See `docs/DEBT.md` item 56.

Gate 50 (`error_association`) is **unchanged** by this work:
`tests/unit/test_uncertainty_contract.py` still reports 25 passed / 2 xfailed
with the documented gaps (EPL −0.0217, BUNDESLIGA −0.0448, LA_LIGA −0.0025,
LIGUE_1 −0.0288, SERIE_A −0.0098). Nothing consumes the corpus yet.
