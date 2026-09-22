"""Regression guard for the E4 StatsBomb identity crosswalk.

The first draft of `audit_statsbomb_e4_coverage.build_crosswalk` used a bare
token-subset test and silently resolved StatsBomb's "Paris Saint-Germain" to
the corpus key `paris` (Paris FC), because {paris} is a subset of
{paris, saint, germain} while {paris, sg} is not. That handed PSG's fixtures
to a different club and reported Ligue 1 coverage as 0 -- a silent
substitution, which Gate D1 explicitly forbids.

This is the same collision `backend/src/services/team_identity.py` already
guards against on the market-matching side. These tests pin the scoring rule
that replaced the subset test, so the audit cannot regress into it.

No network, no database -- the audit module is stdlib-only at import time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from audit_statsbomb_e4_coverage import (  # noqa: E402
    _containment_score,
    build_crosswalk,
)


def _corpus_row(league: str, home: str, away: str) -> dict[str, object]:
    from datetime import date

    return {
        "league": league,
        "season": "2022/2023",
        "date": date(2023, 3, 19),
        "home_key": home,
        "away_key": away,
        "home_raw": home,
        "away_raw": away,
    }


def _sb_match(league: str, home_key: str, away_key: str) -> dict[str, object]:
    from datetime import date

    return {
        "league": league,
        "season": "2022/2023",
        "date": date(2023, 3, 19),
        "home_key": home_key,
        "away_key": away_key,
        "home_raw": home_key,
        "away_raw": away_key,
    }


class TestContainmentScore:
    def test_psg_outscores_paris_fc(self) -> None:
        """The bug: both fit, but 'paris sg' must win outright."""
        assert _containment_score("paris sg", "paris saint germain") == 3
        assert _containment_score("paris", "paris saint germain") == 1

    def test_corpus_token_with_no_counterpart_does_not_fit(self) -> None:
        """A corpus name carrying an unmatched token is a different club."""
        assert _containment_score("paris sg", "paris") is None

    @pytest.mark.parametrize(
        ("corpus_key", "sb_key", "expected"),
        [
            ("marseille", "olympique marseille", 1),
            ("brest", "stade brestois", 1),
            ("reims", "stade reims", 1),
            ("lyon", "lyon", 1),
        ],
    )
    def test_legal_form_prefixes_and_suffixes_still_resolve(
        self, corpus_key: str, sb_key: str, expected: int
    ) -> None:
        assert _containment_score(corpus_key, sb_key) == expected


class TestBuildCrosswalk:
    def test_psg_resolves_to_psg_not_paris_fc(self) -> None:
        corpus = [
            _corpus_row("LIGUE_1", "paris sg", "lyon"),
            _corpus_row("LIGUE_1", "paris", "lille"),
        ]
        mapping, stats = build_crosswalk(
            [_sb_match("LIGUE_1", "paris saint germain", "lyon")], corpus
        )
        assert mapping[("LIGUE_1", "paris saint germain")] == "paris sg"
        assert stats["resolution_rate_pct"] == 100.0

    def test_a_genuine_tie_is_left_unresolved_not_guessed(self) -> None:
        """Fail closed: two equally-scoring candidates resolve to neither."""
        corpus = [_corpus_row("SERIE_A", "inter", "milan")]
        mapping, stats = build_crosswalk(
            [_sb_match("SERIE_A", "inter milan", "inter milan")], corpus
        )
        assert ("SERIE_A", "inter milan") not in mapping
        assert stats["ambiguous_by_league"]["SERIE_A"]

    def test_unknown_entity_is_unresolved_never_substituted(self) -> None:
        corpus = [_corpus_row("EPL", "arsenal", "chelsea")]
        mapping, stats = build_crosswalk(
            [_sb_match("EPL", "hamburger sv", "arsenal")], corpus
        )
        assert ("EPL", "hamburger sv") not in mapping
        assert (
            "Hamburger SV".lower()
            in [n.lower() for n in stats["unresolved_by_league"]["EPL"]]
            or "hamburger sv" in stats["unresolved_by_league"]["EPL"]
        )
