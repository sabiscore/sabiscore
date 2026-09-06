# Paired bootstrap on the candidate-minus-market RPS difference (2026-09-06)

Companion prose for `market-edge-bootstrap-v10_gate7_hpo.json` and
`market-edge-bootstrap-incumbent-v5_phase7.json`. The JSON files are the record;
this explains what was asked and what the answer means.

## What was asked

A directive proposed amending `certification_policy.py` to make the
`no_league_regression` and `market_baseline` gates league-stratified, so that
EPL — the one league where a candidate's RPS came in under the de-vigged market
— could be authorized for staking while the other five stayed fail-closed.

The stated evidence was `apex_v5_66`'s EPL holdout: candidate RPS **0.2049**
against market **0.2054**, a margin of **0.0005** over 375 fixtures.

`PROMOTION_GATES["market_baseline"]` is a point comparison. It asks whether one
mean is below another and has no notion of the sampling error on that
comparison. At a margin of 0.0005 the statements "the candidate beats the market
in EPL" and "the candidate is indistinguishable from the market in EPL" are both
consistent with the observed number, and the gate cannot tell them apart. This
measurement was run to decide which before any policy change was entertained.

## What was built

Nothing in the repository persisted per-match holdout probabilities, which is
why `block_bootstrap_ci` — present in `models/evaluation/metrics.py` since M0 —
had never been run on a candidate-versus-market difference.

- `compare_candidate_vs_incumbent.py` gains `--per-match-output`, writing an
  `.npz` of labels plus candidate, incumbent and de-vigged market probabilities
  per league.
- `scripts/bootstrap_market_edge_ci.py` runs the paired interval.

The market probabilities are not a new data source. They are columns
`market_prob_home/draw/away` of the candidate's own holdout matrix — the exact
slice `train_on_real_matches` uses for `baseline_rps_market`
(`X_test[:, market_columns]`). Rows are therefore paired with the model
probabilities by construction: same fixtures, same order, no join.

## Why pairing, and how it is preserved

`block_bootstrap_ci` resamples row blocks and re-scores one probability matrix.
Calling it separately for each head would draw *different* blocks for each,
destroying the pairing and inflating the interval to roughly the sum of two
independent variances.

Both heads are therefore stacked column-wise into one `(n, 6)` array, and the
metric function splits them apart, so a single set of block indices applies to
both on every replicate. No change to `block_bootstrap_ci` was needed.

This matters more than it sounds: on a correlated pair the paired interval
measured **~34x narrower** than the unpaired equivalent. An unpaired test could
not have resolved a 0.0005 effect at all; the paired one can. The answer below
is a real negative, not an underpowered one.

## Validation performed before trusting the output

1. **Two RPS implementations exist in this repository** —
   `train_on_real_matches.ranked_probability_score` (vectorized, and what
   produced both the candidate figures and `baseline_rps_market`) and the scalar
   one in `models/evaluation/metrics`. They were checked to agree to 1e-12, and
   the script asserts this at startup. Scoring the comparison with a different
   implementation than produced the numbers under test would make an
   implementation difference look like an effect.
2. **The scoring run reproduces the published figures exactly** — LA_LIGA
   0.2018/0.1964, LIGUE_1 0.2032/0.2034, SERIE_A 0.2051/0.1994, 3/6 candidate
   wins, mean RPS improvement +0.0015, matching
   `apex-v5-candidate-evaluation.md`.
3. **The persisted market probabilities reproduce `baseline_rps_market` to six
   decimal places** in 5 of 6 leagues, and every market row sums to 1.0. The
   sixth is explained below.
4. **`block_bootstrap_ci` swallows a failing replicate** with a bare
   `except Exception: continue` — the shape that made `walk_forward_validate`
   report "no valid folds" forever while the real cause was a `TypeError`. The
   script now errors out if the scored replicate count is short of the requested
   one, rather than reporting a quietly narrower interval.
5. **Sensitivity in both directions was demonstrated on synthetic data with
   known answers** before real data was scored: identical heads give exactly
   zero with a zero-width interval; a head blended toward the truth gives an
   interval strictly below zero; a deliberately degraded head gives one strictly
   above. Pinned in `tests/unit/test_market_edge_bootstrap.py`, and the pairing
   guard was watched failing against deliberately broken pairing before being
   trusted.

## Result — candidate `apex_v5_66`, 2526 holdout, 10,000 replicates, block size 10

RPS is lower-is-better, so a genuine edge is a **negative** difference.

| league | n | candidate | market | difference | 95% CI | verdict |
|---|---:|---:|---:|---:|---|---|
| BUNDESLIGA | 301 | 0.1968 | 0.1908 | +0.00590 | [+0.0004, +0.0106] | market beats candidate |
| **EPL** | 375 | 0.2049 | 0.2054 | **−0.00050** | **[−0.0029, +0.0028]** | **indistinguishable** |
| EREDIVISIE | 260 | 0.1988 | 0.1969 | +0.00190 | [−0.0009, +0.0049] | indistinguishable |
| LA_LIGA | 375 | 0.1964 | 0.1963 | +0.00010 | [−0.0038, +0.0034] | indistinguishable |
| LIGUE_1 | 301 | 0.2034 | 0.1991 | +0.00430 | [−0.0014, +0.0095] | indistinguishable |
| SERIE_A | 375 | 0.1994 | 0.1971 | +0.00220 | [−0.0010, +0.0056] | indistinguishable |

**Leagues where the 95% CI excludes zero in the candidate's favour: 0 of 6.**

The EPL interval spans zero with a half-width of 0.00285 — **5.7x the point
estimate**. The margin that motivated the stratification proposal is inside
sampling error.

The only interval excluding zero runs the other way: Bundesliga, where the
candidate is significantly *worse* than the market. Under the Bonferroni
correction for six simultaneous tests, even that becomes indistinguishable.

## The same question of the serving generation

The incumbent `v5_phase7` probabilities were persisted in the same run, so the
comparison costs nothing extra:

| league | n | incumbent | market | difference | 95% CI | verdict |
|---|---:|---:|---:|---:|---|---|
| BUNDESLIGA | 301 | 0.1900 | 0.1908 | −0.00090 | [−0.0092, +0.0067] | indistinguishable |
| EPL | 375 | 0.2036 | 0.2054 | −0.00180 | [−0.0127, +0.0105] | indistinguishable |
| EREDIVISIE | 260 | 0.2048 | 0.1969 | +0.00780 | [−0.0060, +0.0212] | indistinguishable |
| LA_LIGA | 375 | 0.2018 | 0.1963 | +0.00550 | [−0.0011, +0.0129] | indistinguishable |
| LIGUE_1 | 301 | 0.2032 | 0.1991 | +0.00410 | [−0.0063, +0.0152] | indistinguishable |
| SERIE_A | 375 | 0.2051 | 0.1971 | +0.00800 | [+0.0005, +0.0167] | market beats incumbent |

**0 of 6 in the incumbent's favour** as well.

Note the incumbent's intervals are roughly 4x wider than the candidate's. That
is informative rather than noise: the candidate was trained with the Apex market
block and tracks the market closely, so the paired difference has little
variance. Its tight interval around zero is a quantitative statement that
**this candidate is close to reproducing the market**, which is consistent with
`apex_v3_68`'s independent finding that the market already prices what h2h and
home-venue records predict.

## Incidental finding: Eredivisie's market baseline is pooled, not its own

`training_report_real_v10_gate7_hpo.json` has no `EREDIVISIE` key, so
`compare_candidate_vs_incumbent` falls back to `POOLED` (n=1987, all leagues)
for its `baseline_rps_market`. The gate has therefore been comparing
Eredivisie's candidate RPS against an all-league pooled market baseline of
0.197849 rather than Eredivisie's own 0.196923.

This follows from Eredivisie using the pooled model (one season of corpus, no
own holdout — the documented arrangement), so it is a consequence of a known
decision rather than a new defect. It does not change any verdict here: the
paired bootstrap above computes Eredivisie's market RPS from its own 260 rows
and still returns "indistinguishable". Recorded so the discrepancy is not
rediscovered as a bug.

## Conclusion

**The proposed league-stratified amendment is not supported by the evidence.**

The EPL "edge" that motivated it is 0.078 sigma of an unpaired standard error and
well inside a properly paired 95% interval. It was also selected as the best of
six leagues after all six were observed; under the null that the model merely
equals the market, roughly three of six would be expected to come out ahead by
chance, so **1 of 6 is worse than chance, not better**.

A further point the proposal did not address: in EPL, `apex_v5_66` scores 0.2049
against the incumbent's 0.2036. It is 0.0013 *worse than the model already
serving* in the very league proposed for authorization — a regression roughly
three times the size of the claimed market edge.

No gate threshold was changed, and no candidate was promoted.
`promotion_permitted` remains `false` and `stake_permitted` remains `false`.

The instrument built here is reusable and is the standard this decision should
be held to in future: a candidate is a genuine market-beater in a league when
its paired interval excludes zero there, ideally under the family-wise
correction.

## Reproduce

```bash
cd backend
PYTHONPATH=. python scripts/compare_candidate_vs_incumbent.py \
    --candidate-schema apex_v5_66 \
    --per-match-output models/candidate/per_match_v10_gate7_hpo.npz \
    --output models/candidate/comparison_report_v10_gate7_hpo.json

PYTHONPATH=. python scripts/bootstrap_market_edge_ci.py \
    --per-match models/candidate/per_match_v10_gate7_hpo.npz \
    --output reports/evaluation/market-edge-bootstrap-v10_gate7_hpo.json

PYTHONPATH=. python scripts/bootstrap_market_edge_ci.py \
    --per-match models/candidate/per_match_v10_gate7_hpo.npz --head incumbent \
    --output reports/evaluation/market-edge-bootstrap-incumbent-v5_phase7.json
```
