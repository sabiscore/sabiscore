"""Version-independent stacking head for the league ensembles.

WHY THIS EXISTS
---------------
Model artifacts are trained on a developer machine and unpickled by the
production runtime, and the two do not run the same library versions:

    production (Render, Python 3.11):  scikit-learn 1.3.2, xgboost 2.0.3, numpy 1.26
    local      (Python 3.14):          scikit-learn 1.8,   xgboost 3.3,   numpy 2.x

scikit-learn only guarantees pickle compatibility within a single version. A
`LogisticRegression` fitted under 1.8 and unpickled under 1.3.2 loses nothing
visible — it deserialises fine — but 1.3.2's `predict_proba` reads
`self.multi_class`, an attribute 1.8 no longer sets, so the call dies with
`AttributeError: 'LogisticRegression' object has no attribute 'multi_class'`.
That happens inside `_startup_load_models_strict`, which aborts the lifespan, so
the container exits and the release never deploys.

A softmax regression head is a matrix multiply and a normalisation. Storing the
fitted coefficients in a class this repository owns removes the entire class of
problem: unpickling needs only this module and numpy, both stable across the
version gap. The head is still *fitted* by scikit-learn — this type just carries
the result across the boundary.

Base learners (RandomForest / XGBoost / LightGBM) are left alone: they were
verified to load and score correctly under the production versions, and
re-implementing tree inference to avoid a risk that has not materialised would
be a far worse trade.

⚠️ THIS MODULE'S PATH IS PART OF THE ARTIFACT FORMAT. Pickle records it by
import path, so moving or renaming this file invalidates every committed
artifact and requires a retrain.

It lives under ``src/core/`` — a namespace package with no ``__init__.py`` —
specifically so that unpickling runs nothing but ``src/__init__.py``'s
lightweight shims. The obvious home, ``src/models/``, cannot be used: its
``__init__.py`` imports ``src.core.database``, which opens a PostgreSQL
connection at module scope (see docs/DEBT.md item 7), which would make
deserialising a model artifact depend on the database being reachable.
"""

from __future__ import annotations

from typing import Any

import numpy as np

__all__ = [
    "SoftmaxMetaModel",
    "TemperatureScaledMetaModel",
    "VectorScaledMetaModel",
    "BetaCalibratedMetaModel",
    "IsotonicMetaModel",
]


class SoftmaxMetaModel:
    """Multinomial logistic head: ``softmax(X @ coef_.T + intercept_)``.

    Deliberately duck-types the slice of the scikit-learn estimator API that
    `SabiScoreEnsemble.predict()` actually calls — `predict_proba` — rather than
    subclassing anything, so it carries no library version in its pickle.
    """

    def __init__(
        self,
        coef: np.ndarray,
        intercept: np.ndarray,
        classes: np.ndarray,
        feature_names: list[str] | None = None,
    ) -> None:
        self.coef_ = np.asarray(coef, dtype=np.float64)
        self.intercept_ = np.asarray(intercept, dtype=np.float64)
        self.classes_ = np.asarray(classes)
        # Retained for diagnostics and to make a column-order mismatch findable;
        # predict_proba positions by order, exactly as scikit-learn does.
        self.feature_names_in_ = list(feature_names or [])

        if self.coef_.ndim != 2:
            raise ValueError(
                f"coef must be 2-D (n_classes, n_features), got {self.coef_.shape}"
            )
        if self.intercept_.shape[0] != self.coef_.shape[0]:
            raise ValueError("intercept length must equal the number of classes")

    @classmethod
    def from_sklearn(
        cls, model: Any, feature_names: list[str] | None = None
    ) -> "SoftmaxMetaModel":
        """Copy the fitted parameters out of a scikit-learn LogisticRegression."""
        return cls(
            coef=model.coef_,
            intercept=model.intercept_,
            classes=model.classes_,
            feature_names=feature_names
            or list(getattr(model, "feature_names_in_", []) or []),
        )

    def predict_proba(self, X: Any) -> np.ndarray:
        """Class probabilities, shape (n_samples, n_classes).

        Accepts a DataFrame (what `_create_meta_features` produces) or any
        array-like. Softmax is computed on shifted logits so a large activation
        cannot overflow to inf/nan.
        """
        values = np.asarray(getattr(X, "values", X), dtype=np.float64)
        if values.ndim == 1:
            values = values.reshape(1, -1)
        if values.shape[1] != self.coef_.shape[1]:
            raise ValueError(
                f"expected {self.coef_.shape[1]} meta features, got {values.shape[1]}"
            )

        logits = values @ self.coef_.T + self.intercept_
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        return exp / exp.sum(axis=1, keepdims=True)

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"SoftmaxMetaModel(n_classes={self.coef_.shape[0]}, "
            f"n_features={self.coef_.shape[1]})"
        )


class TemperatureScaledMetaModel:
    """Repository-owned calibration wrapper fitted on a later temporal slice."""

    def __init__(self, base_model: SoftmaxMetaModel, temperature: float) -> None:
        if not np.isfinite(temperature) or temperature <= 0:
            raise ValueError("temperature must be finite and positive")
        self.base_model = base_model
        self.temperature = float(temperature)
        self.classes_ = base_model.classes_
        self.feature_names_in_ = base_model.feature_names_in_

    def predict_proba(self, X: Any) -> np.ndarray:
        probabilities = self.base_model.predict_proba(X)
        logits = np.log(np.clip(probabilities, 1e-12, 1.0)) / self.temperature
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        calibrated = exp / exp.sum(axis=1, keepdims=True)
        if not np.all(np.isfinite(calibrated)):
            raise ValueError("calibration produced non-finite probabilities")
        return calibrated

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class VectorScaledMetaModel:
    """Vector scaling calibration wrapper (Guo et al. 2017; directive §20 B2
    candidate #2 -- "vector scaling").

    Generalises ``TemperatureScaledMetaModel``: instead of one scalar shared
    across classes, each class gets its own scale and bias applied to the
    same log-probability proxy temperature scaling uses (the base model's own
    output softmax, not a separate pre-softmax logit -- this repository has
    no access to the base learners' pre-softmax scores, only their averaged
    ``predict_proba``). More flexible than temperature scaling, still far
    less flexible than isotonic regression's per-class step function --
    ``docs/DEBT.md`` item 64 measured isotonic overfitting a few hundred
    calibration rows in 4 of 6 leagues, so this sits deliberately between the
    two on the same complexity spectrum.

    Plain floats only, no fitted scikit-learn object -- same reasoning as
    ``TemperatureScaledMetaModel``, avoiding the cross-version pickle hazard
    this module's docstring documents.
    """

    def __init__(
        self, base_model: SoftmaxMetaModel, scale: np.ndarray, bias: np.ndarray
    ) -> None:
        self.base_model = base_model
        self.scale = np.asarray(scale, dtype=np.float64)
        self.bias = np.asarray(bias, dtype=np.float64)
        n_classes = len(base_model.classes_)
        if self.scale.shape != (n_classes,) or self.bias.shape != (n_classes,):
            raise ValueError(
                f"scale/bias must each be a length-{n_classes} vector; "
                f"got shapes {self.scale.shape} and {self.bias.shape}"
            )
        if not np.all(np.isfinite(self.scale)) or not np.all(np.isfinite(self.bias)):
            raise ValueError("scale/bias must be finite")
        self.classes_ = base_model.classes_
        self.feature_names_in_ = base_model.feature_names_in_

    def predict_proba(self, X: Any) -> np.ndarray:
        probabilities = self.base_model.predict_proba(X)
        logits = np.log(np.clip(probabilities, 1e-12, 1.0)) * self.scale + self.bias
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        calibrated = exp / exp.sum(axis=1, keepdims=True)
        if not np.all(np.isfinite(calibrated)):
            raise ValueError("calibration produced non-finite probabilities")
        return calibrated

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class BetaCalibratedMetaModel:
    """Beta calibration wrapper (Kull, Silva Filho & Flach 2017; directive
    §20 B2 candidate #4 -- "beta calibration where justified").

    Beta calibration is defined for binary problems; extended here via the
    same per-class one-vs-rest decomposition ``IsotonicMetaModel`` already
    uses. Each class's fitted map is ``sigmoid(a*ln(p) + b*ln(1-p) + c)`` --
    three plain floats per class, fit by direct likelihood minimisation
    (``scipy.optimize``) rather than ``sklearn.linear_model.LogisticRegression``
    (the textbook training method for this exact map) specifically to avoid
    storing a fitted scikit-learn estimator in the pickle -- this module's
    docstring documents a real cross-version ``AttributeError`` from exactly
    that class. Renormalised across classes after prediction, identically to
    ``IsotonicMetaModel``.
    """

    def __init__(
        self, base_model: SoftmaxMetaModel, params: list[tuple[float, float, float]]
    ) -> None:
        if len(params) != len(base_model.classes_):
            raise ValueError(
                f"Need one (a, b, c) triple per class; got {len(params)} for "
                f"{len(base_model.classes_)} classes."
            )
        self.base_model = base_model
        self.params = [tuple(float(v) for v in p) for p in params]
        self.classes_ = base_model.classes_
        self.feature_names_in_ = base_model.feature_names_in_

    def predict_proba(self, X: Any) -> np.ndarray:
        raw = self.base_model.predict_proba(X)
        n_classes = raw.shape[1]
        clipped = np.clip(raw, 1e-12, 1.0 - 1e-12)
        calibrated = np.empty_like(raw)
        for cls_idx, (a, b, c) in enumerate(self.params):
            log_p = np.log(clipped[:, cls_idx])
            log_1mp = np.log(1.0 - clipped[:, cls_idx])
            z = np.clip(a * log_p + b * log_1mp + c, -30.0, 30.0)
            calibrated[:, cls_idx] = 1.0 / (1.0 + np.exp(-z))
        # Renormalise -- per-class outputs are not jointly constrained, same
        # degenerate-row guard as IsotonicMetaModel (np.where evaluates both
        # branches, so the divisor must be made safe first).
        row_sums = calibrated.sum(axis=1, keepdims=True)
        positive = row_sums > 0
        safe_sums = np.where(positive, row_sums, 1.0)
        calibrated = np.where(positive, calibrated / safe_sums, 1.0 / n_classes)
        if not np.all(np.isfinite(calibrated)):
            raise ValueError("beta calibration produced non-finite probabilities")
        return calibrated

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class IsotonicMetaModel:
    """Isotonic regression calibration wrapper (Phase B / B3).

    Fits one ``IsotonicRegression`` per output class on the calibration holdout.
    Renormalises the per-class outputs to a valid probability simplex after
    prediction (isotonic regression is not jointly constrained).

    Candidate calibrator alongside ``TemperatureScaledMetaModel``; whichever
    achieves lower reliability on the calibration holdout is selected for the
    next generation (target: reliability ≤ 0.010 per Production Executive
    Directive §4.3 B3).

    ⚠️ THIS MODULE'S PATH IS PART OF THE ARTIFACT FORMAT — see the module
    docstring before moving this file.
    """

    def __init__(
        self,
        base_model: SoftmaxMetaModel,
        calibrators: list,
    ) -> None:
        """
        Args:
            base_model:   The fitted ``SoftmaxMetaModel`` whose outputs will be
                          calibrated.
            calibrators:  One fitted ``sklearn.isotonic.IsotonicRegression`` per
                          class (length must equal ``base_model.classes_``).
        """
        if len(calibrators) != len(base_model.classes_):
            raise ValueError(
                f"Need one calibrator per class; got {len(calibrators)} for "
                f"{len(base_model.classes_)} classes."
            )
        self.base_model = base_model
        self.calibrators = list(calibrators)
        self.classes_ = base_model.classes_
        self.feature_names_in_ = base_model.feature_names_in_

    def predict_proba(self, X: Any) -> np.ndarray:
        """Class probabilities, shape (n_samples, n_classes).

        Runs the base model, applies per-class isotonic regression, then
        renormalises each row to sum to 1.
        """
        raw = self.base_model.predict_proba(X)  # (n, n_classes)
        n_classes = raw.shape[1]
        calibrated = np.empty_like(raw)
        for cls_idx, iso in enumerate(self.calibrators):
            calibrated[:, cls_idx] = iso.predict(raw[:, cls_idx])
        # Renormalise — isotonic per-class outputs are not jointly constrained.
        row_sums = calibrated.sum(axis=1, keepdims=True)
        # Avoid division by zero for degenerate rows; fall back to uniform.
        # np.where evaluates BOTH branches, so the divisor must be made safe
        # first — dividing and discarding emits a RuntimeWarning on every
        # degenerate row and leaves a NaN in the discarded branch.
        positive = row_sums > 0
        safe_sums = np.where(positive, row_sums, 1.0)
        calibrated = np.where(
            positive,
            calibrated / safe_sums,
            1.0 / n_classes,
        )
        if not np.all(np.isfinite(calibrated)):
            raise ValueError("isotonic calibration produced non-finite probabilities")
        return calibrated

    def predict(self, X: Any) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]
