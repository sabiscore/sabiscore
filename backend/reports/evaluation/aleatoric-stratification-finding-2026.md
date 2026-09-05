# Aleatoric Stratification Finding — 2026

**Gate:** Gate 50 (`error_association`)  
**Status:** `INSUFFICIENT_DATA` (live shadow telemetry below floor)  
**Date:** 2026-09-04  
**Author:** measure_aleatoric_stratification.py (automated) + manual annotation  
**Gate impact:** NONE — this report is research-only; Gate 50 is unconditionally CRITICAL

---

## 1. Live execution result

`backend/scripts/measure_aleatoric_stratification.py` was run against the live
`MatchPredictionLog` joined to settled `Match` outcomes.  Shadow telemetry from
PR #152 began accumulating records in late August 2026.

```
status:          INSUFFICIENT_DATA
total_records:   < 20
floor:           _MIN_TOTAL_RECORDS = 20
gate_impact:     NONE
```

The script returned `INSUFFICIENT_DATA` because the settled-prediction count sits
below the 20-record floor.  No quartile computation was performed and no empirical
`corr(aleatoric, RPS)` figure exists yet.

**This is expected and correct.**  PR #152 merged the shadow-telemetry capture path;
several weeks of live traffic are required to accumulate the minimum corpus.

---

## 2. Historical EPL holdout evidence (basis for the hypothesis)

The `corr(aleatoric, RPS) = +0.072` hypothesis was derived from a held-out EPL
evaluation set during the M1/M2 campaign (PRs #119–125, 2026-08-31).  That
analysis used `MatchPredictionLog` records from the 2025/26 season warm-up period,
joined to final scores in `Match`.

| Metric | Value | Direction |
|--------|-------|-----------|
| `corr(aleatoric, RPS)` | +0.072 | Right-signed ✓ |
| `mean_rps(Q4) > mean_rps(Q1)` | True (+0.031) | Right-signed ✓ |
| `corr(epistemic, RPS)` | −0.267 | Wrong-signed ✗ |
| `corr(epistemic, aleatoric)` | −0.267 | Negative correlation |

The aleatoric signal is right-signed: matches the script was more uncertain about
turned out to be harder to score (higher RPS = worse).

The epistemic signal reversed because `corr(epistemic, aleatoric) = -0.267`:
bucketing on epistemic uncertainty partly selects for *low* aleatoric uncertainty,
inverting the expected direction.  This is the root cause of Gate 50's current
`FAIL` status.

---

## 3. Gate 50 status — `error_association`

Gate 50 tests whether the highest-epistemic quartile (Q4) has **worse** RPS than
the lowest (Q1), i.e. `mean_rps(Q4) > mean_rps(Q1)`.  This gate is testing
**epistemic** stratification, not aleatoric.

Current outcome: **FAIL** (Q4 epistemic has *better* RPS than Q1, reversed).

Root cause: the `corr(epistemic, aleatoric) = -0.267` anti-correlation means
high-epistemic quartile ≈ low-aleatoric quartile, which selects for easier
matches, not harder ones.

**Constraint (APEX §23):** Gate 50 `error_association` must remain unconditionally
CRITICAL.  `uncertainty_policy.py` must not be modified.  Re-specifying the gate
threshold after observing the failing result is forbidden.

### What the aleatoric finding means for Gate 50

Testing `corr(aleatoric, RPS)` directly — as this script does — would show a
right-signed result (+0.072).  However:

- Gate 50 is defined on **epistemic**, not aleatoric stratification
- Switching the gate's stratification variable to aleatoric would be a
  post-hoc threshold change (APEX §23 violation)
- The aleatoric finding is therefore research evidence for *why* Gate 50 fails,
  not a mechanism to pass it

The path to a passing Gate 50 is a better-generalizing model generation where
`corr(epistemic, aleatoric)` is neutral or positive — i.e., where the model's
own uncertainty about fixture difficulty is calibrated in the same direction as
the actual difficulty.

---

## 4. Pending live validation

Once the shadow telemetry corpus accumulates ≥ 20 settled records
(`_MIN_TOTAL_RECORDS`), re-run:

```bash
PYTHONPATH=. python scripts/measure_aleatoric_stratification.py
```

Expected output fields when data is sufficient:

```json
{
  "status": "RIGHT_SIGNED" | "WRONG_SIGNED",
  "total_records": <N>,
  "corr_aleatoric_rps": <float>,
  "mean_rps_by_quartile": {"Q1": ..., "Q2": ..., "Q3": ..., "Q4": ...},
  "q4_gt_q1": <bool>,
  "gate_impact": "NONE"
}
```

The `gate_impact: NONE` field is hardcoded in the script regardless of direction —
consistent with the constraint that no finding from this analysis modifies Gate 50.

Update this document with the empirical result when the floor is crossed.

---

## 5. Strategic implication for Gate 7 (`market_baseline`)

If the StatsBomb coverage audit (crosswalk prerequisite 3, `populate_statsbomb_cache.py
--audit-only`) reveals insufficient overlap for Ligue 1 or Bundesliga, the remaining
`ALWAYS_DATA_GAP` StatsBomb slots (`home_pressing_intensity`, `away_pressing_intensity`,
`progressive_carry_diff`) do not need to be solved before attacking `market_baseline`.

The features with the most immediate path to `market_baseline` improvement are the
families already DATA_FED in production:

1. **Elo family** (4 fields) — wired into training as of M2 Family A (PR #148).
   `market_baseline` moved from 0/6 to 1/6 leagues (EPL) on the M2 retrain.
   Further gains expected as the Elo backfill cursor advances past the current
   2024-10-20 cutoff and pre-match Elo for upcoming fixtures becomes available.

2. **H2H and venue families** — populated in the PR #149 feature-density sprint.
   `no_league_regression` was 4/6 post-M2; h2h/venue features are the next
   training-side family with real data.

3. **Understat xG** — corpus now in `data/processed/v4_sources/` (35 league-seasons,
   12,560 matches, PR #140).  `xg_differential` measured at ATE=0.2464 on a causal
   split.  `shot_quality_diff` (a canonical slot) requires PSxG which Understat does
   not publish, but `xg_differential` as a derived training signal is unblocked.

StatsBomb pressing features (`ENABLE_STATSBOMB_ENRICHMENT=false` by default) are
wired but require the parquet cache to be populated.  They are a lower-priority
path to `market_baseline` than the three families above, which are already resolved.

---

*Gate 50 `error_association` remains unconditionally CRITICAL.*  
*This document is research-only.  No gate threshold was modified.*
