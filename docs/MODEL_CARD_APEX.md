# SabiScore Apex candidate model card

Status: **UNVERIFIED CANDIDATE - NOT PROMOTABLE**
Last updated: 2026-08-10

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

Eredivisie coverage is pooled fallback. UCL is generic coverage and its verdict
is capped at `ACTIONABLE` until a dedicated certified model/policy exists.

## Promotion gates

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
both betting engines enforce `No bet — insufficient evidence` and zero stake.
The release status remains `NOT SAFE FOR PRODUCTION`.
