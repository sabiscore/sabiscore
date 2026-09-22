"""Exponentially weighted moving average (EWMA) form features.

3 features per team:
  weighted_win_rate  — EWMA fraction of wins
  weighted_draw_rate — EWMA fraction of draws
  weighted_ppg       — EWMA points per game (0–3 scale)

alpha=0.7 weights recent matches more heavily than distant history.
The feature service computes this separately for home and away and merges
into the canonical vector as home_* / away_* prefixed keys.
"""

from __future__ import annotations

from typing import Dict, List


def weighted_form_features(
    results: List[int],
    alpha: float = 0.7,
) -> Dict[str, float]:
    """Compute EWMA form features from a result sequence.

    Args:
        results: Match outcomes in oldest→newest order. 1=win, 0=draw, -1=loss.
        alpha:   Decay factor. Higher = more weight on recent matches.

    Returns:
        Dict with keys: weighted_win_rate, weighted_draw_rate, weighted_ppg.
    """
    if not results:
        return {
            "weighted_win_rate": 0.50,
            "weighted_draw_rate": 0.333,
            "weighted_ppg": 1.0,
        }

    n = len(results)
    weights = [alpha ** (n - 1 - i) for i in range(n)]
    w = sum(weights)
    normed = [wi / w for wi in weights]

    wins = [1.0 if r == 1 else 0.0 for r in results]
    draws = [1.0 if r == 0 else 0.0 for r in results]
    points = [3.0 if r == 1 else 1.0 if r == 0 else 0.0 for r in results]

    return {
        "weighted_win_rate": round(sum(w * x for w, x in zip(normed, wins)), 4),
        "weighted_draw_rate": round(sum(w * x for w, x in zip(normed, draws)), 4),
        "weighted_ppg": round(sum(w * x for w, x in zip(normed, points)), 4),
    }
