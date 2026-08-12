"""WP-2 regression tests:

1. _get_team_stats / _get_team_results_sequence must not have a wall-clock
   lookback floor — a team's last completed match older than the old 60/120-day
   window must still resolve (the close-season bug).
2. project_match_features()'s data_gaps must be provenance-based (caller-owned
   feature families excluded, never inferred from the numeric value) rather
   than the old `value in (None, 0.0)` heuristic, which was both a false
   positive (a genuine 0.0) and a false negative (a non-zero default silently
   never flagged).

WP-10.1 regression tests (bottom of file): ScrapedTeamFormStore fallback wiring.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match, Team
from src.models.feature_registry import (
    MARKET_FEATURES_14,
    PHASE7_FEATURES_7,
    PHASE7_FEATURES_ALWAYS_DATA_GAP,
)
from src.services.scraped_feature_store import ScrapedTeamFormStore
from src.services.upcoming_match_feature_service import (
    _CALLER_RESOLVED_FEATURES,
    UpcomingMatchFeatureProjector,
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
    return p


MATCH_DATE = datetime(2026, 8, 10, 15, 0)


async def _seed_old_match(session: AsyncSession, days_before: int) -> None:
    session.add_all(
        [
            Team(id="team-home", name="Home FC", active=True),
            Team(id="team-away", name="Away FC", active=True),
            Team(id="team-opp", name="Opponent FC", active=True),
        ]
    )
    await session.commit()
    old_date = MATCH_DATE - timedelta(days=days_before)
    session.add(
        Match(
            id="old-match",
            home_team_id="team-home",
            away_team_id="team-opp",
            match_date=old_date,
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.commit()


async def test_get_team_stats_finds_match_older_than_60_days(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=90)
    stats = await projector._get_team_stats("team-home", session, MATCH_DATE)
    assert stats is not None


async def test_get_team_stats_none_with_no_history(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=90)
    stats = await projector._get_team_stats("team-away", session, MATCH_DATE)
    assert stats is None


async def test_get_team_stats_is_home_controls_key_prefix(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """WP-18/D8b regression: _get_team_stats() must prefix its output keys by
    the is_home argument, not hardcode "home_" regardless of side — the exact
    collision that would silently let one team's stats overwrite the other's
    the moment any remap read these keys (which project_match_features()
    now does)."""
    await _seed_old_match(session, days_before=1)
    home_shaped = await projector._get_team_stats("team-home", session, MATCH_DATE, is_home=True)
    away_shaped = await projector._get_team_stats("team-home", session, MATCH_DATE, is_home=False)
    assert "home_form_5" in home_shaped and "away_form_5" not in home_shaped
    assert "away_form_5" in away_shaped and "home_form_5" not in away_shaped
    # Same team, same underlying history — only the key prefix differs.
    assert away_shaped["away_form_5"] == home_shaped["home_form_5"]


async def test_get_team_results_sequence_finds_match_older_than_120_days(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=150)
    results = await projector._get_team_results_sequence("team-home", session, MATCH_DATE)
    assert results == [1]  # 2-1 win


async def test_get_team_results_sequence_empty_with_no_history(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=150)
    results = await projector._get_team_results_sequence("team-away", session, MATCH_DATE)
    assert results == []


# ---------------------------------------------------------------------------
# _get_h2h_stats / _get_home_venue_stats: value-asserting coverage.
#
# Previously only covered indirectly via a ratio-count assertion in
# test_feature_defaulted_ratio_reflects_resolved_canonical_fields (which
# proves *something* resolved, not that the computed numbers are correct).
# ---------------------------------------------------------------------------


async def test_get_h2h_stats_returns_none_with_no_shared_history(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """_seed_old_match's only match is team-home vs team-opp — team-home and
    team-away have never played each other directly, so h2h must be None,
    not an empty/zeroed dict."""
    await _seed_old_match(session, days_before=1)
    stats = await projector._get_h2h_stats("team-home", "team-away", session, MATCH_DATE)
    assert stats is None


async def test_get_h2h_stats_returns_computed_values_for_seeded_meeting(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=1)  # creates team-home/team-away/team-opp
    session.add(
        Match(
            id="h2h-match",
            home_team_id="team-home",
            away_team_id="team-away",
            match_date=MATCH_DATE - timedelta(days=2),
            status="finished",
            home_score=2,
            away_score=1,
        )
    )
    await session.commit()
    stats = await projector._get_h2h_stats("team-home", "team-away", session, MATCH_DATE)
    assert stats == {
        "h2h_home_wins": 1.0,
        "h2h_away_wins": 0.0,
        "h2h_draws": 0.0,
        "h2h_matches": 1.0,
        "h2h_dominance": 1.0,
    }


async def test_get_home_venue_stats_returns_computed_rates(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """_seed_old_match already gives team-home exactly one home match (a 2-1
    win) before MATCH_DATE — reuse it rather than seeding bespoke data."""
    await _seed_old_match(session, days_before=1)
    stats = await projector._get_home_venue_stats("team-home", session, MATCH_DATE)
    assert stats == {
        "home_venue_win_rate": 1.0,
        "home_venue_draw_rate": 0.0,
        "home_venue_loss_rate": 0.0,
        "home_advantage_strength": 1.0,
    }


# ---------------------------------------------------------------------------
# data_gaps: provenance-based, not value-based
# ---------------------------------------------------------------------------


def test_caller_resolved_features_excludes_always_gap_feature() -> None:
    assert "shot_quality_diff" not in _CALLER_RESOLVED_FEATURES
    for feature in PHASE7_FEATURES_7:
        if feature not in PHASE7_FEATURES_ALWAYS_DATA_GAP:
            assert feature in _CALLER_RESOLVED_FEATURES


async def test_orphan_base_feature_always_flagged_as_gap(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """WP-18/WP-10.3: home_form_last5_home is now resolved once real DB
    history exists and the canonical remap runs — home (team-home, a real
    2-1 win) is rescued; away (team-away, zero match history and no scraped
    fallback available in this test) remains a genuine gap."""
    await _seed_old_match(session, days_before=1)
    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    assert "home_form_last5_home" not in result["data_gaps"]
    assert "away_form_last5_away" in result["data_gaps"]


async def test_project_match_features_home_and_away_form_dont_collide(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """WP-18/D8b regression: home and away canonical last5 fields must reflect
    each side's OWN history, not whichever side's stats merged last. Before
    the fix, _get_team_stats() always wrote "home_"-prefixed keys regardless
    of side, and the away-side dict.update() at the merge step would have
    silently clobbered home's numbers under those identical keys the moment
    a remap ever read them."""
    session.add_all([
        Team(id="team-winner", name="Winner FC", active=True),
        Team(id="team-loser", name="Loser FC", active=True),
        Team(id="team-foe1", name="Foe1 FC", active=True),
        Team(id="team-foe2", name="Foe2 FC", active=True),
    ])
    await session.commit()
    old_date = MATCH_DATE - timedelta(days=1)
    session.add_all([
        Match(
            id="home-win", home_team_id="team-winner", away_team_id="team-foe1",
            match_date=old_date, status="finished", home_score=3, away_score=0,
        ),
        Match(
            id="away-loss", home_team_id="team-foe2", away_team_id="team-loser",
            match_date=old_date, status="finished", home_score=3, away_score=0,
        ),
    ])
    await session.commit()

    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Winner FC", "away_team": "Loser FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    fd = result["features_dict"]
    assert fd["home_wins_last5_home"] == pytest.approx(1.0)  # Winner FC won its only match
    assert fd["away_wins_last5_away"] == pytest.approx(0.0)  # Loser FC lost its only match
    assert fd["home_form_last5_home"] != fd["away_form_last5_away"]


async def test_feature_defaulted_ratio_reflects_resolved_canonical_fields(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, tmp_path
) -> None:
    """WP-18: feature_defaulted_ratio is the before/after measurement
    docs/DEBT.md item 1 calls for — it must drop as real team history
    resolves canonical fields, not stay constant regardless of data (the
    pre-fix behaviour, since home_stats/away_stats keys never intersected a
    canonical feature name at all until this work package)."""
    projector.scraped_form_store = ScrapedTeamFormStore(tmp_path)  # empty dir — no fallback noise

    no_data_result = await projector.project_match_features(
        {"id": "m1", "home_team": "Nobody FC", "away_team": "Nowhere FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    baseline_ratio = no_data_result["data_quality"]["feature_defaulted_ratio"]

    await _seed_old_match(session, days_before=1)
    home_only_result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    home_only_ratio = home_only_result["data_quality"]["feature_defaulted_ratio"]

    n_canonical = len(projector.canonical_features)
    # _seed_old_match seeds "Home FC" as home vs "Opponent FC" (not "Away FC"),
    # so home_stats + venue_stats resolve for "Home FC":
    #   7 = len(_HOME_REMAP_FEATURES)
    #   4 = len(_VENUE_FEATURES)  — home-only venue record for "Home FC"
    # H2H and away-side stats are still None (no Away FC match seeded).
    expected_home_only = baseline_ratio - (11 / n_canonical)
    assert home_only_ratio == pytest.approx(expected_home_only)
    assert home_only_ratio < baseline_ratio


async def test_caller_resolved_features_never_locally_flagged(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """elo/statsbomb features are resolved by the CALLER one layer up
    (build_live_feature_vector) — project_match_features() must defer to it,
    never flag them itself (the old heuristic always flagged elo_difference
    since its default is exactly 0.0, regardless of the real elo overlay that
    happens right after this function returns)."""
    await _seed_old_match(session, days_before=1)
    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    for feature in PHASE7_FEATURES_7:
        if feature in result["data_gaps"] and feature not in PHASE7_FEATURES_ALWAYS_DATA_GAP:
            pytest.fail(f"{feature} is caller-resolved and must not be locally flagged")


async def test_shot_quality_diff_always_flagged(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=1)
    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    assert "shot_quality_diff" in result["data_gaps"]


# ---------------------------------------------------------------------------
# WP-A: market-odds features — honest gapping, same precedent as Elo/StatsBomb
# ---------------------------------------------------------------------------


async def test_market_features_rescued_from_gaps_when_odds_available(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    projector.odds_service.get_match_odds = AsyncMock(
        return_value={"home_win": 2.0, "draw": 3.0, "away_win": 4.0, "source": "odds_api"}
    )
    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    for feature in MARKET_FEATURES_14:
        assert feature not in result["data_gaps"], feature
    assert result["features_dict"]["market_prob_home"] == pytest.approx(6 / 13)


async def test_market_features_remain_gap_when_odds_unavailable(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    projector.odds_service.get_match_odds = AsyncMock(
        return_value={"source": "unavailable", "reason": "coherent_1x2_market_snapshot_not_found"}
    )
    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )
    for feature in MARKET_FEATURES_14:
        assert feature in result["data_gaps"], feature


# ---------------------------------------------------------------------------
# EWMA form: an empty results sequence must not silently pass as fresh data
# ---------------------------------------------------------------------------


async def test_ewma_form_flags_gap_when_team_has_no_history(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """weighted_form_features([]) returns neutral priors without raising — a team
    with zero completed matches must still be flagged as a gap, not silently
    marked freshness=0/source=match_history as if genuinely computed."""
    projector._use_phase8 = True  # only this block matters; pi/berrar/market/context
    # engines are independently gap-tracked and may legitimately fail in this
    # dependency-light test — that's expected and not what's under test here.
    features_dict: dict = {}
    phase8_gaps, freshness, sources = await projector._inject_phase8_features(
        features_dict=features_dict,
        home_team_id="team-does-not-exist-home",
        away_team_id="team-does-not-exist-away",
        home_team="Nowhere FC",
        away_team="Nobody FC",
        league="EPL",
        match_id="m1",
        db=session,
        match_date=MATCH_DATE,
    )
    for key in (
        "home_weighted_win_rate",
        "home_weighted_draw_rate",
        "home_weighted_ppg",
        "away_weighted_win_rate",
        "away_weighted_draw_rate",
        "away_weighted_ppg",
    ):
        assert key in phase8_gaps, f"{key} should be flagged — no match history exists"
        assert freshness[key] is None


async def test_ewma_form_not_flagged_when_history_exists(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    await _seed_old_match(session, days_before=1)
    projector._use_phase8 = True
    features_dict: dict = {}
    phase8_gaps, freshness, _sources = await projector._inject_phase8_features(
        features_dict=features_dict,
        home_team_id="team-home",
        away_team_id="team-opp",
        home_team="Home FC",
        away_team="Opponent FC",
        league="EPL",
        match_id="m1",
        db=session,
        match_date=MATCH_DATE,
    )
    for key in ("home_weighted_win_rate", "away_weighted_win_rate"):
        assert key not in phase8_gaps
        assert freshness[key] == 0


# ---------------------------------------------------------------------------
# WP-3.1: fail-closed schema mismatch (never zero-pad a short feature vector)
# ---------------------------------------------------------------------------


async def test_feature_array_length_mismatch_raises_schema_mismatch(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector
) -> None:
    """The length-mismatch guard in project_match_features() is unreachable via
    normal inputs — features_array is always rebuilt fresh, one scalar per
    entry of self.canonical_features, immediately before the check, so the
    lengths can never diverge through any input mutation. Patch the function's
    single np.array() call site to simulate the guard's precondition directly
    and prove it fails closed (never zero-pads) if that invariant is ever
    broken by a future edit."""
    from unittest.mock import patch

    import numpy as np

    from src.core.exceptions import SchemaMismatchError

    await _seed_old_match(session, days_before=1)

    real_array = np.array

    def _truncated_array(seq, *args, **kwargs):
        result = real_array(seq, *args, **kwargs)
        return result[:-1] if result.ndim == 1 and len(result) > 1 else result

    with patch(
        "src.services.upcoming_match_feature_service.np.array",
        side_effect=_truncated_array,
    ):
        with pytest.raises(SchemaMismatchError):
            await projector.project_match_features(
                {"id": "m1", "home_team": "Home FC", "away_team": "Opponent FC"},
                db=session,
                match_date=MATCH_DATE,
            )


def _write_scraped_form(tmp_path, *, league: str, team: str) -> None:
    payload = [{
        "source": "football-data-csv", "team": team, "matches_sampled": 5,
        "ppg": 1.8, "wins": 2, "draws": 2, "losses": 1,
        "goals_for_avg": 1.4, "goals_against_avg": 1.0,
        "goal_difference_avg": 0.4, "latest_match_date": "01/07/2026",
    }]
    (tmp_path / f"team-form-{league}-2526.json").write_text(json.dumps(payload), encoding="utf-8")


async def test_scraped_fallback_rescues_canonical_form_features(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, tmp_path
) -> None:
    """WP-18/WP-10.3: team-away has zero DB history; a scraped artifact exists
    for it. The fallback must (1) be consulted and tagged with provenance,
    (2) NOT flip is_synthetic (the zero-fab publish gate — see
    project_match_features), and (3) now DOES rescue the canonical last5-form
    + goals/gd fields from data_gaps on both sides — home from real DB
    history, away from the scraped fallback — using real wins/draws/losses
    counts in preference to the round()-based estimate wherever available."""
    await _seed_old_match(session, days_before=1)
    _write_scraped_form(tmp_path, league="EPL", team="Away FC")
    projector.scraped_form_store = ScrapedTeamFormStore(tmp_path)

    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )

    fallback = result["data_quality"]["scraped_fallback"]
    assert fallback["away"]["matches_sampled"] == 5
    assert fallback["away"]["source"].startswith("scraped:football-data-csv:")
    assert "home" not in fallback  # team-home had real DB history — never consulted

    assert result["data_quality"]["is_synthetic"] is True  # DB was still missing for "away"

    for feature in (
        "home_form_last5_home", "home_wins_last5_home", "home_draws_last5_home",
        "home_losses_last5_home", "home_goals_for_avg", "home_goals_against_avg",
        "home_gd_recent",
        "away_form_last5_away", "away_wins_last5_away", "away_draws_last5_away",
        "away_losses_last5_away", "away_goals_for_avg", "away_goals_against_avg",
        "away_gd_recent",
    ):
        assert feature not in result["data_gaps"], feature

    fd = result["features_dict"]
    # Home: 1 real match (a 2-1 win) — real counts must win over the estimate,
    # which would fabricate wins=round(1.0*5.0)=5.0 from win_rate_5=1.0 alone.
    assert fd["home_wins_last5_home"] == pytest.approx(1.0)
    assert fd["home_draws_last5_home"] == pytest.approx(0.0)
    assert fd["home_losses_last5_home"] == pytest.approx(0.0)
    assert fd["home_form_last5_home"] == pytest.approx(3.0)
    assert fd["home_goals_for_avg"] == pytest.approx(2.0)
    assert fd["home_goals_against_avg"] == pytest.approx(1.0)
    assert fd["home_gd_recent"] == pytest.approx(1.0)

    # Away: scraped fixture (matches_sampled=5, wins=2, draws=2, losses=1) —
    # real counts must win over the estimate, which would derive draws=1.0/
    # losses=2.0 from win_rate_5=0.4 alone (only wins=2.0 happens to coincide).
    assert fd["away_wins_last5_away"] == pytest.approx(2.0)
    assert fd["away_draws_last5_away"] == pytest.approx(2.0)
    assert fd["away_losses_last5_away"] == pytest.approx(1.0)
    assert fd["away_form_last5_away"] == pytest.approx(1.8)
    assert fd["away_goals_for_avg"] == pytest.approx(1.4)
    assert fd["away_goals_against_avg"] == pytest.approx(1.0)
    assert fd["away_gd_recent"] == pytest.approx(0.4)


async def test_scraped_fallback_absent_leaves_prior_behaviour_unchanged(
    session: AsyncSession, projector: UpcomingMatchFeatureProjector, tmp_path
) -> None:
    """No artifact on disk (the common case today) — scraped_fallback is empty
    and behaviour matches the pre-WP-10.1 baseline exactly."""
    await _seed_old_match(session, days_before=1)
    projector.scraped_form_store = ScrapedTeamFormStore(tmp_path)  # empty dir

    result = await projector.project_match_features(
        {"id": "m1", "home_team": "Home FC", "away_team": "Away FC", "league": "EPL"},
        session,
        MATCH_DATE,
    )

    assert result["data_quality"]["scraped_fallback"] == {}
    assert result["data_quality"]["is_synthetic"] is True
