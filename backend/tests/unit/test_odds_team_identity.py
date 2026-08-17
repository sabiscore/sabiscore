"""Regression coverage for strict live-odds club-name normalization."""

from __future__ import annotations

import pytest

from src.services.odds_service import OddsService


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
def test_team_key_normalizes_structural_club_affix_variants(
    stored_name: str, provider_name: str
) -> None:
    assert OddsService._team_key(stored_name) == OddsService._team_key(provider_name)


def test_team_key_does_not_strip_affix_letters_from_unrelated_name() -> None:
    assert OddsService._team_key("Africa Sports") == "africasports"
    assert OddsService._team_key("AFC") == "afc"
