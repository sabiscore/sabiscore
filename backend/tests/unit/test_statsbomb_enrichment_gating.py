"""End-to-end coverage for the ENABLE_STATSBOMB_ENRICHMENT-gated pressing
features in both UpcomingMatchFeatureProjector serving paths.

Complements the pure-function unit tests in test_pressing_intensity_ratio.py
by exercising the real call sites (both were previously untested: no test
ever set ``enable_statsbomb_enrichment=True``, so the branch bodies — where
the PPDA-inversion bug lived — never executed under any test run).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.config import settings
from src.core.database import Base, Match, Team
from src.data.enrichment.statsbomb_aggregator import StatsBombFeatureResult
from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector


class _StubStatsBomb:
    """Returns a fixed ppda_ratio per known team id; ppda_ratio is raw PPDA
    (lower = more pressing), matching StatsBombAggregator's real contract."""

    def __init__(self, ppda_by_team: dict[str, float]) -> None:
        self._ppda_by_team = ppda_by_team

    def get_team_features(self, team_id, league, match_date, window: int = 5):
        ppda = self._ppda_by_team.get(str(team_id), 1.0)
        return StatsBombFeatureResult(
            features={
                "ppda_ratio": ppda,
                "progressive_carry_diff": 0.0,
                "shot_quality_diff": 0.0,
                "key_passes_under_pressure_diff": 0.0,
                "set_piece_xg_diff": 0.0,
            },
            data_gaps=[],
            staleness_seconds=0,
        )


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def projector() -> UpcomingMatchFeatureProjector:
    p = UpcomingMatchFeatureProjector()
    p._use_phase8 = False
    # team-home has lower (better) PPDA than team-away => home presses harder.
    p.statsbomb = _StubStatsBomb({"team-home": 8.0, "team-away": 12.0})
    return p


async def _seed_teams(session: AsyncSession) -> None:
    session.add_all(
        [
            Team(id="team-home", name="Arsenal", active=True),
            Team(id="team-away", name="Chelsea", active=True),
        ]
    )
    await session.commit()


async def test_matchup_path_home_pressing_advantage_is_correctly_signed(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_statsbomb_enrichment", True)
    await _seed_teams(session)

    result = await projector.build_live_feature_vector_from_matchup(
        home_team="Arsenal", away_team="Chelsea", league="epl", db=session,
        match_date=datetime(2026, 8, 10, 15, 0),
    )

    # Home PPDA=8 (harder press) vs away PPDA=12 (softer press) => advantage > 1.
    value = result["features_dict"]["home_pressing_intensity"]
    assert value == pytest.approx(12.0 / 8.0)
    assert value > 1.0


async def test_db_match_id_path_home_pressing_advantage_is_correctly_signed(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enable_statsbomb_enrichment", True)
    await _seed_teams(session)
    session.add(
        Match(
            id="match-1",
            home_team_id="team-home",
            away_team_id="team-away",
            match_date=datetime(2026, 8, 10, 15, 0),
            status="scheduled",
        )
    )
    await session.commit()

    result = await projector.build_live_feature_vector(match_id="match-1", league="epl", db=session)

    value = result["features_dict"]["home_pressing_intensity"]
    assert value == pytest.approx(12.0 / 8.0)
    assert value > 1.0


async def test_enrichment_disabled_leaves_registry_default(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default (False) production behavior is unchanged by this fix.

    When disabled, the two call sites never touch home_pressing_intensity —
    whatever project_match_features() already put in features_dict (a
    registry default) passes through untouched. Assert on the final
    canonical features array rather than features_dict directly: the array
    is always built via ``features_dict.get(name, self.defaults.get(name, 0.0))``
    (see the array-assembly line in both methods), so it is the one value
    guaranteed correct regardless of whether an upstream stage happens to
    have pre-populated the dict key.
    """
    monkeypatch.setattr(settings, "enable_statsbomb_enrichment", False)
    await _seed_teams(session)

    result = await projector.build_live_feature_vector_from_matchup(
        home_team="Arsenal", away_team="Chelsea", league="epl", db=session,
        match_date=datetime(2026, 8, 10, 15, 0),
    )

    idx = projector.canonical_features.index("home_pressing_intensity")
    assert result["features"][idx] == pytest.approx(
        projector.defaults.get("home_pressing_intensity", 0.55), abs=1e-6
    )
