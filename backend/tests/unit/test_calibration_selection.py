"""scripts/train_on_real_matches.py::_select_calibrator (Portfolio A / E0 / B2-B3).

PRODUCTION_EXECUTIVE_DIRECTIVE.md §20 B2/B3, a two-stage gate applied as a
simplest-first single-elimination cascade across all four §20 B2 candidates
(temperature, vector, beta, isotonic): stage 1 requires a challenger to beat
whichever calibrator currently leads on the calibration holdout ("reliability
improves AND resolution holds" — reliability improving alone is not
sufficient, since a flat prediction that always emits the base rate is
trivially "reliable" while being completely uninformative); stage 2 requires
that SAME conclusion to "persist on untouched data" using a genuinely disjoint
holdout season before the challenger ships, because a flexible calibrator can
fit a small calibration slice almost exactly -- an in-sample reliability
number near zero is expected of an overfitting calibrator, not evidence it
generalises. This is not a theoretical concern: retraining on the real
per-league corpus, isotonic won stage 1 in 4 of 6 leagues (EPL, LA_LIGA,
LIGUE_1, the pooled EREDIVISIE model) and failed stage 2 in all 4 -- a complete
reversal every time. Temperature scaling shipped in every league as a result
(item 64, docs/DEBT.md) before vector scaling and beta calibration existed as
candidates; the tests below pin that the temperature/isotonic-only case is
byte-identical to that finding, plus the cascade's new property: a later,
more-flexible candidate must beat the CURRENT champion, not always
temperature.

This file also pins the delegation to ``brier_score_decomposition`` -- the
SAME function production's ``/model-performance/calibration`` endpoint uses --
so the numbers this pipeline selects on are never computed a second,
independently-drifting way (this repository has a documented history of
exactly that shape drifting apart: the mean-over-samples vs. mean-over-classes
Brier convention mismatch recorded in ``reports/evaluation/metric-contract.json``).

Not a package (pytest.ini excludes scripts/ from collection and pythonpath
only covers src/), so the module is loaded by inserting its directory onto
sys.path directly — same pattern as test_train_on_real_matches_elo.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import train_on_real_matches  # noqa: E402

from src.models.evaluation.metrics import brier_score_decomposition  # noqa: E402


class _FakeCalibrator:
    """A pre-fitted calibrator stub: predict_proba returns a fixed matrix,
    ignoring its input — the tests below control the matrix directly rather
    than fighting real isotonic/temperature fitting to engineer edge cases."""

    def __init__(self, probs: np.ndarray) -> None:
        self._probs = probs

    def predict_proba(self, X: Any) -> np.ndarray:
        return self._probs


def test_calibration_reliability_matches_production_brier_decomposition() -> None:
    """No second, independently-binned reliability/resolution implementation.

    A prior version special-cased the first bin as [0.0, 0.1] inclusive while
    every other bin -- and both production functions
    (expected_calibration_error, brier_score_decomposition) -- use (lo, hi]
    uniformly. Isotonic regression's y_min=0.0 clip makes exact-zero outputs a
    real occurrence, so the two conventions could disagree by more than
    rounding. This test would fail under that prior implementation.
    """
    rng = np.random.default_rng(7)
    probs = rng.dirichlet([1.0, 1.0, 1.0], size=200)
    y = rng.integers(0, 3, size=200)

    result = train_on_real_matches._calibration_reliability(
        _FakeCalibrator(probs), None, y
    )
    expected = brier_score_decomposition(y, probs, n_bins=10)

    assert result["reliability"] == pytest.approx(expected["mean"]["reliability"])
    assert result["resolution"] == pytest.approx(expected["mean"]["resolution"])


def test_select_calibrator_picks_isotonic_when_reliability_and_resolution_both_improve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    y = np.array([0, 0, 1, 1, 2, 2] * 10)
    # Temperature stand-in: a CONSTANT row regardless of the true class --
    # uninformative but happens to be mildly closer to the true class's own
    # marginal rate than the other two, so it is not flat-zero-resolution.
    temp_probs = np.tile([0.5, 0.3, 0.2], (len(y), 1))
    # Isotonic stand-in: correlated with the true class -- both better
    # calibrated (closer predicted-vs-observed within each bin) and more
    # discriminative (its bins pull further from the base rate).
    iso_probs = np.full((len(y), 3), 0.05)
    iso_probs[np.arange(len(y)), y] = 0.9

    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_temperature",
        lambda *a, **k: _FakeCalibrator(temp_probs),
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_isotonic",
        lambda *a, **k: _FakeCalibrator(iso_probs),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert diagnostics["chosen"] == "isotonic"
    assert (
        diagnostics["isotonic"]["reliability"]
        < diagnostics["temperature"]["reliability"]
    )
    assert (
        diagnostics["isotonic"]["resolution"]
        >= diagnostics["temperature"]["resolution"]
    )
    # Same fixed matrices scored against the same y -- the persistence check
    # is necessarily trivial here; test_..._does_not_persist below exercises
    # the genuinely informative case.
    assert diagnostics["held_out_persistence"]["conclusion_persists"] is True
    assert model.predict_proba(None) is iso_probs


def test_select_calibrator_rejects_isotonic_that_improves_reliability_but_flattens_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The B3 gate this fix adds: reliability improving alone must not win.

    Textbook reliability/resolution trade-off (the "always predict the town's
    average rainfall probability" forecaster): a perfectly flat prediction at
    each class's true marginal rate has ZERO calibration error by
    construction, but zero discrimination too. Temperature scaling here keeps
    real (if imperfect) per-class separation, so it must be preferred despite
    scoring worse on reliability alone.
    """
    y = np.array([0, 1, 2] * 20)
    temp_probs = np.full((len(y), 3), 0.225)
    temp_probs[np.arange(len(y)), y] = 0.55
    iso_probs = np.full((len(y), 3), 1.0 / 3.0)  # exactly the marginal rate, every row

    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_temperature",
        lambda *a, **k: _FakeCalibrator(temp_probs),
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_isotonic",
        lambda *a, **k: _FakeCalibrator(iso_probs),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert (
        diagnostics["isotonic"]["reliability"]
        < diagnostics["temperature"]["reliability"]
    )
    assert (
        diagnostics["isotonic"]["resolution"] < diagnostics["temperature"]["resolution"]
    )
    assert diagnostics["chosen"] == "temperature"
    assert diagnostics["reason"] == "isotonic_degraded_resolution"
    assert model.predict_proba(None) is temp_probs


def test_select_calibrator_rejects_isotonic_when_the_calibration_set_conclusion_does_not_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core new behaviour: isotonic can win on the calibration set purely
    by overfitting it, so a stage-1 win alone must not be enough to ship it.

    Reuses the "isotonic wins" calibration-set setup, but the held-out labels
    are the calibration labels cyclically relabelled (0->1->2->0) — a
    class-balance-preserving permutation that makes isotonic's per-row "hot"
    class wrong for every row on the held-out data, while temperature's
    label-blind constant prediction is mathematically unaffected (a constant
    row's reliability/resolution depend only on each class's marginal rate,
    which the permutation preserves). Directive §20 B3 ("succeeds only if...
    persists on untouched data") means isotonic must lose here — temperature
    ships despite isotonic having "won" the circular calibration-set compare.

    This is not a contrived scenario: on the real per-league corpus, this
    exact reversal happened in all 4 leagues where isotonic ever won the
    calibration-set comparison (see the module docstring).
    """
    y_calibration = np.array([0, 0, 1, 1, 2, 2] * 10)
    temp_probs = np.tile([0.5, 0.3, 0.2], (len(y_calibration), 1))
    iso_probs = np.full((len(y_calibration), 3), 0.05)
    iso_probs[np.arange(len(y_calibration)), y_calibration] = 0.9
    y_holdout = (y_calibration + 1) % 3

    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_temperature",
        lambda *a, **k: _FakeCalibrator(temp_probs),
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_isotonic",
        lambda *a, **k: _FakeCalibrator(iso_probs),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y_calibration,
        meta_features_holdout=None,
        y_holdout=y_holdout,
    )

    expected_temp_holdout = brier_score_decomposition(y_holdout, temp_probs, n_bins=10)[
        "mean"
    ]
    expected_iso_holdout = brier_score_decomposition(y_holdout, iso_probs, n_bins=10)[
        "mean"
    ]

    # Isotonic "won" stage 1 (the calibration set) but must be rejected
    # because it fails stage 2 (the held-out season) -- temperature ships.
    assert diagnostics["chosen"] == "temperature"
    assert (
        diagnostics["reason"]
        == "isotonic_won_calibration_set_but_did_not_persist_on_holdout"
    )
    assert model.predict_proba(None) is temp_probs
    persistence = diagnostics["held_out_persistence"]
    assert persistence["temperature"]["reliability"] == pytest.approx(
        expected_temp_holdout["reliability"]
    )
    assert persistence["isotonic"]["reliability"] == pytest.approx(
        expected_iso_holdout["reliability"]
    )
    assert (
        persistence["isotonic"]["reliability"]
        > persistence["temperature"]["reliability"]
    )
    assert persistence["conclusion_persists"] is False


def test_select_calibrator_falls_back_to_temperature_when_isotonic_fit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    y = np.array([0, 1, 2] * 5)
    temp_probs = np.tile([0.4, 0.35, 0.25], (len(y), 1))
    monkeypatch.setattr(
        train_on_real_matches,
        "_fit_temperature",
        lambda *a, **k: _FakeCalibrator(temp_probs),
    )

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("boom")

    monkeypatch.setattr(train_on_real_matches, "_fit_isotonic", _raise)

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert diagnostics["chosen"] == "temperature"
    assert diagnostics["isotonic"] is None
    assert "boom" in diagnostics["reason"]
    assert diagnostics["held_out_persistence"]["isotonic"] is None
    assert diagnostics["held_out_persistence"]["conclusion_persists"] is True
    assert model.predict_proba(None) is temp_probs


# ── Cascade: vector scaling and beta calibration as additional candidates ────
#
# These stub `_calibration_reliability` directly rather than hand-crafting
# probability arrays that must satisfy brier_score_decomposition's exact
# arithmetic -- that arithmetic is already pinned by
# test_calibration_reliability_matches_production_brier_decomposition above.
# What these tests exercise is the SELECTION logic: which candidate becomes
# champion, and specifically (the property this refactor adds) that a later
# candidate must beat the CURRENT champion, not always temperature.


def test_select_calibrator_can_choose_vector_scaling_over_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    y = np.array([0, 1, 2] * 5)
    temp_model = _FakeCalibrator(np.zeros((len(y), 3)))
    vector_model = _FakeCalibrator(np.ones((len(y), 3)))
    metrics = {
        id(temp_model): {"reliability": 0.10, "resolution": 0.05},
        id(vector_model): {"reliability": 0.02, "resolution": 0.08},
    }

    monkeypatch.setattr(
        train_on_real_matches, "_fit_temperature", lambda *a, **k: temp_model
    )
    monkeypatch.setattr(
        train_on_real_matches, "_fit_vector_scaling", lambda *a, **k: vector_model
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_calibration_reliability",
        lambda model, *a, **k: dict(metrics[id(model)]),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert diagnostics["chosen"] == "vector"
    assert (
        diagnostics["reason"]
        == "reliability_improved_resolution_held_and_persisted_on_holdout"
    )
    # Real fits on `object()` raise AttributeError -- graceful degradation.
    assert diagnostics["isotonic"] is None
    assert diagnostics["beta"] is None
    assert model is vector_model


def test_select_calibrator_can_choose_beta_calibration_over_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    y = np.array([0, 1, 2] * 5)
    temp_model = _FakeCalibrator(np.zeros((len(y), 3)))
    beta_model = _FakeCalibrator(np.ones((len(y), 3)))
    metrics = {
        id(temp_model): {"reliability": 0.10, "resolution": 0.05},
        id(beta_model): {"reliability": 0.02, "resolution": 0.08},
    }

    monkeypatch.setattr(
        train_on_real_matches, "_fit_temperature", lambda *a, **k: temp_model
    )
    monkeypatch.setattr(
        train_on_real_matches, "_fit_beta_calibration", lambda *a, **k: beta_model
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_calibration_reliability",
        lambda model, *a, **k: dict(metrics[id(model)]),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert diagnostics["chosen"] == "beta"
    assert diagnostics["vector"] is None
    assert diagnostics["isotonic"] is None
    assert model is beta_model


def test_select_calibrator_only_lets_a_challenger_win_by_beating_the_current_champion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cascade's whole point: a later, more-flexible candidate must beat
    whichever calibrator currently leads, not always temperature.

    Isotonic is given metrics that would clearly beat temperature on their
    own (the pre-cascade, two-way logic would have shipped it) but that lose
    to vector scaling, which is checked first (simplest-first ordering, see
    _select_calibrator's docstring) and becomes champion. Isotonic must then
    be compared against vector -- and lose.
    """
    y = np.array([0, 1, 2] * 5)
    temp_model = _FakeCalibrator(np.zeros((len(y), 3)))
    vector_model = _FakeCalibrator(np.ones((len(y), 3)))
    iso_model = _FakeCalibrator(np.full((len(y), 3), 2.0))
    metrics = {
        id(temp_model): {"reliability": 0.10, "resolution": 0.05},
        id(vector_model): {"reliability": 0.02, "resolution": 0.08},
        id(iso_model): {"reliability": 0.05, "resolution": 0.09},
    }

    monkeypatch.setattr(
        train_on_real_matches, "_fit_temperature", lambda *a, **k: temp_model
    )
    monkeypatch.setattr(
        train_on_real_matches, "_fit_vector_scaling", lambda *a, **k: vector_model
    )
    monkeypatch.setattr(
        train_on_real_matches, "_fit_isotonic", lambda *a, **k: iso_model
    )
    monkeypatch.setattr(
        train_on_real_matches,
        "_calibration_reliability",
        lambda model, *a, **k: dict(metrics[id(model)]),
    )

    model, diagnostics = train_on_real_matches._select_calibrator(
        object(),
        None,
        y,
        meta_features_holdout=None,
        y_holdout=y,
    )

    assert diagnostics["chosen"] == "vector"
    # Isotonic legitimately beats temperature on its own...
    assert (
        diagnostics["isotonic"]["reliability"]
        < diagnostics["temperature"]["reliability"]
    )
    assert (
        diagnostics["isotonic"]["resolution"]
        >= diagnostics["temperature"]["resolution"]
    )
    # ...but the champion it actually had to beat was vector, and lost.
    assert diagnostics["isotonic"]["reliability"] > diagnostics["vector"]["reliability"]
    assert model is vector_model


# ── Real fits, not stubs: item 64's root cause was code that had been written
# but never executed end-to-end. These smoke-test the actual scipy.optimize
# fits on real (small, synthetic) data. ─────────────────────────────────────


def test_fit_vector_scaling_produces_a_valid_simplex_on_real_data() -> None:
    from src.core.meta_model import SoftmaxMetaModel, VectorScaledMetaModel

    rng = np.random.default_rng(11)
    base = SoftmaxMetaModel(
        coef=np.asarray([[1.5, 0.0], [0.0, 0.0], [-1.5, 0.0]]),
        intercept=np.zeros(3),
        classes=np.asarray([0, 1, 2]),
    )
    X = rng.normal(size=(200, 2))
    y = np.argmax(base.predict_proba(X), axis=1)

    model = train_on_real_matches._fit_vector_scaling(base, X, y)

    assert isinstance(model, VectorScaledMetaModel)
    probabilities = model.predict_proba(X)
    assert probabilities.shape == (200, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(np.isfinite(probabilities))


def test_evaluate_bivariate_poisson_overlay_returns_expected_keys_on_real_data() -> (
    None
):
    """`_evaluate_bivariate_poisson_overlay` (directive Experiment E7) wires
    `src/models/calibration.py::BivariatePoissonDrawOverlay` -- previously
    unwired to any producer, docs/DEBT.md item 71 -- into this pipeline.
    Smoke-tests the real (non-stubbed) integration, not just the overlay's
    own already-tested internals (tests/test_calibration.py)."""
    from src.core.meta_model import SoftmaxMetaModel

    rng = np.random.default_rng(17)
    base = SoftmaxMetaModel(
        coef=np.asarray([[1.0, 0.0], [0.0, 0.0], [-1.0, 0.0]]),
        intercept=np.zeros(3),
        classes=np.asarray([0, 1, 2]),
    )
    X_cal = rng.normal(size=(120, 2))
    y_cal = np.argmax(base.predict_proba(X_cal), axis=1)
    X_hold = rng.normal(size=(80, 2))
    y_hold = np.argmax(base.predict_proba(X_hold), axis=1)

    result = train_on_real_matches._evaluate_bivariate_poisson_overlay(
        base,
        X_cal,
        y_cal,
        X_hold,
        y_hold,
    )

    assert set(result) == {
        "alpha",
        "gate_passed",
        "calibration_draw_f1_before",
        "calibration_draw_f1_after",
        "calibration_brier_before",
        "calibration_brier_after",
        "holdout_draw_f1_before",
        "holdout_draw_f1_after",
        "holdout_brier_before",
        "holdout_brier_after",
    }
    assert 0.0 <= result["alpha"] <= 1.0
    assert isinstance(result["gate_passed"], bool)


def test_fit_beta_calibration_produces_a_valid_simplex_on_real_data() -> None:
    from src.core.meta_model import BetaCalibratedMetaModel, SoftmaxMetaModel

    rng = np.random.default_rng(13)
    base = SoftmaxMetaModel(
        coef=np.asarray([[1.5, 0.0], [0.0, 0.0], [-1.5, 0.0]]),
        intercept=np.zeros(3),
        classes=np.asarray([0, 1, 2]),
    )
    X = rng.normal(size=(200, 2))
    y = np.argmax(base.predict_proba(X), axis=1)

    model = train_on_real_matches._fit_beta_calibration(base, X, y)

    assert isinstance(model, BetaCalibratedMetaModel)
    probabilities = model.predict_proba(X)
    assert probabilities.shape == (200, 3)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    assert np.all(np.isfinite(probabilities))
