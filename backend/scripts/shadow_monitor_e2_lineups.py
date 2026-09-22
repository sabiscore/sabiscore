"""E2 — prospective Gate G5 monitor for lineup availability at the cutoff.

Directive v5 §3 (Rule 3: pre-match information is the unit of truth),
§15 Gate G5, §34 (production failure semantics), §39 (SHADOW state).
Contract: `contracts/lineup_harvest_epl_contract.yaml`.

WHY PROSPECTIVE
---------------
Gate G5 asks: *is this information available at the prediction cutoff?*
API-Football `/fixtures/lineups` publishes no announcement timestamp, so that
question is unanswerable from historical data — a fetch today returns the final
confirmed lineup with no record of when it appeared (docs/DEBT.md item 80).
The only way to measure it is to stand at the cutoff and look: poll upcoming
fixtures at T-20m and record whether a lineup exists at that moment.

WHY A WINDOW POLLER AND NOT A SLEEPING DAEMON
----------------------------------------------
"Wake exactly at T-20m" is implemented as a scheduled sweep over a bounded
window rather than a process that sleeps until a timestamp. A sleeping daemon
loses every pending fixture when it restarts, and a redeploy is routine on this
platform. This script is idempotent and crash-safe: run it every few minutes
from cron or a scheduler, and it polls whichever fixtures are currently inside
the window and have not already been recorded.

THE HONESTY RULE THIS SCRIPT EXISTS TO PROTECT
-----------------------------------------------
A missing lineup and a failed request are different facts. Recording a
transport error, an auth failure or an open circuit as `FALSE` would
manufacture G5 evidence out of our own outage — the "inability to confirm is
not an outage" principle this codebase already applies to its keep-alive and
capability probes. Four terminal states, never collapsed:

    TRUE           provider answered and a coherent lineup was present
    FALSE          provider answered and no lineup was published yet
    POLL_FAILED    provider did not answer (error, circuit, auth, timeout)
    MISSED_WINDOW  kickoff passed without the fixture ever being polled

Only TRUE and FALSE are G5 evidence. The other two are operational facts and
are excluded from the rate.

Usage
-----
    # plan only, no network, no quota
    cd backend && PYTHONPATH=. python scripts/shadow_monitor_e2_lineups.py --dry-run

    # real sweep (intended to run on a schedule)
    cd backend && PYTHONPATH=. python scripts/shadow_monitor_e2_lineups.py

    # report G5 from what has accumulated
    cd backend && PYTHONPATH=. python scripts/shadow_monitor_e2_lineups.py --report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

_CONTRACT_PATH = _REPO_ROOT.parent / "contracts" / "lineup_harvest_epl_contract.yaml"
_LOG_PATH = _REPO_ROOT / "data" / "cache" / "lineup_g5_prospective_log.jsonl"

CUTOFF_MINUTES_PRE_KICKOFF = 20
# Lower edge of the polling band. A sweep that arrives late still counts, but
# only until T-15m; past that the observation is no longer "at the cutoff" and
# the fixture is recorded MISSED_WINDOW rather than silently scored.
FAIL_CLOSED_MINUTES = 15
DAILY_CALL_LIMIT = 100
MAX_POLLS_PER_SWEEP = 40

STATE_TRUE = "TRUE"
STATE_FALSE = "FALSE"
STATE_POLL_FAILED = "POLL_FAILED"
STATE_MISSED_WINDOW = "MISSED_WINDOW"
_TERMINAL = {STATE_TRUE, STATE_FALSE, STATE_MISSED_WINDOW}
_G5_EVIDENCE = {STATE_TRUE, STATE_FALSE}


def load_contract() -> Dict[str, Any]:
    import yaml

    contract = yaml.safe_load(_CONTRACT_PATH.read_text(encoding="utf-8"))
    semantics = contract["cutoff_and_lineup_semantics"]
    if semantics["target_cutoff_minutes_pre_kickoff"] != CUTOFF_MINUTES_PRE_KICKOFF:
        raise ValueError(
            "monitor disagrees with its contract on the cutoff: "
            f"{semantics['target_cutoff_minutes_pre_kickoff']} != {CUTOFF_MINUTES_PRE_KICKOFF}"
        )
    if semantics["fail_closed_threshold_minutes"] != FAIL_CLOSED_MINUTES:
        raise ValueError(
            "monitor disagrees with its contract on the fail-closed threshold: "
            f"{semantics['fail_closed_threshold_minutes']} != {FAIL_CLOSED_MINUTES}"
        )
    return contract


def load_log(path: Path) -> Dict[int, str]:
    """fixture_id -> most recent terminal state. POLL_FAILED is retryable."""
    states: Dict[int, str] = {}
    if not path.exists():
        return states
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # truncated final line from a killed process
            fixture_id, state = (
                record.get("fixture_id"),
                record.get("servable_at_20m_cutoff"),
            )
            if isinstance(fixture_id, int) and state:
                states[fixture_id] = state
    return states


def _append(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        handle.flush()


def _parse_kickoff(raw: str) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def classify_fixture(kickoff_utc: datetime, now: datetime, already: str | None) -> str:
    """Which action this fixture needs right now.

    POLL           inside [T-20m, T-15m] and not yet recorded
    WAIT           kickoff still further out than the cutoff
    MISSED_WINDOW  cutoff band has passed with nothing recorded
    DONE           already carries a terminal state
    """
    if already in _TERMINAL:
        return "DONE"
    minutes_to_kickoff = (kickoff_utc - now).total_seconds() / 60.0
    if minutes_to_kickoff > CUTOFF_MINUTES_PRE_KICKOFF:
        return "WAIT"
    if minutes_to_kickoff >= FAIL_CLOSED_MINUTES:
        return "POLL"
    return "MISSED_WINDOW"


def classify_result(status: Any, records: List[dict], error_code: str | None) -> str:
    """Turn a provider response into a G5 state — never conflating the two nulls.

    A provider that answered and published nothing is FALSE (real G5 evidence).
    A provider that did not answer is POLL_FAILED (an operational fact about us,
    not about lineup availability).
    """
    status_name = getattr(status, "name", str(status)).upper()
    if status_name != "VERIFIED":
        return STATE_POLL_FAILED
    if error_code:
        return STATE_POLL_FAILED
    starters = [r for r in records if (r or {}).get("role") == "starting"]
    return STATE_TRUE if starters else STATE_FALSE


def load_fixtures(path: Path | None) -> List[Dict[str, Any]]:
    """Upcoming fixtures as [{fixture_id, kickoff_utc, league}].

    Read from a file so the monitor stays decoupled from the DB import chain
    (`core/database.py` opens a connection at import, docs/DEBT.md item 7) and
    so --dry-run needs no credentials. A scheduler supplies the file from
    whichever upcoming-fixture source is authoritative at the time.
    """
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    fixtures = (
        payload.get("fixtures", payload) if isinstance(payload, dict) else payload
    )
    out: List[Dict[str, Any]] = []
    for item in fixtures:
        fixture_id = item.get("fixture_id") or item.get("id")
        kickoff = _parse_kickoff(
            str(item.get("kickoff_utc") or item.get("match_date") or "")
        )
        if fixture_id is None or kickoff is None:
            continue  # §5: a fixture we cannot time is skipped, never guessed
        out.append(
            {
                "fixture_id": int(fixture_id),
                "kickoff_utc": kickoff,
                "league": item.get("league") or item.get("competition"),
            }
        )
    return out


def summarise(path: Path) -> Dict[str, Any]:
    """Gate G5 from what has actually been observed."""
    counts: Dict[str, int] = {}
    seen: Set[int] = set()
    if path.exists():
        for fixture_id, state in load_log(path).items():
            seen.add(fixture_id)
            counts[state] = counts.get(state, 0) + 1
    evidence = sum(counts.get(s, 0) for s in _G5_EVIDENCE)
    servable = counts.get(STATE_TRUE, 0)
    return {
        "fixtures_observed": len(seen),
        "counts": counts,
        "g5_evidence_rows": evidence,
        "g5_servable_at_cutoff_pct": (
            round(100.0 * servable / evidence, 2) if evidence else None
        ),
        "note": (
            "POLL_FAILED and MISSED_WINDOW are operational facts, not lineup "
            "availability, and are excluded from the rate."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="plan only; no network, no quota"
    )
    parser.add_argument(
        "--report", action="store_true", help="summarise the accumulated log and exit"
    )
    parser.add_argument(
        "--fixtures-file",
        type=Path,
        default=None,
        help="JSON of upcoming fixtures [{fixture_id, kickoff_utc, league}]",
    )
    parser.add_argument("--max-polls", type=int, default=MAX_POLLS_PER_SWEEP)
    parser.add_argument(
        "--now", type=str, default=None, help="override current UTC time (testing)"
    )
    args = parser.parse_args()

    load_contract()

    if args.report:
        print(json.dumps(summarise(_LOG_PATH), indent=2))
        return 0

    if args.max_polls > DAILY_CALL_LIMIT - 5:
        raise ValueError(
            f"--max-polls {args.max_polls} leaves under 5 calls of headroom "
            f"against the {DAILY_CALL_LIMIT}-call daily quota"
        )

    now = _parse_kickoff(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        raise ValueError(f"--now is not an ISO-8601 timestamp: {args.now!r}")

    recorded = load_log(_LOG_PATH)
    fixtures = load_fixtures(args.fixtures_file)
    if not fixtures:
        logger.warning(
            "No upcoming fixtures supplied (--fixtures-file). This monitor does "
            "not invent a schedule; supply one from the authoritative source."
        )

    buckets: Dict[str, List[Dict[str, Any]]] = {
        "POLL": [],
        "WAIT": [],
        "MISSED_WINDOW": [],
        "DONE": [],
    }
    for fixture in fixtures:
        buckets[
            classify_fixture(
                fixture["kickoff_utc"], now, recorded.get(fixture["fixture_id"])
            )
        ].append(fixture)

    logger.info(
        "Sweep at %s — %d to poll, %d waiting, %d missed, %d already recorded",
        now.isoformat(),
        len(buckets["POLL"]),
        len(buckets["WAIT"]),
        len(buckets["MISSED_WINDOW"]),
        len(buckets["DONE"]),
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "now": now.isoformat(),
                    "to_poll": len(buckets["POLL"]),
                    "waiting": len(buckets["WAIT"]),
                    "missed_window": len(buckets["MISSED_WINDOW"]),
                    "already_recorded": len(buckets["DONE"]),
                    "dry_run": True,
                },
                indent=2,
            )
        )
        return 0

    # A missed window is recorded without spending quota — it is a fact about
    # scheduling, established by the clock alone.
    for fixture in buckets["MISSED_WINDOW"]:
        _append(
            _LOG_PATH,
            {
                "fixture_id": fixture["fixture_id"],
                "league": fixture["league"],
                "kickoff_utc": fixture["kickoff_utc"].isoformat(),
                "cutoff_minutes_pre_kickoff": CUTOFF_MINUTES_PRE_KICKOFF,
                "servable_at_20m_cutoff": STATE_MISSED_WINDOW,
                "observed_at_utc": now.isoformat(),
            },
        )

    todo = buckets["POLL"][: args.max_polls]
    if not todo:
        print(
            json.dumps(
                {"polled": 0, "missed_recorded": len(buckets["MISSED_WINDOW"])},
                indent=2,
            )
        )
        return 0

    import asyncio

    from src.providers.api_football import APIFootballProvider  # noqa: WPS433

    async def sweep() -> Dict[str, int]:
        provider = APIFootballProvider()
        tally: Dict[str, int] = {}
        for fixture in todo:
            observed = datetime.now(timezone.utc)
            lead = (fixture["kickoff_utc"] - observed).total_seconds() / 60.0
            try:
                # Keyword is `fixture_id`; see api_football.lineups signature.
                result = await provider.lineups(fixture_id=fixture["fixture_id"])
                state = classify_result(
                    result.status, result.records or [], result.error_code
                )
                error = result.error_code
            except Exception as exc:  # noqa: BLE001
                # §34: our failure is never recorded as the provider's absence.
                state, error = STATE_POLL_FAILED, type(exc).__name__
                logger.error("fixture %s: poll failed — %s", fixture["fixture_id"], exc)
            _append(
                _LOG_PATH,
                {
                    "fixture_id": fixture["fixture_id"],
                    "league": fixture["league"],
                    "kickoff_utc": fixture["kickoff_utc"].isoformat(),
                    "cutoff_minutes_pre_kickoff": CUTOFF_MINUTES_PRE_KICKOFF,
                    "observed_lead_time_minutes": round(lead, 2),
                    "servable_at_20m_cutoff": state,
                    "error_code": error,
                    "observed_at_utc": observed.isoformat(),
                },
            )
            tally[state] = tally.get(state, 0) + 1
        return tally

    tally = asyncio.run(sweep())
    logger.info("Sweep complete: %s", tally)
    print(
        json.dumps(
            {
                "polled": sum(tally.values()),
                "by_state": tally,
                "missed_recorded": len(buckets["MISSED_WINDOW"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
