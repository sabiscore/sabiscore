"""Tests for scripts/qualify_player_availability_coverage.py's pure logic.

Covers only the resolver, not the live network calls or pandas CSV loading
(matches the precedent set by test_venue_location_qualification.py for the
sibling Portfolio C script). `_identity_key` is an inlined verbatim copy of
`services/team_identity.py`'s function (deliberately not imported — that
module opens a database connection at import time, docs/DEBT.md item 7);
these tests pin that the copy behaves as documented, not that it is
byte-identical to the original.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from qualify_player_availability_coverage import (  # noqa: E402
    _identity_key,
    resolve_against_roster,
)


def test_identity_key_strips_legal_tokens():
    assert _identity_key("Arsenal FC") == "arsenal"
    assert _identity_key("AFC Bournemouth") == "bournemouth"


def test_identity_key_preserves_semantic_words():
    # "United"/"City" are real name components, not decoration -- must survive.
    assert _identity_key("Manchester United") == "manchester united"
    assert _identity_key("Manchester City") == "manchester city"


def test_resolve_exact_match():
    roster = {"Arsenal", "Chelsea", "Fulham"}
    assert resolve_against_roster("Arsenal FC", "EPL", roster) == "Arsenal"


def test_resolve_via_audited_alias():
    # Provider sends the full legal name; the corpus abbreviates it. This is
    # exactly the shape _AUDITED_ALIASES exists to bridge.
    roster = {"Wolves", "Fulham"}
    assert resolve_against_roster("Wolverhampton Wanderers", "EPL", roster) == "Wolves"


def test_resolve_via_subset_containment():
    # No alias needed: "Udinese" is a token subset of "Udinese Calcio".
    roster = {"Udinese Calcio"}
    assert resolve_against_roster("Udinese", "SERIE_A", roster) == "Udinese Calcio"


def test_resolve_returns_none_when_absent():
    # "Manchester United" vs a corpus spelled "Man United" -- a real, honestly
    # unresolved gap this session's live run surfaced (no alias covers this
    # direction yet). Must fail closed, never guess a different club.
    roster = {"Man United", "Fulham"}
    assert resolve_against_roster("Manchester United", "EPL", roster) is None


def test_alias_application_is_league_scoped():
    # ("BUNDESLIGA", "cologne"): "koln" -- "Cologne"/"Koln" share no tokens,
    # so only the alias (not the subset fallback) can bridge them. Watched
    # failing first: an earlier version of this test asserted a same-named
    # cross-league case should return None, which was wrong -- the permissive
    # subset fallback (documented in team_identity.py as a deliberate,
    # bounded residual exposure) is not league-aware by itself, only the
    # alias tables are. This case isolates the part that genuinely is.
    roster = {"Koln"}
    assert resolve_against_roster("Cologne", "BUNDESLIGA", roster) == "Koln"
    assert resolve_against_roster("Cologne", "EPL", roster) is None
