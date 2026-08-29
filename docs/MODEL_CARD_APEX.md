# SabiScore Apex candidate model card

Status: **UNVERIFIED CANDIDATE - NOT PROMOTABLE**
Last updated: 2026-08-10

## Tooling and promotion authority

- CatBoost may be evaluated only as a shadow candidate. Its presence in a Python
  environment is not evidence that it improves RPS, calibration, coverage, or
  serving latency.
- SHAP explanations require a successfully loaded real model and its exact serving
  feature vector. An unavailable or invalid explainer is an explicit data gap;
  mock feature importance is prohibited.
- MLflow is optional offline experiment observability. It is lazily imported only
  when configured, its tracking URI is never logged, and it cannot promote a
  production model.
- Production promotion is atomic and release-controlled: both loaders consume the
  committed, hash-validated active-generation manifest. A mutable local registry,
  MLflow stage, individual artifact copy, or filename change is not promotion.
- No new model-changing work is permitted until the settlement pipeline is proven
  to have a non-zero sample of real settled predictions.

## Intended use

Three-way football outcome forecasting for explicitly supported competitions,
followed by independent evidence and staking gates. The model does not guarantee
an outcome and must not produce a public stake without verified fixture identity,
measured uncertainty, coherent market evidence, and a permitted verdict.

## Candidate design

- Versioned Apex feature schema; the active v5 schema is unchanged.
- Market inputs use one coherent bookmaker 1X2 snapshot.
- Candidate market features are de-vigged probabilities, overround, favorite
  indicators, log prices, probability margin, normalized entropy, home-away
  probability difference, and odds ratio.
- Opening prices may be training features. Closing prices are evaluation/CLV
  evidence only.
- Competition data is chronological. Meta-model predictions use expanding
  temporal folds; calibration uses a later slice; the final season is reserved
  for untouched evaluation.
- The exact served stacked head is the reporting target. Primary metric is RPS;
  Brier, log loss, calibration error/curves, accuracy, market and league-prior
  baselines, feature utilization, and sensitivity are secondary.

## Current evidence

The certification dataset contains 12,765 real matches. Five-match history
requirements exclude 505 rows; 12,256 of 12,260 remaining rows have one coherent
opening 1X2 snapshot. Training uses only rows before 2024/25, calibration uses
2024/25, and evaluation uses untouched 2025/26 fixtures.

| League | Eval n | Candidate RPS | Active RPS | Market RPS | Promotion comparison |
|---|---:|---:|---:|---:|---|
| Bundesliga | 301 | 0.1990 | 0.1900 | 0.1908 | Regression |
| EPL | 375 | 0.2065 | 0.2036 | 0.2054 | Regression |
| Eredivisie | 260 | 0.1984 | 0.2048 | pooled baseline | Improvement, pooled fallback |
| La Liga | 375 | 0.1966 | 0.2018 | 0.1963 | Improvement vs active only |
| Ligue 1 | 301 | 0.2034 | 0.2032 | 0.1991 | Regression |
| Serie A | 375 | 0.1995 | 0.2051 | 0.1971 | Improvement vs active only |

The mean candidate RPS improvement over the active models is +0.00085, but the
candidate wins only 3/6 league comparisons and does not beat the coherent market
baseline in any evaluated league row. Its feature matrix reports 24 defaulted,
non-variable training slots, 11 positions incompatible with the current serving
schema, and four slots that always report a serving data gap.

### Hyperparameter provenance (added 2026-08-30)

Every candidate now records how it was fitted. `training_report_real.json`
carries, per league, `hyperparameter_source` — either `baseline_hardcoded` or
`optuna_tpe_rps_{N}trials` — alongside the exact `hyperparameters` used. A run
without `--tune` reproduces the previous baseline values exactly, so existing
artifacts are unaffected and comparable.

When `--tune N` is passed, `train_on_real_matches.py` runs an Optuna TPE search
per base learner over `n_estimators`, `max_depth`, `learning_rate`,
`reg_lambda`, `subsample` and `colsample_bytree`, scored on **RPS** — the metric
`model_registry.compare_models` promotes on — across a `TimeSeriesSplit` of the
**training slice only**. Calibration and holdout seasons are never seen by the
search, so a tuned candidate's holdout RPS remains an out-of-sample number
rather than a search artifact. Each learner uses its own sampler seed;
a single shared seed made XGBoost and LightGBM converge on identical
hyperparameters and collapsed the ensemble diversity that stacking depends on.

CatBoost is not searched: it is pinned `python_version < "3.14"` and has no
wheel for the development interpreter. Its `depth` / `l2_leaf_reg` /
`iterations` axes are covered by the equivalent XGBoost and LightGBM
parameters.

Machine-readable evidence lives beside the quarantined artifacts:

- `training_report_real.json`: sample windows, RPS, Brier, log loss,
  calibration error, accuracy, league-prior and market baselines;
- `comparison_report.json`: exact served-head active/candidate comparison and
  gate results;
- `feature_availability_matrix.json`: per-feature sources, coverage, missingness,
  freshness, variability, defaults, and train/serve alignment;
- `candidate_manifest.json`: artifact hashes and closed promotion decision.

The candidate passes finite simplex, input responsiveness (minimum 33 responsive
features), coherent-price perturbation, and pooled primary-metric gates. It fails
serving availability, market baseline, and no-league-regression. Its manifest
therefore remains `promotion_permitted: false`; these metrics are research
evidence, not production certification.

The serving-availability failure has two distinct causes, worth separating:
`serving_schema_misaligned_slots: 11` is real and specific — the training
script builds `APEX_FEATURES_68` while the active manifest declares
`phase7_68` (`CANONICAL_FEATURES_68`), and the two differ at exactly indices
20-30 (`docs/DEBT.md` item 37). `always_data_gap_slots: 4` is the structural
issue above and would fail any candidate whatsoever.

Eredivisie coverage is pooled fallback. UCL is generic coverage and its verdict
is capped at `ACTIONABLE` until a dedicated certified model/policy exists.

## Promotion gates

**Authoritative source:** `backend/src/models/certification_policy.py`
(policy v1.0.0, SHA-256
`41cb77031e3c23b744866e3b41e34e6c239445c98e5d20ad170ab918ff8f3dab`). That
module is the frozen transcription of the thresholds actually applied by
`compare_candidate_vs_incumbent.py` and `promotion_evidence._expected_gate()`;
`test_certification_policy.py` fails if the two drift. The prose below
summarises the wider release expectations and is **not** the machine-checked
bar — cite the policy hash, not this list, in any certification manifest.

⚠️ **The `serving_feature_availability` gate is currently unsatisfiable by
construction** (`docs/DEBT.md` item 38): it requires `always_data_gap_slots ==
0`, but all four `PHASE7_FEATURES_ALWAYS_DATA_GAP` features are permanent slots
in every 68-wide schema. No candidate can be promoted until that is
deliberately resolved. Read `promotion_permitted: false` on the current
candidate as "blocked on three gates *and* structurally blocked", not as a
close-run verdict.

- deterministic train/serve parity and dual-loader compatibility;
- valid finite probability simplexes without repair;
- chronological per-competition RPS threshold and declared baseline wins;
- untouched final-season and later calibration evidence;
- meaningful feature sensitivity or documented abstention;
- schema, window, library, artifact, hash, and rollback manifests;
- clean security, backend, frontend, OpenAPI, migration, Docker, CI, live-flow,
  settlement, and deployment gates.

Until every gate passes, the hash-locked active v5 artifacts remain authoritative.
Their generation is currently `UNVERIFIED`, so analytical output may continue but
both verdict engines and the distinct RL advisory integration enforce abstention or
`No bet — insufficient evidence` with zero public stake. The RL API does not share
the verdict taxonomy and is reviewed for equivalent gates, not fabricated parity.
The release status remains `NOT SAFE FOR PRODUCTION`.
