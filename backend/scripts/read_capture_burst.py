"""Read a matchday capture burst from production (directive v11 §4.3, M2, M3).

Run once after the last kickoff of a round (9 Oct after 19:00 UTC, 10 Oct after
the last game), instead of polling /health every five minutes:

    # backend/
    python scripts/read_capture_burst.py --since 2026-10-09T15:00:00Z

It reads ``/health`` → ``components.prediction_capture.recent`` (the passes that
had work to do, with the cgroup memory after each) and The Odds API quota from
``/api/v1/providers/evidence``, then applies M2's acceptance:

- every fixture that fell due was captured;
- the lowest working-set headroom across the burst is at least 100 MB;
- the instance did not restart since ``--since`` (a restart also erases the
  history, so it is itself a failure of M2).

Exit 0 on PASS, 1 on FAIL, 2 when there is nothing to read yet. It only reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.request import Request, urlopen

HEADROOM_FLOOR_MB = 100  # directive v11 M2
DEFAULT_BACKEND = "https://sabiscore-api-bav1.onrender.com"


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # /health's timestamp is aware; a naive --since is read as UTC, not a crash.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _ints(passes: list[dict[str, Any]], key: str) -> list[int]:
    return [p[key] for p in passes if isinstance(p.get(key), int)]


def summarize(
    health: dict[str, Any],
    evidence: Optional[dict[str, Any]] = None,
    since: Optional[str] = None,
) -> dict[str, Any]:
    capture = (health.get("components") or {}).get("prediction_capture") or {}
    passes: list[dict[str, Any]] = capture.get("recent") or []
    headroom = _ints(passes, "headroom_mb")
    due = sum(p.get("due") or 0 for p in passes)
    captured = sum(p.get("captured") or 0 for p in passes)

    checks: dict[str, Optional[bool]] = {
        "captured_equals_due": captured == due if due else None,
        "peak_headroom_ok": min(headroom) >= HEADROOM_FLOOR_MB if headroom else None,
    }
    uptime = health.get("uptime_seconds")
    if since is not None:
        # Asked for but not answerable (unparsable --since, no timestamp or
        # uptime) is None, so the verdict is INCOMPLETE, never a silent PASS.
        start, now = _parse(since), _parse(health.get("timestamp"))
        checks["no_restart_since"] = (
            uptime >= (now - start).total_seconds()
            if start and now and isinstance(uptime, (int, float))
            else None
        )

    quota = (((evidence or {}).get("providers") or {}).get("the_odds_api") or {}).get("quota") or {}
    if not passes:
        verdict = "NO_DATA"
    elif any(value is False for value in checks.values()):
        verdict = "FAIL"
    elif any(value is None for value in checks.values()):
        verdict = "INCOMPLETE"  # a figure M2 needs was not reported
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "checks": checks,
        "passes": len(passes),
        "due": due,
        "captured": captured,
        "errors": sum(p.get("errors") or 0 for p in passes),
        "min_headroom_mb": min(headroom) if headroom else None,
        "max_working_set_mb": max(_ints(passes, "working_set_mb"), default=None),
        "max_anon_mb": max(_ints(passes, "anon_mb"), default=None),
        "max_duration_ms": max((p.get("duration_ms") or 0 for p in passes), default=None),
        "uptime_seconds": uptime,
        "odds_quota_remaining": quota.get("remaining"),
        "odds_quota_used": quota.get("cost"),
    }


def _get(url: str) -> dict[str, Any]:
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=90) as response:
        return json.load(response)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--since", help="ISO time the burst began, for the restart check")
    args = parser.parse_args(argv)
    if args.since and _parse(args.since) is None:
        parser.error("--since must be an ISO time, e.g. 2026-10-09T15:00:00Z")
    health = _get(f"{args.backend}/health")
    try:
        evidence: Optional[dict[str, Any]] = _get(f"{args.backend}/api/v1/providers/evidence")
    except Exception:  # the quota is context for M3, not part of M2's verdict
        evidence = None
    report = summarize(health, evidence, args.since)
    print(json.dumps(report, indent=2))
    return {"PASS": 0, "NO_DATA": 2}.get(report["verdict"], 1)


if __name__ == "__main__":
    sys.exit(main())
