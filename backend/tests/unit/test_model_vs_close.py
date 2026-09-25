"""Directive v8 C3: paired ΔRPS of the model against the de-vigged close."""

from __future__ import annotations

import numpy as np

from src.services.clv_service import compute_model_vs_close


def _records(model_fn, n: int = 400, seed: int = 0) -> list[dict]:
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        close = rng.dirichlet([4, 3, 3])
        outcome = int(rng.choice(3, p=close))
        out.append(
            {
                "model_probs": list(model_fn(close, outcome, rng)),
                "closing_probs": list(close),
                "match_date": f"2026-{1 + (i // 28) % 12:02d}-{1 + i % 28:02d}T15:00:00",
                "outcome": outcome,
                "closing_lag_seconds": 600.0,
            }
        )
    return out


def _noisy(close, _outcome, rng):
    logits = np.log(close) + rng.normal(0, 0.3, 3)
    p = np.exp(logits)
    return p / p.sum()


def test_market_plus_noise_is_never_reported_sharper_than_the_close() -> None:
    # The argmax gap scores this model positive (DEBT 152); a proper score must not.
    result = compute_model_vs_close(_records(_noisy))
    assert result["skipped"] is False
    assert result["delta_rps"] > 0
    assert result["beats_market"] is False


def test_a_model_with_real_information_beats_the_close() -> None:
    def informed(close, outcome, _rng):
        p = 0.5 * np.asarray(close)
        p[outcome] += 0.5
        return p

    result = compute_model_vs_close(_records(informed))
    assert result["beats_market"] is True
    assert result["ci95"][1] < 0


def test_the_close_itself_scores_zero_delta() -> None:
    result = compute_model_vs_close(_records(lambda close, _o, _r: close))
    assert abs(result["delta_rps"]) < 1e-12


def test_unsettled_pairs_are_counted_for_lag_but_never_scored() -> None:
    records = _records(_noisy, n=5)
    for r in records:
        r["outcome"] = None
    result = compute_model_vs_close(records)
    assert result["skipped"] is True
    assert result["n"] == 0
    assert result["n_joined"] == 5
    assert result["median_closing_lag_seconds"] == 600.0
