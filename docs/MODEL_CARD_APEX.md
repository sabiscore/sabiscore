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

The files in `backend/models/candidate/` predate completion of the required
Apex certification run. Their manifest intentionally sets
`promotion_permitted: false`. No metric in those files should be presented as
Apex production certification.

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

Until these pass, the active last-known-good artifacts remain authoritative and
the release status remains `NOT SAFE FOR PRODUCTION` for Apex promotion.
