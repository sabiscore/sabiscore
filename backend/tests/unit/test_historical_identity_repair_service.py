"""Safety regression tests for the historical semantic/Elo repair planner."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.services.historical_identity_repair_service import (
    ReplayMatchEvidence,
    _day_boundary,
    _sequence_hash,
)


def test_day_boundary_rewinds_to_start_of_earliest_affected_day() -> None:
    value = datetime(2019, 8, 10, 15, 37, 42, 1234)
    assert _day_boundary(value) == datetime(2019, 8, 10, 0, 0)


def test_replay_match_sequence_hash_is_order_sensitive_and_deterministic() -> None:
    first = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="west-ham",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    second = ReplayMatchEvidence(
        match_id="m-2",
        league="EPL",
        match_date="2019-08-11T15:00:00",
        home_team_id="united",
        away_team_id="chelsea",
        home_score=4,
        away_score=0,
    )
    assert _sequence_hash((first, second)) == _sequence_hash((first, second))
    assert _sequence_hash((first, second)) != _sequence_hash((second, first))


def test_sequence_hash_changes_when_corrected_identity_changes() -> None:
    good = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="west-ham",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    contaminated = ReplayMatchEvidence(
        match_id="m-1",
        league="EPL",
        match_date="2019-08-10T15:00:00",
        home_team_id="hamburg",
        away_team_id="city",
        home_score=0,
        away_score=5,
    )
    assert _sequence_hash((good,)) != _sequence_hash((contaminated,))


def test_apply_cli_requires_literal_confirmation() -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _CONFIRMATION

    assert _CONFIRMATION == "APPLY_SEMANTIC_IDENTITY_AND_REBUILD_ELO"


@pytest.mark.parametrize(
    "value",
    ["", "abc", "g" * 64, "0" * 63, "0" * 65],
)
def test_apply_cli_rejects_invalid_hashes(value: str) -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _validate_sha256

    with pytest.raises(ValueError):
        _validate_sha256(value, field="--manifest-sha256")


def test_apply_cli_accepts_sha256_case_insensitively() -> None:
    from scripts.repair_semantic_identity_and_rebuild_elo import _validate_sha256

    assert _validate_sha256("A" * 64, field="--plan-sha256") == "a" * 64
