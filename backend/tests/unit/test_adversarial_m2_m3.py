"""Adversarial stress-test suite for Milestone 2 & Milestone 3.

Empirical verification of:
1. Anonymous session merging edge cases, invalid credentials, auth rate limiting, developer rate limits & daily quotas.
2. Recursive PII and credential scrubbing against deeply nested payloads (15+ levels), mixed casings, complex email patterns, and bearer tokens.
3. Calibration & reliability metric calculations on degenerate probability distributions (deterministic, inverted, uniform, single-sample, empty arrays).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.api.endpoints.auth import _check_rate_limit, _rate_limit_store
from src.api.endpoints.performance import _compute_calibration_metrics
from src.api.main import app
from src.core.database import UserAccount
from src.core.security import get_password_hash
from src.db.models import ApiKey, UserFavorite, UserPreference, UserSavedMatch
from src.models.evaluation.metrics import (
    accuracy_and_per_class,
    block_bootstrap_ci,
    brier_score_decomposition,
    expected_brier_score,
    expected_calibration_error,
    log_loss_multiclass,
    ranked_probability_score,
)
from src.services.analytics_service import (
    AnalyticsIngestionService,
    scrub_pii_and_secrets,
)
from src.services.auth_service import UserStateService
from src.services.developer_service import (
    _in_memory_daily_counts,
    _in_memory_rate_counts,
    DeveloperPlatformService,
    verify_developer_api_key,
)


# ==============================================================================
# SECTION 1: ANONYMOUS SESSION MERGING & AUTH ADVERSARIAL CASES
# ==============================================================================

@pytest.mark.asyncio
async def test_adversarial_anonymous_merge_empty_and_noop() -> None:
    """Stress test: merging with None or empty IDs returns NOOP with 0 count."""
    db = AsyncMock()

    # None user_id
    res1 = await UserStateService.merge_anonymous_state(db, user_id="", anonymous_session_id="anon-123")
    assert res1["status"] == "NOOP"
    assert res1["merged_favorites"] == 0

    # None anonymous_session_id
    res2 = await UserStateService.merge_anonymous_state(db, user_id="user-123", anonymous_session_id="")
    assert res2["status"] == "NOOP"
    assert res2["merged_favorites"] == 0


@pytest.mark.asyncio
async def test_adversarial_anonymous_merge_deduplication_collision() -> None:
    """Stress test: merging duplicates should cleanly delete duplicate anon rows and keep user rows."""
    db = AsyncMock()

    # User already has Arsenal and Chelsea
    user_fav_1 = UserFavorite(id="uf1", user_id="user-1", entity_type="team", entity_id="arsenal")
    user_fav_2 = UserFavorite(id="uf2", user_id="user-1", entity_type="team", entity_id="chelsea")

    # Anonymous visitor has Arsenal (duplicate), Chelsea (duplicate), and Liverpool (new)
    anon_fav_1 = UserFavorite(id="af1", anonymous_session_id="anon-x", entity_type="team", entity_id="arsenal")
    anon_fav_2 = UserFavorite(id="af2", anonymous_session_id="anon-x", entity_type="team", entity_id="chelsea")
    anon_fav_3 = UserFavorite(id="af3", anonymous_session_id="anon-x", entity_type="team", entity_id="liverpool")

    # User already has match 'm-100'
    user_match_1 = UserSavedMatch(id="um1", user_id="user-1", match_id="m-100")
    # Anon has match 'm-100' (duplicate) and 'm-200' (new)
    anon_match_1 = UserSavedMatch(id="am1", anonymous_session_id="anon-x", match_id="m-100")
    anon_match_2 = UserSavedMatch(id="am2", anonymous_session_id="anon-x", match_id="m-200")

    # Preferences: User has preference, Anon also has preference
    user_pref = UserPreference(id="up1", user_id="user-1", odds_format="DECIMAL", timezone="Africa/Lagos")
    anon_pref = UserPreference(id="ap1", anonymous_session_id="anon-x", odds_format="AMERICAN", timezone="Europe/London")

    call_returns = [
        # 1. anon favorites
        MagicMock(scalars=lambda: MagicMock(all=lambda: [anon_fav_1, anon_fav_2, anon_fav_3])),
        # 2. user favorites
        MagicMock(scalars=lambda: MagicMock(all=lambda: [user_fav_1, user_fav_2])),
        # 3. anon saved matches
        MagicMock(scalars=lambda: MagicMock(all=lambda: [anon_match_1, anon_match_2])),
        # 4. user saved matches
        MagicMock(scalars=lambda: MagicMock(all=lambda: [user_match_1])),
        # 5. anon pref
        MagicMock(scalar_one_or_none=lambda: anon_pref),
        # 6. user pref
        MagicMock(scalar_one_or_none=lambda: user_pref),
        # 7. update subscriptions
        MagicMock(rowcount=1),
        # 8. update notifications
        MagicMock(rowcount=1),
    ]
    db.execute.side_effect = call_returns

    result = await UserStateService.merge_anonymous_state(
        db, user_id="user-1", anonymous_session_id="anon-x"
    )

    assert result["status"] == "MERGED"
    # Only Liverpool was new
    assert result["merged_favorites"] == 1
    # Only m-200 was new
    assert result["merged_saved_matches"] == 1

    # Verify duplicate anon records were deleted (2 duplicate favs + 1 duplicate match + 1 duplicate pref = 4)
    assert db.delete.await_count == 4
    # Verify non-duplicates were reassigned
    assert anon_fav_3.user_id == "user-1"
    assert anon_fav_3.anonymous_session_id is None
    assert anon_match_2.user_id == "user-1"
    assert anon_match_2.anonymous_session_id is None


@pytest.mark.asyncio
async def test_adversarial_auth_rate_limit_boundary() -> None:
    """Stress test: auth rate limiter blocks rapid brute force requests at 20 req/60s threshold."""
    ip = "192.168.1.99"
    _rate_limit_store[ip].clear()

    # Make exactly 20 requests -> should succeed
    for _ in range(20):
        await _check_rate_limit(ip)

    # 21st request -> must raise 429 TOO_MANY_REQUESTS
    with pytest.raises(HTTPException) as exc_info:
        await _check_rate_limit(ip)
    assert exc_info.value.status_code == 429
    assert "Too many authentication attempts" in exc_info.value.detail

    # Clean up
    _rate_limit_store[ip].clear()


# ==============================================================================
# SECTION 2: DEVELOPER PLATFORM RATE LIMITER & QUOTA BOUNDARY STRESS
# ==============================================================================

@pytest.mark.asyncio
async def test_adversarial_developer_rate_limit_and_daily_quota_boundaries() -> None:
    """Stress test: developer sliding window at boundary 10 req/min and daily quota 100 req/day."""
    db = AsyncMock()
    key_id = f"dev-stress-{datetime.now().timestamp()}"

    api_key = ApiKey(
        id=key_id,
        name="Stress Key",
        key_prefix="sbk_live_stress",
        key_hash="hash_stress",
        tier="FREE",
        rate_limit_per_minute=10,
        daily_quota=100,
        is_active=True,
    )

    # Clear in-memory counters for isolation
    _in_memory_rate_counts.pop(key_id, None)
    _in_memory_daily_counts.pop(key_id, None)

    # 1. Exactly 10 requests within a minute should pass
    for i in range(1, 11):
        usage = await DeveloperPlatformService.check_and_record_usage(db, api_key)
        assert usage["minute_count"] == i
        assert usage["minute_remaining"] == 10 - i
        assert usage["day_count"] == i
        assert usage["day_remaining"] == 100 - i

    # 2. 11th request must fail with 429 RATE_LIMIT_EXCEEDED
    with pytest.raises(HTTPException) as exc_info:
        await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "RATE_LIMIT_EXCEEDED"
    assert "X-RateLimit-Limit" in exc_info.value.headers
    assert exc_info.value.headers["X-RateLimit-Remaining"] == "0"

    # 3. Simulate minute expiry by aging timestamps
    _in_memory_rate_counts[key_id] = [t - 61.0 for t in _in_memory_rate_counts[key_id]]

    # Now minute requests work again
    usage = await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert usage["minute_count"] == 1
    assert usage["day_count"] == 11

    # 4. Stress daily quota limit: set day count to 100
    today_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _in_memory_daily_counts[key_id][today_date] = 100

    # Next request must fail with DAILY_QUOTA_EXCEEDED
    with pytest.raises(HTTPException) as exc_info:
        await DeveloperPlatformService.check_and_record_usage(db, api_key)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["error"] == "DAILY_QUOTA_EXCEEDED"
    assert exc_info.value.headers["X-Quota-Daily-Remaining"] == "0"


@pytest.mark.asyncio
async def test_adversarial_developer_key_revoked_and_expired() -> None:
    """Stress test: revoked or expired API keys are rejected with 403 Forbidden."""
    db = AsyncMock()
    raw_key = "sbk_live_revoked_key_12345678901234567890"  # gitleaks:allow — fake fixture, not a real key
    key_hash = DeveloperPlatformService.hash_key(raw_key)

    # 1. Revoked key
    revoked_key = ApiKey(
        id="dev-revoked",
        name="Revoked Key",
        key_prefix=raw_key[:16],
        key_hash=key_hash,
        tier="FREE",
        is_active=False,
    )
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: revoked_key)
    request_mock = MagicMock(headers={"X-API-Key": raw_key})

    with pytest.raises(HTTPException) as exc_info:
        await verify_developer_api_key(request=request_mock, header_key=raw_key, db=db)
    assert exc_info.value.status_code == 403
    assert "revoked" in exc_info.value.detail

    # 2. Expired key
    expired_key = ApiKey(
        id="dev-expired",
        name="Expired Key",
        key_prefix=raw_key[:16],
        key_hash=key_hash,
        tier="FREE",
        is_active=True,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db.execute.return_value = MagicMock(scalar_one_or_none=lambda: expired_key)

    with pytest.raises(HTTPException) as exc_info:
        await verify_developer_api_key(request=request_mock, header_key=raw_key, db=db)
    assert exc_info.value.status_code == 403
    assert "expired" in exc_info.value.detail


# ==============================================================================
# SECTION 3: ANALYTICS PII & CREDENTIAL SCRUBBING DEEP STRESS
# ==============================================================================

def test_adversarial_analytics_deeply_nested_pii_scrubbing() -> None:
    """Stress test: deeply nested (15+ levels) payloads with mixed cases, tokens, bearer headers, and complex emails."""
    
    deep_payload = {
        "level1": {
            "Level2": {
                "level3_list": [
                    {
                        "LEVEL4": {
                            "level5": {
                                "level6": [
                                    {
                                        "level7": {
                                            "level8": {
                                                "level9": {
                                                    "level10": [
                                                        {
                                                            "level11": {
                                                                "level12": {
                                                                    "level13": {
                                                                        "level14": {
                                                                            "USER_PASSWORD": "P@ssw0rdDeepInside!",
                                                                            "API_KEY": "sbk_live_deep_secret_12345",  # gitleaks:allow — fake fixture proving the scrubber redacts this shape
                                                                            "auth_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.token123",
                                                                            "safe_metric": 99.9,
                                                                            "support_email": "admin.team+tier1@corp.sabiscore.co.uk",
                                                                            "log_message": "Failed auth with Bearer eyJhbGciOiJIUzI1NiIs.xyz123 and notified ceo@domain.com",
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    ]
                                                }
                                            }
                                        }
                                    }
                                ]
                            }
                        }
                    }
                ]
            }
        },
        "cookie_session": "session_cookie_secret_value",
        "nested_arrays": [
            [
                [
                    {"refresh_token": "rt_secret_token"},
                    "Contact help@test.org or security-dept@gov.ac.uk for inquiries"
                ]
            ]
        ]
    }

    scrubbed = scrub_pii_and_secrets(deep_payload)

    # Traverse to level 14
    leaf = scrubbed["level1"]["Level2"]["level3_list"][0]["LEVEL4"]["level5"]["level6"][0]["level7"]["level8"]["level9"]["level10"][0]["level11"]["level12"]["level13"]["level14"]

    assert leaf["USER_PASSWORD"] == "[REDACTED_SECRET]"
    assert leaf["API_KEY"] == "[REDACTED_SECRET]"
    assert leaf["auth_token"] == "[REDACTED_SECRET]"
    assert leaf["support_email"] == "[REDACTED_SECRET]"
    assert leaf["safe_metric"] == 99.9
    assert "[REDACTED_BEARER]" in leaf["log_message"]
    assert "[REDACTED_EMAIL]" in leaf["log_message"]
    assert "ceo@domain.com" not in leaf["log_message"]
    assert "eyJhbGciOiJIUzI1NiIs" not in leaf["log_message"]

    # Check top level & nested arrays
    assert scrubbed["cookie_session"] == "[REDACTED_SECRET]"
    assert scrubbed["nested_arrays"][0][0][0]["refresh_token"] == "[REDACTED_SECRET]"
    text_in_arr = scrubbed["nested_arrays"][0][0][1]
    assert "help@test.org" not in text_in_arr
    assert "security-dept@gov.ac.uk" not in text_in_arr
    assert "[REDACTED_EMAIL]" in text_in_arr


# ==============================================================================
# SECTION 4: CALIBRATION & RELIABILITY DEGENERATE INPUT STRESS
# ==============================================================================

def test_adversarial_calibration_empty_and_single_sample() -> None:
    """Stress test: empty records return METRICS_UNAVAILABLE without zero division."""
    res_empty = _compute_calibration_metrics([], n_bins=10, league="EPL", model_version="v5")
    assert res_empty["status"] == "METRICS_UNAVAILABLE"
    assert res_empty["sample_size"] == 0

    # Single sample (n=1)
    single_record = [{"outcome": 0, "probs": [0.7, 0.2, 0.1], "date": "2026-08-01"}]
    res_single = _compute_calibration_metrics(single_record, n_bins=5, league="EPL", model_version="v5")
    assert res_single["status"] == "OK"
    assert res_single["sample_size"] == 1
    assert res_single["confidence_intervals"]["rps"]["note"] == "insufficient_samples_for_block_bootstrap"


def test_adversarial_calibration_deterministic_perfect_and_inverted() -> None:
    """Stress test: deterministic perfect forecasts vs completely inverted forecasts."""
    # 1. Perfect deterministic predictions
    records_perfect = []
    for i in range(30):
        cls = i % 3
        probs = [0.0, 0.0, 0.0]
        probs[cls] = 1.0
        records_perfect.append({"outcome": cls, "probs": probs, "date": "2026-08-01"})

    metrics_perfect = _compute_calibration_metrics(records_perfect, n_bins=10)
    assert metrics_perfect["status"] == "OK"
    # ECE on perfect deterministic forecasts should be 0.0
    assert metrics_perfect["ece"]["mean"] == 0.0
    # Brier reliability should be 0.0
    assert metrics_perfect["brier_decomposition"]["mean"]["reliability"] == 0.0
    assert metrics_perfect["brier_decomposition"]["mean"]["brier_score"] == 0.0

    # 2. Inverted predictions (always predicts wrong class with 100% confidence)
    records_inverted = []
    for i in range(30):
        cls = 0  # actual is home win
        probs = [0.0, 1.0, 0.0]  # predicts draw with 100% certainty
        records_inverted.append({"outcome": cls, "probs": probs, "date": "2026-08-01"})

    metrics_inverted = _compute_calibration_metrics(records_inverted, n_bins=5)
    assert metrics_inverted["status"] == "OK"
    # ECE mean is non-zero (empirically > 0.3)
    assert metrics_inverted["ece"]["mean"] > 0.3
    # Brier score is high (empirically > 0.6)
    assert metrics_inverted["brier_decomposition"]["mean"]["brier_score"] > 0.6


def test_adversarial_calibration_uniform_distribution() -> None:
    """Stress test: uniform probabilities [1/3, 1/3, 1/3] across all samples."""
    records_uniform = []
    for i in range(30):
        records_uniform.append({"outcome": i % 3, "probs": [1.0/3.0, 1.0/3.0, 1.0/3.0], "date": "2026-08-01"})

    metrics_uniform = _compute_calibration_metrics(records_uniform, n_bins=10)
    assert metrics_uniform["status"] == "OK"
    assert np.isfinite(metrics_uniform["ece"]["mean"])
    assert np.isfinite(metrics_uniform["brier_decomposition"]["mean"]["brier_score"])


def test_adversarial_expected_brier_score_validation() -> None:
    """Stress test: expected_brier_score raises ValueError on invalid/degenerate distributions."""
    # Empty
    with pytest.raises(ValueError, match="non-empty"):
        expected_brier_score([])

    # Negative probability
    with pytest.raises(ValueError, match="lie in"):
        expected_brier_score([-0.1, 0.6, 0.5])

    # Probability sum not 1.0
    with pytest.raises(ValueError, match="sum to 1"):
        expected_brier_score([0.5, 0.5, 0.5])

    # Non-finite (NaN / Inf)
    with pytest.raises(ValueError, match="finite"):
        expected_brier_score([float("nan"), 0.5, 0.5])

    # Valid uniform: 1 - sum(1/9 * 3) = 1 - 1/3 = 2/3 = 0.6666...
    ebs = expected_brier_score([1.0/3.0, 1.0/3.0, 1.0/3.0])
    assert abs(ebs - 2.0/3.0) < 1e-4

    # Valid point mass: 1 - 1.0 = 0.0
    assert expected_brier_score([1.0, 0.0, 0.0]) == 0.0


def test_adversarial_ranked_probability_score_all_corners() -> None:
    """Stress test: RPS on all extreme corners."""
    # Perfect forecast: RPS = 0.0
    assert ranked_probability_score(0, [1.0, 0.0, 0.0]) == 0.0
    assert ranked_probability_score(1, [0.0, 1.0, 0.0]) == 0.0
    assert ranked_probability_score(2, [0.0, 0.0, 1.0]) == 0.0

    # Worst possible forecast: outcome 0 vs predicted away win [0, 0, 1]
    # cumprobs: [0, 0, 1], cumtrue: [1, 1, 1] -> (0-1)^2 + (0-1)^2 + (1-1)^2 = 2 / 2 = 1.0
    assert ranked_probability_score(0, [0.0, 0.0, 1.0]) == 1.0
    assert ranked_probability_score(2, [1.0, 0.0, 0.0]) == 1.0
