# `apex_v5_66` Candidate Evaluation

**Date:** 2026-09-05  
**Schema:** `apex_v5_66`  
**Training suffix:** `v10_gate7_hpo`  
**Holdout season:** 2526  
**Evaluated by:** `scripts/compare_candidate_vs_incumbent.py --candidate-schema apex_v5_66`  
**Incumbent:** `v5_phase7` (68-wide vector)

---

## 1. Context — Phase 4 Step 2: Bayesian HPO

Phase 4 Step 2 applied constrained Bayesian hyperparameter optimisation
(Optuna TPE, 30 trials per learner per league) to the `apex_v4_66` feature
contract.  Schema key: `apex_v5_66`; artifact suffix: `v10_gate7_hpo`.

**Feature width:** 66 = `APEX_FEATURES_68` − 2 event-data gap features
(same 66-wide contract as `apex_v4_66`; PATH B closure carried forward from
the StatsBomb coverage audit, 2026-09-04).

**HPO method:** Optuna TPE Bayesian search, `TimeSeriesSplit(n_splits=3)`,
`MedianPruner`.  Search space:

| Learner | Tuned parameters |
|---|---|
| RandomForest | `n_estimators` {100…500}, `max_depth` {3…12}, `min_samples_leaf` {10…50} |
| XGBoost | `n_estimators` {100…500}, `max_depth` {3…6}, `learning_rate` {0.01…0.3}, `subsample`, `colsample_bytree`, `reg_lambda` |
| LightGBM | `n_estimators` {100…500}, `max_depth` {3…6}, `learning_rate` {0.01…0.3}, `subsample`, `colsample_bytree`, `reg_lambda` |

---

## 2. Best HPO Parameters per League

### BUNDESLIGA

| Learner | Holdout RPS | Best params |
|---|---|---|
| RandomForest | 0.2048 | n_estimators=400, max_depth=4, min_samples_leaf=33 |
| XGBoost | 0.2073 | n_estimators=200, max_depth=3, lr=0.01139, subsample=0.930, colsample=0.705, λ=2.507 |
| LightGBM | 0.2081 | n_estimators=250, max_depth=3, lr=0.01209, subsample=0.705, colsample=0.865, λ=14.44 |

### EPL

| Learner | Holdout RPS | Best params |
|---|---|---|
| RandomForest | 0.1967 | n_estimators=500, max_depth=10, min_samples_leaf=40 |
| XGBoost | 0.1990 | n_estimators=150, max_depth=3, lr=0.01938, subsample=0.772, colsample=0.602, λ=0.802 |
| LightGBM | 0.1995 | n_estimators=150, max_depth=3, lr=0.01837, subsample=0.782, colsample=0.918, λ=19.33 |

### LA_LIGA

| Learner | Holdout RPS | Best params |
|---|---|---|
| RandomForest | 0.1916 | n_estimators=400, max_depth=4, min_samples_leaf=34 |
| XGBoost | 0.1939 | n_estimators=150, max_depth=3, lr=0.01819, subsample=0.795, colsample=0.675, λ=5.382 |
| LightGBM | 0.1939 | n_estimators=150, max_depth=3, lr=0.01820, subsample=0.836, colsample=0.827, λ=11.167 |

### LIGUE_1

| Learner | Holdout RPS | Best params |
|---|---|---|
| RandomForest | 0.2053 | n_estimators=350, max_depth=5, min_samples_leaf=37 |
| XGBoost | 0.2084 | n_estimators=100, max_depth=3, lr=0.03277, subsample=0.916, colsample=0.711, λ=6.937 |
| LightGBM | 0.2095 | n_estimators=300, max_depth=3, lr=0.01085, subsample=0.724, colsample=0.820, λ=19.626 |

### SERIE_A

| Learner | Holdout RPS | Best params |
|---|---|---|
| RandomForest | 0.1919 | n_estimators=400, max_depth=4, min_samples_leaf=34 |
| XGBoost | 0.1935 | n_estimators=150, max_depth=3, lr=0.01910, subsample=0.736, colsample=0.641, λ=0.790 |

---

## 3. Training Results (2526 holdout)

EREDIVISIE uses the pooled all-league model (260 rows, no holdout possible).

| League | Train | Test | Stacked RPS | Market RPS | Beats Market | Responsive |
|---|---|---|---|---|---|---|
| BUNDESLIGA | 1,455 | 301 | 0.1968 | 0.1908 | ✗ | 37/66 |
| EPL | 1,821 | 375 | 0.2049 | 0.2054 | ✓ | 49/66 |
| EREDIVISIE | pooled | 260 | 0.1981 | 0.1978 | ✗ | 50/66 |
| LA_LIGA | 1,817 | 375 | 0.1964 | 0.1963 | ✗ | 49/66 |
| LIGUE_1 | 1,641 | 301 | 0.2034 | 0.1991 | ✗ | 43/66 |
| SERIE_A | 1,803 | 375 | 0.1994 | 0.1971 | ✗ | 47/66 |

---

## 4. Per-League Comparison vs Incumbent (`v5_phase7`, 2526 holdout)

| League | Incumbent RPS | Candidate RPS | Δ RPS | Candidate wins | Beats market |
|---|---|---|---|---|---|
| BUNDESLIGA | 0.1900 | 0.1968 | +0.0068 | ✗ | ✗ (market 0.1908) |
| EPL | 0.2036 | 0.2049 | +0.0013 | ✗ | ✓ (market 0.2054) |
| EREDIVISIE | 0.2048 | 0.1988 | −0.0059 | **✓** | ✗ (market 0.1978) |
| LA_LIGA | 0.2018 | 0.1964 | −0.0054 | **✓** | ✗ (market 0.1963) |
| LIGUE_1 | 0.2032 | 0.2034 | +0.0003 | ✗ | ✗ (market 0.1991) |
| SERIE_A | 0.2051 | 0.1994 | −0.0058 | **✓** | ✗ (market 0.1971) |

RPS is lower-is-better.  
**Candidate wins: 3/6 leagues.  Leagues beating market: 1/6 (EPL).**  
**Mean RPS improvement: +0.00146** (across all 6 leagues; better than `apex_v4_66`'s +0.00066 on this metric).

---

## 5. Gate Results

| Gate | Status | Notes |
|---|---|---|
| `valid_probability_simplex` | **PASS** | No invalid simplex row on holdout |
| `input_responsiveness` | **PASS** | Min responsive: 37/66 (BUNDESLIGA) |
| `coherent_price_perturbation` | **PASS** | All 6 leagues directionally coherent |
| `primary_metric_improvement` | **PASS** | Mean RPS improvement +0.00146 |
| `serving_feature_availability` | **FAIL** | training_defaulted_slots=1; serving_schema_misaligned_slots=14; always_data_gap_slots=4 |
| `no_league_regression` | **FAIL** | 3/6 leagues (EREDIVISIE, LA_LIGA, SERIE_A win); requires 6/6 |
| `market_baseline` | **FAIL** | 1/6 leagues (EPL) beat market; requires 6/6 |

**`promotion_permitted: false`** — three gates fail.

---

## 6. Regression vs `apex_v4_66` (HPO effect)

HPO tuning moved `no_league_regression` from **4/6 → 3/6** — LIGUE_1 flipped
from candidate-better (−0.0007 in v4) to incumbent-better (+0.0003 in v5).
BUNDESLIGA and EPL remained losses in both generations.

| Metric | `apex_v4_66` | `apex_v5_66` | Δ |
|---|---|---|---|
| `no_league_regression` | 4/6 | 3/6 | −1 |
| `market_baseline` | 1/6 | 1/6 | 0 |
| Mean RPS improvement | +0.00066 | +0.00146 | +0.00080 |

The 30-trial Optuna TPE search improved EREDIVISIE, LA_LIGA, and SERIE_A RPS
but regressed LIGUE_1 relative to the untuned v4 candidate.  BUNDESLIGA and
EPL HPO parameters lean toward high regularisation (deep RF/shallow trees,
low learning rates), which appears to overfit to the training cross-validation
folds rather than generalising to the 2526 holdout.

---

## 7. Open Items

- **`serving_schema_misaligned_slots: 14`** — apex market-block dispatch is
  code-complete (PR #78, `is_apex_schema()` dispatch) but the active
  generation still declares `phase7_68`, so the counter remains 14.  Will
  resolve to 0 when an apex-generation manifest is activated.

- **`no_league_regression`** — requires 6/6 wins.  Losing leagues: BUNDESLIGA
  (HPO overfit), EPL (marginal), LIGUE_1 (HPO regression).

- **`market_baseline`** — requires 6/6 leagues.  EPL is the only league where
  the candidate beats the market-implied RPS.

- **Gate 50 (`error_association`)** — unchanged; remains unconditionally
  CRITICAL.  This evaluation does not modify `uncertainty_policy.py`.

---

## 8. Conclusion

`apex_v5_66` is a **valid research candidate**.  It is not promotable today
(three gates fail).  Key outcomes:

1. 30-trial Optuna TPE HPO improved mean RPS by +0.00080 over the untuned
   `apex_v4_66` baseline, but regressed `no_league_regression` from 4/6 → 3/6
   by over-tuning LIGUE_1 to training-CV folds.
2. `market_baseline` remains at 1/6 (EPL only) — HPO alone cannot close the
   market-beating gap; additional training signal or a new feature generation
   is required for the remaining 5 leagues.
3. The schema is sound: min 37/66 responsive features, all 6 leagues
   directionally coherent, no invalid probability rows.

*`promotion_permitted: false`.  `stake_permitted: false` maintained.
System remains `RESEARCH_ONLY / ACTIVE_FAIL_CLOSED`.*
