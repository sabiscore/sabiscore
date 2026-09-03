"""Regression coverage for live-market club-name identity matching.

Both odds paths (``OddsService.get_match_odds`` and the market-lifecycle
observer) resolve a betting-market provider's team names against the
``Team.name`` values fixture sync persists. They previously each carried their
own affix-stripping normalizer, which handled English club suffixes but folded
diacritics away as separators and left full legal names unreduced -- so
continental fixtures never matched and their market evidence was reported as
``COHERENT_1X2_MARKET_UNAVAILABLE``.

The pairs below are not invented spellings. They were read off a real The
Odds API board and the live ``/api/v1/fixtures/upcoming`` response on
2026-08-29, where the shipped matcher resolved 14 of 59 provider events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from src.services.team_identity import identity_key, select_unique_by_team_names


@dataclass(frozen=True)
class _Fixture:
    home_name: str
    away_name: str
    kickoff: datetime = datetime(2026, 8, 29, 13, 30)


def _names(fixture: _Fixture) -> tuple[str, str]:
    return fixture.home_name, fixture.away_name


def _resolve(
    candidates: list[_Fixture], home: str, away: str, league: str
) -> tuple[_Fixture | None, bool]:
    return select_unique_by_team_names(
        candidates, home=home, away=away, league=league, names=_names
    )


# --- structural affix contract (preserved from the pre-unification matcher) ---


@pytest.mark.parametrize(
    ("stored_name", "provider_name"),
    [
        ("Chelsea FC", "Chelsea"),
        ("Chelsea F.C.", "Chelsea"),
        ("Sunderland AFC", "Sunderland"),
        ("AFC Bournemouth", "Bournemouth"),
        ("Elche CF", "Elche"),
        ("C.F. Monterrey", "Monterrey"),
        ("Paris FC", "Paris"),
        ("Chelsea Football Club", "Chelsea"),
        ("Chelsea Soccer Club", "Chelsea"),
    ],
)
def test_structural_club_affix_variants_share_one_identity_key(
    stored_name: str, provider_name: str
) -> None:
    assert identity_key(stored_name) == identity_key(provider_name)


def test_affix_letters_are_not_stripped_from_an_unrelated_name() -> None:
    assert identity_key("Africa Sports") == "africa sports"


def test_a_bare_designator_yields_no_identity_and_fails_closed() -> None:
    """``AFC`` alone names no club, so it must never match one."""
    assert identity_key("AFC") == ""
    match, ambiguous = _resolve([_Fixture("AFC Bournemouth", "Everton FC")], "AFC", "AFC", "EPL")
    assert match is None
    assert ambiguous is False


# --- the defect this change fixes, measured against a real provider board ---


@pytest.mark.parametrize(
    ("league", "provider_home", "provider_away", "stored_home", "stored_away"),
    [
        # Diacritics: the old normalizer split "Munchen" on the umlaut.
        ("BUNDESLIGA", "Bayern Munich", "Mainz", "FC Bayern München", "1. FSV Mainz 05"),
        ("LA_LIGA", "Atlético Madrid", "Sevilla", "Club Atlético de Madrid", "Sevilla FC"),
        # Provider trade name vs stored full legal name.
        ("SERIE_A", "Udinese", "Lazio", "Udinese Calcio", "Lazio"),
        ("SERIE_A", "Genoa", "Como", "Genoa CFC", "Como 1907"),
        ("LA_LIGA", "Real Sociedad", "Espanyol", "Real Sociedad de Fútbol", "RCD Espanyol de Barcelona"),
        # Legal form inserts tokens, so substring containment is not enough.
        ("LA_LIGA", "Celta Vigo", "Barcelona", "RC Celta de Vigo", "FC Barcelona"),
        ("LIGUE_1", "Strasbourg", "RC Lens", "RC Strasbourg Alsace", "Racing Club de Lens"),
        ("EREDIVISIE", "AZ Alkmaar", "PSV Eindhoven", "AZ", "PSV"),
        ("EREDIVISIE", "FC Zwolle", "NEC Nijmegen", "PEC Zwolle", "NEC"),
        ("EPL", "Newcastle United", "Brighton and Hove Albion", "Newcastle", "Brighton"),
        # Endonym/exonym differences that only an identity assertion can bridge.
        ("LIGUE_1", "Lyon", "Le Havre", "Olympique Lyonnais", "Le Havre"),
        ("LIGUE_1", "Brest", "Toulouse", "Stade Brestois 29", "Toulouse FC"),
        ("SERIE_A", "Inter Milan", "Napoli", "FC Internazionale Milano", "SSC Napoli"),
        # Bundesliga fixtures point at Elo-corpus rows, so the stored side is
        # the abbreviated corpus spelling the audited alias table already knows.
        ("BUNDESLIGA", "Eintracht Frankfurt", "Augsburg", "Ein Frankfurt", "Augsburg"),
        ("BUNDESLIGA", "Borussia Monchengladbach", "Elversberg", "M'gladbach", "SV 07 Elversberg"),
    ],
)
def test_real_provider_names_resolve_to_the_stored_fixture(
    league: str, provider_home: str, provider_away: str, stored_home: str, stored_away: str
) -> None:
    target = _Fixture(stored_home, stored_away)
    decoys = [
        _Fixture("Some Other Club", "Another Club FC"),
        _Fixture("Third Club", "Fourth Club"),
    ]
    match, ambiguous = _resolve([*decoys, target], provider_home, provider_away, league)
    assert ambiguous is False
    assert match == target


# --- the collision this repo has already been burned by ---


def test_permissive_stage_refuses_when_two_clubs_both_contain_the_name() -> None:
    """The uniqueness guard is what makes subset comparison usable at all.

    Many Spanish clubs share the ``Real`` prefix, so a short provider name
    satisfies the permissive predicate against several of them at once. The
    matcher must report ambiguity rather than repeat the containment merge
    recorded in docs/DEBT.md item 40.
    """
    sociedad = _Fixture("Real Sociedad de Fútbol", "Getafe CF")
    betis = _Fixture("Real Betis Balompié", "Getafe CF")
    match, ambiguous = _resolve([sociedad, betis], "Real", "Getafe", "LA_LIGA")
    assert match is None
    assert ambiguous is True


def test_exact_identity_wins_before_the_permissive_stage() -> None:
    """Paris FC resolves to itself while PSG is a live candidate.

    Stage ordering is the load-bearing safety property. ``Paris FC`` reduces to
    the bare place name ``paris``, which the permissive stage also finds inside
    ``paris saint germain``; trying exact keys across the whole candidate set
    first is what stops the smaller club being merged into the bigger one.
    """
    paris_fc = _Fixture("Paris FC", "OGC Nice")
    psg = _Fixture("Paris Saint-Germain", "OGC Nice")
    match, ambiguous = _resolve([psg, paris_fc], "Paris FC", "OGC Nice", "LIGUE_1")
    assert ambiguous is False
    assert match == paris_fc


def test_shared_place_name_without_an_exact_key_fails_closed() -> None:
    """When the exact stage cannot separate them, neither club is selected.

    This is the residual exposure of subset comparison, and the honest outcome
    is an unpriced fixture rather than a fixture priced off the wrong market.

    The away side uses "Strasbourg" against the stored "RC Strasbourg Alsace"
    -- deliberately not "Nice" against "OGC Nice" (the original pairing): once
    docs/DEBT.md item 56 Finding 7 added an audited alias for bare "Nice",
    that pairing resolves via the alias exact-matching the away side too and
    genuinely stops being ambiguous, which is a correct market-matching
    outcome, not a bug. "Strasbourg" has no alias entry and legitimately
    still needs the permissive stage (its legal name inserts "Alsace"), so it
    keeps testing the same property: an exact home match alone is not enough
    while the away side is only ever a subset match.
    """
    paris_fc = _Fixture("Paris FC", "RC Strasbourg Alsace")
    psg = _Fixture("Paris Saint-Germain", "RC Strasbourg Alsace")
    match, ambiguous = _resolve([psg, paris_fc], "Paris FC", "Strasbourg", "LIGUE_1")
    assert match is None
    assert ambiguous is True


def test_both_sides_must_match_before_a_fixture_is_selected() -> None:
    """A correct home team is not enough to claim the fixture."""
    match, ambiguous = _resolve(
        [_Fixture("Udinese Calcio", "Lazio")], "Udinese", "Napoli", "SERIE_A"
    )
    assert match is None
    assert ambiguous is False
