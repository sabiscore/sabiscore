"""Model-vs-closing-market disagreement, from already-captured closing lines.

NOT closing-line value. True CLV is ln(o_taken / o_close) and needs the price
available at forecast time, which match_prediction_logs does not store. This
statistic picks the model's argmax, which selects the outcomes where its noise
ran high, so a no-skill model (market + noise) also scores positive: +0.005 at
noise sd 0.1, +0.06 at 0.4 (docs/DEBT.md item 152). A disagreement diagnostic,
not evidence of an edge in either direction. Read-only: never feeds EXECUTE_BET (doesn't exist), never computes ROI
(no stake is ever placed). See docs/adr/0004-clv-capture.md, Addendum 2.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

# Reuses model_registry.MIN_RECORDS_FOR_DECOMPOSITION's threshold rather than
# inventing a second magic number in the same /model-performance response.
_MIN_CLV_SAMPLE_SIZE = 10


def compute_clv_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """records: [{"model_probs": [h,d,a], "closing_probs": [h,d,a]}, ...] from
    repositories.fixtures.get_clv_records(). No outcome field — CLV compares
    model belief to market close, independent of the result.

    CLV per record = model_probs[picked] - closing_probs[picked], where
    picked = argmax(model_probs) (mirrors walk_forward_validate()'s own
    argmax convention for `accuracy`). Sign is reported as-is — this is a
    read-only diagnostic surface, not a verdict.
    """
    valid: list[tuple[list[float], list[float]]] = []
    for rec in records:
        mp, cp = rec.get("model_probs"), rec.get("closing_probs")
        if not mp or not cp or len(mp) != 3 or len(cp) != 3:
            continue
        if not all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in (*mp, *cp)):
            continue
        if not math.isclose(sum(mp), 1.0, abs_tol=1e-6):
            continue
        valid.append((mp, cp))

    n = len(valid)
    if n < _MIN_CLV_SAMPLE_SIZE:
        return {
            "skipped": True,
            "reason": f"need >= {_MIN_CLV_SAMPLE_SIZE} joined predictions, got {n}",
            "n": n,
        }

    clv_values = [mp[mp.index(max(mp))] - cp[mp.index(max(mp))] for mp, cp in valid]
    return {
        "skipped": False,
        "n": n,
        "mean_gap": sum(clv_values) / n,
        "positive_rate": sum(1 for v in clv_values if v > 0) / n,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def compute_model_vs_close(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Directive v8 C3: is the model sharper than the de-vigged closing line?

    Paired, per settled match: ΔRPS = RPS(model) − RPS(close) on the same
    fixture, with an ISO-week cluster bootstrap CI (the G18 instrument).
    "Sharper than the close" means the whole CI lies below zero. Unlike the
    argmax gap above, a proper scoring rule has no selection bias: a model equal
    to the close plus noise scores worse, not better. Also reports the median
    kickoff-minus-capture lag of the closing snapshots used (directive C2).
    """
    import numpy as np

    from ..models.evaluation.metrics import (
        ranked_probability_score_rowwise,
        week_cluster_ci,
    )

    lags = [
        r["closing_lag_seconds"]
        for r in records
        if isinstance(r.get("closing_lag_seconds"), (int, float))
    ]
    settled = [
        r
        for r in records
        if r.get("outcome") in (0, 1, 2)
        and len(r.get("model_probs") or ()) == 3
        and len(r.get("closing_probs") or ()) == 3
        and all(
            isinstance(p, (int, float)) and math.isfinite(p)
            for p in (*r["model_probs"], *r["closing_probs"])
        )
    ]
    base: dict[str, Any] = {
        "benchmark": "de-vigged closing 1X2, latest pre-kickoff snapshot",
        "n_joined": len(records),
        "median_closing_lag_seconds": float(np.median(lags)) if lags else None,
    }
    n = len(settled)
    if n < _MIN_CLV_SAMPLE_SIZE:
        return {
            **base,
            "skipped": True,
            "reason": f"need >= {_MIN_CLV_SAMPLE_SIZE} settled joined predictions, got {n}",
            "n": n,
        }

    y = np.array([r["outcome"] for r in settled])
    model_rps = ranked_probability_score_rowwise(y, np.array([r["model_probs"] for r in settled]))
    market_rps = ranked_probability_score_rowwise(y, np.array([r["closing_probs"] for r in settled]))
    dates = np.array([datetime.fromisoformat(r["match_date"]) for r in settled])
    return {
        **base,
        "skipped": False,
        "n": n,
        "model_rps": float(model_rps.mean()),
        "market_rps": float(market_rps.mean()),
        **week_cluster_ci(model_rps - market_rps, dates, n_boot=2000, seed=0),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
