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


def test_below_the_first_c6_milestone_only_the_count_is_reported() -> None:
    # O8 (d), 2026-09-27: an interim interval invites the peeking C6 forbids, so
    # neither the interval nor the mean is shown before 200 settled forecasts.
    result = compute_model_vs_close(_records(_noisy, n=199))
    assert result["skipped"] is True
    assert (result["n"], result["milestone"]) == (199, 200)
    for key in ("ci95", "delta_rps", "model_rps", "market_rps", "beats_market", "worse_than_market"):
        assert key not in result


def test_the_interval_appears_at_the_milestone() -> None:
    result = compute_model_vs_close(_records(_noisy, n=200))
    assert result["skipped"] is False
    assert len(result["ci95"]) == 2


def test_c6_decision_interval_is_the_bonferroni_one_with_the_95_beside_it() -> None:
    # O8 (f): three looks decide at 98.33% (alpha 0.05 / 3), from the same draws.
    from datetime import datetime, timedelta

    from src.models.evaluation.metrics import week_cluster_ci

    rng = np.random.default_rng(1)
    delta = rng.normal(-0.004, 0.05, 300)
    dates = np.array([datetime(2026, 10, 9) + timedelta(days=int(i // 5)) for i in range(300)])

    default = week_cluster_ci(delta, dates, n_boot=2000, seed=42)
    c6 = week_cluster_ci(delta, dates, n_boot=2000, seed=42, alpha=0.05 / 3)

    assert default["ci"] == default["ci95"]
    assert c6["ci95"] == default["ci95"]
    assert c6["ci"][0] < c6["ci95"][0] and c6["ci"][1] > c6["ci95"][1]
    assert c6["beats_market"] == (c6["ci"][1] < 0)
