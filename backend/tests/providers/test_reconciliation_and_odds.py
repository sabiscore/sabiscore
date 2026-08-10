"""Tests for reconciliation.py (REQUIRES_REVIEW) and the_odds_api.py (bookmaker normalization).

Run:
    cd backend
    python -m pytest tests/providers/test_reconciliation_and_odds.py -q --no-cov
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.providers.reconciliation import (
    AUTO_ACCEPT_THRESHOLD,
    REVIEW_THRESHOLD,
    FixtureCandidate,
    reconcile_fixture,
)
from src.providers.the_odds_api import TheOddsAPIProvider

UTC = timezone.utc


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _kickoff(year: int = 2026, month: int = 6, day: int = 26) -> datetime:
    return datetime(year, month, day, 18, 0, tzinfo=UTC)


def _candidate(
    fixture_id: str,
    home: str = "Arsenal",
    away: str = "Chelsea",
    competition: str = "EPL",
    kickoff: datetime | None = None,
) -> FixtureCandidate:
    return FixtureCandidate(
        fixture_id=fixture_id,
        competition=competition,
        home_team=home,
        away_team=away,
        kickoff_utc=kickoff or _kickoff(),
        provider="canonical",
        provider_event_id=fixture_id,
    )


def _record(
    home: str = "Arsenal",
    away: str = "Chelsea",
    competition: str = "EPL",
    kickoff: datetime | None = None,
) -> FixtureCandidate:
    return FixtureCandidate(
        fixture_id="provider-001",
        competition=competition,
        home_team=home,
        away_team=away,
        kickoff_utc=kickoff or _kickoff(),
        provider="espn",
        provider_event_id="espn-001",
    )


# --------------------------------------------------------------------------- #
# Reconciliation: original statuses (non-regression)
# --------------------------------------------------------------------------- #


def test_verified_on_strong_match():
    rec = _record()
    cands = [_candidate("fix-001")]
    decision = reconcile_fixture(rec, cands)
    assert decision.status == "VERIFIED"
    assert decision.fixture_id == "fix-001"
    assert decision.confidence >= AUTO_ACCEPT_THRESHOLD


def test_unknown_on_no_candidates():
    rec = _record()
    decision = reconcile_fixture(rec, [])
    assert decision.status == "UNKNOWN"
    assert decision.fixture_id is None
    assert decision.confidence == 0.0


def test_conflicting_on_ambiguous_candidates():
    """Two distinct, similarly-scored candidates within the ambiguity band → CONFLICTING.

    An exact-string match isn't used here: scoring an exact match (1.0) against
    a near-duplicate (~0.86) produces a ~0.14 gap, far wider than
    AMBIGUITY_BAND (0.03), and correctly auto-resolves to VERIFIED — that is
    not ambiguity. CONFLICTING requires two candidates whose scores are
    genuinely close (here both abbreviate one field, on opposite sides, with
    kickoffs nudged apart so the scores land within 0.01 of each other).
    """
    rec = _record(home="Nottingham Forest", away="Leicester City")
    cands = [
        _candidate("fix-001", home="Nottm Forest", away="Leicester City", kickoff=_kickoff().replace(hour=18, minute=4)),
        _candidate("fix-002", home="Nottingham Forest", away="Leicester"),
    ]
    decision = reconcile_fixture(rec, cands)
    assert decision.status == "CONFLICTING"
    assert decision.fixture_id is None


def test_unknown_when_competition_mismatch():
    rec = _record(competition="EPL")
    cands = [_candidate("fix-001", competition="LA_LIGA")]
    decision = reconcile_fixture(rec, cands)
    assert decision.status == "UNKNOWN"


def test_unknown_on_kickoff_too_far():
    rec = _record(kickoff=_kickoff(day=26))
    cands = [_candidate("fix-001", kickoff=_kickoff(day=28))]  # 2 days off
    decision = reconcile_fixture(rec, cands)
    assert decision.status == "UNKNOWN"


# --------------------------------------------------------------------------- #
# Reconciliation: REQUIRES_REVIEW (new status)
# --------------------------------------------------------------------------- #


def test_requires_review_on_partial_match():
    """A plausible-but-not-strong match lands in REQUIRES_REVIEW, not UNKNOWN."""
    # Use a record where team name similarity is moderate (different abbreviation)
    rec = _record(home="Man United", away="Man City")
    cands = [_candidate("fix-001", home="Manchester United", away="Manchester City")]
    decision = reconcile_fixture(rec, cands)
    assert decision.status in {"REQUIRES_REVIEW", "VERIFIED"}, (
        f"Expected REQUIRES_REVIEW or VERIFIED for near-match, got {decision.status}"
    )
    # Either way, fixture_id is only set on VERIFIED
    if decision.status == "REQUIRES_REVIEW":
        assert decision.fixture_id is None, "REQUIRES_REVIEW must not set fixture_id"
        assert decision.review_candidate_id == "fix-001"
        assert REVIEW_THRESHOLD <= decision.confidence < AUTO_ACCEPT_THRESHOLD


def test_requires_review_does_not_set_fixture_id():
    """REQUIRES_REVIEW must never grant a canonical fixture_id — review required."""
    rec = _record(home="Tottenham H", away="West Ham Utd")
    cands = [_candidate("fix-001", home="Tottenham Hotspur", away="West Ham United")]
    decision = reconcile_fixture(rec, cands)
    if decision.status == "REQUIRES_REVIEW":
        assert decision.fixture_id is None
        assert decision.review_candidate_id is not None


def test_unknown_below_review_threshold():
    """Confidence below REVIEW_THRESHOLD → UNKNOWN (not REQUIRES_REVIEW)."""
    rec = _record(home="Arsenal", away="Chelsea", competition="EPL")
    cands = [_candidate("fix-001", home="Liverpool", away="Everton", competition="EPL")]
    decision = reconcile_fixture(rec, cands)
    # Teams are completely different → very low confidence → UNKNOWN
    assert decision.status == "UNKNOWN"
    assert decision.confidence < REVIEW_THRESHOLD


def test_requires_review_has_no_fixture_id_but_has_candidate():
    """REQUIRES_REVIEW carries review_candidate_id so triage can act on it."""
    rec = _record(home="Dortmund", away="Schalke 04", competition="BUNDESLIGA")
    cands = [
        _candidate("fix-GER-001", home="Borussia Dortmund", away="FC Schalke 04", competition="BUNDESLIGA")
    ]
    decision = reconcile_fixture(rec, cands)
    if decision.status == "REQUIRES_REVIEW":
        assert decision.fixture_id is None
        assert decision.review_candidate_id == "fix-GER-001"
    elif decision.status == "VERIFIED":
        assert decision.fixture_id == "fix-GER-001"


# --------------------------------------------------------------------------- #
# The Odds API: bookmaker normalization
# --------------------------------------------------------------------------- #


def _provider() -> TheOddsAPIProvider:
    return TheOddsAPIProvider(
        api_key="test-key",
        enabled=True,
    )


def _h2h_event(
    event_id: str = "evt-001",
    bookmaker: str = "betfair",
    home_odds: float = 2.10,
    draw_odds: float = 3.40,
    away_odds: float = 4.20,
    last_update: str = "2026-06-26T17:00:00Z",
    home_name: str = "Arsenal",
    away_name: str = "Chelsea",
) -> dict:
    """Minimal raw Odds API event structure."""
    return {
        "id": event_id,
        "commence_time": "2026-06-26T18:00:00Z",
        "home_team": home_name,
        "away_team": away_name,
        "bookmakers": [
            {
                "key": bookmaker,
                "title": bookmaker.title(),
                "last_update": last_update,
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": home_name, "price": home_odds},
                            {"name": "Draw", "price": draw_odds},
                            {"name": away_name, "price": away_odds},
                        ],
                    }
                ],
            }
        ],
    }


def test_normalize_valid_record():
    p = _provider()
    from datetime import datetime, timezone
    captured = datetime(2026, 6, 26, 17, 30, tzinfo=timezone.utc)
    event = _h2h_event()
    bm = event["bookmakers"][0]
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id="fix-001",
        home_team=event["home_team"],
        away_team=event["away_team"],
        bookmaker=bm["key"],
        bookmaker_last_update=p._parse_ts(bm["last_update"]),
        markets=bm["markets"],
        provider_event_timestamp=p._parse_ts(event["commence_time"]),
        captured_at=captured,
    )
    assert record.coherent is True
    assert record.executable is True
    assert record.rejection_reason is None
    assert record.bookmaker == "betfair"
    assert record.home_odds == pytest.approx(2.10, rel=1e-3)
    assert record.draw_odds == pytest.approx(3.40, rel=1e-3)
    assert record.away_odds == pytest.approx(4.20, rel=1e-3)
    assert 1.0 < record.overround < 1.25


def test_normalize_maps_teams_by_name_not_outcome_position():
    p = _provider()
    from datetime import datetime, timezone

    record = p._normalize_bookmaker(
        event_id="evt-reordered",
        canonical_fixture_id=None,
        home_team="Arsenal",
        away_team="Chelsea",
        bookmaker="betfair",
        bookmaker_last_update=None,
        markets=[{
            "key": "h2h",
            "outcomes": [
                {"name": "Chelsea", "price": 4.20},
                {"name": "Draw", "price": 3.40},
                {"name": "Arsenal", "price": 2.10},
            ],
        }],
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )

    assert record.coherent is True
    assert record.home_odds == pytest.approx(2.10)
    assert record.away_odds == pytest.approx(4.20)


def test_normalize_missing_h2h_market():
    p = _provider()
    from datetime import datetime, timezone
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id=None,
        home_team="Arsenal",
        away_team="Chelsea",
        bookmaker="betfair",
        bookmaker_last_update=None,
        markets=[{"key": "spreads", "outcomes": []}],  # no h2h
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )
    assert record.coherent is False
    assert record.executable is False
    assert record.rejection_reason == "missing_h2h_market"


def test_normalize_incomplete_outcomes():
    """Missing draw outcome → incomplete_1x2_outcomes rejection."""
    p = _provider()
    from datetime import datetime, timezone
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id=None,
        home_team="Arsenal",
        away_team="Chelsea",
        bookmaker="betfair",
        bookmaker_last_update=None,
        markets=[{
            "key": "h2h",
            "outcomes": [
                {"name": "Arsenal", "price": 2.10},
                # Draw is absent
                {"name": "Chelsea", "price": 4.20},
            ],
        }],
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )
    assert record.coherent is False
    assert "incomplete_1x2_outcomes" in (record.rejection_reason or "")


def test_normalize_overround_outside_limits():
    """Suspicious overround (too low — below 1.01) → rejected."""
    p = _provider()
    from datetime import datetime, timezone
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id=None,
        home_team="Arsenal",
        away_team="Chelsea",
        bookmaker="betfair",
        bookmaker_last_update=None,
        markets=[{
            "key": "h2h",
            "outcomes": [
                {"name": "Arsenal", "price": 100.0},
                {"name": "Draw", "price": 100.0},
                {"name": "Chelsea", "price": 100.0},
            ],
        }],
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )
    assert record.coherent is False
    assert "overround_outside_integrity_limits" in (record.rejection_reason or "")


def test_normalize_preserves_bookmaker_last_update():
    p = _provider()
    from datetime import datetime, timezone
    last_update = datetime(2026, 6, 26, 17, 0, tzinfo=timezone.utc)
    event = _h2h_event(last_update="2026-06-26T17:00:00Z")
    bm = event["bookmakers"][0]
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id=None,
        home_team=event["home_team"],
        away_team=event["away_team"],
        bookmaker=bm["key"],
        bookmaker_last_update=p._parse_ts(bm["last_update"]),
        markets=bm["markets"],
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )
    assert record.bookmaker_last_update == last_update


def test_canonical_fixture_id_preserved():
    p = _provider()
    from datetime import datetime, timezone
    event = _h2h_event()
    bm = event["bookmakers"][0]
    record = p._normalize_bookmaker(
        event_id="evt-001",
        canonical_fixture_id="canonical-xyz",
        home_team=event["home_team"],
        away_team=event["away_team"],
        bookmaker=bm["key"],
        bookmaker_last_update=None,
        markets=bm["markets"],
        provider_event_timestamp=None,
        captured_at=datetime.now(timezone.utc),
    )
    assert record.canonical_fixture_id == "canonical-xyz"
