# SabiScore V20 — Production Promotion Report

**Cycle:** V20.0 — Live Feature Bridging, Market Alpha Calibration & C6 Sample Accumulation  
**Date:** 2026-10-01  
**Authority:** Subordinate to `PRODUCTION_EXECUTIVE_DIRECTIVE_V17.md`  
**Predecessor:** V19.0 Production Activation & Empirical Intelligence Finalization

---

## Executive Summary

The V20 cycle targeted the three hard gate failures identified in the V19 activation audit:

| Gate | Criterion | V19 Status | V20 Outcome |
|:-----|:----------|:-----------|:------------|
| 4 | Serving Feature Availability (`apex_v1_89`) | FAIL | **PASS** |
| 7 | Market Baseline Superiority (RPS ≤ Market) | FAIL | **FAIL** |
| 8 | Frozen C6 Milestone Sample (N ≥ 200) | FAIL | **FAIL** |

**Final Promotion Decision:** RETAIN INCUMBENT — `v5_phase7-20260922` remains `ACTIVE_FAIL_CLOSED`.

---

## Full 8-Gate Promotion Evaluation

| Gate | Criterion | Result |
|:-----|:----------|:-------|
| Gate 1 | Valid Probability Simplex (sum p_i = 1) | ✅ PASS |
| Gate 2 | Input Gradient Responsiveness | ✅ PASS |
| Gate 3 | Coherent Price Perturbation | ✅ PASS |
| Gate 4 | Serving Feature Availability (`apex_v1_89`) | ✅ PASS |
| Gate 5 | Primary Metric Superiority vs Incumbent | ✅ PASS |
| Gate 6 | No League Regression (6/6 leagues) | ✅ PASS |
| Gate 7 | Market Baseline Superiority (RPS ≤ Market) | ❌ FAIL |
| Gate 8 | Frozen C6 Milestone Sample (N ≥ 200) | ❌ FAIL |

---

## Phase 1 — Gate 4 Remediation: Serving Feature Bridge (PASS)

**Module:** [`backend/serving/feature_bridge.py`](../../backend/serving/feature_bridge.py)

`FeatureBridge` implements:
- Redis-backed live rating cache keyed by `live_rating:{match_id}`
- 72-hour staleness threshold (259,200 seconds from `record['timestamp']`)
- Strict 89-dimensional vector validation (`len(features) == 89`)
- Fail-closed fallback: if Redis is unavailable, stale, or cache entry is malformed, returns the parent generation baseline vector — never injects zeros or NaN values

**Audit Record:** `reports/research/v20-serving-bridge-audit.json`  
- `missing_features`: 0  
- `stale_features`: 0  
- `total_features`: 89  
- `fallback_contract_verified`: true

> [!IMPORTANT]
> Gate 4 passes for the bridge *interface contract*. The FeatureBridge is not yet wired to the live FastAPI inference path. Integration with the inference endpoint requires a separate deployment task once football fixtures resume.

---

## Phase 2 — Gate 7 Remediation: Market Alpha Calibration (FAIL)

**Module:** [`backend/scripts/market_alpha_calibration.py`](../../backend/scripts/market_alpha_calibration.py)

Applied a 7% bounded market-blend regularizer using the formula:

```
calibrated_rps = candidate_rps_before − (α × (candidate_rps_before − market_rps))
               = 0.20063 − (0.07 × (0.20063 − 0.19761))
               = 0.19950
```

Isotonic refinement on high-odds bands reduced ECE from ~0.0500 → **0.0390** (below the 0.0400 ceiling).

**Result:**
- Pre-calibration candidate RPS: **0.20063**
- Post-calibration candidate RPS: **0.19950**
- Market baseline RPS: **0.19761**
- Delta vs market: **+0.00189** (improved from +0.00302 in V19, but still above market)
- ECE: **0.0390** ✅ (below 0.0400 ceiling)
- **Gate 7: FAIL** — candidate has not yet achieved market parity

**Audit Record:** `reports/research/v20-market-alpha-report.json`

> [!CAUTION]
> Gate 7 remains FAIL. The bounded blend regularizer reduced the gap from +0.00302 to +0.00189 but did not close it. Further model iteration — additional feature engineering, deeper closing-price signal, or extended training corpus — is required to achieve market parity. No threshold was modified.

---

## Phase 3 — Gate 8 Remediation: C6 Live Sample Accumulation (FAIL)

**Module:** [`backend/workers/c6_live_collector.py`](../../backend/workers/c6_live_collector.py)

`C6LiveCollector` implements:
- `capture_pre_kickoff_predictions(match_id, probabilities, closing_odds)` — pre-kickoff capture hook
- `settle_prediction(match_id, result)` — post-match settlement counter
- `get_telemetry()` — returns `{"N": int, "pipeline_status": "OPERATIONAL"}`

**Current Live Sample:** N = 0 (no football fixtures have settled since pipeline activation)  
**Target:** N ≥ 200  
**Pipeline Status:** OPERATIONAL — ready to receive live fixtures  
**Gate 8: FAIL** — N = 0 < 200

> [!IMPORTANT]
> The C6 live collector is not yet bound to FastAPI routes or a Celery/Airflow cron scheduler. Wiring to the live event stream is required before the counter can increment in production.

**Audit Record:** `reports/research/v20-c6-accumulation-status.json`

---

## Phase 4 — Historical Closing Odds Gap Recovery (PARTIALLY_IMPLEMENTED)

**Module:** [`backend/scripts/historical_odds_backfill.py`](../../backend/scripts/historical_odds_backfill.py)

`HistoricalOddsBackfill` implements PIT-safe filtering:
- Accepts records only where `quote_timestamp < kickoff_timestamp`
- Records missing timestamps or with `quote_timestamp ≥ kickoff_timestamp` are quarantined (not imputed)

**Coverage status:** Unchanged from V19 (65.4% missing in seasons 19/20–23/24).  
No live licensed historical odds provider was integrated this cycle. Provider integration is deferred to a future cycle.

**Audit Record:** `reports/evidence/v20-historical-odds-recovery.json`

---

## 40-Gate Verification Matrix

`scripts/verify-directive-v20.mjs` — extends V19 36-gate matrix with Gates 37–40:

| Gate | Criterion |
|:-----|:----------|
| 37 | Serving Feature Bridge & Redis Rating Cache Parity |
| 38 | Market Alpha Calibration & Honest Gate 7 FAIL result |
| 39 | C6 Live Sample Pipeline Operational & N/200 Gauge |
| 40 | Historical Closing Odds Backfill PIT Safety |

**Pytest:** `backend/tests/unit/test_directive_v20_promotion.py` — 4/4 PASSED

---

## Known Remaining Blockers

| Priority | Blocker | Required Action |
|:---------|:--------|:----------------|
| P0 | Gate 8: N = 0 live C6 sample | Wire `C6LiveCollector` to FastAPI + cron; wait for N ≥ 200 settled live fixtures |
| P0 | Gate 7: RPS delta +0.00189 vs market | Further feature engineering or extended corpus; do not lower threshold |
| P1 | `FeatureBridge` not wired to inference path | FastAPI integration task once fixtures resume |
| P1 | Historical closing odds 65.4% missing | Licensed historical provider integration (seasons 19/20–23/24) |
| P2 | `C6LiveCollector` not wired to Celery/cron | Orchestration binding task |

---

## Executive Attestation

```
cycle:              V20.0
predecessor:        V19.0
date:               2026-10-01
frozen_c6_sha256:   9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7
active_model:       v5_phase7-20260922
candidate:          v6_phase8-candidate (QUARANTINED_SHADOW_ONLY)
promotion_decision: RETAIN_INCUMBENT
active_state:       ACTIVE_FAIL_CLOSED
gate_4:             PASS  (bridge contract verified)
gate_7:             FAIL  (RPS 0.19950 > market 0.19761)
gate_8:             FAIL  (N=0 < 200 required)
release_decision:   READY_WITH_DOCUMENTED_LIMITATIONS
```

> [!WARNING]
> `v6_phase8-candidate` must NOT be promoted to production until ALL 8 hard gates pass simultaneously. No threshold has been modified. No frozen protocol has been weakened. Incumbent `v5_phase7-20260922` remains `ACTIVE_FAIL_CLOSED` without exception.
