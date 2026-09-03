# `apex_v2_71` candidate — evaluated and REJECTED (2026-09-03)

Companion prose for `apex-v2-71-candidate-evaluation.json`. The JSON is the
record; this explains what was asked, what was measured, and why the answer is
no.

## What was proposed

Append the three xG features `scripts/measure_xg_feature_ate.py` measured as
`CAUSAL_DRIVER` — `xg_differential`, `xg_attack_diff`, `xg_defense_diff` — to
`APEX_FEATURES_68` as a new candidate schema, train it, and take it to the
promotion gate. `finishing_efficiency_gap` was excluded up front on its own ATE
(0.0101, p=0.32 on the deduplicated corpus).

## What was measured

Both candidate heads scored on the **identical** `apex_v2_71` holdout. This is
the number that matters: the headline comparison scores `apex_v1_68` on 12,256
rows and `apex_v2_71` on 10,779, so its delta mixes "added xG" with "dropped
1,478 rows".

| league | `apex_v1_68` RPS | `apex_v2_71` RPS | xG delta |
|---|---|---|---|
| BUNDESLIGA | 0.2000 | 0.1994 | **+0.0006** |
| EPL | 0.2051 | 0.2055 | −0.0004 |
| LA_LIGA | 0.1974 | 0.1979 | −0.0005 |
| LIGUE_1 | 0.2003 | 0.2063 | −0.0061 |
| SERIE_A | 0.1997 | 0.2013 | −0.0016 |

Mean xG RPS improvement **−0.00159**; improved in **1 of 5** leagues.

Promotion gates (`PROMOTION_REQUIRES_ALL_GATES = True`):

```
valid_probability_simplex      PASS
input_responsiveness           PASS    min 38 responsive features
coherent_price_perturbation    PASS
serving_feature_availability   FAIL    misaligned 14 (11 pre-existing + 3 xG)
primary_metric_improvement     FAIL    mean RPS improvement -0.00134
no_league_regression           FAIL    2 / 5 league wins
market_baseline                FAIL    0 / 5 leagues beat the market
promotion_permitted            False
```

## Why this is a real result, not a pipeline artifact

The three features are **genuinely observed**, not defaulted: every one reports
`training_coverage = 1.0` and `variable_in_training = true`. Rows with no honest
xG answer were dropped, never imputed — serving returns `None` for the same
fixture, so a default would have been a value the model learned that serving can
never reproduce.

`training_defaulted_slots` is **16, identical to the `apex_v1_68` baseline**. The
xG work added no defaulted slot. `serving_schema_misaligned_slots` moved 11 → 14:
the 11 are the pre-existing apex-vs-legacy market-block divergence against a
`phase7_68` active generation, and the 3 new ones are the xG positions, which
have no serving counterpart until `active_generation.json` declares the wider
contract. That is a promotion decision rather than a defect — and moot, given the
RPS result.

## The finding worth remembering

**A large, significant ATE is not evidence of out-of-sample predictive lift.**
ATE 0.2485 / 0.2181 / 0.1832, all p < 1e-68, and the block still costs RPS in 4
of 5 leagues. The causal-screening step (`measure_xg_feature_ate.py`) is a filter
against including *noise*; it is not a promotion criterion, and a future proposal
that reads "high ATE, therefore ship it" is making this mistake again.

Two mechanisms are plausible and neither is separated by this evidence:

1. the market block already prices in shot quality, so xG is largely redundant
   with features the model has;
2. dropping 1,478 rows (12% of the corpus, concentrated in the uncovered 2021/22
   season and all of Eredivisie) costs more than the features add.

Distinguishing them needs `match_stats` populated in production plus a
serving-side measurement, not another offline candidate.

## Coverage, for anyone who repeats this

The Understat join reaches 86% of the football-data corpus overall and 98–99% in
the 2526 holdout for all five covered leagues. It reaches **0% for Eredivisie** —
Understat publishes no Eredivisie corpus — so `apex_v2_71` trains no Eredivisie
model at all, and the league silently leaves the comparison. Any future schema
built on this corpus inherits that.

`2021/22` is absent from all five leagues: the committed corpus files overlap
(`understat_ligue_1_2020` and `understat_ligue_1_2021` both hold the whole
2020/21 season), so the 7 files per league cover 6 distinct seasons. See
`src/data/understat_corpus.py`.

## What was kept

The candidate `.pkl` artifacts were discarded (`backend/models/candidate/*.pkl`
is gitignored). The infrastructure built to run the experiment was kept: the
transactional `--apply` write path, the leak-free `features/xg_replay.py`, the
shared corpus loader, and four pipeline defects fixed along the way. The
`apex_v2_71` key stays registered in `FEATURE_SCHEMA_VERSIONS` so a future xG
candidate can be evaluated without re-deriving any of it — the key is a
measurement contract, not an endorsement.
