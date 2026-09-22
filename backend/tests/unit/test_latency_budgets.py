"""CI budget guard: model inference p95 ≤ 150ms (Production Executive Directive §4.1).

The 150ms budget applies ONLY to predict_proba() over a 68-dim feature vector —
not to the full request cycle (~1–2.5s including DB queries, provider calls, HTTP).
The end-to-end /full-analysis p95 ≤ 2500ms budget is an alert threshold surfaced
in /metrics (timers.analysis.latency.p95_ms), not a CI assertion.

These tests construct synthetic models so no real artifacts or network access are
required, and they run on every CI pass.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import numpy as np
import pytest

if TYPE_CHECKING:
    from src.core.meta_model import SoftmaxMetaModel

# ── Model factory ──────────────────────────────────────────────────────────────

_N_CLASSES = 3
_N_FEATURES = 68
_INFERENCE_BUDGET_MS = 150.0
_WARMUP_N = 10
_MEASURE_N = 200


def _make_softmax_model(n_features: int = _N_FEATURES) -> "SoftmaxMetaModel":
    from src.core.meta_model import SoftmaxMetaModel  # noqa: PLC0415

    rng = np.random.default_rng(42)
    coef = rng.standard_normal((_N_CLASSES, n_features))
    intercept = rng.standard_normal(_N_CLASSES)
    return SoftmaxMetaModel(
        coef=coef,
        intercept=intercept,
        classes=np.array([0, 1, 2]),
        feature_names=[f"f{i}" for i in range(n_features)],
    )


def _p95(durations_ms: list[float]) -> float:
    return float(np.percentile(durations_ms, 95))


def _measure(model: object, x: np.ndarray, n: int = _MEASURE_N) -> float:
    """Run predict_proba n times, return p95 latency in ms."""
    # warm-up
    for _ in range(_WARMUP_N):
        model.predict_proba(x)  # type: ignore[union-attr]
    durations: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        model.predict_proba(x)  # type: ignore[union-attr]
        durations.append((time.perf_counter() - t0) * 1_000)
    return _p95(durations)


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestModelInferenceLatencyBudget:
    """§4.1: model inference ≤ 150ms p95.

    Failure indicates the inference arithmetic has grown unexpectedly expensive
    (new numpy dependency, regression in dot-product path, etc.).
    """

    def test_softmax_meta_model_p95_within_budget(self) -> None:
        """SoftmaxMetaModel: predict_proba over a single 68-vector must be ≤ 150ms p95."""
        model = _make_softmax_model()
        x = np.random.default_rng(0).standard_normal((1, _N_FEATURES))
        p95 = _measure(model, x)
        assert p95 <= _INFERENCE_BUDGET_MS, (
            f"SoftmaxMetaModel inference p95={p95:.2f}ms exceeds the {_INFERENCE_BUDGET_MS}ms budget "
            f"(§4.1 Production Executive Directive). This budget is inference-only — "
            f"not the full request cycle."
        )

    def test_temperature_scaled_model_p95_within_budget(self) -> None:
        """TemperatureScaledMetaModel must also meet the 150ms p95 budget."""
        from src.core.meta_model import TemperatureScaledMetaModel  # noqa: PLC0415

        base = _make_softmax_model()
        model = TemperatureScaledMetaModel(base_model=base, temperature=1.2)
        x = np.random.default_rng(1).standard_normal((1, _N_FEATURES))
        p95 = _measure(model, x)
        assert p95 <= _INFERENCE_BUDGET_MS, (
            f"TemperatureScaledMetaModel inference p95={p95:.2f}ms exceeds {_INFERENCE_BUDGET_MS}ms budget."
        )

    def test_batch_inference_p95_within_budget(self) -> None:
        """Batch inference over 10 samples must also stay within budget.

        Full-analysis calls predict_proba once per fixture; this checks that a
        modest batch doesn't blow the budget either.
        """
        model = _make_softmax_model()
        x_batch = np.random.default_rng(2).standard_normal((10, _N_FEATURES))
        p95 = _measure(model, x_batch)
        assert p95 <= _INFERENCE_BUDGET_MS, (
            f"Batch inference (n=10) p95={p95:.2f}ms exceeds {_INFERENCE_BUDGET_MS}ms budget."
        )

    def test_isotonic_meta_model_p95_within_budget(self) -> None:
        """IsotonicMetaModel (B3 candidate) must meet the 150ms p95 budget."""
        try:
            from src.core.meta_model import IsotonicMetaModel  # noqa: PLC0415
        except ImportError:
            pytest.skip(
                "IsotonicMetaModel not yet available — add it to proceed with B3"
            )

        from sklearn.isotonic import IsotonicRegression  # noqa: PLC0415

        base = _make_softmax_model()
        rng = np.random.default_rng(3)
        # Fit minimal isotonic calibrators on synthetic data
        raw = rng.dirichlet([1, 1, 1], size=200)  # (200, 3) fake probs
        calibrators = []
        for cls_idx in range(_N_CLASSES):
            binary = (rng.integers(0, _N_CLASSES, size=200) == cls_idx).astype(float)
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(raw[:, cls_idx], binary)
            calibrators.append(iso)
        model = IsotonicMetaModel(base_model=base, calibrators=calibrators)
        x = rng.standard_normal((1, _N_FEATURES))
        p95 = _measure(model, x)
        assert p95 <= _INFERENCE_BUDGET_MS, (
            f"IsotonicMetaModel inference p95={p95:.2f}ms exceeds {_INFERENCE_BUDGET_MS}ms budget."
        )
