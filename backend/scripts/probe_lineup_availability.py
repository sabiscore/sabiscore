"""Experiment E2 feasibility probe — is historical lineup data acquirable?

Directive §43 Experiment E2 asks whether lineup continuity and expected-XI
state carry incremental signal. Portfolio B already established the SERVING
answer (`docs/DEBT.md` item 65 §2b): confirmed lineups publish 20-40 minutes
before kickoff, which fails Gate G5 for this platform's primary "browse
upcoming fixtures days ahead" surface.

That leaves one open question this probe answers, and only this one:

    Can a HISTORICAL lineup corpus be acquired on the subscribed plan, so that
    a retrospective Stage 1-3 information-value test is even possible?

Two requests, read-only. Deliberately minimal: `/injuries` returns a whole
league-season in one call (3,168 records, measured), but `/fixtures/lineups`
takes only a `fixture` parameter -- verified in
`src/providers/api_football.py:224` -- so acquisition cost scales with fixture
count, not league-season count. The probe measures whether the endpoint answers
at all and what it carries; the cost arithmetic follows from the endpoint shape
and does not need to be spent to be known.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/probe_lineup_availability.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))

import httpx  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.providers.api_football import APIFootballProvider  # noqa: E402

# A real season-2024 fixture id, surfaced by Portfolio B's own injuries probe
# (docs/DEBT.md item 65 §8) rather than guessed.
KNOWN_HISTORICAL_FIXTURE = 1208021

OUT = _BACKEND.parent / "reports" / "research" / "e2-lineup-availability-probe.json"

# Season fixture counts for the five scoreable leagues: 20-team leagues play
# 380, 18-team leagues 306. Used only for cost arithmetic, not fabricated data.
FIXTURES_PER_SEASON = {
    "EPL": 380,
    "LA_LIGA": 380,
    "SERIE_A": 380,
    "BUNDESLIGA": 306,
    "LIGUE_1": 306,
}
FREE_TIER_DAILY_QUOTA = 100


async def main() -> int:
    findings: dict[str, Any] = {
        "probe": "E2 historical lineup availability",
        "directive": "§43 Experiment E2; §15 Gates G1/G5; §41 kill criteria",
        "requests_spent": 0,
        "endpoint_shape": {
            "path": "/fixtures/lineups",
            "accepts_bulk_league_season_query": False,
            "evidence": (
                "src/providers/api_football.py:224 sends params={'fixture': id} "
                "only; there is no league/season form, unlike /injuries which "
                "Portfolio B measured returning 3,168 records for one "
                "league-season in a single call."
            ),
        },
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        # NB: the Settings attribute is `api_football_key`, not
        # `api_football_api_key` (the env var is API_FOOTBALL_API_KEY). Getting
        # this wrong is what made docs/DEBT.md item 65 first misdiagnose real
        # credentials as absent.
        provider = APIFootballProvider(
            api_key=settings.api_football_key,
            enabled=True,
            live_tests=True,
            http_client=client,
        )

        print(f"1) lineups(fixture_id={KNOWN_HISTORICAL_FIXTURE}) ...")
        result = await provider.lineups(fixture_id=KNOWN_HISTORICAL_FIXTURE)
        findings["requests_spent"] += 1
        records = result.records or []
        findings["historical_fixture_probe"] = {
            "fixture_id": KNOWN_HISTORICAL_FIXTURE,
            "status": str(result.status),
            "error_code": result.error_code,
            "record_count": len(records),
            "warnings": list(result.warnings or [])[:5],
            "sample_record_keys": sorted(records[0].keys()) if records else None,
            "sample_record": records[0] if records else None,
            "quota": result.quota.model_dump(mode="json") if result.quota else None,
        }
        print(
            f"   -> {result.status} | {len(records)} records | {result.error_code or 'no error'}"
        )

    # ---- feasibility arithmetic (derived from the endpoint shape, not guessed)
    per_season = sum(FIXTURES_PER_SEASON.values())
    findings["acquisition_cost"] = {
        "requests_per_season_5_leagues": per_season,
        "free_tier_daily_quota": FREE_TIER_DAILY_QUOTA,
        "days_of_full_quota_per_season": round(per_season / FREE_TIER_DAILY_QUOTA, 1),
        "note": (
            "Continuity metrics (expected-XI overlap, positional disruption) "
            "need consecutive fixtures per team, so a usable study needs "
            "essentially the whole season, not a sample. One request per "
            "fixture is the only available shape."
        ),
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(findings, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nrequests spent: {findings['requests_spent']}")
    print(
        f"cost for one season x 5 leagues: {per_season} requests = "
        f"{findings['acquisition_cost']['days_of_full_quota_per_season']} days of full free-tier quota"
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
