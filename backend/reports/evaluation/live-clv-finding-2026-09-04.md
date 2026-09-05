# Live CLV Finding — 2026-09-04

**Type:** Evidence report — first real out-of-sample closing-line value measurement  
**Triggered by:** CLV series crossing the 10-record floor during live production operation

---

## Summary

Closing-line value (CLV) crossed its 10-record floor in production. The first live
measurement reads **negative**: the model's pre-kickoff price is worse than the
closing market on average.

| Metric | Value |
|---|---|
| n (joined predictions) | 17 |
| mean_clv | −3.15% (−0.0315) |
| positive_rate | 52.9% (9/17 predictions beat closing) |
| measurement date | 2026-09-03 |
| endpoint | `GET /api/v1/model-performance` → `clv` field |

---

## Why this matters

This is an independent, live confirmation of what `market_baseline` already measures
offline. Two instruments, same verdict:

| Instrument | Method | Result |
|---|---|---|
| `market_baseline` (offline gate) | Candidate RPS vs de-vigged market-implied RPS, held-out corpus | 0 / 6 leagues pass |
| Live CLV (production measure) | Model pre-kickoff probability vs market consensus at kickoff | −3.15% mean, n=17 |

The model is not beating the market. This was the hypothesis; it is now confirmed
on real fixtures in real time, not just on a historical corpus.

---

## What CLV measures

`clv_service.compute_clv_summary()` computes per-prediction:

```
clv_record = model_prob[argmax(model)] - closing_prob[argmax(model)]
```

Positive CLV means the model assigned higher probability than the closing market to
the outcome that was most likely at kickoff — i.e., the model "saw something"
before the sharp money did. Negative CLV means the model was systematically behind
the market.

At n=17 the confidence interval is wide. This is a directional finding, not a
precise estimate. The sign is what matters: the model is on the wrong side.

---

## What this does NOT mean

- It does not mean the model is broken. It fails closed correctly (`stake_permitted:
  false`), and a negative CLV on a research-grade model is expected.
- It does not mean CLV will stay negative indefinitely. A better-trained generation
  could reverse it.
- It does not unlock any promotion gate. `market_baseline` requires beating the
  market on a held-out corpus in every league — live CLV is a complementary signal,
  not a substitute gate.

---

## Implications for Phase 3

The directive identifies `market_baseline` as "the single blocker." This finding
strengthens that conclusion: three independent measurements now agree.

| Evidence | Measurement |
|---|---|
| apex_v2_71 candidate | mean RPS −0.00159, rejected |
| apex_v3_68 candidate | market_baseline 0/6 leagues, rejected |
| Live CLV (this finding) | −3.15%, n=17 |

Phase 3 (candidate evaluation) remains the correct next step, and this finding
sets an honest baseline for what "improvement" means. Any future candidate that
claims positive CLV must be measured against this baseline with the same join
methodology (`clv_service.get_clv_records()`).

---

## Data lineage

- Predictions: `MatchPredictionLog`, written by Apex v3 capture path
- Closing odds: `MarketSnapshot(is_closing_line=True)`, written by
  `clv_capture_service` via `TheOddsAPIProvider`
- Join key: `match_id` (not `canonical_fixture_id` — see CLAUDE.md vΩ.37 note;
  `closing_market_snapshot_id` FK is permanently NULL, the `match_id` join is
  the live production path)
- CLV computation: `backend/src/services/clv_service.py` `compute_clv_summary()`

---

## Metric contract

Consistent with `reports/evaluation/metric-contract.json` v1.0.0.
CLV is not a ranked probability score; it does not use the M0 RPS formulation.
Do not compare CLV values to RPS thresholds.

---

## Next action

No code change. This report is the action — it closes the "record the finding"
obligation in the Tier 1 plan and provides a baseline for future CLV measurement.

When n ≥ 50: re-run `GET /api/v1/model-performance` and compare `clv.mean_clv`
against this report. A generation that produces positive live CLV is a meaningful
signal even if `market_baseline` on the historical corpus is still borderline.
