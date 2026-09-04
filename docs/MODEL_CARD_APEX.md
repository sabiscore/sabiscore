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

## Candidates evaluated and rejected

| candidate | date | verdict | decisive gate |
|---|---|---|---|
| `apex_v2_71` (Apex 68 + 3 rolling-xG features) | 2026-09-03 | **REJECTED** | `market_baseline` 0/5 |
| `apex_v3_68` (Apex 68, h2h/venue/interaction now training-computed) | 2026-09-04 | **REJECTED** | `market_baseline` 0/6 |

`apex_v2_71` appended the three features `measure_xg_feature_ate.py` classified
`CAUSAL_DRIVER` (ATE 0.2485 / 0.2181 / 0.1832, all p < 1e-68). On an identical
holdout the block was neutral-to-worse in 4 of 5 leagues (mean RPS −0.00159),
and it beat the market baseline in 0 of 5. All three columns were genuinely
observed — `training_coverage = 1.0`, `variable_in_training = true` — and
`training_defaulted_slots` was identical to the `apex_v1_68` baseline, so the
pipeline is not the explanation.

**A large, significant ATE is not evidence of out-of-sample predictive lift.**
The causal screen filters noise; it is not a promotion criterion. Full evidence:
`backend/reports/evaluation/apex-v2-71-candidate-evaluation.{json,md}`;
reasoning in `docs/DEBT.md` item 58.

`apex_v3_68` populated 13 of `APEX_FEATURES_68`'s slots (h2h, home-venue, and
three market-interaction fields) that training had left at a constant
registry default since before this contract existed, even though serving
computes real values for them today — `training_defaulted_slots` moved 16 →
3. Unlike `apex_v2_71` it drops no row, so `apex_v1_68` and `apex_v3_68` train
on byte-identical row sets. The model measurably uses the new signal
(responsive features up 8–13 per league), and the mean RPS delta is barely
positive (+0.00028), but the result is a 3/6 win split against the incumbent
with the single largest movement a loss (Bundesliga, −0.0094) — and it beats
the market baseline in 0 of 6 leagues, unchanged from `apex_v2_71`.
`serving_feature_availability` was known to be unpassable by this candidate
before training ran: `serving_schema_misaligned_slots` (11, the pre-existing
apex-vs-legacy market-block divergence) is untouched by anything this
candidate does. Full evidence:
`backend/reports/evaluation/apex-v3-68-candidate-evaluation.{json,md}`;
reasoning in `docs/DEBT.md` item 56.

**Two candidates, two different feature families, the same answer on the gate
that matters.** `apex_v2_71` added a causally-validated signal and lost RPS;
`apex_v3_68` added signal the model demonstrably uses and produced a
statistical wash. Neither closed the gap to the market baseline in any
league. The market-implied probability already prices in what a team's h2h
and home-venue record predict, at least as well as this ensemble family does.

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
(policy v1.1.0, SHA-256
`7e1e238456df14de182d957a0351485c63892c7980746d3a72488f248697d07a`). That
module is the frozen transcription of the thresholds actually applied by
`compare_candidate_vs_incumbent.py` and `promotion_evidence._expected_gate()`;
`test_certification_policy.py` fails if the two drift. The prose below
summarises the wider release expectations and is **not** the machine-checked
bar — cite the policy hash, not this list, in any certification manifest.

⚠️ **This paragraph previously said the `serving_feature_availability` gate was
"unsatisfiable by construction" because it required `always_data_gap_slots == 0`
against four permanently-gapped slots. That was true under policy v1.0.0 and is
no longer true.** `docs/DEBT.md` item 38 was resolved (authorized) on
2026-08-22: the term was removed as a blocker in policy v1.1.0, the count still
surfaces in every evidence summary, and it no longer disqualifies.

Read `promotion_permitted: false` on any candidate as a verdict on its
measured evidence, **not** as a structural artefact. The `apex_v2_71`
evaluation below is the worked example: it failed `market_baseline` 0/5 and
`no_league_regression` 2/5 on merit, and would have failed them under any
version of this policy.

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
