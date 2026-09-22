"""Offline integrity gate for the Portfolio F venue-location manifest.

`docs/DEBT.md` item 44 rejected hand-entered stadium coordinates because a wrong
one produces *confidently wrong* weather, which is worse than no weather.
`qualify_venue_locations.py` answered that by deriving coordinates from the
club's own name and geocoding them with a country filter — but it verifies that
the resolved **name** matches, and nothing verifies the resolved **place** is
plausible.

That gap is not hypothetical. `Espanol` (RCD Espanyol, Barcelona) resolved to a
place called "Español" at 28.5N -16.33 — Tenerife, in the Canary Islands. The
country code is `ES`, so the country filter passed; the name matches after
diacritic folding, so the classifier marked it VERIFIED; and the ingestion
script has been feeding subtropical Atlantic weather into a Barcelona fixture's
features ever since. It is ~1,300 km from the real stadium.

This script closes that gap **offline**. It reads only the committed manifest,
issues no network requests, and is therefore safe to run on every commit —
unlike re-geocoding, which is rate-limited, non-deterministic under upstream
change, and would make a CI step flaky for no added assurance.

WHAT IT CHECKS, AND WHY EACH IS FABRICATION-FREE
------------------------------------------------
Every check below is derived from the manifest itself. None consults an
authored table of city coordinates or bounding boxes — writing one from recall
would reintroduce exactly the invented reference data item 44 rejected.

1. Header counts match the entries they summarise.
2. Coordinates are finite and inside valid lat/lon ranges.
3. Every VERIFIED entry carries at least one candidate, since the ingestion
   script reads ``candidates[0]`` and would otherwise fail at use time.
4. A VERIFIED candidate's ``country_code`` matches the entry's own country —
   the country filter is supposed to make a cross-border resolution impossible,
   so a mismatch means the filter did not hold.
5. **Geographic plausibility**: a VERIFIED club that sits implausibly far from
   every other VERIFIED club in its own league country is flagged. Football
   clubs in a national league cluster geographically; a coordinate that does
   not is a resolution error, not a remote stadium.

ON THE ISOLATION THRESHOLD
--------------------------
Measured over the 116 VERIFIED clubs in the committed manifest, nearest-
neighbour distance within a country has median 60.7 km, MAD 35.3 km and p99
431.7 km. The largest legitimate value is Cagliari at 431.7 km (Sardinia, an
island club). The single bad entry sits at 1,296 km — a 3x break above it.

``_ISOLATION_KM`` is set in the empty gap between those two, which makes it a
reasoned starting point rather than a calibrated one. It is labelled
``DEFAULT_PENDING_CALIBRATION`` for the same reason `core/portfolio_exposure.py`
labels its constants: the number is defensible and is not yet validated against
a second corpus. Widening it to silence a future failure is the wrong move —
investigate the club first.

    cd backend && PYTHONPATH=. python scripts/validate_venue_manifest.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MANIFEST = (
    _BACKEND_ROOT.parent
    / "reports"
    / "research"
    / "portfolio-f-venue-location-manifest.json"
)

#: Nearest-neighbour distance, within a country, beyond which a VERIFIED club is
#: treated as a resolution error rather than a remote stadium. See the module
#: docstring for the measured distribution this sits inside.
_ISOLATION_KM = 750.0

_VERIFIED = "VERIFIED"
_REQUIRES_REVIEW = "REQUIRES_REVIEW"
_ISOLATION_POLICY_SOURCE = "DEFAULT_PENDING_CALIBRATION"


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres.

    Deliberately duplicated from `qualify_venue_locations.py` rather than
    imported: that module performs live geocoding at import-adjacent scope and
    pulls in the provider stack. This gate must stay offline and importable in
    a bare environment.
    """
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _primary_point(entry: dict[str, Any]) -> tuple[float, float] | None:
    """The coordinate ingestion would actually use: ``candidates[0]``."""
    candidates = entry.get("candidates") or []
    if not candidates:
        return None
    first = candidates[0]
    lat, lon = first.get("latitude"), first.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return float(lat), float(lon)


def _isolated_clubs(
    verified_points: dict[str, list[tuple[str, tuple[float, float]]]],
    isolation_km: float = _ISOLATION_KM,
) -> dict[str, tuple[str, float]]:
    """club -> (country, nearest VERIFIED neighbour's distance in km).

    Only clubs whose nearest other VERIFIED club, within their own league
    country, exceeds ``isolation_km``. A country with fewer than two VERIFIED
    clubs is skipped -- nothing to compare against is not evidence of
    correctness, so it is silently excluded rather than flagged either way.

    Shared by `validate()` (the offline CI gate, item 5) and
    `demote_geographically_implausible()` (the generation-time counterpart) so
    the two can never drift apart -- see DEBT 101's second follow-up, which
    named exactly that risk: a full manifest regeneration silently re-promoting
    a club like Espanol because the isolation rule lived only in the gate that
    checks a manifest after the fact, never in the code that writes one.
    """
    isolated: dict[str, tuple[str, float]] = {}
    for country, items in verified_points.items():
        if len(items) < 2:
            continue
        for club, point in items:
            nearest = min(
                haversine_km(point, other) for name, other in items if name != club
            )
            if nearest > isolation_km:
                isolated[club] = (country, nearest)
    return isolated


def validate(manifest: dict[str, Any]) -> list[str]:
    """Return a list of failures; empty means the manifest is sound."""
    failures: list[str] = []
    entries = manifest.get("entries") or []

    if not entries:
        return ["manifest contains no entries"]

    # 1. Header counts describe the entries.
    declared = manifest.get("counts") or {}
    actual: dict[str, int] = defaultdict(int)
    for entry in entries:
        actual[str(entry.get("verdict"))] += 1
    if dict(actual) != dict(declared):
        failures.append(
            f"counts header {dict(declared)} does not match entries {dict(actual)}"
        )

    verified_points: dict[str, list[tuple[str, tuple[float, float]]]] = defaultdict(
        list
    )

    for entry in entries:
        club = str(entry.get("club"))
        if entry.get("verdict") != _VERIFIED:
            continue

        # 3. Ingestion reads candidates[0]; a VERIFIED entry without one is a
        #    failure at use time, not a gap it can route around.
        point = _primary_point(entry)
        if point is None:
            failures.append(f"{club}: VERIFIED but has no usable candidate coordinate")
            continue

        lat, lon = point
        # 2. Range sanity.
        if not (math.isfinite(lat) and math.isfinite(lon)):
            failures.append(f"{club}: non-finite coordinate ({lat}, {lon})")
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            failures.append(f"{club}: coordinate out of range ({lat}, {lon})")
            continue

        # 4. The country filter is supposed to make this impossible.
        country = entry.get("country")
        for candidate in entry.get("candidates") or []:
            code = candidate.get("country_code")
            if code is not None and code != country:
                failures.append(
                    f"{club}: candidate {candidate.get('name')!r} has country_code "
                    f"{code!r} but the club's league country is {country!r}"
                )

        verified_points[str(country)].append((club, point))

    # 5. Geographic plausibility within each league country.
    for club, (country, nearest) in sorted(_isolated_clubs(verified_points).items()):
        failures.append(
            f"{club} ({country}): nearest VERIFIED club in its own league "
            f"country is {nearest:,.0f} km away, beyond the "
            f"{_ISOLATION_KM:,.0f} km plausibility bound. A national league "
            f"clusters geographically — this is a resolution error, not a "
            f"remote stadium. Investigate the club before widening the bound."
        )

    return failures


def demote_geographically_implausible(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Generation-time counterpart to `validate()`'s isolation check.

    `qualify_venue_locations.py` calls this on the manifest it just built,
    before writing it to disk, so a full regeneration cannot silently
    re-promote a club the way Espanol was VERIFIED (DEBT 101): the isolation
    rule is applied once, here, and shared with `validate()` via
    `_isolated_clubs()`, so the gate that gates and the generator that
    generates cannot drift apart.

    Never invents a coordinate. A flagged entry is demoted to
    REQUIRES_REVIEW with the measured distance recorded in ``review_note`` --
    the same fail-closed direction `classify()` already takes for every other
    kind of geocoding ambiguity. Returns a new manifest (the input is never
    mutated) and the sorted list of demoted club names, which is empty when
    nothing needed demoting.
    """
    out = json.loads(json.dumps(manifest))  # deep copy without a stdlib import
    entries = out.get("entries") or []

    verified_points: dict[str, list[tuple[str, tuple[float, float]]]] = defaultdict(
        list
    )
    by_club: dict[str, dict[str, Any]] = {}
    for entry in entries:
        club = str(entry.get("club"))
        by_club[club] = entry
        if entry.get("verdict") != _VERIFIED:
            continue
        point = _primary_point(entry)
        if point is not None:
            verified_points[str(entry.get("country"))].append((club, point))

    isolated = _isolated_clubs(verified_points)
    for club, (country, nearest) in isolated.items():
        entry = by_club[club]
        entry["verdict"] = _REQUIRES_REVIEW
        entry["reason"] = "resolved_place_is_geographically_implausible_for_its_league"
        entry["review_note"] = (
            f"Nearest other VERIFIED club in {country} is {nearest:,.0f} km away, "
            f"beyond the {_ISOLATION_KM:,.0f} km plausibility bound "
            f"({_ISOLATION_POLICY_SOURCE}). Demoted at generation time by "
            f"demote_geographically_implausible() -- see docs/DEBT.md item 101."
        )

    if isolated:
        counts: dict[str, int] = defaultdict(int)
        for entry in entries:
            counts[str(entry.get("verdict"))] += 1
        out["counts"] = dict(counts)
        roster_size = out.get("roster_size") or len(entries)
        verified_count = counts.get(_VERIFIED, 0)
        out["coverage_verified"] = (
            round(verified_count / roster_size, 4) if roster_size else 0.0
        )

    return out, sorted(isolated)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=_DEFAULT_MANIFEST)
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"FAIL: venue manifest not found at {args.manifest}", file=sys.stderr)
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    failures = validate(manifest)

    verified = (manifest.get("counts") or {}).get(_VERIFIED, 0)
    if failures:
        print(
            f"FAIL: {len(failures)} venue-manifest integrity violation(s) "
            f"across {verified} VERIFIED clubs\n",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            f"\nisolation bound: {_ISOLATION_KM:,.0f} km ({_ISOLATION_POLICY_SOURCE})",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: venue manifest sound — {verified} VERIFIED clubs, "
        f"coordinates in range, country filter held, none isolated beyond "
        f"{_ISOLATION_KM:,.0f} km ({_ISOLATION_POLICY_SOURCE})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
