"""Gate G1 (fixture coverage) for Portfolio F — can we locate the corpus at all?

`docs/DEBT.md` item 44 ships Open-Meteo acquisition and then gates the feature
work behind three prerequisites, the first of which is:

    A team -> location mapping with a review step. Geocoding is derived, not
    invented, but it is still a guess for clubs whose name is not their city
    (Bayer Leverkusen, Hoffenheim, Atalanta). It needs the same
    VERIFIED/REQUIRES_REVIEW treatment as team identity, not silent acceptance.

This script answers that with measured numbers instead of an estimate, over the
exact roster a weather backfill would have to cover: every distinct club in
`backend/data/cache/fd_*.csv`, the 12,765-match corpus the models train on.

It is read-only and acquires nothing. It issues keyless Open-Meteo geocoding
requests and writes a manifest plus a summary; no weather is fetched, no
database is touched, no artifact is modified. Run it before deciding whether a
12,765-row archive backfill is worth starting.

    cd backend
    python scripts/qualify_venue_locations.py --out reports/research/venue-location-manifest.json

Design notes that are load-bearing, not decoration:

* **Every query string is text the club calls itself.** The full name, then each
  of its own tokens. Nothing is recalled from memory, so a wrong answer is a
  wrong *derivation* an operator can audit, never an invented coordinate.
* **The country filter fails closed.** "Arsenal" is a place in several
  countries; constrained to GB it resolves to nothing, and nothing is the
  correct answer here. Never let a name resolve outside its own league.
* **Ambiguity is surfaced, not resolved.** When a club's tokens point at places
  further apart than one weather grid cell, that is REQUIRES_REVIEW. Picking the
  first hit is how `odds_service` silently priced the wrong fixture for months.
* **VERIFIED is a narrow claim.** It means "the club's own name contains a place
  that geocodes uniquely inside its own country" -- not "the club plays there".
  Those coincide for most European clubs and not for all, which is exactly why
  the remaining step is a human review rather than an automatic promotion.
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.providers.open_meteo import GeoPoint, OpenMeteoProvider  # noqa: E402

# football-data.co.uk division code -> ISO-3166-1 alpha-2 of the league's country.
# Closed set: a division outside it is not in the corpus and must not be guessed.
LEAGUE_COUNTRY: dict[str, str] = {
    "D1": "DE",
    "E0": "GB",
    "F1": "FR",
    "I1": "IT",
    "N1": "NL",
    "SP1": "ES",
}

# Two resolutions this far apart are the same weather observation. Open-Meteo
# snaps every request to its own grid cell, so agreement inside one cell is
# agreement for the only purpose this mapping has.
WEATHER_CELL_KM = 25.0

# Legal-form and corporate tokens that are never a place. Deliberately tiny.
#
# An earlier draft of this list also held `milan`, `roma`, `napoli`, `lazio`,
# `schalke`, `holstein` and `bayern` on the theory that they are "club words".
# They are place names -- exactly the ones this script exists to resolve -- and
# suppressing them would have manufactured a low coverage number out of a bad
# stopword list. Every entry here costs coverage if it is wrong, and a token
# that genuinely is not a place simply resolves to nothing at no cost, so the
# list stays at the handful that are unambiguously corporate.
_NON_PLACE_TOKENS = frozenset({
    "club", "calcio", "futbol", "football", "sportiva", "sportif", "verein",
})

# A three-letter token carries too little locational information to accept
# without review: "man" (from "Man United") resolves to the Isle of Man, 250 km
# from Manchester, and would otherwise pass the name-match test. Four is the
# shortest length at which the corpus's own place tokens still all survive.
_MIN_TOKEN_LEN = 4

VERIFIED = "VERIFIED"
REQUIRES_REVIEW = "REQUIRES_REVIEW"
UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------
# Pure logic. Everything below this line is testable without a network call.
# --------------------------------------------------------------------------


def fold(text: str) -> str:
    """Lowercase, strip diacritics, collapse everything else to single spaces.

    Mirrors `team_identity._identity_key`'s NFKD convention so a name folded
    here and a name folded there cannot disagree about the same club.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def query_terms(club_name: str) -> list[str]:
    """Every string worth asking the geocoder about, most specific first.

    The full folded name, then each of its own tokens that could plausibly be a
    place. Order matters only for readability of the manifest -- all terms are
    tried, because a club named after neither its city nor a single token (Inter,
    Atalanta) must be allowed to resolve to nothing.
    """
    folded = fold(club_name)
    if not folded:
        return []
    terms = [folded]
    for token in folded.split():
        if len(token) < _MIN_TOKEN_LEN or token.isdigit() or token in _NON_PLACE_TOKENS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in kilometres between two (lat, lon) pairs."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def within_one_cell(points: Sequence[tuple[float, float]]) -> bool:
    """True when every point sits inside one weather grid cell of every other."""
    return all(
        haversine_km(points[i], points[j]) <= WEATHER_CELL_KM
        for i in range(len(points))
        for j in range(i + 1, len(points))
    )


def place_is_named_in_club(place_name: str, club_name: str) -> bool:
    """True when the resolved place's name appears verbatim in the club's name.

    This is the whole basis of a VERIFIED verdict, so it is deliberately strict:
    every token of the place must be a token of the club. "Frankfurt" inside
    "Ein Frankfurt" qualifies; "Saint Etienne" against "St Etienne" does not,
    and is left for a human rather than folded together by an abbreviation rule
    that would also fold apart clubs it should not.
    """
    club_tokens = set(fold(club_name).split())
    place_tokens = [t for t in fold(place_name).split() if t]
    return bool(place_tokens) and all(t in club_tokens for t in place_tokens)


def classify(
    club_name: str, resolutions: Sequence[GeoPoint]
) -> tuple[str, str, Sequence[GeoPoint]]:
    """Map a club's geocoding results onto the identity trust taxonomy.

    Returns ``(verdict, reason, confirmed)`` where ``confirmed`` is the subset
    of ``resolutions`` whose place name is named in the club -- the evidence a
    VERIFIED verdict actually rests on. The taxonomy and the fail-closed
    default are the same ones `providers/reconciliation.py` already uses for
    team identity.

    ``confirmed`` matters beyond this function: DEBT 101 recorded that the
    manifest used to store every raw candidate with no record of which one
    ``classify`` actually trusted, so `ingest_openmeteo_weather.py` fell back
    to `candidates[0]` -- correct for Sheffield United only because the
    geocoder happened to return "Sheffield" before "United Kingdom", not
    because anything enforced it. A reordered upstream response would have
    silently handed it the wrong centroid while the manifest still said
    VERIFIED. Callers persist this subset so ingestion can read the coordinate
    the verdict was actually earned on.
    """
    if not resolutions:
        return UNKNOWN, "no_geocoding_match_within_league_country", ()

    # A generic token can drag in a place nobody asked about -- "united", from
    # "Newcastle United", resolves to the United Kingdom's own centroid. When
    # some candidate is confirmed by the club's own name, the unconfirmed ones
    # are that kind of noise and would otherwise fake an ambiguity that is not
    # there. When none is confirmed, everything stays and the club goes to
    # review, which is the fail-closed direction.
    confirmed = [g for g in resolutions if place_is_named_in_club(g.name, club_name)]
    considered = confirmed or list(resolutions)

    if not within_one_cell([(g.latitude, g.longitude) for g in considered]):
        return REQUIRES_REVIEW, "candidates_span_more_than_one_weather_cell", ()

    if confirmed:
        return VERIFIED, "place_name_appears_in_club_name", confirmed

    return REQUIRES_REVIEW, "resolved_place_is_not_named_in_the_club_name", ()


# --------------------------------------------------------------------------
# Corpus roster
# --------------------------------------------------------------------------


def corpus_roster(cache_dir: Path) -> dict[str, set[str]]:
    """Every distinct club in the training corpus, mapped to its divisions.

    Handles both column conventions present in `data/cache/fd_*.csv`
    (`HomeTeam`/`AwayTeam` and `home_team`/`away_team`) -- the files are not
    uniform, and silently reading only one convention undercounts the roster by
    a factor of five.
    """
    import pandas as pd

    roster: dict[str, set[str]] = {}
    for path in sorted(glob.glob(str(cache_dir / "fd_*.csv"))):
        frame = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
        home = "HomeTeam" if "HomeTeam" in frame.columns else "home_team"
        away = "AwayTeam" if "AwayTeam" in frame.columns else "away_team"
        if home not in frame.columns or away not in frame.columns:
            continue
        division = os.path.basename(path).split("fd_")[1].split("_")[0]
        for value in pd.concat([frame[home], frame[away]]).dropna().unique():
            roster.setdefault(str(value).strip(), set()).add(division)
    return roster


# --------------------------------------------------------------------------
# Live resolution
# --------------------------------------------------------------------------


async def resolve_club(
    provider: OpenMeteoProvider,
    club_name: str,
    country_code: str,
    *,
    pause_seconds: float,
) -> tuple[list[GeoPoint], list[str]]:
    """Geocode every term derived from the club name, country-filtered."""
    found: list[GeoPoint] = []
    attempted: list[str] = []
    for term in query_terms(club_name):
        attempted.append(term)
        try:
            point = await provider.geocode(term, country_code=country_code)
        except Exception as exc:  # noqa: BLE001 - a failed term is data, not a crash
            print(f"    ! {term!r}: {type(exc).__name__}", file=sys.stderr)
            point = None
        if point is not None and not any(
            haversine_km((point.latitude, point.longitude), (g.latitude, g.longitude)) < 0.5
            for g in found
        ):
            found.append(point)
        await asyncio.sleep(pause_seconds)
    return found, attempted


async def run(cache_dir: Path, out_path: Optional[Path], pause_seconds: float) -> dict[str, Any]:
    roster = corpus_roster(cache_dir)
    if not roster:
        raise SystemExit(f"no corpus files found under {cache_dir}")

    provider = OpenMeteoProvider(enabled=True)
    entries: list[dict[str, Any]] = []

    for index, club in enumerate(sorted(roster), start=1):
        divisions = sorted(roster[club])
        countries = {LEAGUE_COUNTRY[d] for d in divisions if d in LEAGUE_COUNTRY}
        if len(countries) != 1:
            entries.append({
                "club": club,
                "divisions": divisions,
                "country": None,
                "verdict": REQUIRES_REVIEW,
                "reason": "club_appears_in_more_than_one_country",
                "candidates": [],
                "queried": [],
            })
            continue

        country = countries.pop()
        found, attempted = await resolve_club(
            provider, club, country, pause_seconds=pause_seconds
        )
        verdict, reason, confirmed = classify(club, found)
        # Frozen dataclass -> hashable -> identity-safe membership check.
        # `confirmed` is filtered from this exact `found` list (see classify's
        # docstring), never copied, so `in` here is comparing the same objects.
        confirmed_set = set(confirmed)
        entries.append({
            "club": club,
            "divisions": divisions,
            "country": country,
            "verdict": verdict,
            "reason": reason,
            "candidates": [
                {
                    "name": g.name,
                    "latitude": round(g.latitude, 4),
                    "longitude": round(g.longitude, 4),
                    "country_code": g.country_code,
                    # The candidate classify() actually trusted -- see DEBT 101.
                    # Ingestion must read this one, never assume candidates[0].
                    "confirmed": g in confirmed_set,
                }
                for g in found
            ],
            "queried": attempted,
        })
        print(f"[{index:>3}/{len(roster)}] {club:<24} {country}  {verdict:<16} {reason}")

    counts = {v: sum(1 for e in entries if e["verdict"] == v) for v in (VERIFIED, REQUIRES_REVIEW, UNKNOWN)}
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": str(cache_dir),
        "roster_size": len(roster),
        "weather_cell_km": WEATHER_CELL_KM,
        "counts": counts,
        "coverage_verified": round(counts[VERIFIED] / len(roster), 4) if roster else 0.0,
        "entries": entries,
    }

    # DEBT 101's second follow-up: classify() sees one club at a time and
    # cannot itself apply the isolation rule, which needs the whole national
    # cluster. Applied here, once, on every regeneration, so a from-scratch
    # rerun cannot silently re-promote a club the way Espanol was VERIFIED --
    # shared with the offline gate via validate_venue_manifest._isolated_clubs
    # so the two cannot drift apart.
    # Loaded by path, not by module name: this script's own directory is
    # not reliably on sys.path (a direct `python qualify_venue_locations.py`
    # run adds it automatically; being imported as `scripts.qualify_venue_
    # locations` under pytest does not). The same pattern the tests for
    # both scripts already use.
    import importlib.util

    _vvm_path = Path(__file__).resolve().parent / "validate_venue_manifest.py"
    _vvm_spec = importlib.util.spec_from_file_location("_vvm_for_qualify", _vvm_path)
    assert _vvm_spec is not None and _vvm_spec.loader is not None
    _vvm = importlib.util.module_from_spec(_vvm_spec)
    _vvm_spec.loader.exec_module(_vvm)

    manifest, demoted = _vvm.demote_geographically_implausible(manifest)
    if demoted:
        print(f"demoted for geographic implausibility: {', '.join(demoted)}")
        counts = manifest["counts"]

    print("\n--- Gate G1 ---")
    for verdict, count in counts.items():
        print(f"{verdict:<16} {count:>4}  ({count / len(roster):.1%})")

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nmanifest -> {out_path}")
    return manifest


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=_BACKEND_ROOT / "data" / "cache")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--pause-seconds", type=float, default=0.2)
    args = parser.parse_args(list(argv) if argv is not None else None)
    asyncio.run(run(args.cache_dir, args.out, args.pause_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
