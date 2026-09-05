"""Aleatoric-stratification measurement over live shadow telemetry records.

PURPOSE
-------
Gate 50 (error_association) fails because HIGH-EPISTEMIC fixtures show
BETTER RPS than LOW-EPISTEMIC ones — the reverse of the required direction
(docs/DEBT.md item 50, uncertainty_policy.py IMPLEMENTATION_STATUS).

Root cause (epistemic_residualizer.py): epistemic is anti-correlated with
aleatoric (corr = -0.267 on the EPL holdout). Bucketing on raw epistemic
therefore implicitly *reverse*-buckets on aleatoric, and aleatoric IS the
component that legitimately tracks realised error (corr = +0.072).

This script tests the alternative directly: does ALEATORIC uncertainty
stratify realised error in the right direction on live settled fixtures?

  High aleatoric → intrinsically uncertain match → higher RPS (worse)
  Low aleatoric  → more predictable match          → lower RPS (better)

If confirmed on live data, it:
  (a) corroborates the residualizer's explanation
  (b) provides the evidence base for an authorised gate revision (item 50)
      should one ever be approved
  (c) does NOT itself certify, bypass, or modify any existing gate

⚠️  THIS IS READ-ONLY AND CERTIFIES NOTHING.
    error_association still gates on raw epistemic, still fails, and
    MODEL_UNCERTAINTY_UNAVAILABLE stays unconditionally CRITICAL.

USAGE
-----
    PYTHONPATH=. python scripts/measure_aleatoric_stratification.py

    # Print JSON instead of the table
    PYTHONPATH=. python scripts/measure_aleatoric_stratification.py --json

    # Run against a non-default DATABASE_URL
    DATABASE_URL=postgresql://... python scripts/measure_aleatoric_stratification.py

DATA REQUIREMENTS
-----------------
Records are joined on match_id between MatchPredictionLog (which stores
research_uncertainty.aleatoric in its JSONB payload) and Match (for the
settled outcome). The minimum useful analysis is ~50 records per quartile;
report only prints quartile results, not stake-permitted or gate state.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_MIN_TOTAL_RECORDS = 20   # below this: print a warning and skip quartile analysis
_MIN_BUCKET_RECORDS = 5   # below this: a quartile result is marked INSUFFICIENT


# ── RPS formulation (M0, metric-contract.json v1.0.0) ───────────────────────

def _ranked_probability_score(outcome_index: int, probs: list[float]) -> float:
    """Ranked probability score for a single fixture (lower = better).

    outcome_index: 0=home_win, 1=draw, 2=away_win
    probs: [p_home, p_draw, p_away] (must sum to 1, 3-class)
    """
    n = len(probs)
    cumulative_pred = 0.0
    cumulative_actual = 0.0
    rps = 0.0
    for k in range(n - 1):
        cumulative_pred += probs[k]
        cumulative_actual += 1.0 if k >= outcome_index else 0.0
        rps += (cumulative_pred - cumulative_actual) ** 2
    return rps / (n - 1)


def _actual_outcome_index(home_score: int, away_score: int) -> int:
    if home_score > away_score:
        return 0
    if away_score > home_score:
        return 2
    return 1


# ── DB query ─────────────────────────────────────────────────────────────────

_QUERY = """
SELECT
    mpl.id,
    mpl.match_id,
    mpl.home_probability,
    mpl.draw_probability,
    mpl.away_probability,
    mpl.payload -> 'research_uncertainty' -> 'aleatoric'  AS aleatoric,
    mpl.payload -> 'research_uncertainty' -> 'available'  AS uncertainty_available,
    m.home_score,
    m.away_score
FROM match_prediction_logs mpl
JOIN matches m ON m.id = mpl.match_id
WHERE
    m.status IN ('FINISHED', 'SETTLED')
    AND m.home_score IS NOT NULL
    AND m.away_score IS NOT NULL
    AND (mpl.payload -> 'research_uncertainty' ->> 'available')::boolean = true
    AND mpl.payload -> 'research_uncertainty' -> 'aleatoric' IS NOT NULL
ORDER BY mpl.evaluated_at
"""


def _fetch_records() -> list[dict]:
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

    records = []
    for row in rows:
        try:
            aleatoric = float(row["aleatoric"])
            probs = [
                float(row["home_probability"]),
                float(row["draw_probability"]),
                float(row["away_probability"]),
            ]
            outcome_idx = _actual_outcome_index(int(row["home_score"]), int(row["away_score"]))
            rps = _ranked_probability_score(outcome_idx, probs)
            records.append({"match_id": row["match_id"], "aleatoric": aleatoric, "rps": rps})
        except (TypeError, ValueError):
            continue  # malformed row — skip, don't crash the whole run

    return records


# ── Stratification logic ─────────────────────────────────────────────────────

def _quartile_label(value: float, thresholds: list[float]) -> int:
    """1-indexed quartile (1=lowest aleatoric, 4=highest)."""
    for i, t in enumerate(thresholds):
        if value <= t:
            return i + 1
    return 4


def _stratify(records: list[dict]) -> dict:
    """Returns per-quartile summary and a right-sign verdict."""
    import statistics

    aleatoric_values = [r["aleatoric"] for r in records]

    # Quartile thresholds from the accumulated live distribution
    # (NOT hardcoded corpus values — let the live data define its own quartiles)
    sorted_a = sorted(aleatoric_values)
    n = len(sorted_a)
    thresholds = [
        sorted_a[int(n * 0.25) - 1],
        sorted_a[int(n * 0.50) - 1],
        sorted_a[int(n * 0.75) - 1],
    ]

    buckets: dict[int, list[float]] = {1: [], 2: [], 3: [], 4: []}
    for r in records:
        q = _quartile_label(r["aleatoric"], thresholds)
        buckets[q].append(r["rps"])

    per_quartile = {}
    for q in (1, 2, 3, 4):
        bucket = buckets[q]
        n_q = len(bucket)
        if n_q >= _MIN_BUCKET_RECORDS:
            per_quartile[q] = {
                "n": n_q,
                "mean_rps": round(statistics.mean(bucket), 6),
                "status": "OK",
            }
        else:
            per_quartile[q] = {
                "n": n_q,
                "mean_rps": None,
                "status": f"INSUFFICIENT (need >= {_MIN_BUCKET_RECORDS})",
            }

    q1_rps = per_quartile[1]["mean_rps"]
    q4_rps = per_quartile[4]["mean_rps"]
    if q1_rps is not None and q4_rps is not None:
        right_signed = q4_rps > q1_rps
        gap = round(q4_rps - q1_rps, 6)
    else:
        right_signed = None
        gap = None

    return {
        "n_total": n,
        "aleatoric_quartile_thresholds": [round(t, 6) for t in thresholds],
        "per_quartile": per_quartile,
        "q4_rps_greater_than_q1": right_signed,
        "gap_q4_minus_q1": gap,
        "interpretation": (
            "RIGHT-SIGNED: high-aleatoric fixtures have worse RPS (higher) — "
            "consistent with aleatoric as intrinsic-difficulty signal"
            if right_signed is True
            else (
                "WRONG-SIGNED: high-aleatoric fixtures have better RPS — "
                "same direction as the Gate 50 failure on raw epistemic"
                if right_signed is False
                else "INSUFFICIENT: cannot determine sign yet"
            )
        ),
        "gate_impact": "NONE — this is diagnostic only. error_association still gates on raw epistemic and still fails.",
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Output JSON instead of formatted table")
    args = parser.parse_args()

    print("Fetching settled shadow records...", file=sys.stderr)
    records = _fetch_records()
    print(f"Loaded {len(records)} usable records", file=sys.stderr)

    if len(records) < _MIN_TOTAL_RECORDS:
        result = {
            "status": "INSUFFICIENT_DATA",
            "n_total": len(records),
            "note": f"Need >= {_MIN_TOTAL_RECORDS} settled records with research_uncertainty.available=true. "
                    f"Run again after more fixtures settle.",
            "gate_impact": "NONE",
        }
    else:
        result = {"status": "OK", **_stratify(records)}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_table(result)


def _print_table(result: dict) -> None:
    print("\n" + "=" * 60)
    print("ALEATORIC STRATIFICATION MEASUREMENT (shadow telemetry)")
    print("=" * 60)
    print(f"Status          : {result['status']}")
    print(f"Total records   : {result.get('n_total', 0)}")

    if result["status"] != "OK":
        print(f"Note            : {result.get('note', '')}")
        print(f"Gate impact     : {result['gate_impact']}")
        return

    thresholds = result["aleatoric_quartile_thresholds"]
    print(f"Quartile bounds : Q1≤{thresholds[0]} | Q2≤{thresholds[1]} | Q3≤{thresholds[2]} | Q4>")
    print()
    print(f"{'Quartile':>8}  {'n':>6}  {'mean_RPS':>10}  {'status'}")
    print("-" * 50)
    for q in (1, 2, 3, 4):
        qd = result["per_quartile"][q]
        rps_str = f"{qd['mean_rps']:.6f}" if qd["mean_rps"] is not None else "    —   "
        print(f"{'Q' + str(q):>8}  {qd['n']:>6}  {rps_str:>10}  {qd['status']}")
    print()
    print(f"Q4 > Q1 (right-signed) : {result['q4_rps_greater_than_q1']}")
    print(f"Gap Q4 - Q1            : {result['gap_q4_minus_q1']}")
    print(f"Interpretation         : {result['interpretation']}")
    print(f"Gate impact            : {result['gate_impact']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
