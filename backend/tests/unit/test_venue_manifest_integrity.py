"""The venue manifest must not carry a geographically implausible VERIFIED club.

`docs/DEBT.md` item 44 rejected hand-entered stadium coordinates because a wrong
one produces *confidently wrong* weather — worse than no weather.
`qualify_venue_locations.py` derives them instead, but it verifies the resolved
**name**, and nothing verified the resolved **place**.

RCD Espanyol proved the gap real: it resolved to a place called "Español" at
28.5N -16.33 (Tenerife), passed the ES country filter, matched on name after
diacritic folding, and was marked VERIFIED — roughly 1,296 km from the real
Barcelona stadium, feeding subtropical Atlantic weather into that fixture's
features.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
_SCRIPT = _BACKEND / "scripts" / "validate_venue_manifest.py"
_MANIFEST = (
    _BACKEND.parent
    / "reports"
    / "research"
    / "portfolio-f-venue-location-manifest.json"
)

_SPEC = importlib.util.spec_from_file_location("_venue_manifest_gate", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_GATE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_GATE)


def _load() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_the_committed_manifest_is_sound() -> None:
    assert _GATE.validate(_load()) == []


def test_a_club_marooned_from_its_league_is_rejected() -> None:
    """The Espanol case, reconstructed.

    A single VERIFIED club is moved to the Canary Islands while its country
    code stays ES — exactly what happened, and exactly what the name-based
    classifier cannot see.
    """
    manifest = _load()
    spanish = [
        e
        for e in manifest["entries"]
        if e["verdict"] == "VERIFIED"
        and e.get("country") == "ES"
        and e.get("candidates")
    ]
    assert len(spanish) >= 2, "fixture assumption: several VERIFIED Spanish clubs"

    spanish[0]["candidates"][0]["latitude"] = 28.5
    spanish[0]["candidates"][0]["longitude"] = -16.3333

    failures = _GATE.validate(manifest)
    assert any("km away" in f for f in failures), failures


def test_a_cross_border_resolution_is_rejected() -> None:
    """The country filter is meant to make this impossible; prove we'd notice."""
    manifest = _load()
    entry = next(
        e
        for e in manifest["entries"]
        if e["verdict"] == "VERIFIED" and e.get("candidates")
    )
    entry["candidates"][0]["country_code"] = "XX"
    assert any("country_code" in f for f in _GATE.validate(manifest))


def test_a_verified_club_without_a_coordinate_is_rejected() -> None:
    """Ingestion reads candidates[0]; an empty list fails at use time."""
    manifest = _load()
    entry = next(
        e
        for e in manifest["entries"]
        if e["verdict"] == "VERIFIED" and e.get("candidates")
    )
    entry["candidates"] = []
    assert any("no usable candidate" in f for f in _GATE.validate(manifest))


@pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (0.0, 181.0), (float("nan"), 0.0)])
def test_out_of_range_coordinates_are_rejected(lat: float, lon: float) -> None:
    manifest = _load()
    entry = next(
        e
        for e in manifest["entries"]
        if e["verdict"] == "VERIFIED" and e.get("candidates")
    )
    entry["candidates"][0]["latitude"] = lat
    entry["candidates"][0]["longitude"] = lon
    assert _GATE.validate(manifest), f"({lat}, {lon}) accepted"


def test_header_counts_must_describe_the_entries() -> None:
    manifest = _load()
    manifest["counts"] = {"VERIFIED": 9999}
    assert any("counts header" in f for f in _GATE.validate(manifest))


# ── Generation-time demotion (DEBT 101's second follow-up) ──────────────────


def _fresh_manifest_with_espanol_reproduction() -> dict:
    """Rebuild the Espanol-shaped failure as a VERIFIED entry.

    `demote_geographically_implausible()` is the generation-time counterpart
    to `validate()`'s check 5 -- it must catch the identical shape before a
    manifest is ever written, not just after.
    """
    manifest = _load()
    spanish = [
        e
        for e in manifest["entries"]
        if e["verdict"] == "VERIFIED"
        and e.get("country") == "ES"
        and e.get("candidates")
    ]
    assert len(spanish) >= 2, "fixture assumption: several VERIFIED Spanish clubs"
    spanish[0] = dict(spanish[0])
    spanish[0]["candidates"] = [dict(spanish[0]["candidates"][0])]
    spanish[0]["candidates"][0]["latitude"] = 28.5
    spanish[0]["candidates"][0]["longitude"] = -16.3333
    # Replace the entry for that club in place.
    for i, e in enumerate(manifest["entries"]):
        if e.get("club") == spanish[0]["club"]:
            manifest["entries"][i] = spanish[0]
            break
    return manifest, spanish[0]["club"]


def test_demotion_catches_the_espanol_shape_before_it_is_written() -> None:
    manifest, club = _fresh_manifest_with_espanol_reproduction()
    out, demoted = _GATE.demote_geographically_implausible(manifest)

    assert demoted == [club]
    entry = next(e for e in out["entries"] if e["club"] == club)
    assert entry["verdict"] == "REQUIRES_REVIEW"
    assert "km" in entry["review_note"]

    # And the demotion must make the manifest pass validate() -- the whole
    # point is that the two never disagree.
    assert _GATE.validate(out) == []


def test_demotion_is_a_no_op_on_a_sound_manifest() -> None:
    manifest = _load()
    out, demoted = _GATE.demote_geographically_implausible(manifest)
    assert demoted == []
    assert out == manifest


def test_demotion_recomputes_counts_and_coverage() -> None:
    manifest, club = _fresh_manifest_with_espanol_reproduction()
    before_verified = manifest["counts"]["VERIFIED"]
    out, demoted = _GATE.demote_geographically_implausible(manifest)
    assert out["counts"]["VERIFIED"] == before_verified - 1
    assert out["coverage_verified"] < manifest["coverage_verified"]


def test_demotion_never_mutates_the_input_manifest() -> None:
    manifest, club = _fresh_manifest_with_espanol_reproduction()
    import copy

    before = copy.deepcopy(manifest)
    _GATE.demote_geographically_implausible(manifest)
    assert manifest == before
