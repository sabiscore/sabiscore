"""Guard: no two distinct corpus clubs may be merged by either name resolver.

docs/DEBT.md item 40. Two clubs that share a place name are the classic way a
name resolver silently merges distinct histories. Production carries a proven
instance: PSG's entire Elo history (276 snapshots from 2019/2020 onward) sits
on the ``Paris FC`` team row, in seasons when Paris FC was in Ligue 2.

SabiScore has **two** independent name resolvers, and this scans the committed
football-data.co.uk corpora once for both:

* ``historical_backfill_service.TeamIndex`` consumes the corpus short names
  directly. It already refuses the Paris pair (PR #25), and
  ``test_teamindex_refuses_every_corpus_containment_collision`` keeps that
  true for every future pair, behaviourally -- not by trusting a table.
* ``team_identity.resolve_team_id`` serves the live provider path. Its
  containment rule (``Brighton`` ⊂ ``Brighton & Hove Albion FC``) matches the
  Paris pair too, and ``_unique_match``'s uniqueness check does *not* save it:
  exactly one candidate matches, so the merge looks unambiguous. Only an
  explicit ``_AUDITED_ALIASES`` assertion stops it.

Adding a season whose promoted club collides with an incumbent fails here,
loudly, instead of quietly merging two clubs' histories.
"""
from __future__ import annotations

import csv
import glob
import os
from pathlib import Path

from src.services.historical_backfill_service import TeamIndex
from src.services.team_identity import _AUDITED_ALIASES, _identity_key

# football-data.co.uk division code -> SabiScore canonical league id.
_DIVISION_TO_LEAGUE = {
    "E0": "EPL",
    "SP1": "LA_LIGA",
    "D1": "BUNDESLIGA",
    "I1": "SERIE_A",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}

# Both column conventions appear in the committed cache: the older files were
# normalized to snake_case, the newest retain the raw upstream headers. Reading
# only one silently sees a fraction of the corpus -- which is exactly how an
# earlier hand-check of this data undercounted PSG from 243 appearances to 34.
_TEAM_COLUMNS = ("HomeTeam", "AwayTeam", "home_team", "away_team")

_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


def _corpus_names_by_league() -> dict[str, set[str]]:
    by_league: dict[str, set[str]] = {}
    for path in sorted(glob.glob(str(_CACHE_DIR / "fd_*.csv"))):
        division = os.path.basename(path).split("_")[1]
        league = _DIVISION_TO_LEAGUE.get(division)
        if league is None:
            continue
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            for row in csv.DictReader(handle):
                for column in _TEAM_COLUMNS:
                    name = (row.get(column) or "").strip()
                    if name:
                        by_league.setdefault(league, set()).add(name)
    return by_league


def _containment_collisions(names: set[str]) -> list[tuple[str, str, str, str]]:
    """Pairs of distinct names whose identity keys contain one another.

    Mirrors ``resolve_team_id``'s containment predicate exactly, including its
    ``len(key) >= 5`` floor -- a divergence here would make this guard describe
    a rule the resolver does not actually apply.
    """
    keyed = {name: _identity_key(name) for name in names}
    collisions: list[tuple[str, str, str, str]] = []
    ordered = sorted(names)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            first_key, second_key = keyed[first], keyed[second]
            if not first_key or not second_key or first_key == second_key:
                continue
            if len(first_key) < 5 or len(second_key) < 5:
                continue
            if (
                f" {first_key} " in f" {second_key} "
                or f" {second_key} " in f" {first_key} "
            ):
                collisions.append((first, first_key, second, second_key))
    return collisions


def _all_collisions() -> list[tuple[str, str, str, str, str]]:
    return [
        (league, *pair)
        for league, names in sorted(_corpus_names_by_league().items())
        for pair in _containment_collisions(names)
    ]


def test_corpus_is_present_so_these_guards_are_not_vacuous() -> None:
    """A guard that scans an empty corpus passes while proving nothing."""
    by_league = _corpus_names_by_league()
    assert by_league, f"no fd_*.csv corpora found under {_CACHE_DIR}"
    assert sum(len(names) for names in by_league.values()) > 100


def test_the_known_paris_collision_is_actually_detected() -> None:
    """Pins the detector itself against the real pair that motivated it.

    If a future ``_identity_key`` change stopped producing this collision, the
    guards below would pass vacuously; this keeps them honest.
    """
    assert _containment_collisions({"Paris FC", "Paris SG"}) == [
        ("Paris FC", "paris", "Paris SG", "paris sg")
    ]


def test_teamindex_refuses_every_corpus_containment_collision() -> None:
    """The corpus-facing resolver must never bind one club's name to the other.

    Behavioural, not table-based: ``TeamIndex`` is seeded with only one club of
    the pair -- the exact state the backfill is in when it meets the other name
    for the first time -- and must return ``None`` rather than the incumbent.
    """
    merged: list[str] = []
    for league, first, first_key, second, second_key in _all_collisions():
        for present, probe in ((first, second), (second, first)):
            index = TeamIndex([(f"seeded:{present}", present)])
            resolved = index.resolve(probe)
            if resolved is not None:
                merged.append(
                    f"{league}: TeamIndex holding only {present!r} resolved "
                    f"{probe!r} -> {resolved!r} (keys {first_key!r} / {second_key!r})"
                )

    assert not merged, (
        "TeamIndex merged two distinct corpus clubs. Add a _TEAM_ALIASES entry "
        "in historical_backfill_service asserting the real identity -- do NOT "
        "weaken this test:\n  " + "\n  ".join(merged)
    )


def test_every_containment_collision_is_asserted_for_the_live_resolver() -> None:
    """``resolve_team_id``'s containment rule needs an explicit alias per pair.

    Uniqueness does not protect this path: exactly one candidate matches a
    place-name collision, so the merge reads as unambiguous. Only an audited
    alias -- consulted *before* containment -- prevents it.
    """
    uncovered: list[str] = []
    for league, first, first_key, second, second_key in _all_collisions():
        if (league, first_key) in _AUDITED_ALIASES:
            continue
        if (league, second_key) in _AUDITED_ALIASES:
            continue
        uncovered.append(
            f"{league}: {first!r} (key={first_key!r}) <-> {second!r} (key={second_key!r})"
        )

    assert not uncovered, (
        "Distinct corpus clubs would be merged by resolve_team_id()'s containment "
        "heuristic. Add an _AUDITED_ALIASES entry in team_identity asserting the "
        "real identity for one side of each pair -- do NOT weaken this test:\n  "
        + "\n  ".join(uncovered)
    )
