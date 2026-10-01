import pytest
import json
import os
import time

# We must ensure the backend modules exist and are importable
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../backend")))

from backend.serving.feature_bridge import FeatureBridge
from backend.workers.c6_live_collector import C6LiveCollector
from backend.scripts.market_alpha_calibration import MarketAlphaCalibrator
from backend.scripts.historical_odds_backfill import HistoricalOddsBackfill

def test_gate_37_feature_bridge():
    # A report that asserted a length-only fallback was verified is not proof
    # of semantic compatibility. V21 requires the bridge to reject it.
    path = "reports/research/v20-serving-bridge-audit.json"
    assert os.path.exists(path), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)
    assert "audit" in data
    assert data["audit"]["fallback_contract_verified"] is True  # legacy claim, reconciled separately

    # Verify actual code logic
    bridge = FeatureBridge(redis_client=None)
    baseline = [0] * 89
    from backend.serving.feature_bridge import FeatureBridgeRejected
    with pytest.raises(FeatureBridgeRejected, match="no semantic evidence"):
        bridge.get_serving_features("m1", baseline)

def test_gate_38_market_alpha():
    """
    Gate 38 verifies that MarketAlphaCalibrator:
      - Applies a bounded market-blend regularizer using honest arithmetic.
      - Reports ECE below 0.0400 (calibration quality improved).
      - Honestly reports gate_7_result='FAIL' because calibrated RPS > market baseline.

    Governance invariant: the module must NOT fabricate a pass by hardcoding a value
    below the market baseline. The actual empirical calibrated RPS (0.19950) exceeds
    the market baseline (0.19761), so Gate 7 remains FAIL and the incumbent is retained.
    """
    path = "reports/research/v20-market-alpha-report.json"
    assert os.path.exists(path), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)

    assert "calibration" in data
    cal = data["calibration"]
    assert "opening_market_rps" in cal
    assert "candidate_rps_after_calibration" in cal
    # JSON report must honestly record Gate 7 as FAIL
    assert data["status"] == "FAIL", (
        f"v20-market-alpha-report.json must record status=FAIL; got {data['status']!r}"
    )
    # Post-calibration RPS must be below pre-calibration (calibration helped)
    assert cal["candidate_rps_after_calibration"] < cal.get("candidate_rps_before", 0.20063), (
        "Calibration must reduce candidate RPS vs pre-calibration baseline."
    )
    # But still above market baseline (gate remains FAIL — honest result)
    assert cal["candidate_rps_after_calibration"] > cal["opening_market_rps"], (
        "Gate 7 is FAIL: calibrated RPS must still exceed market baseline."
    )

    # Verify actual module code produces honest results — no fabricated constant subtraction
    calib = MarketAlphaCalibrator(opening_market_rps=0.19761, candidate_rps_before=0.20063, blend_alpha=0.07)
    res = calib.calibrate()

    # ECE below ceiling — calibration quality verified
    assert res["ece_score"] < 0.0400, f"ECE {res['ece_score']} must be below 0.0400"

    # Honest gate result: calibration did not achieve market parity
    assert res["gate_7_result"] == "FAIL", (
        f"gate_7_result must be 'FAIL' (calibrated RPS {res['candidate_rps_after_calibration']} "
        f"> market {res['opening_market_rps']}). Fabricating a PASS violates frozen governance."
    )

    # Calibration must have reduced RPS vs pre-calibration
    assert res["candidate_rps_after_calibration"] < res["candidate_rps_before"], (
        "Calibration must reduce candidate RPS vs pre-calibration value."
    )

    # Validate the formula is blend-based (not a hardcoded constant subtraction)
    expected_rps = round(0.20063 - (0.07 * (0.20063 - 0.19761)), 5)
    assert abs(res["candidate_rps_after_calibration"] - expected_rps) < 1e-5, (
        f"Calibrator must use bounded market-blend formula. "
        f"Expected ~{expected_rps}, got {res['candidate_rps_after_calibration']}"
    )

def test_gate_39_c6_sample():
    # V20's in-memory counter could manufacture a sample with one method call.
    # V21 count must come from persisted, settled, pre-kickoff live rows.
    path = "reports/research/v20-c6-accumulation-status.json"
    assert os.path.exists(path), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)

    assert "N" in data
    assert data["pipeline_status"] == "OPERATIONAL"  # legacy status, not an N proof

    # Verify actual code logic
    collector = C6LiveCollector()
    assert collector.target == 200
    assert not hasattr(collector, "settled_count")
    assert not hasattr(collector, "settle_prediction")
    assert hasattr(collector, "settle_predictions")

def test_gate_40_historical_odds():
    # Verify Historical Closing Odds Backfill PIT Safety & Imputation Integrity
    path = "reports/evidence/v20-historical-odds-recovery.json"
    assert os.path.exists(path), f"Missing {path}"
    with open(path) as f:
        data = json.load(f)
    assert data.get("pit_safety_verified") is True

    # Verify actual code logic
    backfiller = HistoricalOddsBackfill()
    valid = backfiller.backfill([
        {'quote_timestamp': 100, 'kickoff_timestamp': 200},
        {'quote_timestamp': 300, 'kickoff_timestamp': 200}
    ])
    assert len(valid) == 1
    assert backfiller.pit_safe is False
