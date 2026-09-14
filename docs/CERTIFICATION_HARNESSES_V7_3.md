# SabiScore v7.3 Evidence Harness Runbook

## Purpose

These scripts generate certification evidence. They do **not** promote a model,
change `certification_policy.py`, or turn blocked CI into a pass.

The supported execution target is Python 3.12 on a Windows workstation with a
strict 8 GB RAM ceiling.

## 1. Repository and Python setup

Use the exact PR/release commit that produced the candidate artifacts. Do not
run evidence against a dirty working tree.

```powershell
git checkout feat/v7.3-evidence-harnesses-20260914
git status --short
ggit rev-parse HEAD
py -3.12 -m venv .venv-cert
.\.venv-cert\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-training.txt
```

`backend/requirements-training.txt` pins `mapie==1.5.0`; do not silently
upgrade MAPIE during a certification run. Record the installed versions:

```powershell
python -m pip freeze > artifacts\certification\environment_freeze.txt
```

## 2. 8 GB Windows resource guard

Set conservative BLAS/thread limits before importing NumPy, scikit-learn or
XGBoost. The harnesses are intentionally single-process and use small batches.

```powershell
$env:OMP_NUM_THREADS="1"
$env:OPENBLAS_NUM_THREADS="1"
$env:MKL_NUM_THREADS="1"
$env:NUMEXPR_NUM_THREADS="1"
$env:VECLIB_MAXIMUM_THREADS="1"
$env:BLIS_NUM_THREADS="1"
$env:JOBLIB_MULTIPROCESSING="0"
$env:PYTHONHASHSEED="0"
```

Do not start multiple harnesses concurrently. Run G11, G16, G18 and G24
sequentially. Each script uses `float32` where practical and performs explicit
`gc.collect()` sweeps.

## 3. Evidence inputs

### G11/G15

Create a **pre-match forecast artifact** with one row per evaluated match:

```text
home_win_prob,draw_prob,away_win_prob,result
```

Recommended provenance columns:

```text
league,season,evaluation_at,generation_id,artifact_sha256
```

`evaluation_at` must precede the match kickoff. The compiler does not infer
this property from the filename.

### G18

Create a candidate/market evidence artifact containing:

```text
league,season,date,home_team,away_team,
home_win_prob,draw_prob,away_win_prob,
B365H,B365D,B365A
```

or the repository's `bet365_*`, `PS*`, `pinnacle_*`, or generic
`home_odds/draw_odds/away_odds` equivalents.

The market harness selects one complete bookmaker triple; it never averages or
mixes bookmakers. Football-data/soccerdata is the historical match/odds
lineage. Understat remains an xG/feature lineage and must not be substituted
for bookmaker probabilities.

## 4. Run the evidence harnesses

### G11/G15 — adaptive ECE + Brier

```powershell
python backend\scripts\evaluate_g11_ece.py `
  --input artifacts\evidence\served_predictions_2526.csv `
  --bins 10 `
  --output artifacts\certification\g11_ece.json
```

The primary ECE is confidence ECE with stable equal-mass bins. Classwise ECE
is also emitted. The Murphy identity is checked to an absolute residual of
`1e-6`.

### G16 — served-path MAPIE

```powershell
python backend\scripts\evaluate_g16_uncertainty.py `
  --cache-dir backend\data\cache `
  --holdout-season 2526 `
  --output artifacts\certification\g16_uncertainty.json
```

This is a temporal conformalization/test split. The estimator is the actual
`PredictionEngine._run_inference` adapter. A raw or fallback prediction cannot
be silently conformalized as certified uncertainty evidence.

The result reports exact empirical marginal coverage at 80% and 90% nominal
confidence.

### G18 — market baseline

```powershell
python backend\scripts\evaluate_g18_bootstrap.py `
  --input artifacts\evidence\g18_candidate_market_2526.csv `
  --holdout-start 2025-08-01 `
  --holdout-end 2026-08-01 `
  --bootstrap-reps 10000 `
  --block-length 10 `
  --batch-size 250 `
  --output artifacts\certification\g18_bootstrap.json
```

`--bootstrap-reps 10000` is mandatory. The comparison is paired candidate RPS
minus de-vigged market RPS; lower RPS is better. The pooled scope and every
league with sufficient evidence are evaluated independently.

### G24 — deployment parity

```powershell
$env:VERCEL_TOKEN="<vercel-token>"
$env:VERCEL_TEAM_ID="<optional-team-id>"

python backend\scripts\validate_deployment.py `
  --expected-sha "<40-character-release-sha>" `
  --vercel-project-id "<vercel-project-id>" `
  --frontend-health-url "https://<production-domain>/api/health" `
  --backend-health-url "https://<render-domain>/health"
```

The validator checks the Vercel production deployment API, Next.js health
`vercelSha`, Next.js health `backendSha`, and Render `release_sha`. Health
requests are cache-busted and retried with bounded exponential backoff.

## 5. Compile one certificate

The compiler is deliberately fail-closed and refuses to overwrite an existing
report.

```powershell
python backend\scripts\compile_certification_report.py `
  --g11 artifacts\certification\g11_ece.json `
  --g16 artifacts\certification\g16_uncertainty.json `
  --g18 artifacts\certification\g18_bootstrap.json `
  --g24 artifacts\certification\g24_deployment.json `
  --core-evidence artifacts\certification\core_gates.json `
  --output artifacts\certification\certification_report_<generation>_<timestamp>.json
```

`--core-evidence` is mandatory for an `ACTIONABLE_CERTIFIED` result. It must
contain the pre-existing v7.3 promotion gates. Supplying only G11/G15/G16/G18/G24
therefore cannot accidentally manufacture a release certification.

## 6. Expected state machine

```text
missing/blocked evidence
        ↓
      HOLD
        ↓
all required evidence generated
        ↓
all required gates PASS
        ↓
core v7.3 gates supplied and PASS
        ↓
ACTIONABLE_CERTIFIED
```

A failed or missing G16/G18/G24 remains a hard blocker. Operator override may
bypass CI execution, but it does not change `INV-17`: an unexecuted test is not
a pass.

## 7. Artifact integrity

Every artifact records the repository SHA and, where an input snapshot exists,
a SHA-256 digest. The compiler records:

- frozen `certification_policy.py` version and SHA-256;
- evidence-policy version and SHA-256;
- evidence source paths;
- model/deployment metadata;
- every gate verdict;
- failure reasons;
- immutable output semantics.

Never edit a generated certification report in place. Re-run the harness and
produce a new timestamped artifact.

## 8. Interpretation constraints

- G16 marginal coverage is a population-level empirical property, not a claim
  that an individual fixture has an 80%/90% probability of containing the truth.
- G18 market comparison is a research measurement. It is not a guarantee,
  sure-bet claim, or staking authorization.
- G11/G15 thresholds are evidence gates, not model-quality guarantees.
- Historical/reanalysis data must never be represented as a forecast generated
  before the corresponding kickoff.
