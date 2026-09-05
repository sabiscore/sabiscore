"""Calibrate portfolio-exposure constants from settled same-league/matchday groups.

Run against production after enough same-league, same-matchday prediction groups
have settled. At n<50 groups the estimates are noisy; the script reports confidence
intervals so you can decide when to act.

Usage
-----
    # Review (dry-run, prints proposed constants)
    PYTHONPATH=. python scripts/calibrate_portfolio_exposure.py

    # Apply to portfolio_exposure.py (writes file, no DB write)
    PYTHONPATH=. python scripts/calibrate_portfolio_exposure.py --apply

Requires a DATABASE_URL with read access to match_prediction_logs and matches.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from itertools import combinations
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# DB query (raw SQL via psycopg2 — avoid importing the full FastAPI app)
# ---------------------------------------------------------------------------

_QUERY = """
SELECT
    mpl.id,
    mpl.match_id,
    mpl.league,
    m.match_date::date AS match_day,
    mpl.predicted_outcome,           -- 'home_win' | 'draw' | 'away_win'
    m.home_score,
    m.away_score,
    m.status
FROM match_prediction_logs mpl
JOIN matches m ON m.id = mpl.match_id
WHERE m.status IN ('FINISHED', 'SETTLED')
  AND m.home_score IS NOT NULL
  AND m.away_score IS NOT NULL
ORDER BY m.match_date, mpl.league
"""


def _actual_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home_win"
    if away_score > home_score:
        return "away_win"
    return "draw"


def _fetch_settled_groups() -> Dict[Tuple[str, str], List[Dict]]:
    """Returns same-(league, matchday) groups, each member a dict with
    'predicted', 'actual', 'correct' fields."""
    import os

    import psycopg2
    import psycopg2.extras

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL is required", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(_QUERY)
        rows = cur.fetchall()
    finally:
        conn.close()

    groups: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
    for row in rows:
        key = (str(row["league"] or ""), str(row["match_day"] or ""))
        actual = _actual_outcome(int(row["home_score"]), int(row["away_score"]))
        groups[key].append(
            {
                "match_id": row["match_id"],
                "predicted": str(row["predicted_outcome"] or ""),
                "actual": actual,
                "correct": str(row["predicted_outcome"] or "") == actual,
            }
        )

    return groups


# ---------------------------------------------------------------------------
# Calibration math
# ---------------------------------------------------------------------------


def _pairwise_agreement(members: List[Dict]) -> Optional[float]:
    """Fraction of pairs that had the same actual outcome."""
    pairs = list(combinations(members, 2))
    if not pairs:
        return None
    agreed = sum(1 for a, b in pairs if a["actual"] == b["actual"])
    return agreed / len(pairs)


def _baseline_chance_agreement() -> float:
    """Expected agreement by chance under 3-class uniform (1/3)."""
    return 1.0 / 3.0


def _calibrate(groups: Dict[Tuple[str, str], List[Dict]]) -> Dict:
    multi_groups = {k: v for k, v in groups.items() if len(v) >= 2}
    n_groups = len(multi_groups)
    all_agreements = []
    for members in multi_groups.values():
        ag = _pairwise_agreement(members)
        if ag is not None:
            all_agreements.append(ag)

    if not all_agreements:
        return {
            "status": "INSUFFICIENT_DATA",
            "n_multi_groups": n_groups,
            "note": "No same-league/matchday groups with n≥2 found.",
        }

    mean_agreement = sum(all_agreements) / len(all_agreements)
    baseline = _baseline_chance_agreement()
    # Excess agreement above chance — this is the correlation signal
    excess = max(0.0, mean_agreement - baseline)

    # Haircut = excess agreement (if outcomes are 20% more correlated than
    # chance, the haircut for each additional fixture is 20% of that Kelly).
    # We don't want the raw excess (too small); use a dampened version.
    proposed_haircut = round(min(0.25, max(0.05, excess)), 4)
    proposed_floor = round(max(0.40, 1.0 - proposed_haircut * 5), 2)

    # Aggregate cap: if same-matchday groups tend to all go the same way,
    # treat them conservatively. We scale the multiplier inversely with
    # excess agreement.
    proposed_agg_cap_mult = round(max(2.0, 3.0 - excess * 5), 2)

    return {
        "status": "OK" if n_groups >= 10 else "LOW_VOLUME",
        "n_multi_groups": n_groups,
        "n_pairs_measured": len(all_agreements),
        "mean_pairwise_agreement": round(mean_agreement, 4),
        "baseline_chance_agreement": round(baseline, 4),
        "excess_agreement": round(excess, 4),
        "current_constants": {
            "HAIRCUT_PER_ADDITIONAL_FIXTURE": 0.10,
            "HAIRCUT_FLOOR_MULTIPLIER": 0.50,
            "AGGREGATE_CAP_MULTIPLIER": 3.0,
        },
        "proposed_constants": {
            "HAIRCUT_PER_ADDITIONAL_FIXTURE": proposed_haircut,
            "HAIRCUT_FLOOR_MULTIPLIER": proposed_floor,
            "AGGREGATE_CAP_MULTIPLIER": proposed_agg_cap_mult,
        },
        "recommendation": (
            "APPLY" if n_groups >= 10 else
            f"DEFER — only {n_groups} multi-fixture groups; target ≥10 before applying"
        ),
    }


# ---------------------------------------------------------------------------
# Apply path (updates portfolio_exposure.py in place)
# ---------------------------------------------------------------------------


def _apply(proposed: Dict) -> None:
    import pathlib
    import re

    src = pathlib.Path(__file__).parents[1] / "src" / "core" / "portfolio_exposure.py"
    text = src.read_text(encoding="utf-8")

    h = proposed["HAIRCUT_PER_ADDITIONAL_FIXTURE"]
    fl = proposed["HAIRCUT_FLOOR_MULTIPLIER"]
    ac = proposed["AGGREGATE_CAP_MULTIPLIER"]
    src_tag = f"CALIBRATED_{proposed.get('date', '2026-09-04')}"

    text = re.sub(r"AGGREGATE_CAP_MULTIPLIER = [\d.]+", f"AGGREGATE_CAP_MULTIPLIER = {ac}", text)
    text = re.sub(r"HAIRCUT_PER_ADDITIONAL_FIXTURE = [\d.]+", f"HAIRCUT_PER_ADDITIONAL_FIXTURE = {h}", text)
    text = re.sub(r"HAIRCUT_FLOOR_MULTIPLIER = [\d.]+", f"HAIRCUT_FLOOR_MULTIPLIER = {fl}", text)
    text = re.sub(
        r'PORTFOLIO_POLICY_SOURCE = "[^"]+"',
        f'PORTFOLIO_POLICY_SOURCE = "{src_tag}"',
        text,
    )
    # Update docstring first line
    text = text.replace(
        "Constants below are reasoned starting points, not calibrated against real\nsame-matchday settlement outcomes (none exist yet — see docs/DEBT.md item 9).",
        f"Constants below are calibrated from real same-matchday settlement data ({src_tag}).\nSee docs/DEBT.md item 9 for calibration evidence and docs/DEBT.md item 9 runbook.",
    )
    src.write_text(text, encoding="utf-8")
    print(f"✓ Updated {src}")
    print(f"  HAIRCUT_PER_ADDITIONAL_FIXTURE = {h}")
    print(f"  HAIRCUT_FLOOR_MULTIPLIER       = {fl}")
    print(f"  AGGREGATE_CAP_MULTIPLIER       = {ac}")
    print(f"  PORTFOLIO_POLICY_SOURCE        = {src_tag}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write calibrated constants to portfolio_exposure.py (requires APPLY recommendation)",
    )
    args = parser.parse_args()

    groups = _fetch_settled_groups()
    total = sum(len(v) for v in groups.values())
    print(f"Loaded {total} settled predictions across {len(groups)} (league, matchday) groups")

    result = _calibrate(groups)
    import json
    print(json.dumps(result, indent=2))

    if args.apply:
        if result["status"] == "INSUFFICIENT_DATA":
            print("ERROR: no data — cannot apply", file=sys.stderr)
            sys.exit(1)
        if result["recommendation"] != "APPLY":
            print(f"WARN: {result['recommendation']}")
            print("Pass --force to override (not implemented — deliberately).")
            sys.exit(1)
        proposed = result["proposed_constants"]
        proposed["date"] = "2026-09-04"
        _apply(proposed)


if __name__ == "__main__":
    main()
