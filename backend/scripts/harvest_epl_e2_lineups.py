"""E2 — EPL-scoped lineup harvester (resumable, quota-bounded).

Directive v5 §15 Gate G5, §32 (raw data retention), §34 (failure semantics),
§35 (compute policy). Contract: `contracts/lineup_harvest_epl_contract.yaml`.

WHAT THIS CAN AND CANNOT ESTABLISH
----------------------------------
It harvests lineup CONTENT (starters, formation) for EPL 2024/2025 — the raw
material E2's continuity features need — one fixture per request, resumable
across the 100-call daily free-tier quota.

It CANNOT establish Gate G5. API-Football `/fixtures/lineups` returns no
announcement timestamp (measured: `reports/research/e2-lineup-availability-probe.json`
sample_record_keys has no temporal field), so `lead_time_minutes` is not
derivable and `servable_at_cutoff` is written as the literal `UNKNOWN`. Per §5
a missing value is a state of knowledge, not a measurement — this script will
not infer a lead time it cannot observe. See the contract header for the
prospective probe design that *can* answer G5.

Resumability: every fetched fixture is appended to a JSONL checkpoint before
the next request, so an interrupted or quota-exhausted run resumes exactly
where it stopped. Re-running is idempotent — already-harvested fixture ids are
skipped without spending quota.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/harvest_epl_e2_lineups.py --dry-run
    cd backend && PYTHONPATH=. python scripts/harvest_epl_e2_lineups.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

_CONTRACT_PATH = _REPO_ROOT.parent / "contracts" / "lineup_harvest_epl_contract.yaml"
_CHECKPOINT = _REPO_ROOT / "data" / "cache" / "lineup_harvest_epl.jsonl"

# Mirrors the contract. Kept as module constants so a drifted contract is
# caught by the loader below rather than silently ignored.
LEAGUE = "EPL"
SEASON_LABEL = "2024/2025"
HARVEST_BATCH_SIZE = 95
DAILY_CALL_LIMIT = 100
THROTTLE_SLEEP_SECONDS = 1.2
CUTOFF_MINUTES_PRE_KICKOFF = 20

_SERVABLE_UNKNOWN = "UNKNOWN"


@dataclass
class HarvestState:
    """What has already been written, so a resumed run spends no quota twice."""

    harvested: Set[int] = field(default_factory=set)
    rows: int = 0

    @classmethod
    def load(cls, path: Path) -> "HarvestState":
        state = cls()
        if not path.exists():
            return state
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # A partially-written final line from a killed process.
                    # Skip it; the fixture simply gets re-fetched.
                    continue
                fixture_id = record.get("fixture_id")
                if isinstance(fixture_id, int):
                    state.harvested.add(fixture_id)
                    state.rows += 1
        return state


def load_contract() -> Dict[str, Any]:
    """Read the contract and fail closed if it disagrees with this script."""
    import yaml

    contract = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    target = contract["target_competition"]
    policy = contract["rate_limit_policy"]

    mismatches = []
    if target["canonical_league_id"] != LEAGUE:
        mismatches.append(f"league {target['canonical_league_id']!r} != {LEAGUE!r}")
    if target["season"] != SEASON_LABEL:
        mismatches.append(f"season {target['season']!r} != {SEASON_LABEL!r}")
    if policy["harvest_batch_size"] != HARVEST_BATCH_SIZE:
        mismatches.append(
            f"batch {policy['harvest_batch_size']} != {HARVEST_BATCH_SIZE}"
        )
    if mismatches:
        raise ValueError(
            "harvester disagrees with its contract: " + "; ".join(mismatches)
        )
    if policy["harvest_batch_size"] >= policy["daily_call_limit"]:
        raise ValueError(
            "harvest_batch_size must leave headroom under daily_call_limit"
        )
    return contract


def _normalise_lineup(
    fixture_id: int, kickoff_utc: str | None, records: Iterable[dict]
) -> Dict[str, Any]:
    """Fold provider records into one contract-shaped row.

    Two teams per fixture; the first team encountered is treated as home only
    when the caller supplies the home team id, otherwise both sides are stored
    under their provider team id and resolution is left to the consumer. No
    guessing: an unresolvable side stays null rather than being assigned.
    """
    by_team: Dict[int, Dict[str, Any]] = {}
    for record in records:
        team_id = record.get("team_id")
        if team_id is None:
            continue
        slot = by_team.setdefault(
            team_id,
            {
                "team_id": team_id,
                "team_name": record.get("team_name"),
                "formation": record.get("formation"),
                "starters": [],
            },
        )
        if record.get("role") == "starting" and record.get("player_id") is not None:
            slot["starters"].append(record["player_id"])

    teams = list(by_team.values())
    confirmed = len(teams) == 2 and all(len(t["starters"]) == 11 for t in teams)
    return {
        "fixture_id": fixture_id,
        "kickoff_time_utc": kickoff_utc,
        # §5: declared in the contract, never populated — the source has no
        # announcement timestamp. Writing a value here would be fabrication.
        "lineup_announced_utc": None,
        "lead_time_minutes": None,
        "servable_at_cutoff": _SERVABLE_UNKNOWN,
        "cutoff_minutes_pre_kickoff": CUTOFF_MINUTES_PRE_KICKOFF,
        "is_confirmed": confirmed,
        "teams": teams,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def _append(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        handle.flush()


def fixtures_to_harvest(
    state: HarvestState, fixture_ids: List[int], batch: int
) -> List[int]:
    pending = [f for f in fixture_ids if f not in state.harvested]
    return pending[:batch]


# ---------------------------------------------------------------------------
# SUSPENDED 2026-09-11 — quota is reserved for the prospective G5 monitor.
#
# This harvest yields lineup CONTENT for continuity features but provably
# cannot answer Gate G5 (no announcement timestamp; see the module docstring).
# `shadow_monitor_e2_lineups.py` measures G5 prospectively and needs the same
# 100-call daily budget, so the historical batch is halted rather than allowed
# to race it for quota. Re-enable with --i-understand-this-does-not-answer-g5
# once G5 is settled or a paid plan lifts the quota.
# ---------------------------------------------------------------------------
SUSPENDED = True
SUSPENSION_REASON = (
    "suspended 2026-09-11: the 100-call/day quota is reserved for "
    "shadow_monitor_e2_lineups.py, which measures Gate G5 prospectively. "
    "This harvest cannot answer G5 (docs/DEBT.md item 80)."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="report the plan and spend no quota"
    )
    parser.add_argument(
        "--i-understand-this-does-not-answer-g5",
        action="store_true",
        dest="override_suspension",
        help="resume the suspended historical harvest and spend quota on it",
    )
    parser.add_argument("--batch-size", type=int, default=HARVEST_BATCH_SIZE)
    parser.add_argument(
        "--fixture-ids",
        type=Path,
        default=None,
        help="JSON list of provider fixture ids for EPL 2024/2025",
    )
    args = parser.parse_args()

    if SUSPENDED and not args.override_suspension and not args.dry_run:
        logger.error("HALTED — %s", SUSPENSION_REASON)
        print(
            json.dumps(
                {
                    "status": "SUSPENDED",
                    "reason": SUSPENSION_REASON,
                    "requests_spent": 0,
                },
                indent=2,
            )
        )
        return 0

    contract = load_contract()
    if args.batch_size > DAILY_CALL_LIMIT - 5:
        raise ValueError(
            f"--batch-size {args.batch_size} leaves under 5 calls of headroom "
            f"against the {DAILY_CALL_LIMIT}-call daily quota"
        )

    state = HarvestState.load(_CHECKPOINT)
    logger.info(
        "Checkpoint %s: %d fixtures already harvested",
        _CHECKPOINT.name,
        len(state.harvested),
    )

    if args.fixture_ids is None:
        logger.warning(
            "No --fixture-ids supplied. Provider fixture ids for %s %s must be "
            "resolved before harvesting; this script does not mint or guess them.",
            LEAGUE,
            SEASON_LABEL,
        )
        fixture_ids: List[int] = []
    else:
        fixture_ids = json.loads(args.fixture_ids.read_text(encoding="utf-8"))

    todo = fixtures_to_harvest(state, fixture_ids, args.batch_size)
    expected_total = contract["target_competition"]["fixture_count"]
    logger.info(
        "Plan: %d of %d EPL fixtures pending; this run would fetch %d "
        "(batch %d, %.1fs throttle, ~%.1f min)",
        max(expected_total - len(state.harvested), 0),
        expected_total,
        len(todo),
        args.batch_size,
        THROTTLE_SLEEP_SECONDS,
        len(todo) * THROTTLE_SLEEP_SECONDS / 60.0,
    )
    logger.warning(
        "Gate G5 is NOT answerable from this harvest: the endpoint publishes no "
        "announcement timestamp, so every row records servable_at_cutoff=%s. "
        "See the contract header for the prospective probe that can answer it.",
        _SERVABLE_UNKNOWN,
    )

    if args.dry_run or not todo:
        print(
            json.dumps(
                {
                    "already_harvested": len(state.harvested),
                    "pending_this_run": len(todo),
                    "g5_answerable": False,
                    "dry_run": bool(args.dry_run),
                },
                indent=2,
            )
        )
        return 0

    # Provider import is deferred: --dry-run must work with no credentials.
    import asyncio

    from src.providers.api_football import APIFootballProvider  # noqa: WPS433

    async def run() -> int:
        provider = APIFootballProvider()
        spent = 0
        for fixture_id in todo:
            try:
                # Keyword name is `fixture_id`, not `fixture` — a mismatch here
                # is a TypeError on every call, the vΩ.32 defect shape.
                result = await provider.lineups(fixture_id=fixture_id)
            except Exception as exc:  # noqa: BLE001
                # §34 State D: record the failure, never a fabricated lineup.
                logger.error("fixture %s: %s — not written", fixture_id, exc)
                break
            spent += 1
            records = getattr(result, "records", None) or []
            _append(_CHECKPOINT, _normalise_lineup(fixture_id, None, records))
            time.sleep(THROTTLE_SLEEP_SECONDS)
        return spent

    spent = asyncio.run(run())
    logger.info("Harvest complete: %d requests spent this run", spent)
    print(json.dumps({"requests_spent": spent, "g5_answerable": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
