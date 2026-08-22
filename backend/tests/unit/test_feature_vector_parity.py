"""Train/serve feature-vector parity (APEX directive 7.3, docs/DEBT.md item 36).

WHY THIS EXISTS
---------------
The directive asks that, given the same historical cutoff, training /
backtest / shadow / serving vectors hash identically where they represent the
same prediction event. Until this file, **nothing anywhere in the repo ran one
fixture through more than one pipeline**, so the claim was unfalsifiable.

``TeamHistory.stats()`` (scripts/train_on_real_matches.py) carries the
docstring "Mirror _get_team_stats(). Newest-first, exactly as the DB query
orders." That intent had never been verified. This module verifies it: the
same synthetic match history is fed to the training accumulator *and* seeded
as ``Match`` rows for ``UpcomingMatchFeatureProjector._get_team_stats()``, and
the two are compared value-by-value and by digest.

WHAT IS PROVEN, AND WHAT IS DELIBERATELY NOT
--------------------------------------------
PROVEN — training and serving agree on:
  * the per-side stats dict both pipelines build from raw results;
  * every canonical feature the two provably share one implementation for
    (last-5 form, goals, combination, temporal, league, legacy market),
    compared by SHA-256 over the ordered sub-vector — an actual vector hash.

NOT PROVEN, and named rather than silently skipped:
  * ``FeatureTransformer.engineer_features()`` — the *second* serving
    implementation (data/transformers.py, serving insights/engine.py). It
    recomputes temporal/league/combination with its own inline logic rather
    than calling the shared helpers, so it cannot enter this harness without
    first being unified. That is the open half of DEBT item 36.
  * backtest. ``model_registry.walk_forward_validate()`` consumes
    pre-computed ``{date, outcome, probs}`` records and has **no independent
    feature-computation step**. There is structurally nothing to compare, so
    backtest parity is N/A by construction — not merely untested. Pinned by
    ``test_backtest_has_no_independent_feature_computation_to_compare`` so
    that if a future change gives it one, this file fails and demands it.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db import models as _db_models  # noqa: F401  (registers metadata)
from src.models.feature_registry import (
    COMBINATION_FEATURES,
    LEAGUE_ONEHOT_FEATURES,
    LEAGUE_RATE_FEATURES,
    MARKET_FEATURES_14,
    TEMPORAL_FEATURES,
    derive_combination_features,
    derive_last5_form_features,
    derive_league_features,
    derive_market_features,
    derive_temporal_features,
)

# One fixed synthetic history per side. Six results each, so both pipelines
# clear their >=5 threshold and take the real (not fallback) branch — the
# fallback branches are where they legitimately differ, and are out of scope.
_HOME_RESULTS: Sequence[Tuple[int, int]] = ((2, 0), (1, 1), (3, 1), (0, 2), (2, 2), (1, 0))
_AWAY_RESULTS: Sequence[Tuple[int, int]] = ((0, 1), (2, 1), (1, 1), (1, 3), (2, 0), (0, 0))

_LEAGUE = "EPL"
_KICKOFF = datetime(2026, 8, 22, 15, 0, 0)
_ODDS = (2.10, 3.40, 3.60)

_HOME_ID = "team-home"
_AWAY_ID = "team-away"


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed(session: AsyncSession) -> None:
    """Seed both sides' history as finished Match rows.

    Oldest first, one day apart, all strictly before _KICKOFF — so the serving
    query's ``Match.match_date < match_date`` cutoff admits exactly the same
    six results per side the training accumulator was fed, in the same order
    after its ``desc()`` sort.
    """
    rows: List[Match] = []
    for side, team_id, results in (
        ("h", _HOME_ID, _HOME_RESULTS),
        ("a", _AWAY_ID, _AWAY_RESULTS),
    ):
        for i, (goals_for, goals_against) in enumerate(results):
            rows.append(
                Match(
                    id=f"{side}-{i}",
                    league_id=_LEAGUE,
                    home_team_id=team_id,
                    away_team_id=f"opp-{side}-{i}",
                    match_date=_KICKOFF - timedelta(days=len(results) - i),
                    status="finished",
                    home_score=goals_for,
                    away_score=goals_against,
                )
            )
    session.add_all(rows)
    await session.commit()


def _training_stats(results: Sequence[Tuple[int, int]], *, is_home: bool) -> Dict[str, float]:
    """Run the real training accumulator, not a reimplementation of it."""
    from scripts.train_on_real_matches import TeamHistory

    history = TeamHistory()
    team = "T"
    for goals_for, goals_against in results:
        history.append(team, goals_for, goals_against)
    stats = history.stats(team, is_home=is_home)
    assert stats is not None, "fixture assumption: enough history for the real branch"
    return stats


def _vector_sha256(features: Dict[str, float], order: Sequence[str]) -> str:
    """SHA-256 over an ordered feature sub-vector — the 7.3 vector hash.

    Rounded to 12dp before hashing: both pipelines run identical float
    arithmetic, but a numpy scalar and a plain float can differ in repr while
    being numerically equal, and a hash over reprs would report a false
    mismatch. 12dp is far tighter than any real feature's precision.
    """
    payload = json.dumps(
        [[name, round(float(features[name]), 12)] for name in order],
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _assemble(home_stats: Dict[str, float], away_stats: Dict[str, float]) -> Dict[str, float]:
    """Assemble the provably-shared canonical block from one side-pair.

    Calls the same shared registry functions both real pipelines call. This is
    the assembly step under test — if training and serving ever stop feeding
    these functions equivalent inputs, the digests diverge.
    """
    out: Dict[str, float] = {}
    out.update(derive_last5_form_features(
        home_stats["home_form_5"], home_stats["home_win_rate_5"], is_home=True,
        wins_5=home_stats["wins_5"], draws_5=home_stats["draws_5"],
        losses_5=home_stats["losses_5"],
    ))
    out.update(derive_last5_form_features(
        away_stats["away_form_5"], away_stats["away_win_rate_5"], is_home=False,
        wins_5=away_stats["wins_5"], draws_5=away_stats["draws_5"],
        losses_5=away_stats["losses_5"],
    ))
    out["home_goals_for_avg"] = float(home_stats["home_goals_per_match_5"])
    out["home_goals_against_avg"] = float(home_stats["home_goals_conceded_per_match_5"])
    out["away_goals_for_avg"] = float(away_stats["away_goals_per_match_5"])
    out["away_goals_against_avg"] = float(away_stats["away_goals_conceded_per_match_5"])
    out["home_gd_recent"] = float(home_stats["home_gd_avg_5"])
    out["away_gd_recent"] = float(away_stats["away_gd_avg_5"])
    out.update(derive_combination_features(
        home_goals_for_avg=out["home_goals_for_avg"],
        home_goals_against_avg=out["home_goals_against_avg"],
        away_goals_for_avg=out["away_goals_for_avg"],
        away_goals_against_avg=out["away_goals_against_avg"],
    ))
    out.update(derive_temporal_features(_KICKOFF))
    out.update(derive_league_features(_LEAGUE))
    out.update(derive_market_features(*_ODDS))
    return out


#: The canonical names this harness proves parity for. Every one is produced
#: by a shared registry function both pipelines call — verified by import +
#: call-site grep, and recorded per-feature as training_source/serving_source
#: in backend/models/feature_contract.json.
PARITY_SCOPE: Tuple[str, ...] = (
    "home_form_last5_home", "home_wins_last5_home",
    "home_draws_last5_home", "home_losses_last5_home",
    "away_form_last5_away", "away_wins_last5_away",
    "away_draws_last5_away", "away_losses_last5_away",
    "home_goals_for_avg", "home_goals_against_avg",
    "away_goals_for_avg", "away_goals_against_avg",
    "home_gd_recent", "away_gd_recent",
    *COMBINATION_FEATURES,
    *TEMPORAL_FEATURES,
    *LEAGUE_ONEHOT_FEATURES,
    *LEAGUE_RATE_FEATURES,
    *MARKET_FEATURES_14,
)


async def test_training_and_serving_stats_agree_on_identical_history(
    session: AsyncSession,
) -> None:
    """TeamHistory.stats()'s "Mirror _get_team_stats()" claim, actually checked.

    Both are handed the same six results per side. Every key the two dicts
    share must match exactly — this is the input half of vector parity, and
    the half that would silently drift first.
    """
    from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

    await _seed(session)
    projector = UpcomingMatchFeatureProjector()

    for team_id, results, is_home in (
        (_HOME_ID, _HOME_RESULTS, True),
        (_AWAY_ID, _AWAY_RESULTS, False),
    ):
        serving = await projector._get_team_stats(team_id, session, _KICKOFF, is_home=is_home)
        training = _training_stats(results, is_home=is_home)

        assert serving is not None
        shared = sorted(set(serving) & set(training))
        assert shared, "fixture assumption: the two dicts overlap at all"
        for key in shared:
            assert float(serving[key]) == pytest.approx(float(training[key])), (
                f"{'home' if is_home else 'away'} side diverged on {key}: "
                f"serving={serving[key]!r} training={training[key]!r}"
            )


async def test_training_and_serving_vectors_hash_identically(
    session: AsyncSession,
) -> None:
    """7.3 proper: same cutoff, same ordered sub-vector, same SHA-256.

    Not a shape check — a shape-only assertion would pass while every value
    diverged, which is exactly the failure mode DEBT item 29 records for the
    Phase 8 columns.
    """
    from src.services.upcoming_match_feature_service import UpcomingMatchFeatureProjector

    await _seed(session)
    projector = UpcomingMatchFeatureProjector()

    serving_vec = _assemble(
        await projector._get_team_stats(_HOME_ID, session, _KICKOFF, is_home=True),
        await projector._get_team_stats(_AWAY_ID, session, _KICKOFF, is_home=False),
    )
    training_vec = _assemble(
        _training_stats(_HOME_RESULTS, is_home=True),
        _training_stats(_AWAY_RESULTS, is_home=False),
    )

    serving_hash = _vector_sha256(serving_vec, PARITY_SCOPE)
    training_hash = _vector_sha256(training_vec, PARITY_SCOPE)

    assert serving_hash == training_hash, (
        "train/serve vector parity broken over PARITY_SCOPE.\n"
        + "\n".join(
            f"  {name}: serving={serving_vec[name]!r} training={training_vec[name]!r}"
            for name in PARITY_SCOPE
            if float(serving_vec[name]) != float(training_vec[name])
        )
    )


def test_a_divergence_actually_breaks_the_hash() -> None:
    """A guard nobody has watched fail is not a guard.

    Perturbing one feature by 1e-9 must change the digest — otherwise the test
    above could pass while the two pipelines genuinely diverged.
    """
    base = _assemble(
        _training_stats(_HOME_RESULTS, is_home=True),
        _training_stats(_AWAY_RESULTS, is_home=False),
    )
    perturbed = dict(base)
    perturbed["home_goals_for_avg"] = base["home_goals_for_avg"] + 1e-9

    assert _vector_sha256(base, PARITY_SCOPE) != _vector_sha256(perturbed, PARITY_SCOPE)


def test_parity_scope_matches_the_contract_s_own_attribution() -> None:
    """PARITY_SCOPE must not drift from the generated contract.

    Every name here must carry a non-UNDECLARED training_source or
    serving_source in the contract — otherwise the harness claims parity for a
    feature the contract admits it cannot attribute, and one of the two is
    wrong.
    """
    from src.models.feature_registry import build_feature_contract

    contract = build_feature_contract("phase7_68")
    by_name = {record["feature_name"]: record for record in contract["features"]}

    missing = [name for name in PARITY_SCOPE if name not in by_name]
    assert not missing, f"not in the phase7_68 contract at all: {missing}"

    unattributed = [
        name for name in PARITY_SCOPE
        if by_name[name]["training_source"] == "UNDECLARED"
        and by_name[name]["serving_source"] == "UNDECLARED"
    ]
    assert not unattributed, (
        "PARITY_SCOPE claims parity for features the contract attributes to "
        f"no pipeline at all: {unattributed}"
    )


def test_backtest_has_no_independent_feature_computation_to_compare() -> None:
    """Backtest parity is N/A by construction — recorded, not silently skipped.

    walk_forward_validate() takes {date, outcome, probs} records a caller
    already produced. It never builds a feature vector, so there is no
    backtest vector to hash against training/serving. If this ever fails,
    walk_forward_validate has grown a feature-computation step and genuinely
    needs to enter PARITY_SCOPE — see docs/DEBT.md item 36.
    """
    import inspect

    from src.models.model_registry import ModelRegistry

    source = inspect.getsource(ModelRegistry.walk_forward_validate)
    for builder in (
        "derive_last5_form_features",
        "derive_temporal_features",
        "derive_league_features",
        "derive_market_features",
        "project_match_features",
        "engineer_features",
    ):
        assert builder not in source, (
            f"walk_forward_validate now calls {builder} — it has an independent "
            "feature path and must be added to the parity harness"
        )


# -- The second serving implementation (7.2 unification) --------------------
# FeatureTransformer._project_to_canonical_features() kept its own inline
# copies of the temporal, league and combination arithmetic until it was
# unified onto the shared registry helpers. These tests are the evidence that
# the unification is behaviour-preserving, and they extend 7.3 coverage to the
# serving path insights/engine.py uses.

#: Fixed goal averages, so the combination features have non-trivial inputs
#: rather than all landing on a shared registry default.
_HOME_GOALS_FOR, _HOME_GOALS_AGAINST = 1.83, 1.12
_AWAY_GOALS_FOR, _AWAY_GOALS_AGAINST = 1.44, 1.61


def _transformer_canonical(league: str, kickoff: datetime) -> Dict[str, float]:
    """Run the real second serving implementation over a fixed input row.

    allow_legacy_defaults=True keeps the fail-closed guards out of the way so
    the arithmetic under test is what actually runs; the guards themselves are
    covered separately below.
    """
    import pandas as pd

    from src.data.transformers import FeatureTransformer

    transformer = FeatureTransformer(allow_legacy_defaults=True)
    row = pd.DataFrame([{
        "home_goals_per_match_5": _HOME_GOALS_FOR,
        "home_goals_conceded_per_match_5": _HOME_GOALS_AGAINST,
        "away_goals_per_match_5": _AWAY_GOALS_FOR,
        "away_goals_conceded_per_match_5": _AWAY_GOALS_AGAINST,
    }])
    match_data = {
        "schedule": {"date": kickoff.isoformat(), "league": league},
        "odds": {"home_win": _ODDS[0], "draw": _ODDS[1], "away_win": _ODDS[2]},
    }
    projected = transformer._project_to_canonical_features(row, match_data)
    return projected.iloc[0].to_dict()


@pytest.mark.parametrize(
    "league",
    ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "premier_league", "laliga"],
)
def test_second_serving_implementation_matches_the_shared_league_helper(
    league: str,
) -> None:
    """Every one-hot and prior must equal derive_league_features()'s answer.

    Parametrised over both vocabularies (display and alias forms) because the
    two-league-vocabulary trap has fired repeatedly in this repo, and EPL is
    spelled identically in both -- an EPL-only check proves nothing.
    """
    canonical = _transformer_canonical(league, _KICKOFF)
    expected = derive_league_features(league)

    for name, value in expected.items():
        assert float(canonical[name]) == pytest.approx(float(value)), f"{league}:{name}"


@pytest.mark.parametrize(
    "kickoff",
    [
        datetime(2026, 8, 22, 15, 0),
        datetime(2026, 1, 1, 20, 0),
        datetime(2026, 12, 31, 12, 0),
        datetime(2026, 5, 17, 9, 30),
    ],
)
def test_second_serving_implementation_matches_the_shared_temporal_helper(
    kickoff: datetime,
) -> None:
    """pandas .dayofweek and datetime.weekday() must agree, including at the
    January and December boundaries where season_phase clamps -- an off-by-one
    there would be invisible mid-season.
    """
    canonical = _transformer_canonical("EPL", kickoff)
    expected = derive_temporal_features(kickoff)

    for name, value in expected.items():
        assert float(canonical[name]) == pytest.approx(float(value)), f"{kickoff}:{name}"


def test_second_serving_implementation_matches_the_shared_combination_helper() -> None:
    """All four combination features, from real non-default goal averages."""
    canonical = _transformer_canonical("EPL", _KICKOFF)
    expected = derive_combination_features(
        home_goals_for_avg=_HOME_GOALS_FOR,
        home_goals_against_avg=_HOME_GOALS_AGAINST,
        away_goals_for_avg=_AWAY_GOALS_FOR,
        away_goals_against_avg=_AWAY_GOALS_AGAINST,
    )

    assert expected, "fixture assumption: the helper returns the four fields"
    for name, value in expected.items():
        assert float(canonical[name]) == pytest.approx(float(value)), name


def test_unifying_did_not_remove_the_unsupported_league_guard() -> None:
    """The stricter caller must still refuse a league with no measured priors.

    derive_league_features() deliberately falls back for Eredivisie/UCL so the
    projector can keep serving them. FeatureTransformer is the strict caller and
    must keep raising -- if the guard were moved into the shared helper this
    would still pass while the projector silently broke, so the guard's
    *location* is what this pins.
    """
    import pandas as pd

    from src.core.exceptions import DataUnavailableError
    from src.data.transformers import FeatureTransformer
    from src.models.feature_registry import has_league_rate_priors

    assert not has_league_rate_priors("EREDIVISIE")

    strict = FeatureTransformer(allow_legacy_defaults=False)
    with pytest.raises(DataUnavailableError):
        strict._project_to_canonical_features(
            pd.DataFrame([{}]),
            {
                "schedule": {"date": _KICKOFF.isoformat(), "league": "EREDIVISIE"},
                "odds": {"home_win": _ODDS[0], "draw": _ODDS[1], "away_win": _ODDS[2]},
            },
        )
