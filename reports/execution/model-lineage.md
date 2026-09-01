# SabiScore Machine Learning Model Lineage & Certification Report

**Document Version:** 1.0.0  
**Generated:** 2026-09-01T10:10:00Z  
**Scope:** Active Production Generation, Candidate Models, Training Data Lineage, Feature Contracts, Calibration, and Gate Certification  
**Governance Authority:** `AGENTS.md` §5, `docs/MODEL_CARD_APEX.md`, `backend/models/active_generation.json`  

---

## 1. Executive Summary & Active Generation Overview

SabiScore enforces a mathematically rigorous, zero-fabrication machine learning governance framework. All production inference is strictly decoupled from ad-hoc experimentation. Model promotion requires passing multidimensional statistical, temporal, responsiveness, and serving-parity gates.

### Active Generation Architecture

| Property | Active Generation Specification |
|---|---|
| **Generation Identifier** | `v5_phase7-20260808` (`canonical_68_v2` / `v5_phase7`) |
| **Feature Schema Version** | `phase7_68` (68 positional float features) |
| **Served Ensemble Head** | `SoftmaxMetaModel` (Calibrated meta-learner over XGBoost, LightGBM, CatBoost) |
| **Certification State** | `UNVERIFIED` (Fail-closed; analytical research only) |
| **Promotion State** | `ACTIVE_FAIL_CLOSED` (`stake_permitted: false`, zero public Kelly exposure) |
| **Authority Manifest** | `backend/models/active_generation.json` (SHA-256 locked) |

### Active Artifact Checksum Verification

```
bundesliga:  58e6b40ae6b3e147ac59b6cc078147bcbc119ff2887f16b1bee9cfa2b60445f6 (4.81 MB)
epl:         9928f9f8307e260f335f0f9ed3bd772bbcfe66992337c62361b4a9f0b1baff30 (5.19 MB)
eredivisie:  6e7a59b3082503eca8089dd2b702eda2e8bf4dfc1611fde4b77f969b229d6f43 (9.32 MB)
la_liga:     ee7c7b726fff6ac9abc298bbb42743b6afda0bcc8329157b3f2f6adcbe955bb9 (5.19 MB)
ligue_1:     3dfd97cfbc720170fb7899a7c8a28ef0a1863801fc67a8dc9f86acda521f5823 (4.99 MB)
serie_a:     f57b2dc1e9ac37fe2a96bf192d37e7b550db3e269a84a66447d166b4fc7ddd65 (5.35 MB)
```

---

## 2. Dataset Lineage & Temporal Partitioning

Training, calibration, and evaluation partitions are chronologically isolated to eliminate lookahead bias and temporal leakage.

```
       ┌────────────────────────┬───────────────────┬─────────────────────┐
       │     Pre-2024/25        │     2024/25       │     2025/26         │
       │    Training Slice      │ Calibration Slice │   Holdout Slice     │
       │   (12,256 Matches)     │  (Isotonic/Platt) │   (1,987 Matches)   │
       └────────────────────────┴───────────────────┴─────────────────────┘
 2018-08-01                2024-08-01          2025-08-01            2026-06-01
```

### Dataset Distribution by League

| Competition | Training Sample (Pre-24/25) | Holdout Sample (25/26) | Primary Data Source |
|---|---|---|---|
| **Bundesliga** | 2,052 matches | 301 matches | Football-Data.org / API-Football |
| **Premier League (EPL)** | 2,571 matches | 375 matches | Football-Data.org / API-Football |
| **Eredivisie** | 260 matches | 260 matches | Football-Data.org |
| **La Liga** | 2,572 matches | 375 matches | Football-Data.org / API-Football |
| **Ligue 1** | 2,248 matches | 301 matches | Football-Data.org / API-Football |
| **Serie A** | 2,553 matches | 375 matches | Football-Data.org / API-Football |
| **TOTAL** | **12,256 matches** | **1,987 matches** | Multi-Provider Ingestion |

### Temporal Integrity Invariants
1. **Rolling-Origin Split:** Training sets only contain data temporally strictly prior to the match kickoff (`kickoff_utc < target_kickoff`).
2. **Post-Kickoff Data Quarantine:** Verified by `tests/e2e/tier1-feature-coverage.spec.ts` test 2.4 (`leakage-audit`), post-kickoff stats, match results, and closing lines are structurally excluded from feature projection.
3. **Elo Historical Replay:** Elo ratings and trends are computed strictly via `backend/src/features/elo_replay.py` (`FastEloReplay`) to ensure exact point-in-time state reconstruction.

---

## 3. Feature Versioning & Contract Specification (`feature_contract.json`)

The feature vector is strictly versioned under schema `phase7_68` containing 68 floating-point variables ordered deterministically:

```json
{
  "schema_version": "phase7_68",
  "feature_count": 68,
  "default_missing_policy": "FAIL_CLOSED_OR_DATA_GAP"
}
```

### Feature Categorization Breakdown

| Feature Category | Count | Representative Features | Serving Availability Source |
|---|---|---|---|
| **Elo & Strength Signals** | 12 | `elo_difference`, `elo_home_trend_5`, `elo_away_trend_5`, `elo_momentum_cross` | `elo_replay.py` / `EloService` |
| **Form & Momentum** | 14 | `home_form_points_last5`, `away_form_points_last5`, `home_goal_diff_last5` | `upcoming_match_feature_service.py` |
| **Rolling Match Statistics** | 16 | `home_shots_on_target_avg_5`, `away_conceded_avg_5`, `home_xg_trend` | Ingestion cache / historical tables |
| **Market Odds & De-vigged Prices** | 14 | `market_home_prob`, `market_draw_prob`, `market_away_prob`, `odds_movement_delta` | `The Odds API` / `MarketSnapshot` |
| **Advanced Tactical / xG Gaps** | 8 | `ppda_ratio`, `progressive_carry_diff`, `set_piece_xg_diff`, `shot_quality_diff` | **Quarantined Data Gap** (StatsBomb corpus pending) |
| **Context & Environmental** | 4 | `rest_days_diff`, `derby_match_flag`, `weather_temperature`, `weather_precipitation` | `Open-Meteo` / Calendar policy |

---

## 4. Empirical Evaluation: Candidate vs Incumbent Comparison

A full retrospective evaluation was conducted comparing the **Incumbent (`v5_phase7`)** against the **M2 Family A Retrained Candidate (`candidate_phase9_v1`)** on the untouched 2025/2026 holdout slice (1,987 matches).

### Holdout Performance Matrix (Season 2025/2026)

| League | Model | Sample (N) | Accuracy | RPS (Ranked Prob Score) | Brier Score | Log Loss | ECE (Calib Error) | Market RPS | Candidate Wins? | Beats Market? |
|---|---|---|---|---|---|---|---|---|---|---|
| **Bundesliga** | Incumbent | 301 | **55.48%** | **0.18996** | **0.5510** | **0.9355** | 0.1202 | 0.19084 | — | — |
| | Candidate | 301 | 52.49% | 0.20000 | 0.5835 | 0.9818 | **0.0588** | 0.19084 | **NO (-0.01004)** | **NO** |
| **EPL** | Incumbent | 375 | **51.73%** | **0.20361** | 0.6189 | 1.0403 | **0.0435** | 0.20537 | — | — |
| | Candidate | 375 | 48.53% | 0.20514 | **0.6098** | **1.0155** | 0.0694 | 0.20537 | **NO (-0.00153)** | **YES (+0.00023)** |
| **Eredivisie** | Incumbent | 260 | 49.62% | 0.20477 | 0.6060 | 1.0129 | 0.0652 | 0.19785 | — | — |
| | Candidate | 260 | **52.69%** | **0.19841** | **0.5927** | **0.9943** | **0.0609** | 0.19785 | **YES (+0.00636)** | **NO** |
| **La Liga** | Incumbent | 375 | 53.33% | 0.20180 | 0.5797 | 0.9730 | 0.0637 | 0.19628 | — | — |
| | Candidate | 375 | **54.93%** | **0.19697** | **0.5756** | **0.9727** | **0.0316** | 0.19628 | **YES (+0.00483)** | **NO** |
| **Ligue 1** | Incumbent | 301 | **52.49%** | 0.20318 | 0.5949 | 0.9974 | 0.0895 | 0.19913 | — | — |
| | Candidate | 301 | 52.16% | **0.20027** | **0.5868** | **0.9875** | **0.0376** | 0.19913 | **YES (+0.00291)** | **NO** |
| **Serie A** | Incumbent | 375 | 52.80% | 0.20515 | 0.6021 | 1.0063 | 0.0552 | 0.19714 | — | — |
| | Candidate | 375 | **53.33%** | **0.19969** | **0.5886** | **0.9911** | **0.0269** | 0.19714 | **YES (+0.00546)** | **NO** |
| **OVERALL** | Incumbent | 1,987 | 52.74% | 0.20164 | 0.5929 | 0.9959 | 0.0694 | 0.19810 | — | — |
| | Candidate | 1,987 | **52.44%** | **0.20031** | **0.5898** | **0.9917** | **0.0463** | 0.19810 | **4/6 WINS (+0.00133)** | **1/6 WINS** |

---

## 5. Certification Gates & Formal Promotion Blockers

Promotion from shadow evaluation to active production is governed by `backend/src/models/certification_policy.py`. All 7 gates must evaluate to `PASS`.

```
┌─ CANDIDATE PROMOTION GATES AUDIT ───────────────────────────────────────────┐
│ 1. Valid Probability Simplex:        PASS (All holdout rows sum to 1.0)     │
│ 2. Input Responsiveness:             PASS (>=35 active responsive features) │
│ 3. Coherent Price Perturbation:      PASS (Directional monotonicity held)   │
│ 4. Serving Feature Availability:     FAIL (11 schema mismatches, 4 gaps)    │
│ 5. Primary Metric Improvement:       PASS (Mean RPS delta: +0.001333)       │
│ 6. No-League-Regression Gate:        FAIL (4/6 won; lost Bundesliga & EPL)  │
│ 7. Market Baseline Gate:             FAIL (1/6 beat bookmaker closing line) │
├─────────────────────────────────────────────────────────────────────────────┤
│ PROMOTION DECISION:                  PROMOTION_PERMITTED = FALSE            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Forensic Analysis of the Four Promotion Blockers

1. **Blocker 1: Serving Feature Availability Deficit (`FAIL`)**
   - **Root Cause:** 20 features in training dataset build (`build_dataset()`) default to constant `0.0`; 11 positional feature indices in `APEX_FEATURES_68` are misaligned with the live serving transformer in `upcoming_match_feature_service.py`; 4 StatsBomb tactical features are permanently gapped.
   - **Resolution Required:** Complete train/serve parity alignment and regenerated `feature_contract.json`.

2. **Blocker 2: No-League-Regression Violation (`FAIL`)**
   - **Root Cause:** While the candidate improved overall mean RPS by `+0.001333`, it regressed in **Bundesliga** (RPS `0.18996` → `0.20000`) and **EPL** (RPS `0.20361` → `0.20514`).
   - **Resolution Required:** Hyperparameter tuning via Optuna Bayesian search (`train_on_real_matches.py --tune 30`) per league.

3. **Blocker 3: Market Baseline Gate Violation (`FAIL`)**
   - **Root Cause:** The candidate only beat the de-vigged closing market baseline in EPL (Candidate `0.20514` vs Market `0.20537`). In all 5 other leagues, the bookmaker closing line outperformed the model.
   - **Resolution Required:** Ingestion of live closing line histories and multi-source consensus de-vigging.

4. **Blocker 4: Settled Match Volume Floor (`FAIL`)**
   - **Root Cause:** Live production database currently has 11 settled prediction logs. While exceeding the initial floor of 10, walk-forward confidence intervals require higher volume (>100 settled fixtures) for statistical significance.

---

## 6. Uncertainty Estimation & Calibration Architecture

### Multiclass Calibration
Probability calibration is computed using Isotonic Regression and Platt scaling across each outcome class ($y \in \{0: \text{Home Win}, 1: \text{Draw}, 2: \text{Away Win}\}$).
- Multiclass Expected Calibration Error (ECE) is reduced from **0.0694** to **0.0463** in the candidate.
- Murphy Brier score decomposition is exposed via `/api/v1/model-performance/calibration`:
  $$\text{Brier} = \text{Reliability} - \text{Resolution} + \text{Uncertainty}$$

### Epistemic & Aleatoric Uncertainty Gating (ADR 0009)
Uncertainty is evaluated through a Bayesian Ensemble:
- **Aleatoric Uncertainty ($u_a$):** Inherent match randomness, bounded by Dirichlet entropy.
- **Epistemic Uncertainty ($u_e$):** Model parameter variance across ensemble heads.
- **Fail-Closed Staking Invariant:** If $u_e > \theta_{\text{epistemic}}$ or if `MODEL_UNCERTAINTY_UNAVAILABLE` is raised, `stake_permitted` is forced to `false` and `Quarter-Kelly` stake is zeroed.
