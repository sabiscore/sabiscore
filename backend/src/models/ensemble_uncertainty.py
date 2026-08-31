"""Ensemble-dispersion epistemic/aleatoric uncertainty (ADR 0009, M2).

Implements ``UNCERTAINTY_METHOD = "ensemble_dispersion"`` — the only method
``uncertainty_policy.py`` authorises to satisfy the ``MODEL_UNCERTAINTY_UNAVAILABLE``
certification gate. Uses the BALD / mutual-information decomposition
(Depeweg et al. 2018; Houlsby et al. 2011)::

    total      = H( mean_m p_m )      predictive entropy of the ensemble mean
    aleatoric  = mean_m H( p_m )      average within-member entropy
    epistemic  = total - aleatoric    mutual information; >= 0, zero iff members agree

``m`` indexes ensemble members; ``H`` is Shannon entropy in nats, bounded by
``ln(3)`` for this 3-outcome task — so is ``epistemic``, since it is a
subtraction of a non-negative quantity from a quantity it can never exceed.

Members are the shipped ``random_forest`` base learner's own bootstrap-resampled
trees (``estimators_``), not the ensemble's three distinct base algorithms
(random_forest / xgboost / lightgbm). ``UNCERTAINTY_GATES.sufficient_members``
(``uncertainty_policy.py``) prefers bootstrap/resampling variants because they
vary the training sample — the sampling uncertainty epistemic uncertainty is
meant to capture — over distinct model classes, which vary only algorithm
choice. The shipped artifacts carry exactly this (300 trees per league),
clearing ``preferred_members=30`` by an order of magnitude with no retraining
and no new dependency (ADR 0009's feasibility measurement).

This is NOT a transform of the ensemble's own aggregate prediction. Two
fixtures with an identical mean probability vector receive different
epistemic values whenever their trees disagree by different amounts — exactly
the information ``FORBIDDEN_EPISTEMIC_SOURCES`` (``1 - max(p)``, ``entropy(p)``,
...) cannot carry, because those are deterministic functions of that same mean
vector alone.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from ..core.redaction import redact_text
from .prediction import PredictionEngine
from .uncertainty_policy import UNCERTAINTY_METHOD

logger = logging.getLogger(__name__)

#: Versions the *shape* of `EnsembleUncertainty`'s fields. Bump only on a
#: breaking field change — a value/threshold change is `UNCERTAINTY_POLICY_VERSION`'s
#: job (`uncertainty_policy.py`), not this module's.
UNCERTAINTY_CONTRACT_VERSION = "u1"

#: Mirrors `UNCERTAINTY_GATES["sufficient_members"]["threshold"]["min_members"]`.
#: Duplicated as a literal (not imported) so this module's own failure mode
#: never depends on policy-module internals beyond the one constant it cites;
#: `test_uncertainty_contract.py` pins the two to stay equal.
MIN_MEMBERS = 3

#: Upper bound on Shannon entropy for a 3-outcome task (nats); also the upper
#: bound on `epistemic`, since `epistemic <= total` by construction.
MAX_ENTROPY_NATS = math.log(3)


@dataclass(frozen=True)
class EnsembleUncertainty:
    """Typed, versioned `ensemble_dispersion` result (ADR 0009 / Stage 10).

    ``epistemic``/``aleatoric``/``total`` are Shannon-entropy nats, in
    ``[0, ln(3)]`` for this 3-outcome task. ``credible_interval`` is the real
    empirical 95% interval of the ensemble's own predicted probability for its
    top (mean-vector-argmax) class, across members — not a parametric (Wald)
    approximation.

    ``available=True`` only when the computation ran on real, independently
    trained ensemble members and returned finite output for every quantity.
    There is no fallback value: ``available=False`` is the only alternative to
    a genuine measurement (`AVAILABILITY_SEMANTICS` in `uncertainty_policy.py`).
    """

    epistemic: float
    aleatoric: float
    total: float
    credible_interval: Tuple[float, float]
    method: str
    model_count: int
    version: str
    available: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "epistemic": self.epistemic,
            "aleatoric": self.aleatoric,
            "total": self.total,
            "credible_interval": list(self.credible_interval),
            "method": self.method,
            "model_count": self.model_count,
            "version": self.version,
            "available": self.available,
        }


UNAVAILABLE = EnsembleUncertainty(
    epistemic=0.0,
    aleatoric=0.0,
    total=0.0,
    credible_interval=(0.0, 0.0),
    method=UNCERTAINTY_METHOD,
    model_count=0,
    version=UNCERTAINTY_CONTRACT_VERSION,
    available=False,
)


def _ordered_vector(feature_columns: List[str], features: Mapping[str, Any]) -> Optional[np.ndarray]:
    """Build the model's exact training-order feature vector, or None.

    Strict on purpose, mirroring `UncertaintyService._build_input_tensor`'s
    `strict=True` path: a feature missing from `features` returns None rather
    than being zero-filled, so an incomplete evidence set cannot masquerade as
    a real measurement.
    """
    values: List[float] = []
    for name in feature_columns:
        if name not in features:
            return None
        try:
            value = float(features[name])
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        values.append(value)
    return np.asarray(values, dtype=np.float64).reshape(1, -1)


def member_probabilities(models_dict: Dict[str, Any], X: np.ndarray) -> List[np.ndarray]:
    """One normalised probability vector per bootstrap tree in `random_forest`.

    Each `DecisionTreeClassifier` in `estimators_` was fit on a different
    bootstrap resample of the training rows, so its `predict_proba` on the
    same input genuinely differs from its siblings' — real sampling
    disagreement, not a copy of the forest's own aggregate vote.
    """
    rf = models_dict.get("random_forest")
    trees = getattr(rf, "estimators_", None) if rf is not None else None
    if not trees:
        return []
    members: List[np.ndarray] = []
    for tree in trees:
        try:
            p = np.asarray(tree.predict_proba(X), dtype=np.float64)[0]
        except Exception:
            continue
        if p.shape != (3,) or not np.isfinite(p).all() or p.sum() <= 0:
            continue
        members.append(p / p.sum())
    return members


def _entropy_nats(p: np.ndarray) -> float:
    clipped = np.clip(p, 1e-12, 1.0)
    return float(-(clipped * np.log(clipped)).sum())


def dispersion_from_members(members: List[np.ndarray]) -> EnsembleUncertainty:
    """Pure BALD decomposition over already-collected member probability vectors.

    Separated from the model-loading path so validation tests (determinism,
    independence, error association — Stage 11) can exercise the exact
    certified math directly against a real member matrix, without an artifact
    load or an event loop.
    """
    if len(members) < MIN_MEMBERS:
        return UNAVAILABLE
    stacked = np.stack(members, axis=0)  # (M, 3)
    mean_p = stacked.mean(axis=0)
    total = _entropy_nats(mean_p)
    aleatoric = float(np.mean([_entropy_nats(m) for m in stacked]))
    epistemic = total - aleatoric
    if not all(math.isfinite(v) for v in (total, aleatoric, epistemic)):
        return UNAVAILABLE
    # Non-negative by construction (mutual information); clamp defensively
    # against floating-point underflow rather than let a -1e-16 fail a >= 0
    # assertion downstream.
    epistemic = max(0.0, epistemic)

    top_idx = int(np.argmax(mean_p))
    top_probs = stacked[:, top_idx]
    lower = float(np.clip(np.percentile(top_probs, 2.5), 0.0, 1.0))
    upper = float(np.clip(np.percentile(top_probs, 97.5), 0.0, 1.0))

    return EnsembleUncertainty(
        epistemic=epistemic,
        aleatoric=aleatoric,
        total=total,
        credible_interval=(lower, upper),
        method=UNCERTAINTY_METHOD,
        model_count=len(members),
        version=UNCERTAINTY_CONTRACT_VERSION,
        available=True,
    )


async def compute_ensemble_uncertainty(league: str, features: Mapping[str, Any]) -> EnsembleUncertainty:
    """Ensemble-dispersion epistemic/aleatoric/total for one fixture's feature row.

    Reuses `PredictionEngine`'s own cached artifact — the identical league
    model, feature-width contract, and load path the live prediction for this
    same fixture already used, so uncertainty and prediction can never
    silently diverge on which artifact generation produced them.
    """
    if not features:
        return UNAVAILABLE
    try:
        bundle = await PredictionEngine().get_artifact_bundle(league)
    except Exception as exc:
        logger.warning(
            "EnsembleUncertainty: artifact load failed for league=%s: %s",
            league,
            redact_text(exc),
        )
        return UNAVAILABLE
    if bundle is None or not bundle.models_dict or not bundle.feature_columns:
        return UNAVAILABLE

    X = _ordered_vector(bundle.feature_columns, features)
    if X is None:
        return UNAVAILABLE

    members = member_probabilities(bundle.models_dict, X)
    return dispersion_from_members(members)
