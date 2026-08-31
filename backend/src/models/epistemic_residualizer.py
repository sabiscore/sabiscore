"""Aleatoric residualization of epistemic uncertainty (ADR 0009 / docs/DEBT.md item 50).

WHY THIS EXISTS
---------------
`ensemble_uncertainty.py` measures epistemic uncertainty as BALD mutual
information over ensemble members. Measured on real holdouts, that quantity is
anti-correlated with aleatoric uncertainty (`corr = -0.267` on the EPL holdout),
and aleatoric is the component that legitimately tracks realised error
(`corr(aleatoric, RPS) = +0.072`). Bucketing fixtures by raw epistemic therefore
implicitly *reverse*-buckets them by aleatoric, which is most of why
`UNCERTAINTY_GATES["error_association"]` measures a reversed relationship
(ADR 0009 Addendum 3).

This module removes that confound by fitting a monotonic baseline
``f(u_alea) -> E[u_epi | u_alea]`` and reporting the residual
``u_epi_residual = u_epi - f(u_alea)`` — "how much more (or less) do the members
disagree than is typical for fixtures of this intrinsic difficulty".

⚠️ **THIS CHANGES NO GATE AND CERTIFIES NOTHING.**
`UNCERTAINTY_GATES["error_association"]` is unmodified and still measures raw
epistemic, still fails, and still keeps `MODEL_UNCERTAINTY_UNAVAILABLE`
unconditionally CRITICAL. Re-specifying that gate around this residual would be
redefining a certification measurement *after* observing that it blocks
promotion — what APEX §23 forbids — and is a deliberate, recorded authorization
decision, not a side effect of this module existing. Until such a decision is
taken and versioned into the frozen policy, this is diagnostic instrumentation
only, exercised by `scripts/diagnose_decoupled_uncertainty.py`.

⚠️ **FIT OUT-OF-FOLD.** Fitting ``f`` on the same rows the residual is then
evaluated on makes the residual decorrelated from aleatoric *by construction*
on exactly that data, so any downstream association it shows is partly a
fitting artifact. Fit on rows disjoint from the evaluation set — the diagnostic
uses pre-holdout seasons — and treat an in-sample-fit number as an upper bound,
never as evidence.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

# sklearn is a hard dependency of the training/serving stack (requirements.txt),
# unlike scipy, which this codebase soft-imports where it is used. sklearn ships
# no py.typed marker and the repo has no mypy config to blanket-ignore it, so an
# untyped-import error is raised per import site; silenced here so this module
# adds nothing to the legacy ceiling.
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

#: Bumped when the residual's definition changes, never for wording.
RESIDUALIZER_VERSION = "r1"

#: Below this many fit rows the isotonic baseline is noise fitted to noise.
MIN_FIT_ROWS = 50


class EpistemicResidualizerError(RuntimeError):
    """Raised when a residual is requested from an unfitted or invalid model."""


class EpistemicResidualizer:
    """Isotonic ``f(u_alea) -> E[u_epi | u_alea]``, and the residual around it.

    Isotonic rather than linear because the confound is a *monotone* nuisance
    trend with no reason to be straight: the model only assumes that fixtures
    with higher intrinsic difficulty tend toward a higher baseline member
    disagreement, not that they do so linearly.
    """

    #: ⚠️ ``"auto"``, never ``True``. The real confound is NEGATIVE — epistemic
    #: *decreases* as aleatoric rises (corr = -0.267 on the EPL holdout). A
    #: hardcoded ``increasing=True`` can only fit a non-decreasing baseline, so
    #: against this data it fits a near-flat line, subtracts a constant, and
    #: removes none of the trend while appearing to work. sklearn's ``"auto"``
    #: picks the direction from the data via Spearman.
    #: `test_residual_removes_the_monotone_aleatoric_trend` fails if this is
    #: pinned back to True.
    _INCREASING = "auto"

    def __init__(self, out_of_bounds: str = "clip") -> None:
        self.out_of_bounds = out_of_bounds
        self._model: Optional[IsotonicRegression] = None

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    def fit(self, u_alea: np.ndarray, u_epi: np.ndarray) -> "EpistemicResidualizer":
        """Fit the monotone baseline. Both inputs are per-row 1-D arrays."""
        alea = np.asarray(u_alea, dtype=np.float64).ravel()
        epi = np.asarray(u_epi, dtype=np.float64).ravel()

        if alea.size != epi.size:
            raise ValueError(f"length mismatch: u_alea={alea.size} u_epi={epi.size}")
        if alea.size < MIN_FIT_ROWS:
            raise ValueError(f"need >= {MIN_FIT_ROWS} rows to fit a baseline, got {alea.size}")
        if not (np.isfinite(alea).all() and np.isfinite(epi).all()):
            raise ValueError("u_alea/u_epi contain non-finite values")

        model = IsotonicRegression(increasing=self._INCREASING, out_of_bounds=self.out_of_bounds)
        model.fit(alea, epi)
        self._model = model
        return self

    def transform(self, u_alea: np.ndarray, u_epi: np.ndarray) -> np.ndarray:
        """``u_epi - f(u_alea)``. Sign is meaningful; the residual is centred on
        the fitted baseline, so it is negative for fixtures whose members agree
        more than is typical at that aleatoric level."""
        if self._model is None:
            raise EpistemicResidualizerError("residualizer must be fitted before transform")

        alea = np.asarray(u_alea, dtype=np.float64).ravel()
        epi = np.asarray(u_epi, dtype=np.float64).ravel()
        if alea.size != epi.size:
            raise ValueError(f"length mismatch: u_alea={alea.size} u_epi={epi.size}")

        baseline = np.asarray(self._model.predict(alea), dtype=np.float64)
        return (epi - baseline).astype(np.float64)

    def fit_transform(self, u_alea: np.ndarray, u_epi: np.ndarray) -> np.ndarray:
        """⚠️ In-sample by definition — see the module docstring. Use only for a
        deliberate upper-bound reading, never as evaluation evidence."""
        return self.fit(u_alea, u_epi).transform(u_alea, u_epi)

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable state, for embedding in an artifact manifest."""
        if self._model is None:
            return {"version": RESIDUALIZER_VERSION, "is_fitted": False}
        return {
            "version": RESIDUALIZER_VERSION,
            "is_fitted": True,
            "out_of_bounds": self.out_of_bounds,
            # Knots only. `from_dict` re-fits on them rather than assigning
            # sklearn's private fitted attributes: assigning `f_x_`/`y_thresholds_`
            # directly leaves the interpolator `f_` unbuilt, so `predict` raises,
            # and the private attribute names are not stable across sklearn
            # versions. Re-fitting on already-isotonic knots reproduces the same
            # function through the public API.
            # The resolved direction is stored, not re-derived: "auto" re-runs a
            # Spearman test on the knots, and a reconstruction must reproduce the
            # baseline that was actually fitted, not re-decide it.
            "increasing": bool(self._model.increasing_),
            "x_thresholds": np.asarray(self._model.X_thresholds_, dtype=np.float64).tolist(),
            "y_thresholds": np.asarray(self._model.y_thresholds_, dtype=np.float64).tolist(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpistemicResidualizer":
        instance = cls(out_of_bounds=str(data.get("out_of_bounds", "clip")))
        if not data.get("is_fitted", False):
            return instance

        version = str(data.get("version", ""))
        if version != RESIDUALIZER_VERSION:
            raise EpistemicResidualizerError(
                f"residualizer version mismatch: artifact declares {version!r}, "
                f"this build is {RESIDUALIZER_VERSION!r}"
            )

        x = np.asarray(data["x_thresholds"], dtype=np.float64)
        y = np.asarray(data["y_thresholds"], dtype=np.float64)
        if x.size != y.size or x.size == 0:
            raise EpistemicResidualizerError("malformed isotonic knots in serialised state")

        model = IsotonicRegression(
            increasing=bool(data["increasing"]), out_of_bounds=instance.out_of_bounds
        )
        model.fit(x, y)  # already isotonic -> reproduces the same interpolator
        instance._model = model
        return instance
