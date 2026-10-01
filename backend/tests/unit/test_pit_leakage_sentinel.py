"""Adversarial Negative Control & PIT Leakage Sentinel Tests.

Directive V18.0 Section 3.2 & Gate C.
Enforces:
    t_feature <= t_evaluation < t_closing < t_kickoff
Tests fail-closed halts on injected future data, shifted timestamps, and post-match features.
"""

from datetime import datetime, timezone, timedelta
import pytest

from src.evidence.temporal import (
    TemporalLineageChecker,
    LeakageSentinel,
    TemporalViolationError,
)
from src.models.feature_registry import CANONICAL_FEATURES_68


def test_canonical_68_features_contain_no_future_substrings():
    """Verify standard APEX 68 features have zero post-match or retrospective columns."""
    contaminated = LeakageSentinel.scan_feature_schema(CANONICAL_FEATURES_68)
    assert not contaminated, f"Found contaminated feature columns in production schema: {contaminated}"


def test_adversarial_injection_of_future_column_fails_closed():
    """Negative control: injecting future-only column raises TemporalViolationError."""
    malicious_schema = list(CANONICAL_FEATURES_68) + ["post_match_xg_ratio", "final_score_home"]
    
    with pytest.raises(TemporalViolationError, match="Contaminated future features detected"):
        LeakageSentinel.assert_no_leakage(malicious_schema, [])


def test_adversarial_timestamp_leakage_fails_closed():
    """Negative control: feature effective after information cutoff raises TemporalViolationError."""
    checker = TemporalLineageChecker()
    
    kickoff = "2026-10-05T15:00:00Z"
    cutoff = "2026-10-05T13:00:00Z"
    leaked_effective_at = "2026-10-05T13:30:00Z"  # 30 mins after cutoff!
    
    result = checker.verify_feature_timing(
        feature_name="market_prob_home",
        source_effective_at=leaked_effective_at,
        information_cutoff=cutoff,
        kickoff_timestamp=kickoff,
    )
    
    assert not result.is_valid
    assert "Leakage detected" in (result.violation_reason or "")
    
    with pytest.raises(TemporalViolationError, match="PIT boundary violation"):
        LeakageSentinel.assert_no_leakage(["market_prob_home"], [result])


def test_adversarial_cutoff_post_kickoff_fails_closed():
    """Negative control: evaluation cutoff at or after kickoff fails closed."""
    checker = TemporalLineageChecker()
    
    kickoff = "2026-10-05T15:00:00Z"
    invalid_cutoff = "2026-10-05T15:05:00Z"
    effective_at = "2026-10-05T14:00:00Z"
    
    result = checker.verify_feature_timing(
        feature_name="home_form_last5_home",
        source_effective_at=effective_at,
        information_cutoff=invalid_cutoff,
        kickoff_timestamp=kickoff,
    )
    
    assert not result.is_valid
    assert "Cutoff invalid" in (result.violation_reason or "")


def test_valid_point_in_time_passes():
    """Positive control: strictly pre-cutoff observations pass validation."""
    checker = TemporalLineageChecker()
    
    kickoff = "2026-10-05T15:00:00Z"
    cutoff = "2026-10-05T13:00:00Z"
    effective_at = "2026-10-05T12:00:00Z"
    
    result = checker.verify_feature_timing(
        feature_name="home_form_last5_home",
        source_effective_at=effective_at,
        information_cutoff=cutoff,
        kickoff_timestamp=kickoff,
    )
    
    assert result.is_valid
    assert result.violation_reason is None
    # Ensure no exception is raised
    LeakageSentinel.assert_no_leakage(["home_form_last5_home"], [result])
