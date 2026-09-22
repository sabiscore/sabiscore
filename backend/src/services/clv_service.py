"""Compute the backend-diagnostic CLV aggregate from already-captured closing
lines. Read-only: never feeds EXECUTE_BET (doesn't exist), never computes ROI
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
        "mean_clv": sum(clv_values) / n,
        "positive_rate": sum(1 for v in clv_values if v > 0) / n,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
