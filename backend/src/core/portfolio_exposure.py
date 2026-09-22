"""Advisory portfolio-exposure policy (ADR-0005).

Stateless — no persistence, no I/O. This platform places no stake by
construction (``EXECUTE_BET`` does not exist), so "concurrently recommended"
has no meaning beyond "co-present in one in-memory batch response." There is
no other notion of an open position to query across requests.

Three advisory policies, computed and surfaced but never gating or resizing
a live recommendation:

(a) Aggregate open-exposure cap — a bankroll-% ceiling summed across every
    ``has_value`` fixture in the batch. Exceeding it *flags* later-ranked
    (lowest-edge) fixtures; it never suppresses or silently resizes them.
(b) Same-matchday/same-league correlation haircut — fixtures sharing a
    (canonical league, UTC calendar day) key have their individual Kelly
    stake reduced by a haircut that grows with the group size, floored so it
    never removes more than half the stake.
(c) Bankroll drawdown limit — stubbed honestly. No settled positions exist
    yet to compute a real drawdown from; this never fabricates a ``0.0``.

Constants below are reasoned starting points, not calibrated against real
same-matchday settlement outcomes (none exist yet — see docs/DEBT.md item 9).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .league_policy import (
    LeaguePolicyUnavailableError,
    canonical_league_id,
    get_league_policy,
)

# aggregate cap = this multiple of the largest per-league kelly_cap present in
# the batch — reuses an existing deliberated number rather than a fresh
# invented percentage.
AGGREGATE_CAP_MULTIPLIER = 3.0
HAIRCUT_PER_ADDITIONAL_FIXTURE = 0.10
HAIRCUT_FLOOR_MULTIPLIER = 0.50
PORTFOLIO_POLICY_SOURCE = (
    "DEFAULT_PENDING_CALIBRATION"  # mirrors LeaguePolicy's own vocabulary
)
_FALLBACK_KELLY_CAP = 0.05  # matches models/prediction.py's MAX_KELLY_CAP


def haircut_multiplier(n: int) -> float:
    """Stake multiplier for a same-league/same-day group of size n."""
    if n <= 1:
        return 1.0
    return max(HAIRCUT_FLOOR_MULTIPLIER, 1.0 - HAIRCUT_PER_ADDITIONAL_FIXTURE * (n - 1))


def drawdown_status() -> Dict[str, Any]:
    """Policy (c) stub. Always honest about lacking settled-position data —
    reuses the exact reason string /model-performance already established
    (docs/DEBT.md item 2), never a fabricated 0.0. Real wiring point:
    rl_agent.py's `current_drawdown` field, once a real settled-position
    query exists — not built here."""
    return {
        "status": "insufficient_settled_predictions",
        "realized_drawdown_pct": None,
        "paused": False,
    }


def _is_flagged(match: Dict[str, Any]) -> bool:
    return bool(match.get("has_value")) and match.get("best_value_bet") is not None


def _utc_day(match_date: str) -> str:
    try:
        dt = datetime.fromisoformat(str(match_date).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()
    except (ValueError, TypeError):
        return str(match_date)[:10]  # best-effort, never raises


def _group_key(match: Dict[str, Any]) -> Tuple[str, str]:
    raw_league = str(match.get("league") or "")
    try:
        league = canonical_league_id(raw_league)
    except LeaguePolicyUnavailableError:
        league = "UNKNOWN"
    return (league, _utc_day(str(match.get("match_date") or "")))


def _league_cap(match: Dict[str, Any]) -> Optional[float]:
    try:
        return min(
            get_league_policy(str(match.get("league") or "")).kelly_cap,
            _FALLBACK_KELLY_CAP,
        )
    except LeaguePolicyUnavailableError:
        return None


def compute_portfolio_exposure(matches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Adds a `portfolio` key to each flagged match in place (None on
    unflagged matches) — strictly additive, never touches value_bets/
    best_value_bet/kelly_stake_pct. Returns the batch-level summary.
    """
    flagged = [m for m in matches if _is_flagged(m)]

    group_sizes: Dict[Tuple[str, str], int] = defaultdict(int)
    for m in flagged:
        group_sizes[_group_key(m)] += 1

    for m in matches:
        if not _is_flagged(m):
            m["portfolio"] = None
            continue
        n = group_sizes[_group_key(m)]
        raw = float(m["best_value_bet"].get("kelly_stake_pct", 0.0))
        mult = haircut_multiplier(n)
        m["portfolio"] = {
            "raw_kelly_stake_pct": round(raw, 2),
            "correlation_group_size": n,
            "correlation_haircut_multiplier": round(mult, 2),
            "adjusted_kelly_stake_pct": round(raw * mult, 2),
            "exceeds_aggregate_cap": False,  # set below, in edge-ranked order
        }

    caps = [c for c in (_league_cap(m) for m in flagged) if c is not None]
    aggregate_cap_pct = round(
        AGGREGATE_CAP_MULTIPLIER * (max(caps) if caps else _FALLBACK_KELLY_CAP) * 100, 2
    )

    ranked = sorted(
        flagged,
        key=lambda m: float(m["best_value_bet"].get("edge_pct", 0.0)),
        reverse=True,
    )
    running_total = 0.0
    for m in ranked:
        running_total += m["portfolio"]["adjusted_kelly_stake_pct"]
        m["portfolio"]["exceeds_aggregate_cap"] = running_total > aggregate_cap_pct

    return {
        "aggregate_recommended_pct": round(running_total, 2),
        "aggregate_cap_pct": aggregate_cap_pct,
        "exceeds_aggregate_cap": running_total > aggregate_cap_pct,
        "drawdown": drawdown_status(),
    }
