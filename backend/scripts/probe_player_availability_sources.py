#!/usr/bin/env python3
"""Live probe for docs/DEBT.md item 65 — Portfolio B (player availability).

Answers, with a real credential, the questions the Gate R1 qualification
study (reports/research/portfolio-b-player-availability-source-qualification.md)
could not answer from documentation alone:

  1. Does api_football's /injuries respond at all on this subscription, and
     what does the real response shape look like (does each record really
     carry a per-record fixture.id, as the test fixture already assumed)?
  2. What is the actual subscribed rate-limit tier (read from response
     headers — never hardcoded, per api_football.py's own design)?
  3. Does the NEW fixture-scoped query mode (--fixture-id on injuries())
     added this session actually work, using a real fixture id harvested
     from (1) rather than a guessed one?
  4. Does sportmonks' injuries() (the bare /sidelined call) actually 404,
     as its own probe() docstring already suspects from a 2026-07-04 note?

CREDENTIAL SAFETY (non-negotiable, matches every other provider adapter in
this codebase): the API key is read ONLY via settings.api_football_key /
settings.sportmonks_api_key (pydantic-settings, from the existing .env /
backend/.env — never passed on the command line, never printed, never
included in any exception message this script prints). ProviderResult
objects from this codebase's own adapters never carry auth material by
construction (checked before writing this script) — only status, records,
quota, warnings. This script prints records and summary fields, which are
public sports data (player/team names, injury types), never headers or the
raw payload.

Read-only. Makes at most 3 GET requests total (one broad api_football call,
one fixture-scoped follow-up using an id harvested from the first response,
one sportmonks call). No writes, no DB access, no orchestrator involvement.

Usage:
    cd backend
    PYTHONPATH=. python scripts/probe_player_availability_sources.py [--competition EPL]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import httpx  # noqa: E402

from src.core.config import settings  # noqa: E402
from src.providers.api_football import APIFootballProvider  # noqa: E402
from src.providers.sportmonks import SportmonksProvider  # noqa: E402


def _redact(value: object) -> str:
    """Never trust a caller to remember to redact — the print helper does it."""
    text = str(value)
    for secret in (settings.api_football_key, settings.sportmonks_api_key):
        if secret:
            text = text.replace(secret, "***REDACTED***")
    return text


def _print(label: str, value: object) -> None:
    print(f"{label}: {_redact(value)}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--competition", default="EPL")
    args = parser.parse_args()

    if not settings.api_football_key and not settings.sportmonks_api_key:
        print("No api_football or sportmonks credential configured — nothing to probe.")
        return 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        print("=" * 70)
        print(
            f"1) api_football.injuries(competition={args.competition!r}) — broad query"
        )
        print("=" * 70)
        api_football = APIFootballProvider(
            api_key=settings.api_football_key,
            enabled=True,
            live_tests=True,
            http_client=client,
        )
        broad = await api_football.injuries(competition=args.competition)
        _print("status", broad.status)
        _print("error_code", broad.error_code)
        _print("record_count", len(broad.records))
        _print("quota", broad.quota)
        _print("warnings (first 3)", broad.warnings[:3])
        harvested_fixture_id = None
        for record in broad.records:
            if record.get("coherent") and record.get("fixture_id"):
                harvested_fixture_id = record["fixture_id"]
                _print(
                    "sample_record",
                    {
                        "player_name": record.get("player_name"),
                        "team_name": record.get("team_name"),
                        "fixture_id": record.get("fixture_id"),
                        "injury_type": record.get("injury_type"),
                        "reason": record.get("reason"),
                    },
                )
                break
        if harvested_fixture_id is None:
            print(
                "No coherent record with a fixture_id found — cannot test fixture-scoped mode."
            )

        print()
        print("=" * 70)
        print(
            "1b) api_football.injuries(competition=%r, season=2024) — plan-permitted season"
            % args.competition
        )
        print("=" * 70)
        historical = await api_football.injuries(
            competition=args.competition, season=2024
        )
        _print("status", historical.status)
        _print("error_code", historical.error_code)
        _print("record_count", len(historical.records))
        _print("quota", historical.quota)
        _print("warnings (first 3)", historical.warnings[:3])
        if harvested_fixture_id is None:
            for record in historical.records:
                if record.get("coherent") and record.get("fixture_id"):
                    harvested_fixture_id = record["fixture_id"]
                    _print(
                        "sample_record",
                        {
                            "player_name": record.get("player_name"),
                            "team_name": record.get("team_name"),
                            "fixture_id": record.get("fixture_id"),
                            "injury_type": record.get("injury_type"),
                            "reason": record.get("reason"),
                        },
                    )
                    break

        if harvested_fixture_id is not None:
            print()
            print("=" * 70)
            print(
                f"2) api_football.injuries(fixture_id={harvested_fixture_id}) — scoped query"
            )
            print("=" * 70)
            scoped = await api_football.injuries(
                competition=args.competition, fixture_id=harvested_fixture_id
            )
            _print("status", scoped.status)
            _print("error_code", scoped.error_code)
            _print("record_count", len(scoped.records))
            _print("quota", scoped.quota)
            fixture_ids_in_scoped = {
                r.get("fixture_id") for r in scoped.records if r.get("coherent")
            }
            _print("distinct_fixture_ids_returned", fixture_ids_in_scoped)
            _print(
                "scoped_query_actually_scoped",
                fixture_ids_in_scoped == {harvested_fixture_id}
                if scoped.records
                else "no_records",
            )

        print()
        print("=" * 70)
        print(
            f"3) sportmonks.injuries(competition={args.competition!r}) — bare /sidelined"
        )
        print("=" * 70)
        if settings.sportmonks_api_key:
            sportmonks = SportmonksProvider(
                api_key=settings.sportmonks_api_key,
                enabled=True,
                live_tests=True,
                http_client=client,
            )
            sm_result = await sportmonks.injuries(competition=args.competition)
            _print("status", sm_result.status)
            _print("error_code", sm_result.error_code)
            _print("record_count", len(sm_result.records))
            _print("warnings (first 3)", sm_result.warnings[:3])
        else:
            print("No sportmonks credential configured — skipped.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
