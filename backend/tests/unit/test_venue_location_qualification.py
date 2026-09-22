"""Pins the venue-location classifier used for Portfolio C's Gate G1 study.

The measured coverage number in
`reports/research/portfolio-c-weather-venue-location-qualification.md` is only
as good as this classifier. Every rule that decides VERIFIED vs REQUIRES_REVIEW
vs UNKNOWN is exercised here with no network call, because a rule that silently
loosens turns a review queue into an invented coordinate.
"""

from __future__ import annotations

import pytest

from scripts.qualify_venue_locations import (
    REQUIRES_REVIEW,
    UNKNOWN,
    VERIFIED,
    WEATHER_CELL_KM,
    classify,
    fold,
    haversine_km,
    place_is_named_in_club,
    query_terms,
    within_one_cell,
)
from src.providers.open_meteo import GeoPoint


def _point(name: str, lat: float, lon: float, country: str = "DE") -> GeoPoint:
    return GeoPoint(latitude=lat, longitude=lon, name=name, country_code=country)


# --- folding -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("M'gladbach", "m gladbach"),
        ("Ein Frankfurt", "ein frankfurt"),
        ("Deportivo Alavés", "deportivo alaves"),
        ("FC Köln", "fc koln"),
        ("  Paris   SG  ", "paris sg"),
    ],
)
def test_fold_strips_diacritics_and_punctuation(raw: str, expected: str) -> None:
    assert fold(raw) == expected


# --- query derivation ----------------------------------------------------


def test_every_query_term_is_text_the_club_calls_itself() -> None:
    """No term may be invented; each is the full name or one of its tokens."""
    club = "Bayern Munich"
    terms = query_terms(club)
    assert terms[0] == "bayern munich"
    for term in terms[1:]:
        assert term in fold(club).split()


def test_short_tokens_are_not_queried() -> None:
    """ "man" resolves to the Isle of Man, 250 km from Manchester.

    It would otherwise pass the name-match test and produce a confidently wrong
    coordinate, which is the exact failure this study exists to avoid.
    """
    assert query_terms("Man United") == ["man united", "united"]
    assert "man" not in query_terms("Man United")


def test_pure_digit_tokens_are_not_queried() -> None:
    assert query_terms("Schalke 04") == ["schalke 04", "schalke"]


def test_place_names_are_not_suppressed_as_club_words() -> None:
    """Regression guard for a real defect in this script's first draft.

    `milan`, `roma`, `napoli`, `lazio` and `schalke` were briefly on the
    non-place stopword list. They are the very place names the study resolves,
    and suppressing them would have manufactured a low coverage number out of a
    bad stopword list rather than out of the corpus.
    """
    for club in ("Milan", "Roma", "Napoli", "Lazio", "Schalke 04"):
        assert fold(club).split()[0] in query_terms(club)


# --- geometry ------------------------------------------------------------


def test_haversine_matches_a_known_distance() -> None:
    # London -> Paris is ~343 km.
    assert 335 <= haversine_km((51.5074, -0.1278), (48.8566, 2.3522)) <= 350


def test_within_one_cell_is_pairwise_not_just_first_to_rest() -> None:
    """Three points can each be near their neighbour and still span two cells."""
    a = (48.14, 11.58)
    b = (48.14, 11.58 + WEATHER_CELL_KM / 111.0 * 0.9)
    c = (48.14, 11.58 + WEATHER_CELL_KM / 111.0 * 1.8)
    assert within_one_cell([a, b])
    assert not within_one_cell([a, b, c])


# --- name confirmation ---------------------------------------------------


def test_place_is_named_in_club_requires_every_place_token() -> None:
    assert place_is_named_in_club("Frankfurt", "Ein Frankfurt")
    # "am"/"Main" are not in the club name, so this needs a human.
    assert not place_is_named_in_club("Frankfurt am Main", "Ein Frankfurt")


def test_abbreviations_are_not_folded_together() -> None:
    """ "St Etienne" must not silently become "Saint-Etienne".

    An abbreviation rule permissive enough to join these also joins clubs it
    should not, so the strict form leaves it for review instead.
    """
    assert not place_is_named_in_club("Saint-Etienne", "St Etienne")


# --- the taxonomy --------------------------------------------------------


def test_no_resolution_is_unknown_not_a_guess() -> None:
    verdict, reason, confirmed = classify("Atalanta", [])
    assert verdict == UNKNOWN
    assert reason == "no_geocoding_match_within_league_country"


def test_name_confirmed_single_place_is_verified() -> None:
    verdict, reason, confirmed = classify(
        "Leverkusen", [_point("Leverkusen", 51.03, 6.98)]
    )
    assert verdict == VERIFIED
    assert reason == "place_name_appears_in_club_name"


def test_two_confirmed_places_far_apart_go_to_review() -> None:
    """ "Bayern" resolves to the state, "Munich" to the city, ~90 km apart.

    Both are named in the club, so neither can be dismissed as noise; the
    disagreement is real and belongs to a human.
    """
    verdict, reason, confirmed = classify(
        "Bayern Munich",
        [_point("Bayern", 47.80, 12.53), _point("Munich", 48.14, 11.58)],
    )
    assert verdict == REQUIRES_REVIEW
    assert reason == "candidates_span_more_than_one_weather_cell"


def test_unconfirmed_noise_does_not_veto_a_confirmed_place() -> None:
    """The "united" token drags in the United Kingdom's own centroid.

    Newcastle is confirmed by the club's name and the country centroid is not,
    so the centroid is noise from a generic token rather than an ambiguity, and
    must not downgrade a club that did resolve.
    """
    verdict, _, confirmed = classify(
        "Newcastle United",
        [
            _point("Newcastle", 54.97, -1.61, "GB"),
            _point("United Kingdom", 54.76, -2.70, "GB"),
        ],
    )
    assert verdict == VERIFIED
    # The confirmed evidence is Newcastle alone -- the UK centroid never earns
    # trust just because it happened not to veto the verdict (DEBT 101).
    assert [g.name for g in confirmed] == ["Newcastle"]


def test_when_nothing_is_confirmed_everything_counts_and_review_wins() -> None:
    """The fail-closed direction: an unconfirmed resolution is never VERIFIED."""
    verdict, reason, confirmed = classify(
        "Man United",
        [_point("United Kingdom", 54.76, -2.70, "GB")],
    )
    assert verdict == REQUIRES_REVIEW
    assert reason == "resolved_place_is_not_named_in_the_club_name"


def test_verified_never_arises_from_an_unnamed_place() -> None:
    """The whole basis of VERIFIED is the club naming the place. Nothing else."""
    for name in ("Bergamo", "Amsterdam", "Turin"):
        verdict, _, confirmed = classify("Atalanta", [_point(name, 45.7, 9.67, "IT")])
        assert verdict == REQUIRES_REVIEW


# --- DEBT 101: the confirmed subset must be the evidence VERIFIED rests on ---


def test_verified_returns_exactly_the_confirmed_candidates() -> None:
    """VERIFIED must never come back with an empty or unconfirmed evidence set."""
    verdict, _, confirmed = classify("Leverkusen", [_point("Leverkusen", 51.03, 6.98)])
    assert verdict == VERIFIED
    assert [g.name for g in confirmed] == ["Leverkusen"]


def test_non_verified_verdicts_return_no_confirmed_evidence() -> None:
    """REQUIRES_REVIEW and UNKNOWN both mean 'nothing to trust yet'."""
    _, _, confirmed_unknown = classify("Atalanta", [])
    assert confirmed_unknown == ()

    _, _, confirmed_review = classify(
        "Man United", [_point("United Kingdom", 54.76, -2.70, "GB")]
    )
    assert confirmed_review == ()

    _, _, confirmed_split = classify(
        "Bayern Munich",
        [_point("Bayern", 47.80, 12.53), _point("Munich", 48.14, 11.58)],
    )
    assert confirmed_split == ()
