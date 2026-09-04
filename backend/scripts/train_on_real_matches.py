#!/usr/bin/env python3
"""Train per-league ensembles on the real football-data.co.uk corpus.

WHY THIS EXISTS
---------------
The incumbent ``*_ensemble_v5_phase7.pkl`` artifacts were trained on
``backend/data/processed/*_training.csv`` — 500 rows of ``np.random.randn()``
noise under column names (``form_0``, ``xg_7``, ``fatigue_3``) that do not even
appear in the canonical feature registry. A per-feature sensitivity sweep showed
the resulting models respond to only 4 of 68 inputs, and because the two
enrichment parquets feeding those 4 are keyed by synthetic placeholder team ids
that never join to a real fixture, every live fixture received a byte-identical
prediction.

This script retrains on the 12,765 real matches committed under
``backend/data/cache/fd_*.csv``.

TRAIN/SERVE CONSISTENCY IS THE WHOLE GAME
-----------------------------------------
A model must only be trained on features that are genuinely resolved at serving
time. Training on a feature that is a registry default in production is worse
than useless: the model learns to lean on a signal that will be constant when it
matters, which yields confident, wrong, and undifferentiated output — precisely
the failure being fixed here.

So this script computes exactly the feature set
``UpcomingMatchFeatureProjector`` resolves, using the *same* shared helpers
(``derive_last5_form_features``, ``derive_temporal_features``,
``derive_league_features``, ``derive_combination_features``) and replicating
``_get_team_stats``'s window semantics verbatim:

  * last **20** finished matches strictly before kickoff, **all venues** (the
    ``home_``/``away_`` prefix is a naming convention, not a venue filter),
  * ``form_5``  = sum(points over the newest 5) / 15.0,
  * ``goals_per_match_5`` / ``goals_conceded_per_match_5`` / ``gd_avg_5``
    = mean over the newest 5,
  * real integer ``wins_5`` / ``draws_5`` / ``losses_5`` counts.

docs/DEBT.md item 56: h2h, home-venue, and market-interaction (13 slots —
``derive_h2h_features``/``derive_home_venue_features``/
``derive_market_interaction_features``, walk-forward state on ``TeamHistory``)
and Elo (docs/DEBT.md item 48, ``compute_elo_training_columns``) are likewise
real, mirroring their own serving computations exactly. Every remaining
canonical slot is written as its registry default — identical to what serving
supplies for those — so the learners cannot attach weight to it.

NO LEAKAGE
----------
Team history is accumulated strictly forward in date order, and a match's
features are computed from the state *before* that match is appended. The
holdout is temporal (the most recent season), never random, so a model cannot
be scored on matches that preceded its own training data.

PROMOTION IS NOT AUTOMATIC
--------------------------
Artifacts are written to ``--out-dir`` (default: a ``candidate/`` subdirectory).
Promotion over the certified champion is a separate, deliberate step —
CLAUDE.md requires measurable temporal out-of-sample improvement first, and this
script prints the incumbent-vs-candidate comparison needed to make that call.

Usage:
    PYTHONPATH=. python scripts/train_on_real_matches.py [--out-dir DIR] [--holdout-season 2425]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_FEATURE_SPEC = importlib.util.spec_from_file_location(
    "sabiscore_feature_registry",
    _BACKEND_ROOT / "src" / "models" / "feature_registry.py",
)
if _FEATURE_SPEC is None or _FEATURE_SPEC.loader is None:
    raise RuntimeError("Unable to load the canonical feature registry")
_FEATURE_REGISTRY = importlib.util.module_from_spec(_FEATURE_SPEC)
_FEATURE_SPEC.loader.exec_module(_FEATURE_REGISTRY)
APEX_FEATURES_68 = _FEATURE_REGISTRY.APEX_FEATURES_68
APEX_FEATURES_71 = _FEATURE_REGISTRY.APEX_FEATURES_71
APEX_FEATURES_89 = _FEATURE_REGISTRY.APEX_FEATURES_89
APEX_MARKET_FEATURES_14 = _FEATURE_REGISTRY.APEX_MARKET_FEATURES_14
CANONICAL_FEATURES_68 = _FEATURE_REGISTRY.CANONICAL_FEATURES_68
DEFAULT_FEATURE_VALUES_68 = _FEATURE_REGISTRY.DEFAULT_FEATURE_VALUES_68
DEFAULT_FEATURE_VALUES_89 = _FEATURE_REGISTRY.DEFAULT_FEATURE_VALUES_89
derive_combination_features = _FEATURE_REGISTRY.derive_combination_features
derive_goals_gd_features = _FEATURE_REGISTRY.derive_goals_gd_features
derive_last5_form_features = _FEATURE_REGISTRY.derive_last5_form_features
derive_league_features = _FEATURE_REGISTRY.derive_league_features
derive_apex_market_features = _FEATURE_REGISTRY.derive_apex_market_features
derive_market_features = _FEATURE_REGISTRY.derive_market_features
derive_temporal_features = _FEATURE_REGISTRY.derive_temporal_features
# docs/DEBT.md item 56 / PRODUCTION_EXECUTIVE_DIRECTIVE.md §2/§5 Phase 2 — the
# h2h/venue/interaction family. Formulas live in feature_registry so training
# and serving (upcoming_match_feature_service.py) compute them identically;
# TeamHistory below owns only the walk-forward state.
H2H_WINDOW = _FEATURE_REGISTRY.H2H_WINDOW
HOME_VENUE_WINDOW = _FEATURE_REGISTRY.HOME_VENUE_WINDOW
derive_h2h_features = _FEATURE_REGISTRY.derive_h2h_features
derive_home_venue_features = _FEATURE_REGISTRY.derive_home_venue_features
derive_market_interaction_features = _FEATURE_REGISTRY.derive_market_interaction_features

# src/features/ is free of database imports at module scope (market.py and
# match_context.py guard theirs behind TYPE_CHECKING), so this is a plain import
# rather than another spec_from_file_location dance. src/models/ is NOT — its
# __init__ pulls in core.database, which is why the registry above is loaded by
# path instead.
from src.features.phase8_historical import (  # noqa: E402 - after the sys.path bootstrap
    RESOLVED_FEATURES as PHASE8_RESOLVED_FEATURES,
    UNRESOLVED_FEATURES as PHASE8_UNRESOLVED_FEATURES,
    compute_phase8_training_columns,
)
from src.models.training_manifest import (  # noqa: E402 - after the sys.path bootstrap
    build_training_manifest,
    dataset_fingerprint,
    write_training_manifest,
)
from src.features.elo_replay import (  # noqa: E402 - after the sys.path bootstrap
    compute_elo_training_columns,
    cross_verify_against_elo_engine,
)
from src.features.xg_replay import (  # noqa: E402 - after the sys.path bootstrap
    XG_TRAINING_COLUMNS,
    compute_xg_training_columns,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("retrain")

#: Single seed for every fitted estimator and sampler in this pipeline. It is
#: recorded verbatim in the reproducibility manifest, so it must be the value
#: actually used — five separate `random_state=42` literals would let the
#: manifest keep reporting 42 after someone edited one of them.
_TRAINING_SEED = 42

# football-data.co.uk division code -> canonical SabiScore league id / model slug.
_DIV_TO_LEAGUE = {
    "E0": "EPL",
    "SP1": "LA_LIGA",
    "D1": "BUNDESLIGA",
    "I1": "SERIE_A",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}
_LEAGUE_TO_SLUG = {
    "EPL": "epl",
    "LA_LIGA": "la_liga",
    "BUNDESLIGA": "bundesliga",
    "SERIE_A": "serie_a",
    "LIGUE_1": "ligue_1",
    "EREDIVISIE": "eredivisie",
}

#: Every feature-schema version this script can train -> its artifact suffix,
#: keyed exactly as `feature_registry.FEATURE_SCHEMA_VERSIONS` keys it. The
#: suffix is part of the filename because `prediction.py._wrap_artifact` infers
#: provenance from artifact shape: writing a differently-shaped model over a
#: v5_phase7 filename would make the two disagree.
_SCHEMAS: Dict[str, str] = {
    "apex_v1_68": "v5_phase7",
    "apex_v1_89": "v6_phase8",
    "apex_v2_71": "v7_xg71",
    # Same 68-column contract as apex_v1_68 (feature_registry.py:
    # FEATURE_SCHEMA_VERSIONS["apex_v3_68"] is the identical object as
    # ["apex_v1_68"]) — this key exists only so a run that now varies the 13
    # h2h/venue/interaction slots writes its own *_v8_dense68.pkl artifacts
    # rather than overwriting the checked-in apex_v1_68 baseline Phase 3
    # compares against.
    "apex_v3_68": "v8_dense68",
}
_DEFAULT_SCHEMA = "apex_v1_68"


def _schema_features(schema: str) -> List[str]:
    """The column list for a schema, read from the module attribute each call.

    Deliberately NOT a list captured in `_SCHEMAS` at import time. The
    market-block assertion in `build_dataset` exists to catch a future edit that
    swaps or reorders the Apex market block (docs/DEBT.md item 37), and
    `test_train_on_real_matches_market_block` proves it by rebinding
    `APEX_FEATURES_68` on this module. A captured list would keep pointing at
    the original object, so the guard would report clean against a corrupted
    contract — the guard testing itself rather than the schema.
    """
    if schema in ("apex_v1_68", "apex_v3_68"):
        return APEX_FEATURES_68
    if schema == "apex_v1_89":
        return APEX_FEATURES_89
    if schema == "apex_v2_71":
        return APEX_FEATURES_71
    raise ValueError(f"unknown schema {schema!r}; expected one of {sorted(_SCHEMAS)}")


def _schema_for(schema: str) -> Tuple[List[str], str]:
    """(columns, artifact suffix) for a registered schema."""
    return _schema_features(schema), _SCHEMAS[schema]


def _schema_version_for(schema: str, feature_names: Sequence[str]) -> str:
    """Validate, then return, the caller's own declared schema version.

    ⚠️ Was content-matching `feature_names` against every registered contract
    and returning the first hit — correct while every registered contract had
    a distinct column list, but apex_v3_68 registers the SAME 68-name list as
    apex_v1_68 (docs/DEBT.md item 56: two schemas can share a contract while
    differing in which slots training actually varied). Content-matching would
    therefore always resolve to whichever of the two appears first in
    `_SCHEMAS`'s insertion order, silently mislabelling every apex_v3_68
    artifact as apex_v1_68 regardless of what was actually requested — the
    exact fallback-serving-under-a-confident-wrong-label failure this
    function's own docstring already warns about, just from the opposite
    direction. The caller already knows which schema it asked for; this now
    only confirms `feature_names` actually matches that schema's registered
    contract (catching a mismatched pair) rather than re-deriving the answer
    from columns that no longer uniquely determine it.
    """
    if schema not in _SCHEMAS:
        raise ValueError(f"unknown schema {schema!r}; expected one of {sorted(_SCHEMAS)}")
    if list(feature_names) != list(_schema_features(schema)):
        raise ValueError(
            f"feature_names ({len(list(feature_names))} columns) does not match "
            f"the registered contract for schema {schema!r} -- refusing to stamp "
            "a mismatched version"
        )
    return schema


# Serving reads the newest 20 finished matches and derives its last-5 window
# from that list (upcoming_match_feature_service._get_team_stats).
_HISTORY_WINDOW = 20
_FORM_WINDOW = 5
# Both sides must have a full last-5 window, matching the branch serving takes
# when it has real history; below that serving falls into a different estimate.
_MIN_HISTORY = 5


class TeamHistory:
    """Rolling per-team result history, appended strictly in date order.

    Keyed per-league (one instance per `histories[league]` in build_dataset),
    same approximation _by_team already makes for form: serving's h2h/venue
    queries have no league boundary, but the training corpus is organized
    per-league from separate football-data.co.uk files, so a genuinely
    cross-league meeting cannot be reconstructed here. Reported, not hidden —
    see the Phase 2 evaluation report.
    """

    def __init__(self) -> None:
        self._by_team: Dict[str, Deque[Tuple[int, int]]] = defaultdict(
            lambda: deque(maxlen=_HISTORY_WINDOW)
        )
        # docs/DEBT.md item 56: h2h/venue/interaction family. Two more
        # keyed-deque accumulators over data already in this loop — no
        # separate replay module, unlike Elo/xG, which need cross-verification
        # or an external corpus.
        self._home_venue: Dict[str, Deque[Tuple[int, int]]] = defaultdict(
            lambda: deque(maxlen=HOME_VENUE_WINDOW)
        )
        # Keyed by the SORTED pair (order-independent, mirroring
        # _get_h2h_stats()'s OR-both-orientations query); each stored entry
        # keeps which side hosted THAT meeting so a read can flip perspective
        # onto whichever team is home in the CURRENT fixture.
        self._h2h: Dict[Tuple[str, str], Deque[Tuple[str, int, int]]] = defaultdict(
            lambda: deque(maxlen=H2H_WINDOW)
        )

    def stats(self, team: str, *, is_home: bool) -> Optional[Dict[str, float]]:
        """Mirror _get_team_stats(). Newest-first, exactly as the DB query orders."""
        history = self._by_team.get(team)
        if not history or len(history) < _MIN_HISTORY:
            return None

        newest_first = list(history)[::-1]
        goals_for = [gf for gf, _ in newest_first]
        goals_against = [ga for _, ga in newest_first]
        points = [3 if gf > ga else 1 if gf == ga else 0 for gf, ga in newest_first]

        prefix = "home" if is_home else "away"
        window = slice(0, _FORM_WINDOW)
        return {
            f"{prefix}_form_5": sum(points[window]) / 15.0,
            f"{prefix}_win_rate_5": sum(1 for p in points[window] if p == 3) / 5.0,
            "wins_5": float(sum(1 for p in points[window] if p == 3)),
            "draws_5": float(sum(1 for p in points[window] if p == 1)),
            "losses_5": float(sum(1 for p in points[window] if p == 0)),
            f"{prefix}_goals_per_match_5": float(np.mean(goals_for[window])),
            f"{prefix}_goals_conceded_per_match_5": float(np.mean(goals_against[window])),
            f"{prefix}_gd_avg_5": float(
                np.mean([gf - ga for gf, ga in zip(goals_for[window], goals_against[window])])
            ),
        }

    def append(self, team: str, goals_for: int, goals_against: int) -> None:
        self._by_team[team].append((goals_for, goals_against))

    def h2h(self, home: str, away: str) -> Optional[Dict[str, float]]:
        """Last H2H_WINDOW meetings between this pair, from `home`'s
        perspective as the CURRENT fixture's home side. Mirrors
        _get_h2h_stats(): newest-first, arithmetic in derive_h2h_features().
        """
        log = self._h2h.get(tuple(sorted((home, away))))
        if not log:
            return None
        newest_first = list(log)[::-1]
        perspective = [
            (hg, ag) if match_home == home else (ag, hg)
            for match_home, hg, ag in newest_first
        ]
        return derive_h2h_features(perspective)

    def venue(self, home: str) -> Optional[Dict[str, float]]:
        """Home-venue record for `home` over its last HOME_VENUE_WINDOW hosted
        matches. Mirrors _get_home_venue_stats(); arithmetic in
        derive_home_venue_features().
        """
        log = self._home_venue.get(home)
        if not log:
            return None
        return derive_home_venue_features(list(log)[::-1])

    def record_match(self, home: str, away: str, home_goals: int, away_goals: int) -> None:
        """Update the h2h/venue accumulators. Called once per match, after
        that match's row has been emitted — same leak-boundary discipline as
        `append()` above (see build_dataset's loop-bottom comment)."""
        self._home_venue[home].append((home_goals, away_goals))
        self._h2h[tuple(sorted((home, away)))].append((home, home_goals, away_goals))


def _parse_date(raw: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


# WP-A: opening 1X2 odds, one fallback tier per bookmaker,
# clean-schema name paired with its raw-schema equivalent per tier. A given
# CSV's DictReader.fieldnames only ever contains one name per pair, so the
# miss on the absent one is just a dict .get() returning None. Bet365 is
# preferred and Pinnacle is the fallback. Cross-bookmaker averages are
# excluded because they are not one coherent bookmaker snapshot. Opening
# lines only — see build_dataset's
# docstring note for why closing lines are deliberately never read.
_ODDS_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("bet365_home", "bet365_draw", "bet365_away"),
    ("B365H", "B365D", "B365A"),
    ("pinnacle_home", "pinnacle_draw", "pinnacle_away"),
    ("PSH", "PSD", "PSA"),
)


def _parse_odds_row(row: dict) -> Optional[Tuple[float, float, float]]:
    """First COMPLETE (home, draw, away) triple across the tier list, else
    None. Atomic per tier — never mixes columns from two different
    bookmakers/tiers for one row, matching the "coherent single-bookmaker
    snapshot" principle OddsMarketRecord already enforces for live odds."""
    for h_col, d_col, a_col in _ODDS_COLUMNS:
        h, d, a = row.get(h_col), row.get(d_col), row.get(a_col)
        if h in (None, "") or d in (None, "") or a in (None, ""):
            continue
        try:
            prices = (float(h), float(d), float(a))
            if not all(np.isfinite(price) and price > 1.0 for price in prices):
                continue
            return prices
        except (TypeError, ValueError):
            continue
    return None


def load_matches(cache_dir: Path) -> List[dict]:
    """Every parseable finished match, ascending by kickoff."""
    rows: List[dict] = []
    for path in sorted(cache_dir.glob("fd_*.csv")):
        parts = path.stem.split("_")
        if len(parts) < 3:
            continue
        league = _DIV_TO_LEAGUE.get(parts[1])
        if league is None:
            continue
        season = parts[2]
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                date = _parse_date(row.get("date") or row.get("Date") or "")
                home = (row.get("home_team") or row.get("HomeTeam") or "").strip()
                away = (row.get("away_team") or row.get("AwayTeam") or "").strip()
                raw_hg = row.get("home_goals") or row.get("FTHG") or ""
                raw_ag = row.get("away_goals") or row.get("FTAG") or ""
                if not (date and home and away and raw_hg != "" and raw_ag != ""):
                    continue
                try:
                    hg, ag = int(float(raw_hg)), int(float(raw_ag))
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "league": league, "season": season, "date": date,
                    "home": home, "away": away, "hg": hg, "ag": ag,
                    "odds": _parse_odds_row(row),
                })
    rows.sort(key=lambda r: r["date"])
    return rows


def build_dataset(
    matches: List[dict],
    include_phase8: bool = False,
    *,
    schema: Optional[str] = None,
    xg_sources_dir: Optional[Path] = None,
) -> Dict[str, dict]:
    """Walk forward in time, emitting one feature row per match with enough history.

    History is keyed per (league, team) and updated only AFTER the row is
    emitted, so a match never sees its own result.

    WP-A: the 14 market features are populated from each row's OPENING 1X2
    price (see _ODDS_COLUMNS) when one was parsed, else left at their
    registry default like every other unresolved feature. Opening, not
    closing: live serving fetches odds hours-to-days before kickoff and can
    never see a closing line for a future fixture, so training on closing
    prices would teach the model to lean on a systematically more-informed
    signal than serving can ever supply.

    ``include_phase8`` widens the vector from 68 to 89 by replaying the Phase 8
    rating/form engines over the same corpus (see
    ``src.features.phase8_historical``). 15 of the 21 Phase 8 columns carry real
    replayed values; the remaining 6 — market drift and match importance —
    cannot be honestly derived from this corpus and stay at their registry
    default, exactly like any other unresolved slot. The replay is a separate
    chronological pass over ``matches`` and is aligned to it by index.

    docs/DEBT.md item 48: ``elo_difference``, ``elo_home_trend_5``,
    ``elo_away_trend_5`` and ``elo_momentum_cross`` are likewise replayed for
    real via ``src.features.elo_replay.compute_elo_training_columns`` — every
    prior candidate (including the served v5_phase7 generation) trained with
    these at their constant registry default because nothing replayed Elo over
    this corpus. ``elo_league_adjusted`` stays at its default; it is
    permanently ``PHASE7_FEATURES_ALWAYS_DATA_GAP`` by ATE-review policy.

    ``schema`` selects the feature contract and defaults to whatever
    ``include_phase8`` already implied, so every existing caller
    (``compare_candidate_vs_incumbent``, ``test_uncertainty_contract``) is
    unaffected. ``apex_v2_71`` additionally replays real rolling xG from the
    Understat corpus via ``src.features.xg_replay``.

    ⚠️ Under ``apex_v2_71`` a row whose xG features are unavailable is DROPPED,
    not defaulted. Serving answers the same fixture with None
    (``project_xg_rolling_features``), so filling a default here would train the
    model on a value serving can never reproduce — the train/serve parity break
    ``promotion_evidence`` exists to catch, and APEX section 26's "treat
    defaults as observations" prohibition. The dropped count is logged, and
    Eredivisie drops out entirely: Understat publishes no Eredivisie corpus.
    """
    histories: Dict[str, TeamHistory] = defaultdict(TeamHistory)
    out: Dict[str, dict] = defaultdict(
        lambda: {"X": [], "X_incumbent": [], "y": [], "seasons": [], "dates": []}
    )
    skipped = 0
    odds_rows = 0
    total_rows = 0

    schema = schema or ("apex_v1_89" if include_phase8 else _DEFAULT_SCHEMA)
    if schema not in _SCHEMAS:
        raise ValueError(f"unknown schema {schema!r}; expected one of {sorted(_SCHEMAS)}")
    if include_phase8 and schema != "apex_v1_89":
        raise ValueError(f"include_phase8=True contradicts schema={schema!r}")
    include_phase8 = schema == "apex_v1_89"
    include_xg = schema == "apex_v2_71"

    feature_names = _schema_features(schema)
    base_defaults = DEFAULT_FEATURE_VALUES_89 if include_phase8 else DEFAULT_FEATURE_VALUES_68

    # docs/DEBT.md item 37: every candidate this script trains declares
    # feature_schema_version: apex_v1_{width} (below), so the market-block
    # slice of feature_names must actually BE the Apex block. A future edit
    # that quietly swapped in the legacy MARKET_FEATURES_14 (or reordered it)
    # would train a candidate whose metadata lies about its own schema —
    # exactly the fabrication the feature contract exists to prevent. Static,
    # one-time check; not worth paying per-row.
    _market_start = feature_names.index(APEX_MARKET_FEATURES_14[0])
    _market_slice = feature_names[_market_start:_market_start + len(APEX_MARKET_FEATURES_14)]
    assert _market_slice == list(APEX_MARKET_FEATURES_14), (
        "feature_names does not carry APEX_MARKET_FEATURES_14 contiguously "
        f"in order at index {_market_start} (got {_market_slice}) — a future "
        "edit may have swapped in the legacy market block while artifacts "
        "still declare apex_v1_* (docs/DEBT.md item 37)"
    )
    phase8_rows: List[Dict[str, float]] = []
    if include_phase8:
        replay = compute_phase8_training_columns(matches)
        phase8_rows = replay.rows
        logger.info("Phase 8 replay: %s", replay.summary())
        logger.info(
            "Phase 8 columns computed from history: %d (%s)",
            len(PHASE8_RESOLVED_FEATURES), ", ".join(PHASE8_RESOLVED_FEATURES),
        )
        logger.info(
            "Phase 8 columns left at registry default (not derivable from this corpus): %d (%s)",
            len(PHASE8_UNRESOLVED_FEATURES), ", ".join(PHASE8_UNRESOLVED_FEATURES),
        )

    elo_replay = compute_elo_training_columns(matches)
    logger.info("Elo replay: %s", elo_replay.summary())

    xg_rows: List[Dict[str, float]] = []
    dropped_no_xg = 0
    if include_xg:
        sources = xg_sources_dir or (_BACKEND_ROOT / "data" / "processed" / "v4_sources")
        xg_replay = compute_xg_training_columns(matches, sources)
        xg_rows = xg_replay.rows
        logger.info("xG replay: %s", xg_replay.summary())
        logger.info(
            "xG columns computed from the Understat corpus: %d (%s)",
            len(XG_TRAINING_COLUMNS), ", ".join(XG_TRAINING_COLUMNS),
        )

    for idx, m in enumerate(matches):
        league, hist = m["league"], histories[m["league"]]
        home_stats = hist.stats(m["home"], is_home=True)
        away_stats = hist.stats(m["away"], is_home=False)
        # docs/DEBT.md item 56: reads only, mirroring home_stats/away_stats
        # above — cheap (bounded deque lookups) and independent of whether a
        # row ends up emitted, same as those two.
        h2h_stats = hist.h2h(m["home"], m["away"])
        venue_stats = hist.venue(m["home"])

        if home_stats is not None and away_stats is not None:
            features = dict(base_defaults)

            features.update(derive_last5_form_features(
                home_stats["home_form_5"], home_stats["home_win_rate_5"], is_home=True,
                wins_5=home_stats["wins_5"], draws_5=home_stats["draws_5"],
                losses_5=home_stats["losses_5"],
            ))
            # Strict lookup on purpose: training drops an incomplete row
            # rather than imputing, so the default is never reached here.
            features.update(derive_goals_gd_features(
                lambda key, _default: home_stats[key], is_home=True,
            ))

            features.update(derive_last5_form_features(
                away_stats["away_form_5"], away_stats["away_win_rate_5"], is_home=False,
                wins_5=away_stats["wins_5"], draws_5=away_stats["draws_5"],
                losses_5=away_stats["losses_5"],
            ))
            features.update(derive_goals_gd_features(
                lambda key, _default: away_stats[key], is_home=False,
            ))

            features.update(derive_temporal_features(m["date"]))
            features.update(derive_league_features(league))
            features.update(derive_combination_features(
                home_goals_for_avg=features["home_goals_for_avg"],
                home_goals_against_avg=features["home_goals_against_avg"],
                away_goals_for_avg=features["away_goals_for_avg"],
                away_goals_against_avg=features["away_goals_against_avg"],
            ))
            # docs/DEBT.md item 56: unconditional across every schema, same as
            # the Elo replay two lines below — NOT gated behind
            # schema == "apex_v3_68" the way phase8/xg are, because h2h/venue
            # (like Elo) are real for every schema's training corpus, not a
            # property only one candidate contract carries. A cold-start
            # pair/team leaves the slot at its registry default, matching
            # exactly what _get_h2h_stats()/_get_home_venue_stats() answer
            # serving with (None -> registry default), independent of market.
            if h2h_stats:
                features.update(h2h_stats)
            if venue_stats:
                features.update(venue_stats)
            # docs/DEBT.md item 48: real, cross-verified Elo replay — see
            # compute_elo_training_columns's module docstring. Merged before
            # the incumbent_features copy below so both X and X_incumbent
            # carry it.
            features.update(elo_replay.rows[idx])

            if include_phase8:
                # Aligned to `matches` by index; an empty dict (skipped record)
                # leaves every Phase 8 slot at its registry default rather than
                # substituting an invented value.
                features.update(phase8_rows[idx])

            market_features = None
            if m.get("odds") is not None:
                try:
                    market_features = derive_apex_market_features(*m["odds"])
                except ValueError:
                    market_features = None
            total_rows += 1

            # Empty dict = no corpus observation, or a side below the rolling
            # minimum. Serving returns None for the same fixture, so the row
            # leaves the candidate matrix rather than carrying a fabricated
            # value. Expressed as a gate on the emit condition rather than a
            # `continue`, so the history update at the bottom of the loop stays
            # the single place a match is appended to it — a dropped row must
            # still advance every team's form window.
            xg_available = True
            if include_xg:
                xg_features = xg_rows[idx]
                xg_available = bool(xg_features)
                if xg_available:
                    features.update(xg_features)
                else:
                    dropped_no_xg += 1

            if market_features is not None and xg_available:
                # docs/DEBT.md item 56: mirrors the projector's interaction
                # block exactly — market_prob_home from the JUST-computed
                # apex block (not yet merged into `features`), each of the
                # other three inputs independently gated on its own
                # resolution. Merged into `features` BEFORE the incumbent
                # copy below, so X_incumbent carries these too (see the
                # inertness argument above the h2h/venue merge).
                features.update(derive_market_interaction_features(
                    market_prob_home=market_features["market_prob_home"],
                    home_form_last5_home=features.get("home_form_last5_home"),
                    home_venue_win_rate=(venue_stats or {}).get("home_venue_win_rate"),
                    h2h_dominance=(h2h_stats or {}).get("h2h_dominance"),
                ))
                incumbent_features = dict(features)
                incumbent_features.update(derive_market_features(*m["odds"]))
                features.update(market_features)
                odds_rows += 1
                label = 0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2
                out[league]["X"].append([features[name] for name in feature_names])
                out[league]["X_incumbent"].append(
                    [incumbent_features[name] for name in CANONICAL_FEATURES_68]
                )
                out[league]["y"].append(label)
                out[league]["seasons"].append(m["season"])
                out[league]["dates"].append(m["date"])
        else:
            skipped += 1

        hist.append(m["home"], m["hg"], m["ag"])
        hist.append(m["away"], m["ag"], m["hg"])
        hist.record_match(m["home"], m["away"], m["hg"], m["ag"])

    logger.info("Rows skipped for insufficient history (both sides need %d): %d", _MIN_HISTORY, skipped)
    if include_xg:
        logger.info(
            "Rows dropped for unavailable xG (no corpus observation or side below "
            "the rolling minimum): %d", dropped_no_xg,
        )
    logger.info(
        "Rows with real market odds: %d/%d (%.0f%%)",
        odds_rows, total_rows, 100.0 * odds_rows / max(total_rows, 1),
    )
    return out


# ── Metrics ────────────────────────────────────────────────────────────────────

def ranked_probability_score(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Ordered-outcome RPS over [home, draw, away]. Lower is better."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((np.cumsum(probs, axis=1) - np.cumsum(onehot, axis=1)) ** 2, axis=1) / 2.0))


def multiclass_brier(y_true: np.ndarray, probs: np.ndarray) -> float:
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def evaluate(y_true: np.ndarray, probs: np.ndarray) -> Dict[str, float]:
    probs = np.asarray(probs, dtype=np.float64)
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError(f"expected an (n, 3) probability matrix, got {probs.shape}")
    if not np.all(np.isfinite(probs)) or np.any(probs < 0.0) or np.any(probs > 1.0):
        raise ValueError("model emitted non-finite or out-of-bounds probabilities")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("model probability rows do not sum to one")
    confidence = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == y_true).astype(np.float64)
    calibration_error = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        mask = (confidence >= lower) & (confidence < lower + 0.1)
        if mask.any():
            calibration_error += float(mask.mean()) * abs(
                float(correct[mask].mean()) - float(confidence[mask].mean())
            )
    return {
        "accuracy": float((probs.argmax(axis=1) == y_true).mean()),
        "rps": ranked_probability_score(y_true, probs),
        "brier": multiclass_brier(y_true, probs),
        "log_loss": float(-np.mean(np.log(np.maximum(probs[np.arange(len(y_true)), y_true], 1e-12)))),
        "calibration_error": calibration_error,
        "n": int(len(y_true)),
    }


def _sensitivity(models: dict, X_ref: np.ndarray) -> int:
    """How many of the 68 inputs actually move the output. The incumbent scores 4."""
    def predict(x):
        return np.mean([m.predict_proba(x)[0] for m in models.values()], axis=0)

    base = predict(X_ref.reshape(1, -1))
    moved = 0
    for i in range(X_ref.shape[0]):
        probe = X_ref.copy()
        probe[i] = probe[i] + (abs(probe[i]) * 2.0 + 1.0)
        if np.abs(predict(probe.reshape(1, -1)) - base).max() > 1e-6:
            moved += 1
    return moved


def _served_sensitivity(models: dict, meta_model: Any, X_ref: np.ndarray) -> int:
    def predict(x: np.ndarray) -> np.ndarray:
        return meta_model.predict_proba(_build_meta_features(models, x))[0]

    base = predict(X_ref.reshape(1, -1))
    moved = 0
    for index in range(X_ref.shape[0]):
        probe = X_ref.copy()
        probe[index] += abs(probe[index]) * 2.0 + 1.0
        if np.abs(predict(probe.reshape(1, -1)) - base).max() > 1e-6:
            moved += 1
    return moved


def _build_meta_features(models: dict, X: np.ndarray) -> Any:
    """Reproduce SabiScoreEnsemble._create_meta_features() exactly.

    Column names and order must match what that method emits at inference —
    it iterates ``self.models.items()`` and appends
    ``{name}_prob_home`` / ``_prob_draw`` / ``_prob_away`` per model.
    """
    import pandas as pd

    frame = pd.DataFrame()
    for name, model in models.items():
        probs = model.predict_proba(X)
        frame[f"{name}_prob_home"] = probs[:, 0]
        frame[f"{name}_prob_draw"] = probs[:, 1]
        frame[f"{name}_prob_away"] = probs[:, 2]
    return frame


def _fit_meta_model(models: dict, X_train: np.ndarray, y_train: np.ndarray):
    """Stacking meta-learner over out-of-fold base predictions.

    REQUIRED, not optional: two independent loaders read these artifacts.
    `PredictionEngine._ensemble_predict_dict` averages the base learners and
    ignores this, but `SabiScoreEnsemble.predict()` — the strict startup path
    behind `/health/ready` — calls `meta_model.predict_proba()` and raises
    "Meta model is not initialized" on None, which aborts application startup.

    Meta features come from `cross_val_predict`, never from base models scoring
    their own training rows: an in-sample fit would hand the meta-learner
    near-perfect inputs it will never see again and teach it to trust whichever
    base model overfits hardest.
    """
    import pandas as pd
    from sklearn.base import clone
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import TimeSeriesSplit

    from src.core.meta_model import SoftmaxMetaModel

    if len(X_train) < 300:
        raise ValueError("at least 300 chronological rows are required for temporal stacking")
    cv = TimeSeriesSplit(n_splits=5)
    columns = [
        f"{name}_prob_{outcome}"
        for name in models
        for outcome in ("home", "draw", "away")
    ]
    oof_values = np.full((len(X_train), len(columns)), np.nan, dtype=np.float64)
    for train_index, validation_index in cv.split(X_train):
        if len(np.unique(y_train[train_index])) != 3:
            continue
        offset = 0
        for model in models.values():
            fold_model = clone(model)
            fold_model.fit(X_train[train_index], y_train[train_index])
            probabilities = fold_model.predict_proba(X_train[validation_index])
            if list(fold_model.classes_) != [0, 1, 2]:
                raise ValueError("temporal fold did not produce all three outcome classes")
            oof_values[validation_index, offset : offset + 3] = probabilities
            offset += 3

    usable = np.all(np.isfinite(oof_values), axis=1)
    if usable.sum() < 100:
        raise ValueError("insufficient expanding-window OOF rows for stacking")
    oof = pd.DataFrame(oof_values[usable], columns=columns)

    # multinomial is the default for multiclass in sklearn >= 1.5; the explicit
    # multi_class kwarg was removed in 1.8.
    fitted = LogisticRegression(max_iter=1000, random_state=_TRAINING_SEED)
    fitted.fit(oof, y_train[usable])

    # The fitted estimator is NOT what gets pickled. Production runs
    # scikit-learn 1.3.2 against artifacts built here on 1.8, and 1.3.2's
    # LogisticRegression.predict_proba reads self.multi_class — an attribute 1.8
    # no longer sets — so the unpickled estimator raises AttributeError inside
    # the strict startup check and the release fails to deploy. Carry the fitted
    # coefficients across in a type this repo owns instead.
    return SoftmaxMetaModel.from_sklearn(fitted, feature_names=list(oof.columns))


def _fit_temperature(meta_model: Any, meta_features: Any, y_calibration: np.ndarray):
    """Fit one temperature on a later, untouched chronological slice."""

    from scipy.optimize import minimize_scalar
    from src.core.meta_model import TemperatureScaledMetaModel

    raw = meta_model.predict_proba(meta_features)

    def objective(temperature: float) -> float:
        logits = np.log(np.maximum(raw, 1e-12)) / temperature
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probabilities = exp / exp.sum(axis=1, keepdims=True)
        return float(
            -np.mean(
                np.log(np.maximum(probabilities[np.arange(len(y_calibration)), y_calibration], 1e-12))
            )
        )

    result = minimize_scalar(objective, bounds=(0.25, 4.0), method="bounded")
    if not result.success or not np.isfinite(result.x):
        raise ValueError("temperature calibration failed")
    return TemperatureScaledMetaModel(meta_model, float(result.x))


# ---------------------------------------------------------------------------
# Optional Bayesian hyperparameter search
# ---------------------------------------------------------------------------

# Baseline hyperparameters. These are what ship when --tune is not passed, so
# an untuned run stays byte-identical to every prior candidate.
_BASE_PARAMS: Dict[str, Dict[str, object]] = {
    "random_forest": {"n_estimators": 300, "max_depth": 8, "min_samples_leaf": 15},
    "xgboost": {"n_estimators": 250, "max_depth": 4, "learning_rate": 0.05,
                "subsample": 0.85, "colsample_bytree": 0.85, "reg_lambda": 2.0},
    "lightgbm": {"n_estimators": 250, "max_depth": 5, "learning_rate": 0.05,
                 "subsample": 0.85, "colsample_bytree": 0.85, "reg_lambda": 2.0},
}


def _suggest(trial, learner: str) -> Dict[str, object]:
    """Search space per learner.

    CatBoost is deliberately absent: it is pinned `python_version < "3.14"` in
    requirements.txt and has no wheel for the local interpreter, so a CatBoost
    space could be written but never executed or verified here. Its parameters
    map onto the two gradient-boosted learners that ARE available —
    ``depth`` -> ``max_depth``, ``l2_leaf_reg`` -> ``reg_lambda``,
    ``iterations`` -> ``n_estimators`` — so the same axes are searched.
    """
    if learner == "random_forest":
        return {
            "n_estimators": trial.suggest_int("n_estimators", 150, 500, step=50),
            "max_depth": trial.suggest_int("max_depth", 4, 14),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 5, 40),
        }
    return {
        "n_estimators": trial.suggest_int("n_estimators", 100, 500, step=50),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "reg_lambda": trial.suggest_float("reg_lambda", 0.5, 20.0, log=True),
    }


def _instantiate(learner: str, params: Dict[str, object], *, n_jobs: int = -1):
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier

    if learner == "random_forest":
        return RandomForestClassifier(random_state=_TRAINING_SEED, n_jobs=n_jobs, **params)
    if learner == "xgboost":
        return XGBClassifier(
            objective="multi:softprob", num_class=3, random_state=_TRAINING_SEED,
            tree_method="hist", eval_metric="mlogloss", n_jobs=n_jobs, **params,
        )
    return LGBMClassifier(
        objective="multiclass", num_class=3, random_state=_TRAINING_SEED, verbose=-1,
        n_jobs=n_jobs, **params,
    )


def tune_hyperparameters(
    X_train: np.ndarray,
    y_train: np.ndarray,
    *,
    n_trials: int,
    league: str,
) -> Dict[str, Dict[str, object]]:
    """Bayesian (TPE) search over the three base learners, scored on RPS.

    Three deliberate choices:

    * **RPS, not accuracy or log-loss.** RPS is the repo's certified promotion
      metric (``model_registry.compare_models`` defaults to it, ascending), and
      it is ordinal-aware — a football forecast that puts its mass on the wrong
      side of a draw should be punished more than one that is merely unsure.
      Tuning on anything else optimises a target certification does not read.
    * **TimeSeriesSplit over the TRAINING slice only.** The calibration and
      holdout seasons are never touched, so a tuned candidate's holdout RPS
      stays an honest out-of-sample number rather than a search artifact.
    * **MedianPruner + n_jobs=1 inside trials.** Parallelism multiplies across
      trees x folds x trials, which is what exhausts memory on a laptop; the
      pruner also abandons a bad configuration after its first fold instead of
      paying for all of them.
    """
    import optuna
    from sklearn.model_selection import TimeSeriesSplit

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    splitter = TimeSeriesSplit(n_splits=3)
    tuned: Dict[str, Dict[str, object]] = {}

    # Each learner gets its own sampler seed. A single shared seed makes TPE
    # walk the identical sequence for xgboost and lightgbm — they share a search
    # space — so both converge on byte-identical hyperparameters and the stack
    # loses the diversity that is the entire reason for ensembling them.
    for offset, learner in enumerate(("random_forest", "xgboost", "lightgbm")):
        def objective(trial, _learner=learner) -> float:
            params = _suggest(trial, _learner)
            scores = []
            for fold, (tr, va) in enumerate(splitter.split(X_train)):
                model = _instantiate(_learner, params, n_jobs=1)
                model.fit(X_train[tr], y_train[tr])
                scores.append(
                    ranked_probability_score(y_train[va], model.predict_proba(X_train[va]))
                )
                trial.report(float(np.mean(scores)), fold)
                if trial.should_prune():
                    raise optuna.TrialPruned()
            return float(np.mean(scores))

        study = optuna.create_study(
            direction="minimize",                    # RPS: lower is better
            sampler=optuna.samplers.TPESampler(seed=_TRAINING_SEED + offset),
            pruner=optuna.pruners.MedianPruner(n_warmup_steps=1),
            study_name=f"{league}_{learner}",
        )
        study.optimize(objective, n_trials=n_trials, gc_after_trial=True)
        tuned[learner] = dict(study.best_params)
        logger.info(
            "    %-14s tuned rps=%.4f (%d trials, %d pruned) %s",
            learner, study.best_value, len(study.trials),
            sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED),
            study.best_params,
        )

    return tuned


def train_league(
    league: str,
    data: dict,
    holdout_season: str,
    feature_names: Optional[List[str]] = None,
    tune_trials: int = 0,
    schema: str = _DEFAULT_SCHEMA,
) -> Optional[dict]:
    # Learner construction lives in _instantiate() so the tuning path and the
    # baseline path cannot drift into two different model definitions.
    # The vector's own width decides the schema — a caller cannot mislabel an
    # 89-wide matrix as 68 (or vice versa) by passing the wrong list.
    feature_names = list(feature_names or APEX_FEATURES_68)

    X = np.asarray(data["X"], dtype=np.float32)
    if X.ndim == 2 and X.shape[1] != len(feature_names):
        raise ValueError(
            f"{league}: feature matrix is {X.shape[1]} wide but {len(feature_names)} "
            "names were supplied — refusing to train a mislabelled artifact"
        )
    y = np.asarray(data["y"], dtype=np.int64)
    seasons = np.asarray(data["seasons"])
    dates = np.asarray(data["dates"], dtype=object)

    test_mask = seasons == holdout_season
    if test_mask.sum() < 50:
        logger.warning("  %s: insufficient split (train=%d test=%d) — skipped",
                       league, int((~test_mask).sum()), int(test_mask.sum()))
        return None

    holdout_start = min(dates[test_mask])
    holdout_end = max(dates[test_mask])
    if any(date > holdout_end for date in dates[~test_mask]):
        raise ValueError(
            f"holdout season {holdout_season} is not the latest season for {league}"
        )
    pretest_mask = np.asarray([date < holdout_start for date in dates], dtype=bool)
    if pretest_mask.sum() < 200:
        logger.warning("  %s: insufficient pre-holdout rows (%d)", league, int(pretest_mask.sum()))
        return None

    pretest_seasons = list(dict.fromkeys(seasons[pretest_mask].tolist()))
    pretest_seasons.sort(key=lambda season: max(dates[seasons == season]))
    if len(pretest_seasons) < 2:
        logger.warning("  %s: no independent calibration season — skipped", league)
        return None
    calibration_season = pretest_seasons[-1]
    calibration_mask = (seasons == calibration_season) & pretest_mask
    core_mask = pretest_mask & ~calibration_mask
    if calibration_mask.sum() < 50 or core_mask.sum() < 300:
        logger.warning(
            "  %s: insufficient core/calibration split (core=%d calibration=%d) — skipped",
            league, int(core_mask.sum()), int(calibration_mask.sum()),
        )
        return None

    X_train, y_train = X[core_mask], y[core_mask]
    X_calibration, y_calibration = X[calibration_mask], y[calibration_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    # Search only over the training slice; calibration and holdout stay unseen so
    # the reported holdout RPS remains an out-of-sample number, not a search result.
    params = {name: dict(cfg) for name, cfg in _BASE_PARAMS.items()}
    tuned_params: Optional[Dict[str, Dict[str, object]]] = None
    if tune_trials > 0:
        logger.info("  %s: Bayesian search, %d trials/learner", league, tune_trials)
        tuned_params = tune_hyperparameters(
            X_train, y_train, n_trials=tune_trials, league=league
        )
        params = tuned_params

    models = {name: _instantiate(name, params[name]) for name in _BASE_PARAMS}
    meta_model = _fit_meta_model(models, X_train, y_train)
    for model in models.values():
        model.fit(X_train, y_train)
    meta_model = _fit_temperature(
        meta_model,
        _build_meta_features(models, X_calibration),
        y_calibration,
    )

    probs = np.mean([m.predict_proba(X_test) for m in models.values()], axis=0)
    metrics = evaluate(y_test, probs)
    # The stacked head is what SabiScoreEnsemble.predict() serves, so it is
    # scored here too rather than assumed equivalent to the averaged base.
    metrics["stacked"] = evaluate(
        y_test, meta_model.predict_proba(_build_meta_features(models, X_test))
    )
    metrics["hyperparameters"] = params
    metrics["hyperparameter_source"] = (
        f"optuna_tpe_rps_{tune_trials}trials" if tuned_params else "baseline_hardcoded"
    )
    metrics["train_n"] = int(len(y_train))
    metrics["calibration_n"] = int(len(y_calibration))
    metrics["evaluation_n"] = int(len(y_test))
    metrics["responsive_features"] = _served_sensitivity(models, meta_model, X_test[0].copy())

    # Always-predict-home baseline: the bar any real model must clear.
    home_rate = float((y_test == 0).mean())
    prior = np.tile(np.bincount(y_train, minlength=3) / len(y_train), (len(y_test), 1))
    metrics["baseline_accuracy_home"] = home_rate
    metrics["baseline_rps_trainprior"] = ranked_probability_score(y_test, prior)
    market_columns = [feature_names.index(name) for name in (
        "market_prob_home", "market_prob_draw", "market_prob_away"
    )]
    metrics["baseline_rps_market"] = ranked_probability_score(y_test, X_test[:, market_columns])
    metrics["calibration_season"] = calibration_season
    metrics["holdout_season"] = holdout_season
    metrics["training_window"] = {
        "start": min(dates[core_mask]).date().isoformat(),
        "end": max(dates[core_mask]).date().isoformat(),
    }
    metrics["calibration_window"] = {
        "start": min(dates[calibration_mask]).date().isoformat(),
        "end": max(dates[calibration_mask]).date().isoformat(),
    }
    metrics["evaluation_window"] = {
        "start": holdout_start.date().isoformat(),
        "end": holdout_end.date().isoformat(),
    }

    logger.info(
        "  %-12s train=%5d test=%4d | avg: acc=%.4f rps=%.4f | stacked: acc=%.4f rps=%.4f "
        "| home-only %.4f prior-rps %.4f market-rps %.4f responsive=%d/%d",
        league, metrics["train_n"], metrics["n"], metrics["accuracy"], metrics["rps"],
        metrics["stacked"]["accuracy"], metrics["stacked"]["rps"],
        metrics["baseline_accuracy_home"], metrics["baseline_rps_trainprior"],
        metrics["baseline_rps_market"],
        metrics["responsive_features"], len(feature_names),
    )

    return {
        "models": models,
        "meta_model": meta_model,
        "feature_columns": list(feature_names),
        "is_trained": True,
        "model_metadata": {
            "accuracy": metrics["stacked"]["accuracy"],
            "brier_score": metrics["stacked"]["brier"],
            "log_loss": metrics["stacked"]["log_loss"],
            "rps": metrics["stacked"]["rps"],
            "calibration_error": metrics["stacked"]["calibration_error"],
            "trained_at": datetime.now().isoformat(),
            "feature_count": len(feature_names),
            "feature_schema_version": _schema_version_for(schema, feature_names),
            # The honesty record for docs/DEBT.md item 29: a bare
            # feature_count: 89 would let a reader assume all 21 Phase 8 columns
            # carry learned signal. These two lists say which actually varied in
            # training and which were a constant registry default, so a future
            # promotion review can see it without re-deriving it.
            **(
                {
                    "phase8_features_replayed": list(PHASE8_RESOLVED_FEATURES),
                    "phase8_features_defaulted": list(PHASE8_UNRESOLVED_FEATURES),
                }
                if len(feature_names) == len(APEX_FEATURES_89)
                else {}
            ),
            "served_head": "stacked_logistic_regression",
            "validation_status": "UNVERIFIED_CANDIDATE",
            "training_samples": metrics["train_n"],
            "holdout_samples": metrics["n"],
            "holdout_season": holdout_season,
            "calibration_season": calibration_season,
            "training_window": {
                "start": min(dates[core_mask]).date().isoformat(),
                "end": max(dates[core_mask]).date().isoformat(),
            },
            "calibration_window": metrics["calibration_window"],
            "evaluation_window": metrics["evaluation_window"],
            "calibration_samples": metrics["calibration_n"],
            "market_baseline_rps": metrics["baseline_rps_market"],
            "league_prior_baseline_rps": metrics["baseline_rps_trainprior"],
            "data_source": "football-data.co.uk (real matches)",
            "responsive_features": metrics["responsive_features"],
        },
        "_metrics": metrics,
    }


def train_pooled(
    dataset: Dict[str, dict],
    holdout_season: str,
    feature_names: Optional[List[str]] = None,
    tune_trials: int = 0,
    schema: str = _DEFAULT_SCHEMA,
) -> Optional[dict]:
    """One model over every league, for leagues too small to train alone.

    Eredivisie has a single committed season (306 matches, none in the holdout),
    which is far too little to fit and impossible to validate temporally. Rather
    than leave it on the degenerate incumbent — it is the league with live
    fixtures right now — it gets a model trained on the full corpus. The league
    one-hot block is part of the feature vector, so the learners can still
    condition on competition; Eredivisie simply presents an all-zero block, which
    is exactly what it presents at serving time too.
    """
    pooled = {"X": [], "y": [], "seasons": [], "dates": []}
    for league, data in dataset.items():
        for key in pooled:
            pooled[key].extend(data[key])
    logger.info("\nPooled model over %d leagues, %d rows", len(dataset), len(pooled["y"]))
    return train_league(
        "POOLED", pooled, holdout_season,
        feature_names=feature_names, tune_trials=tune_trials, schema=schema,
    )


def _feature_contract_sha() -> Optional[str]:
    """The committed feature contract's digest, or None when it is unreadable.

    None is honest here: a fabricated hash in a reproducibility record is worse
    than an absent one.
    """
    path = _BACKEND_ROOT / "models" / "feature_contract.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("feature_contract_sha256")
    except (json.JSONDecodeError, OSError):
        return None


def _emit_reproducibility_manifest(args, feature_names, artifact_suffix, report, schema) -> None:
    """Record what produced this run (certification Stage 4/8).

    The training report says how well the run scored; this says what produced
    it — corpus fingerprint, contract hashes, seed, interpreter and library
    versions. Without it, "retrain and you get the same model" is an assertion,
    and a metric change cannot be attributed to data versus a library upgrade.
    """
    # The Understat corpus is a real training input under apex_v2_71 and is
    # invisible to cache_dir's fd_*.csv glob, so it is fingerprinted alongside
    # it. Without this the manifest would claim reproducibility while omitting
    # the source of three of the 71 columns.
    auxiliary = {}
    if any(name in feature_names for name in XG_TRAINING_COLUMNS):
        auxiliary["understat_xg_corpus"] = dataset_fingerprint(
            args.xg_sources_dir, pattern="understat_matches_*.parquet"
        )

    manifest = build_training_manifest(
        cache_dir=args.cache_dir,
        auxiliary_datasets=auxiliary,
        feature_schema_version=_schema_version_for(schema, feature_names),
        feature_names=feature_names,
        feature_contract_sha256=_feature_contract_sha(),
        holdout_season=args.holdout_season,
        seed=_TRAINING_SEED,
        tune_trials=args.tune,
        leagues=report,
        artifact_suffix=artifact_suffix,
    )
    manifest_path = write_training_manifest(
        manifest,
        args.out_dir,
        # apex_v1_68 keeps the bare historical filename; every other generation
        # gets its own, so two candidates in one out-dir no longer overwrite
        # each other's reproducibility evidence.
        artifact_suffix=None if artifact_suffix == "v5_phase7" else artifact_suffix,
    )
    logger.info(
        "Reproducibility manifest -> %s (dataset %s, reproducibility %s)",
        manifest_path.name,
        manifest["dataset"]["dataset_sha256"][:12],
        manifest["reproducibility_sha256"][:12],
    )
    if manifest["git"]["dirty"]:
        logger.warning(
            "Working tree is DIRTY — the recorded commit does not fully describe "
            "the code that produced these artifacts."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=_BACKEND_ROOT / "data" / "cache")
    ap.add_argument("--out-dir", type=Path, default=_BACKEND_ROOT / "models" / "candidate")
    ap.add_argument("--holdout-season", default="2526")
    ap.add_argument(
        "--tune", type=int, default=0, metavar="N",
        help="Run N Optuna (TPE) trials per base learner, scored on RPS over a "
             "TimeSeriesSplit of the training slice. 0 (default) keeps the "
             "baseline hyperparameters, so an untuned run is unchanged. "
             "Start around 30; trials are pruned on the median rule.",
    )
    ap.add_argument(
        "--include-phase8",
        action="store_true",
        help=(
            "Widen the vector from 68 to 89 by replaying the Phase 8 rating/form "
            "engines over the corpus. 15 of the 21 Phase 8 columns get real "
            "values; market drift and match importance (6) are not derivable "
            "from this corpus and stay at their registry default. Writes "
            "v6_phase8 artifacts, never over the v5_phase7 filenames."
        ),
    )
    ap.add_argument(
        "--schema",
        choices=sorted(_SCHEMAS),
        default=None,
        help=(
            "Feature contract to train. Defaults to apex_v1_68 (or apex_v1_89 "
            "with --include-phase8). apex_v2_71 appends the three validated "
            "rolling-xG features and DROPS every row the Understat corpus "
            "cannot answer, because serving returns a DATA_GAP for those. "
            "apex_v3_68 is the SAME 68-column contract as apex_v1_68 — h2h, "
            "home-venue, and market-interaction (13 slots) go from "
            "training-constant to training-computed; writes its own "
            "*_v8_dense68.pkl artifacts rather than overwriting apex_v1_68's."
        ),
    )
    ap.add_argument(
        "--xg-sources-dir",
        type=Path,
        default=_BACKEND_ROOT / "data" / "processed" / "v4_sources",
        help="Tracked Understat parquet corpus, read only by --schema apex_v2_71.",
    )
    args = ap.parse_args()

    import joblib

    matches = load_matches(args.cache_dir)
    logger.info("Loaded %d real matches from %s", len(matches), args.cache_dir)
    if not matches:
        logger.error("No matches parsed — nothing to train on.")
        return 1

    # docs/DEBT.md item 48: never trust the fast Elo replay at scale without
    # first proving it agrees with the real EloEngine on a real subset — a
    # from-scratch reimplementation can silently diverge from the algorithm
    # it means to replicate.
    cross_verify_against_elo_engine(matches, n_check=300)
    logger.info("Elo replay cross-verified against EloEngine on 300 matches: identical.")

    if args.include_phase8 and args.schema not in (None, "apex_v1_89"):
        logger.error(
            "--include-phase8 and --schema %s disagree; pass one or the other.",
            args.schema,
        )
        return 1
    schema = args.schema or ("apex_v1_89" if args.include_phase8 else _DEFAULT_SCHEMA)
    feature_names, artifact_suffix = _schema_for(schema)
    logger.info("Feature schema: %s (%d columns) -> *_%s.pkl",
                schema, len(feature_names), artifact_suffix)
    dataset = build_dataset(
        matches,
        include_phase8=(schema == "apex_v1_89"),
        schema=schema,
        xg_sources_dir=args.xg_sources_dir,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("\nTemporal holdout: season %s\n", args.holdout_season)
    report: Dict[str, dict] = {}
    trained: set = set()
    for league in sorted(dataset):
        bundle = train_league(
            league, dataset[league], args.holdout_season,
            feature_names=feature_names, tune_trials=args.tune, schema=schema,
        )
        if bundle is None:
            continue
        report[league] = bundle.pop("_metrics")
        trained.add(league)
        joblib.dump(
            bundle, args.out_dir / f"{_LEAGUE_TO_SLUG[league]}_ensemble_{artifact_suffix}.pkl"
        )

    # Cover whatever was too small to fit on its own.
    uncovered = sorted(set(dataset) - trained)
    if uncovered:
        pooled_bundle = train_pooled(
            dataset, args.holdout_season, feature_names=feature_names,
            tune_trials=args.tune, schema=schema,
        )
        if pooled_bundle is not None:
            report["POOLED"] = pooled_bundle.pop("_metrics")
            pooled_bundle["model_metadata"]["pooled_fallback_for"] = uncovered
            pooled_bundle["model_metadata"]["note"] = (
                "Trained on all leagues; used for competitions with too little "
                "history to fit or validate independently."
            )
            for league in uncovered:
                joblib.dump(
                    pooled_bundle,
                    args.out_dir / f"{_LEAGUE_TO_SLUG[league]}_ensemble_{artifact_suffix}.pkl",
                )
                logger.info("  %s -> pooled model (own history: %d rows, no holdout)",
                            league, len(dataset[league]["y"]))

    # apex_v1_68 keeps the historical bare name (candidate_manifest.json and
    # compare_candidate_vs_incumbent both reference it), phase8 keeps the name
    # it has always written, and any further schema is named for its suffix.
    report_name = {
        "apex_v1_68": "training_report_real.json",
        "apex_v1_89": "training_report_real_phase8.json",
    }.get(schema, f"training_report_real_{artifact_suffix}.json")
    (args.out_dir / report_name).write_text(json.dumps(report, indent=2), encoding="utf-8")

    logger.info("\nWrote artifacts for %d leagues to %s", len(trained) + len(uncovered), args.out_dir)
    _emit_reproducibility_manifest(args, feature_names, artifact_suffix, report, schema)
    logger.info("NOT promoted — compare against the incumbent before replacing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
