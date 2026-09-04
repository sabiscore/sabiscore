# `apex_v3_68` candidate — evaluated and REJECTED (2026-09-04)

Companion prose for `apex-v3-68-candidate-evaluation.json`. The JSON is the
record; this explains what was asked, what was measured, and why the answer is
no.

## What was proposed

`PRODUCTION_EXECUTIVE_DIRECTIVE.md` §2/§5 Phase 2: populate the 13 of
`APEX_FEATURES_68`'s 68 slots (h2h block, home-venue block, 3
market-interaction fields) that `train_on_real_matches.build_dataset` had
left at their registry default since before this feature registry existed —
even though `UpcomingMatchFeatureProjector` computes real values for the
equivalent fixture at serving time today. A column that is constant across
every training row is never split on, so no ensemble had ever used signal
serving already pays to compute. This was the directive's own best-argued
attack on `market_baseline`, the one gate that has failed for every model
measured so far.

Two corrections to the directive's own premise, made **before** training, not
discovered after: the directive's cited parity reference
(`data/transformers.py:407-474`) is a second, divergent pipeline computing
these fields through materially different formulas — the real serving
computation, and the one this candidate mirrors, is
`upcoming_match_feature_service.py`'s `_get_h2h_stats`/`_get_home_venue_stats`/
its interaction block. And `total_goals_expected` has zero call sites in that
real path, so it stays defaulted — `training_defaulted_slots` moves 16 → **3**,
not 16 → 2 as the directive states.

## What was measured

Both heads scored on the **identical** rows — this candidate drops no row (a
cold start degrades to the registry default rather than excluding the
fixture, exactly what serving does), so `rows_by_league` is byte-identical
between `apex_v1_68` and `apex_v3_68` by construction, confirmed directly
before training. Unlike `apex_v2_71`, there is no "added features" vs.
"dropped rows" delta to separate here.

| league | incumbent RPS | candidate RPS | delta | market RPS | beats market |
|---|---|---|---|---|---|
| BUNDESLIGA | 0.1900 | 0.1994 | **−0.0094** | 0.1908 | no |
| EPL | 0.2036 | 0.2054 | −0.0018 | 0.2054 | no |
| EREDIVISIE | 0.2048 | 0.1993 | +0.0054 | 0.1978 | no |
| LA_LIGA | 0.2018 | 0.1976 | +0.0043 | 0.1963 | no |
| LIGUE_1 | 0.2032 | 0.2043 | −0.0011 | 0.1991 | no |
| SERIE_A | 0.2051 | 0.2008 | +0.0043 | 0.1971 | no |

Mean RPS improvement **+0.00028**; candidate wins **3 of 6** leagues, loses 3.
The single largest movement in either direction is Bundesliga's loss
(−0.0094) — larger than any of the three wins.

Promotion gates (`PROMOTION_REQUIRES_ALL_GATES = True`):

```
valid_probability_simplex      PASS
input_responsiveness           PASS    min 43 responsive features (up from 35-45 per league on the incumbent)
coherent_price_perturbation    PASS
serving_feature_availability   FAIL    training_defaulted_slots 16->3; serving_schema_misaligned_slots unchanged at 11
primary_metric_improvement     PASS    mean RPS improvement +0.00028
no_league_regression           FAIL    3 / 6 league wins
market_baseline                FAIL    0 / 6 leagues beat the market
promotion_permitted            False
```

## Why this is a real, mixed result — not a clean rejection and not a pass

`primary_metric_improvement` technically clears (mean delta is positive) and
`input_responsiveness` clears with room — every league gained 8-13 more
responsive features over the incumbent (35→43 through 45→55), meaning the
model genuinely does split on some of this new signal, not merely carry it
inertly. That is a real, measured difference from a no-op.

It does not matter, because the decisive gate is `market_baseline`, and it
reads exactly what it read before this work: **0 of 6.** Even in the three
leagues the candidate beats the incumbent (Eredivisie, La Liga, Serie A), it
still does not beat the market in any of them — Eredivisie 0.1993 vs. market
0.1978, La Liga 0.1976 vs. 0.1963, Serie A 0.2008 vs. 0.1971. Denser features
narrowed the gap to the incumbent in half the leagues and widened it in the
other half; they did not narrow the gap to the market anywhere.

## `serving_feature_availability` cannot pass from this work, by design

This was stated in the implementation plan **before training ran**, not
discovered afterward. `serving_schema_misaligned_slots` is **11**, unchanged
from the `apex_v1_68` baseline — the pre-existing divergence between the
Apex market block (positions 20-30) and the currently-active `phase7_68`
generation's legacy serving contract. `serving_feature_availability` requires
both `training_defaulted_slots == 0` and `serving_schema_misaligned_slots ==
0`. This candidate can only ever move the first number; the second requires
activating an apex generation, a separate promotion decision entirely outside
this candidate's scope. Even a candidate that swept every RPS gate would
still fail this one.

## The finding worth remembering

**Denser, genuinely-observed features that the model measurably uses are
still not sufficient to beat the market.** This is the second candidate in a
row to demonstrate that shape — `apex_v2_71` added three `CAUSAL_DRIVER`
xG features (ATE > 0.18, p < 1e-68) and lost RPS in 4 of 5 leagues;
`apex_v3_68` adds thirteen features the model responds to and produces a
statistical wash (3-3, ±0.0003 mean). Two candidates, two different feature
families, two different directions of the incumbent-comparison result, and
the same answer on the gate that matters: **0 of however-many leagues beat
the market, both times.**

The market-implied probability already prices in whatever a team's h2h
record and home-venue record predict, at least as well as a five-learner
stacked ensemble trained on 12,256 real matches does. That is not a defect in
this implementation — the parity work is real, tested, and worth keeping
(serving now shares the exact same formulas, converting future drift from a
possible bug into a structural impossibility) — but it closes, rather than
opens, the "more training-time feature density" branch of attacking
`market_baseline`. The remaining unexplored branches are model-family choices
(this ensemble's own architecture) and event-level data SabiScore does not
have (`home_pressing_intensity`, `progressive_carry_diff` — the two slots
that stay permanently defaulted regardless of any training-side work).

## Coverage, for anyone who repeats this

Eredivisie's h2h coverage is measurably worse than the other five leagues: 41.2%
of its rows have no prior meeting between the pair (registry default), against
18.5-20.2% for BUNDESLIGA/EPL/LA_LIGA/LIGUE_1/SERIE_A. This is a corpus-depth
consequence, not a bug — `data/cache` holds one football-data.co.uk season for
Eredivisie against six-to-seven for every other league, and within one season
each pairing meets at most twice. Home-venue coverage is better everywhere
(9.2% at default globally) since it only needs the HOME side's own history,
not a specific pair.

## What was kept

The candidate `.pkl` artifacts, `feature_availability_matrix_v8_dense68.json`,
`comparison_report_v8_dense68.json`, and `training_report_real_v8_dense68.json`
are gitignored under `models/candidate/*.pkl` / regenerable from the
manifest; this evaluation report is the durable record. The infrastructure is
kept and is not candidate-specific: `feature_registry.py`'s three new pure
functions, `TeamHistory`'s walk-forward accumulators, and
`upcoming_match_feature_service.py`'s refactor to the shared formulas are now
load-bearing for train/serve parity regardless of this candidate's outcome —
a future proposal in this feature family (e.g. sourcing
`home_pressing_intensity`/`progressive_carry_diff` from real event data) can
build on them without re-deriving the accumulator or the parity test. The
`apex_v3_68` key stays registered in `FEATURE_SCHEMA_VERSIONS` as a
measurement contract, not an endorsement — matching `apex_v2_71`'s precedent.
