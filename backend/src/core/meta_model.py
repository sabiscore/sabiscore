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

__all__ = ["SoftmaxMetaModel", "TemperatureScaledMetaModel"]


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
            raise ValueError(f"coef must be 2-D (n_classes, n_features), got {self.coef_.shape}")
        if self.intercept_.shape[0] != self.coef_.shape[0]:
            raise ValueError("intercept length must equal the number of classes")

    @classmethod
    def from_sklearn(cls, model: Any, feature_names: list[str] | None = None) -> "SoftmaxMetaModel":
        """Copy the fitted parameters out of a scikit-learn LogisticRegression."""
        return cls(
            coef=model.coef_,
            intercept=model.intercept_,
            classes=model.classes_,
            feature_names=feature_names or list(getattr(model, "feature_names_in_", []) or []),
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
