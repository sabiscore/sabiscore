"""Deterministic Football-Data <-> Understat join and prior-only rolling xG features.

V23 Task 1. A vocabulary-safe join on the compound key

    (canonical league, kickoff date +/- 1 day, home_goals, away_goals)

narrowed to a unique match by team-name agreement on *both* sides (accent /
punctuation / common-affix normalization plus an explicit alias override table,
``services/understat/team_aliases.json``). A same-league, same-scoreline,
same-day collision is resolved by the team names; an ambiguous or unmatched
fixture yields ``None`` (fail-closed), never a guessed join.

Point-in-time contract (absolute): a fixture's own match stats never enter its
own pre-match vector. Every rolling value is the mean over a team's matches that
finished *strictly before* the fixture; fewer than ``window`` prior matches -> the
value is ``np.nan`` (never 0.0, never a league mean).

Corpus bound (recorded, not worked around -- see ``src.data.understat_corpus``):
the committed corpus covers five leagues (no Eredivisie) and omits 2021/22
entirely (two season files overlap and are de-duplicated). It carries xG
for/against and goals only -- no xA, no shot counts, no xPTS -- so the observable
rolling family is xG-for, xG-against and the xG-derived finishing efficiency
(sum goals / sum xG over the window). xA, true shot-count shot efficiency and
xPTS are NOT in the corpus and are never fabricated here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

ROLLING_WINDOW: int = 5

#: Default alias table shipped beside the Understat services.
_ALIAS_PATH: Path = (
    Path(__file__).resolve().parents[1] / "services" / "understat" / "team_aliases.json"
)

#: Prior-only rolling feature columns Candidate-U adds on top of the Tier-A baseline.
#: All are observable from the committed corpus (xG + goals). Ordered, stable.
UNDERSTAT_ROLLING_FEATURES: list[str] = [
    "home_roll_xg_for",
    "away_roll_xg_for",
    "delta_roll_xg_for",
    "home_roll_xg_against",
    "away_roll_xg_against",
    "delta_roll_xg_against",
    "home_roll_finishing_eff",
    "away_roll_finishing_eff",
    "delta_roll_finishing_eff",
]

#: Families the directive lists that the committed corpus cannot support. Recorded
#: so the evaluator can state them as explicit data gaps rather than fabricate them.
CORPUS_UNAVAILABLE_FAMILIES: tuple[str, ...] = (
    "xa",
    "shot_efficiency_shot_count_based",
    "xpts",
)

_AFFIX_RE = re.compile(
    r"\b(fc|cf|afc|sc|ac|club|cd|rcd|ssc|us|ud|calcio|balompie|de|the)\b"
)
_NONWORD_RE = re.compile(r"[^a-z0-9]+")
_WS_RE = re.compile(r"\s+")


def normalize_team_name(name: Any) -> str:
    """Fold a team name to a comparison key: ASCII, lower-case, affixes stripped.

    Diacritics are removed (NFKD -> ASCII), common club affixes dropped, and all
    non-alphanumerics collapsed to single spaces. Deterministic and side-effect free.
    """
    folded = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    folded = folded.lower()
    folded = _AFFIX_RE.sub(" ", folded)
    folded = _NONWORD_RE.sub(" ", folded)
    return _WS_RE.sub(" ", folded).strip()


def load_team_aliases(path: Optional[Path] = None) -> dict[str, str]:
    """Load the alias overrides as a normalized Understat-key -> normalized FD-value map.

    Returns an empty map if the file is absent (the join then relies on
    normalization alone). Keys/values are normalized once here so callers never
    re-normalize the table per fixture.
    """
    alias_path = Path(path) if path is not None else _ALIAS_PATH
    try:
        raw = json.loads(alias_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    table = raw.get("aliases", raw) if isinstance(raw, dict) else {}
    return {
        normalize_team_name(k): normalize_team_name(v)
        for k, v in table.items()
        if not str(k).startswith("__")
    }


def teams_match(understat_name: Any, fd_name: Any, alias_norm: Mapping[str, str]) -> bool:
    """True when an Understat name and a Football-Data name denote the same club.

    Match if the normalized forms are equal, or if the alias table maps the
    normalized Understat name onto the normalized FD name.
    """
    nu = normalize_team_name(understat_name)
    nf = normalize_team_name(fd_name)
    if nu == nf:
        return True
    return alias_norm.get(nu) == nf


def _canonical_league(sabi_league: Any) -> str:
    """Understat filename slug (e.g. ``la_liga``) -> canonical SabiScore league id."""
    return str(sabi_league).upper()


def compute_prior_rolling(
    corpus: pd.DataFrame, window: int = ROLLING_WINDOW
) -> dict[int, dict[str, float]]:
    """Per-match prior-only rolling xG features, keyed by Understat ``game_id``.

    For every match, the home side's values describe the home team's form over its
    ``window`` matches finishing strictly before this one, and likewise for the away
    side. ``shift(1)`` excludes the current match (PIT); ``min_periods=window``
    yields ``NaN`` below the required history. Finishing efficiency is the window
    sum of goals over the window sum of xG (stable; ``NaN`` when the xG sum is
    non-positive).

    Args:
        corpus: Output of ``src.data.understat_corpus.load_corpus_matches`` -- one
            row per distinct played match, ascending by ``date``.
        window: Rolling window (default 5).

    Returns:
        ``{game_id: {feature_name: value}}`` over ``UNDERSTAT_ROLLING_FEATURES``;
        every value is a Python ``float`` or ``float('nan')``.
    """
    required = ("game_id", "date", "home_team", "away_team", "home_xg", "away_xg", "home_goals", "away_goals")
    missing = [c for c in required if c not in corpus.columns]
    if missing:
        raise ValueError(f"Understat corpus is missing columns required for rolling: {missing}")

    # One row per (team, match), from that team's own perspective.
    home = pd.DataFrame(
        {
            "game_id": corpus["game_id"].to_numpy(),
            "date": pd.to_datetime(corpus["date"]).dt.tz_localize(None).to_numpy(),
            "team": corpus["home_team"].astype("string").to_numpy(),
            "side": "home",
            "xg_for": pd.to_numeric(corpus["home_xg"], errors="coerce").to_numpy(),
            "xg_against": pd.to_numeric(corpus["away_xg"], errors="coerce").to_numpy(),
            "goals_for": pd.to_numeric(corpus["home_goals"], errors="coerce").to_numpy(),
        }
    )
    away = pd.DataFrame(
        {
            "game_id": corpus["game_id"].to_numpy(),
            "date": pd.to_datetime(corpus["date"]).dt.tz_localize(None).to_numpy(),
            "team": corpus["away_team"].astype("string").to_numpy(),
            "side": "away",
            "xg_for": pd.to_numeric(corpus["away_xg"], errors="coerce").to_numpy(),
            "xg_against": pd.to_numeric(corpus["home_xg"], errors="coerce").to_numpy(),
            "goals_for": pd.to_numeric(corpus["away_goals"], errors="coerce").to_numpy(),
        }
    )
    long = pd.concat([home, away], ignore_index=True)
    # Stable chronological order within each team so shift(1) is "the previous match".
    long = long.sort_values(["team", "date"], kind="stable").reset_index(drop=True)

    grp = long.groupby("team", sort=False)
    prev = grp.shift(1)  # exclude the current match from every rolling input (PIT)
    roll = prev.groupby(long["team"], sort=False)
    xg_for_mean = roll["xg_for"].rolling(window, min_periods=window).mean().reset_index(level=0, drop=True)
    xg_against_mean = roll["xg_against"].rolling(window, min_periods=window).mean().reset_index(level=0, drop=True)
    goals_sum = roll["goals_for"].rolling(window, min_periods=window).sum().reset_index(level=0, drop=True)
    xg_for_sum = roll["xg_for"].rolling(window, min_periods=window).sum().reset_index(level=0, drop=True)
    fin_eff = goals_sum / xg_for_sum.where(xg_for_sum > 0.0)  # NaN when denom <= 0 or < window

    long = long.assign(
        roll_xg_for=xg_for_mean.to_numpy(),
        roll_xg_against=xg_against_mean.to_numpy(),
        roll_finishing_eff=fin_eff.to_numpy(),
    )

    out: dict[int, dict[str, float]] = {}
    for side, sub in long.groupby("side", sort=False):
        prefix = "home" if side == "home" else "away"
        for row in sub.itertuples(index=False):
            gid = int(row.game_id)
            rec = out.setdefault(gid, {})
            rec[f"{prefix}_roll_xg_for"] = float(row.roll_xg_for)
            rec[f"{prefix}_roll_xg_against"] = float(row.roll_xg_against)
            rec[f"{prefix}_roll_finishing_eff"] = float(row.roll_finishing_eff)

    for gid, rec in out.items():
        rec["delta_roll_xg_for"] = rec["home_roll_xg_for"] - rec["away_roll_xg_for"]
        rec["delta_roll_xg_against"] = rec["home_roll_xg_against"] - rec["away_roll_xg_against"]
        rec["delta_roll_finishing_eff"] = (
            rec["home_roll_finishing_eff"] - rec["away_roll_finishing_eff"]
        )
    return out


def build_join_index(
    corpus: pd.DataFrame,
) -> dict[tuple[str, int, int], list[tuple[pd.Timestamp, str, str, int]]]:
    """Index corpus matches by ``(canonical_league, home_goals, away_goals)``.

    Each value is a list of ``(normalized_kickoff_date, home_team, away_team,
    game_id)`` used to resolve a Football-Data fixture to a unique Understat match.
    """
    index: dict[tuple[str, int, int], list[tuple[pd.Timestamp, str, str, int]]] = {}
    dates = pd.to_datetime(corpus["date"]).dt.tz_localize(None).dt.normalize()
    for row, d in zip(corpus.itertuples(index=False), dates):
        key = (_canonical_league(row.sabi_league), int(row.home_goals), int(row.away_goals))
        index.setdefault(key, []).append((d, str(row.home_team), str(row.away_team), int(row.game_id)))
    return index


def understat_features_for_fixture(
    fixture: Mapping[str, Any],
    join_index: Mapping[tuple[str, int, int], list[tuple[pd.Timestamp, str, str, int]]],
    rolling_by_game: Mapping[int, Mapping[str, float]],
    alias_norm: Mapping[str, str],
) -> Optional[dict[str, np.float32]]:
    """Prior-only Understat rolling features for one Football-Data fixture, or ``None``.

    ``fixture`` must carry ``league`` (canonical), ``date`` (datetime-like),
    ``home_team``, ``away_team``, ``fthg`` and ``ftag`` (final goals). Returns a
    dict over ``UNDERSTAT_ROLLING_FEATURES`` as ``np.float32`` (``np.nan`` for any
    rolling value without enough prior history), or ``None`` when no unique
    name-matched Understat match exists (missing, ambiguous, or unmapped).
    """
    try:
        key = (str(fixture["league"]), int(fixture["fthg"]), int(fixture["ftag"]))
    except (KeyError, TypeError, ValueError):
        return None
    candidates = join_index.get(key)
    if not candidates:
        return None
    fd_date = pd.Timestamp(fixture["date"]).tz_localize(None).normalize()
    named = [
        (d, uh, ua, gid)
        for (d, uh, ua, gid) in candidates
        if abs((d - fd_date).days) <= 1
        and teams_match(uh, fixture["home_team"], alias_norm)
        and teams_match(ua, fixture["away_team"], alias_norm)
    ]
    if len(named) != 1:  # 0 -> unmatched; >1 -> ambiguous. Fail closed either way.
        return None
    game_id = named[0][3]
    rec = rolling_by_game.get(game_id)
    if rec is None:
        return None
    return {name: np.float32(rec.get(name, np.nan)) for name in UNDERSTAT_ROLLING_FEATURES}


__all__ = [
    "ROLLING_WINDOW",
    "UNDERSTAT_ROLLING_FEATURES",
    "CORPUS_UNAVAILABLE_FAMILIES",
    "normalize_team_name",
    "load_team_aliases",
    "teams_match",
    "compute_prior_rolling",
    "build_join_index",
    "understat_features_for_fixture",
]
