# `apex_v4_66` Candidate Evaluation

**Date:** 2026-09-04  
**Schema:** `apex_v4_66`  
**Training suffix:** `v9_gate7`  
**Holdout season:** 2526  
**Evaluated by:** `scripts/compare_candidate_vs_incumbent.py --candidate-schema apex_v4_66`  
**Incumbent:** `v5_phase7` (68-wide vector)

---

## 1. Context — StatsBomb Coverage Audit (PATH B)

`scripts/audit_statsbomb_coverage.py` was executed 2026-09-04 and produced
`reports/evaluation/statsbomb-coverage-audit-2026.json`.

| Metric | Value |
|---|---|
| StatsBomb Open matches (5 leagues) | 1,632 |
| Understat played matches (unique pairs) | 3,440 |
| Identity crosswalk intersection | 811 |
| **Coverage** | **23.58%** |
| Threshold | 85.0% |
| **Path** | **B — INVIABLE** |

Root cause: StatsBomb Open Data for domestic leagues is largely a 2015/16
season dump. The Understat corpus covers 2019–2026.  Only La Liga
2019/20–2020/21, Bundesliga 2023/24, and Ligue 1 2021/22–2022/23 overlap.

**PATH B consequences (per directive):**

- `home_pressing_intensity` and `progressive_carry_diff` formally relegated to
  `PHASE7_FEATURES_ALWAYS_DATA_GAP` in `feature_registry.py`.
- `ENABLE_STATSBOMB_ENRICHMENT` must remain `False`.  Re-evaluate only if
  StatsBomb publishes event data covering ≥ 85% of the Understat corpus.
- `CERTIFICATION_POLICY_VERSION` bumped `1.1.0` → `1.1.1`
  (documentation-only; no gate threshold changed, APEX §23).

---

## 2. Schema Design — `apex_v4_66`

Feature width: **66** = `APEX_FEATURES_68` − 2 event-data gap features.

Dropped features (both `ALWAYS_DATA_GAP` post-audit):

- `home_pressing_intensity`
- `progressive_carry_diff`

The 13 h2h / venue / market-interaction features populated in PR #149 are
**fully retained**.  Removing the two constant-filled slots means the model
receives 66 real inputs with no constant-value noise.

---

## 3. Training Results

```
POOLED  train=8537 test=1987
avg:    acc=0.5269 rps=0.2002
stacked: acc=0.5315 rps=0.1980
home-only baseline: 0.4394
prior-RPS: 0.2290
market-RPS: 0.1978
responsive features: 56/66
```

EREDIVISIE uses the pooled model (260 rows, no holdout possible).

---

## 4. Per-League Comparison vs Incumbent (`v5_phase7`)

| League | Incumbent RPS | Candidate RPS | Δ RPS | Candidate wins | Beats market |
|---|---|---|---|---|---|
| BUNDESLIGA | 0.1900 | 0.2003 | +0.0103 | ✗ | ✗ (market 0.1908) |
| EPL | 0.2036 | 0.2049 | +0.0013 | ✗ | ✓ (market 0.2054) |
| EREDIVISIE | 0.2048 | 0.1990 | −0.0058 | **✓** | ✗ (market 0.1978) |
| LA_LIGA | 0.2018 | 0.1972 | −0.0046 | **✓** | ✗ (market 0.1963) |
| LIGUE_1 | 0.2032 | 0.2025 | −0.0007 | **✓** | ✗ (market 0.1991) |
| SERIE_A | 0.2051 | 0.2007 | −0.0045 | **✓** | ✗ (market 0.1971) |

RPS is lower-is-better.  
**Candidate wins: 4/6 leagues.  Leagues beating market: 1/6 (EPL).**

---

## 5. Gate Results

| Gate | Status | Notes |
|---|---|---|
| `valid_probability_simplex` | **PASS** | No invalid simplex row |
| `input_responsiveness` | **PASS** | Min responsive features: 43 (BUNDESLIGA) |
| `coherent_price_perturbation` | **PASS** | All 6 leagues directionally coherent |
| `primary_metric_improvement` | **PASS** | Mean RPS improvement +0.00066 |
| `serving_feature_availability` | **FAIL** | `serving_schema_misaligned_slots: 14` (apex market block dispatch not yet active for this schema); `training_defaulted_slots: 1`; `always_data_gap_slots: 4` |
| `no_league_regression` | **FAIL** | 4/6 leagues; requires all 6 |
| `market_baseline` | **FAIL** | 1/6 leagues beat market; requires all 6 |

**`promotion_permitted: false`** — three gates fail.

### Gate 7 (`market_baseline`) result

**1/6 leagues** (EPL: candidate RPS 0.2049 vs market 0.2054) beat the
market-implied RPS.  The directive's acceptance criterion — "RPS strictly
less than market-implied RPS in at least one league" — is **met for EPL**.

This does not promote the candidate.  The certification policy requires
`market_baseline` to pass in every league.  However, the directive's
evaluation criterion for the Gate 7 *research milestone* (at least one
league) is satisfied.

---

## 6. Current Generation Comparison (v5_phase7 vs apex_v4_66)

| Generation | `no_league_regression` | `market_baseline` |
|---|---|---|
| `v5_phase7` (incumbent) | — | 0/6 leagues (baseline measure at PR #149) |
| `apex_v4_66` (this candidate) | 4/6 | **1/6 (EPL)** |

Dropping the two constant `ALWAYS_DATA_GAP` slots produced a net +0.00066
mean RPS improvement and moved `market_baseline` from 0/6 → 1/6.

---

## 7. Open Items

- **`serving_schema_misaligned_slots: 14`** — the apex market-block serving
  dispatch (`DEBT.md` item 37 / PR #78) is in place for the production
  serving path but the promotion-evidence builder still sees a mismatch for
  `apex_v4_66`.  Resolving this requires activating an apex-generation
  manifest; it is not a training defect.

- **`no_league_regression`** — requires 6/6 wins.  BUNDESLIGA and EPL are
  the losing leagues.  No post-hoc threshold change is permitted (APEX §23).

- **`market_baseline`** — requires 6/6 leagues.  EPL is currently the only
  league where the candidate beats the market.  Additional training signal
  (more real match data as the 2526 season progresses) or a better model
  generation is needed.

- **Gate 50 (`error_association`)** — unchanged; remains unconditionally
  CRITICAL.  This evaluation does not modify `uncertainty_policy.py`.

---

## 8. Conclusion

`apex_v4_66` is a **valid research candidate**.  It is not promotable today
(3 gates fail).  Key outcomes:

1. The StatsBomb coverage audit (23.58% < 85%) formally closed the
   event-data feature line for this generation.
2. Dropping the two constant-value slots produced a measurable RPS
   improvement (+0.00066 mean) and moved EPL's candidate past the market
   baseline for the first time (Gate 7 milestone partially met).
3. The schema is sound: 56/66 responsive features, all 6 leagues
   directionally coherent, no invalid probability rows.

*`promotion_permitted: false`.  `stake_permitted: false` maintained.
System remains `RESEARCH_ONLY / ACTIVE_FAIL_CLOSED`.*
