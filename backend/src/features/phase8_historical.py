"""Historical replay of Phase 8 features, for training-time feature construction.

WHY THIS EXISTS
---------------
Phase 8's 21 features are computed at serving time by
``UpcomingMatchFeatureProjector._inject_phase8_features``, but nothing ever
computed them for *training* data. ``retrain_with_expanded_features.py`` fills
all 21 columns with constant registry defaults, so a model trained that way
sees zero variance in those slots and cannot learn from them — while at serving
time the same slots carry real, varying values. The artifact would nonetheless
report ``feature_count: 89``: a false-confidence signal, because "89 features
present" would pass a naive check while 21 of them taught the model nothing.
That is ``docs/DEBT.md`` item 29, and this module is its fix.

WHAT IS REPLAYED (15 of 21)
---------------------------
Pi-ratings (6) and Berrar ratings (3) are stateful, Elo-shaped systems: a
match's feature row is the *pre-match* rating snapshot, and that match's result
then advances the rating for every later match. EWMA form (6) is a pure
function of a team's preceding results. All three are reconstructible from
match results alone — exactly what the historical corpus holds — so all three
are replayed here by calling the *same* engine classes serving calls. Not a
reimplementation: a divergent second copy of this arithmetic is the precise
failure this module exists to prevent.

WHAT IS NOT (6 of 21), AND WHY FAKING IT WOULD BE WORSE
-------------------------------------------------------
Market drift (5) and match importance (1) are absent from every row this
module returns, so a caller merging onto ``DEFAULT_FEATURE_VALUES_89`` leaves
them at their registry default — the same treatment ``build_dataset`` already
gives every other unresolved canonical slot. They are not computed because
they genuinely cannot be, from this corpus:

  * ``compute_market_drift`` measures movement between an opening snapshot in
    ``OddsHistory`` and current odds, and gates on staleness against wall-clock
    ``now``. For a match played years ago that gate can never pass. More
    fundamentally, the corpus carries a single opening price per match, not a
    movement series — there is no drift in the data to measure, so any value
    would be invented.
  * ``compute_match_context`` reads ``LeagueStanding``, which has no season and
    no as-of-date column: it is a current-snapshot table. "What were the
    standings before this 2019 fixture" is not a question it can answer, and
    using *today's* standings for a historical match is leakage, not a feature.

Both need their own durable point-in-time store — the shape
``elo_rating_snapshots`` gave Elo — which is separate, larger work. Until then
they stay constant *and declared* (see ``UNRESOLVED_FEATURES``), so a caller
can see 15/21 resolved instead of believing 21/21.

CHRONOLOGY AND ALIGNMENT
------------------------
``PiRatingSystem`` and ``BerrarRatingSystem`` both document that callers must
feed matches in ascending date order, and neither validates it; feeding them
out of order silently introduces look-ahead bias. This module therefore sorts
internally rather than trusting its input, but writes each result back to its
*original* index, so ``result.rows[i]`` always corresponds to ``matches[i]``
whatever order the caller supplied.

ONE BAD RECORD MUST NOT WEDGE THE BATCH
---------------------------------------
Mirrors the lesson ``elo_state_service.apply_finished_match_to_elo`` learned
the hard way (``docs/DEBT.md`` items 23/24): a malformed or self-play record is
skipped, counted, and the loop continues. It never raises, and it never
poisons the rows around it.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Mapping, Sequence, Tuple

from .berrar_ratings import BerrarRatingSystem
from .form import weighted_form_features
from .pi_ratings import PiRatingSystem

logger = logging.getLogger(__name__)

# Serving reads the newest 10 finished matches for EWMA form
# (UpcomingMatchFeatureProjector._get_team_results_sequence, n=10), all venues,
# oldest->newest. Diverging from that window would be a train/serve mismatch.
_FORM_WINDOW = 10

PI_FEATURES: Tuple[str, ...] = (
    "home_pi_attack",
    "home_pi_defense",
    "away_pi_attack",
    "away_pi_defense",
    "pi_attack_diff",
    "pi_defense_diff",
)

BERRAR_FEATURES: Tuple[str, ...] = (
    "home_berrar_rating",
    "away_berrar_rating",
    "berrar_rating_diff",
)

FORM_FEATURES: Tuple[str, ...] = (
    "home_weighted_win_rate",
    "home_weighted_draw_rate",
    "home_weighted_ppg",
    "away_weighted_win_rate",
    "away_weighted_draw_rate",
    "away_weighted_ppg",
)

#: The 15 Phase 8 columns this module genuinely computes from history.
RESOLVED_FEATURES: Tuple[str, ...] = PI_FEATURES + BERRAR_FEATURES + FORM_FEATURES

#: The 6 Phase 8 columns that cannot be honestly derived from the historical
#: corpus (see the module docstring). Never emitted; callers leave them at their
#: registry default. ``test_phase8_historical.py`` asserts that
#: ``RESOLVED_FEATURES | UNRESOLVED_FEATURES`` is exactly ``PHASE8_FEATURES_21``,
#: so adding a Phase 8 feature without classifying it here fails the suite
#: rather than silently shipping an unlisted column.
UNRESOLVED_FEATURES: Tuple[str, ...] = (
    "odds_drift_home",
    "odds_drift_draw",
    "odds_drift_away",
    "max_abs_odds_drift",
    "sharp_money_direction",
    "match_importance_score",
)


@dataclass(frozen=True)
class Phase8ReplayResult:
    """Per-match Phase 8 columns plus the counters needed to audit the run.

    ``rows`` is always the same length as the input and aligned to it by index.
    A skipped match yields an empty dict, so a caller merging it onto the
    registry defaults leaves every Phase 8 slot at its default rather than
    receiving a fabricated value.
    """

    rows: List[Dict[str, float]] = field(default_factory=list)
    matches_seen: int = 0
    skipped_self_play: int = 0
    skipped_malformed: int = 0

    @property
    def rows_resolved(self) -> int:
        """Rows carrying real replayed values (i.e. not skipped)."""
        return sum(1 for row in self.rows if row)

    def summary(self) -> str:
        return (
            f"phase8 replay: {self.rows_resolved}/{self.matches_seen} rows resolved "
            f"({len(RESOLVED_FEATURES)} of {len(RESOLVED_FEATURES) + len(UNRESOLVED_FEATURES)} "
            f"columns computable), skipped_self_play={self.skipped_self_play}, "
            f"skipped_malformed={self.skipped_malformed}"
        )


def _result_code(goals_for: int, goals_against: int) -> int:
    """1=win, 0=draw, -1=loss — identical to _get_team_results_sequence."""
    if goals_for > goals_against:
        return 1
    return 0 if goals_for == goals_against else -1


def _coerce_match(match: Mapping[str, Any]) -> Tuple[str, datetime, str, str, int, int]:
    """Pull the fields the replay needs, raising if any is unusable.

    Raises rather than returning a sentinel so the caller's per-record handler
    counts it as malformed and moves on.
    """
    league = str(match["league"])
    date = match["date"]
    if not isinstance(date, datetime):
        raise TypeError(f"match date must be a datetime, got {type(date).__name__}")
    home = str(match["home"]).strip()
    away = str(match["away"]).strip()
    if not home or not away:
        raise ValueError("home and away team names must both be non-empty")
    home_goals = int(match["hg"])
    away_goals = int(match["ag"])
    if home_goals < 0 or away_goals < 0:
        raise ValueError("goal counts cannot be negative")
    return league, date, home, away, home_goals, away_goals


def compute_phase8_training_columns(
    matches: Sequence[Mapping[str, Any]],
) -> Phase8ReplayResult:
    """Replay Pi-ratings, Berrar ratings and EWMA form over historical matches.

    Args:
        matches: Match records shaped as ``train_on_real_matches.load_matches``
            emits them — ``league``, ``date`` (datetime), ``home``, ``away``,
            ``hg``, ``ag``. Extra keys are ignored. Order does not matter; the
            replay sorts chronologically and realigns to the input order.

    Returns:
        A :class:`Phase8ReplayResult` whose ``rows[i]`` holds the 15 resolvable
        Phase 8 columns for ``matches[i]``, or an empty dict if that record was
        skipped. The 6 unresolvable columns are never present — merge onto
        ``DEFAULT_FEATURE_VALUES_89`` to fill them.
    """
    rows: List[Dict[str, float]] = [{} for _ in matches]
    pi_engines: Dict[str, PiRatingSystem] = defaultdict(
        lambda: PiRatingSystem(parquet_path=None)
    )
    berrar_engines: Dict[str, BerrarRatingSystem] = defaultdict(
        lambda: BerrarRatingSystem(parquet_path=None)
    )
    # Per league, per team: the newest _FORM_WINDOW results, oldest->newest.
    form_history: Dict[str, Dict[str, Deque[int]]] = defaultdict(
        lambda: defaultdict(lambda: deque(maxlen=_FORM_WINDOW))
    )

    skipped_self_play = 0
    skipped_malformed = 0

    # Chronological by date, tie-broken by original position so the walk is
    # deterministic; results are written back to the original index.
    #
    # The key must never raise: this sort runs before the per-record handler
    # below, so a single unusable date here would wedge the entire batch at sort
    # time — precisely the failure mode this module exists to avoid. Unusable
    # records sort to the front and are then skipped and counted in the loop.
    def _chronological_key(index: int) -> Tuple[datetime, int]:
        record = matches[index]
        date = record.get("date") if isinstance(record, Mapping) else None
        return (date if isinstance(date, datetime) else datetime.min, index)

    order = sorted(range(len(matches)), key=_chronological_key)

    for index in order:
        try:
            record = matches[index]
            if not isinstance(record, Mapping):
                raise TypeError(f"match must be a mapping, got {type(record).__name__}")
            league, date, home, away, home_goals, away_goals = _coerce_match(record)
        except (KeyError, TypeError, ValueError) as exc:
            skipped_malformed += 1
            logger.warning("phase8 replay: skipping malformed match at index %d (%s)", index, exc)
            continue

        # A team cannot play itself. Elo hit exactly this in production (26 rows,
        # docs/DEBT.md item 23) where it wedged the entire batch; here it would
        # corrupt that team's own rating against itself.
        if home == away:
            skipped_self_play += 1
            logger.warning(
                "phase8 replay: skipping self-play match at index %d (%s vs itself)", index, home
            )
            continue

        pi = pi_engines[league]
        berrar = berrar_engines[league]
        league_form = form_history[league]

        # Pre-match snapshot: read state BEFORE this result is applied. This is
        # the no-leakage invariant — mirrors build_dataset's own ordering.
        pi_context = pi.get_context(home, away)
        berrar_context = berrar.get_context(home, away)
        home_form = weighted_form_features(list(league_form[home]))
        away_form = weighted_form_features(list(league_form[away]))

        rows[index] = {
            "home_pi_attack": float(pi_context.home_pi_attack),
            "home_pi_defense": float(pi_context.home_pi_defense),
            "away_pi_attack": float(pi_context.away_pi_attack),
            "away_pi_defense": float(pi_context.away_pi_defense),
            "pi_attack_diff": float(pi_context.pi_attack_diff),
            "pi_defense_diff": float(pi_context.pi_defense_diff),
            "home_berrar_rating": float(berrar_context.home_berrar_rating),
            "away_berrar_rating": float(berrar_context.away_berrar_rating),
            "berrar_rating_diff": float(berrar_context.berrar_rating_diff),
            "home_weighted_win_rate": float(home_form["weighted_win_rate"]),
            "home_weighted_draw_rate": float(home_form["weighted_draw_rate"]),
            "home_weighted_ppg": float(home_form["weighted_ppg"]),
            "away_weighted_win_rate": float(away_form["weighted_win_rate"]),
            "away_weighted_draw_rate": float(away_form["weighted_draw_rate"]),
            "away_weighted_ppg": float(away_form["weighted_ppg"]),
        }

        # Advance state for subsequent matches. The id is a replay-local dedupe
        # key for the engines' idempotency check, deliberately prefixed so it can
        # never be mistaken for canonical fixture identity — nothing here is
        # persisted or joined to a real fixture.
        replay_id = f"replay:{league}:{date:%Y%m%d}:{home}:{away}"
        home_result = _result_code(home_goals, away_goals)
        try:
            pi.update(replay_id, home, away, home_goals, away_goals, league, date)
            berrar.update(replay_id, home, away, home_result, league, date)
        except Exception:  # noqa: BLE001 - one bad record must not wedge the batch
            skipped_malformed += 1
            logger.warning(
                "phase8 replay: rating update failed at index %d; ratings unchanged", index,
                exc_info=True,
            )

        league_form[home].append(home_result)
        league_form[away].append(_result_code(away_goals, home_goals))

    result = Phase8ReplayResult(
        rows=rows,
        matches_seen=len(matches),
        skipped_self_play=skipped_self_play,
        skipped_malformed=skipped_malformed,
    )
    logger.info("%s", result.summary())
    return result
