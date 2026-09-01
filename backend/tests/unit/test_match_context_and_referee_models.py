"""Unit tests for RefereeProfile and MatchContext models (R3 of v5 directive)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.db.models import RefereeProfile, MatchContext


class TestRefereeProfileModel:
    """Test RefereeProfile SQLAlchemy model definitions and invariants."""

    def test_instantiation_with_measured_zeros_vs_nulls(self):
        """Verify strict distinction between NULL (no observation) and 0.0 (measured zero)."""
        now = datetime.now(timezone.utc)
        # Measured zero: referee had a match with 0 cards
        ref_measured = RefereeProfile(
            name="Michael Oliver",
            avg_yellow_cards=0.0,
            avg_red_cards=0.0,
            penalties_awarded=0,
            strictness_index=0.0,
            sample_size=1,
            source="fbref",
            observed_at=now,
            created_at=now,
            updated_at=now,
        )
        assert ref_measured.avg_yellow_cards == 0.0
        assert ref_measured.avg_red_cards == 0.0
        assert ref_measured.penalties_awarded == 0

        # Unobserved: data unavailable (NULL)
        ref_unobserved = RefereeProfile(
            name="Anthony Taylor",
            avg_yellow_cards=None,
            avg_red_cards=None,
            penalties_awarded=None,
            strictness_index=None,
            sample_size=None,
            source="manual",
            observed_at=now,
            created_at=now,
            updated_at=now,
        )
        assert ref_unobserved.avg_yellow_cards is None
        assert ref_unobserved.avg_red_cards is None
        assert ref_unobserved.penalties_awarded is None

    def test_tablename_and_structure(self):
        assert RefereeProfile.__tablename__ == "referee_profiles"
        cols = {c.name for c in RefereeProfile.__table__.columns}
        expected = {
            "id", "name", "avg_yellow_cards", "avg_red_cards",
            "penalties_awarded", "strictness_index", "sample_size",
            "source", "observed_at", "created_at", "updated_at"
        }
        assert expected.issubset(cols)


class TestMatchContextModel:
    """Test MatchContext SQLAlchemy model definitions and invariants."""

    def test_instantiation_with_metrics_and_weather(self):
        now = datetime.now(timezone.utc)
        ctx = MatchContext(
            match_id="match_12345",
            weather_condition="Rainy, 14C",
            weather_source="open-meteo",
            weather_observed_at=now,
            fatigue_index_home=1.2,
            fatigue_index_away=0.8,
            ppda_home=9.4,
            ppda_away=12.1,
            psxg_home=1.85,
            psxg_away=0.92,
            source_metadata={"provider": "statsbomb_opta_blend"},
            created_at=now,
            updated_at=now,
        )
        assert ctx.match_id == "match_12345"
        assert ctx.ppda_home == 9.4
        assert ctx.psxg_home == 1.85
        assert ctx.weather_condition == "Rainy, 14C"

    def test_tablename_and_structure(self):
        assert MatchContext.__tablename__ == "match_contexts"
        cols = {c.name for c in MatchContext.__table__.columns}
        expected = {
            "id", "match_id", "weather_condition", "weather_source",
            "weather_observed_at", "fatigue_index_home", "fatigue_index_away",
            "ppda_home", "ppda_away", "psxg_home", "psxg_away",
            "source_metadata", "created_at", "updated_at"
        }
        assert expected.issubset(cols)
