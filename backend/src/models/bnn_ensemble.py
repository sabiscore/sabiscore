"""
backend/src/models/bnn_ensemble.py

Soft-loading wrapper around bnn_ensemble_impl. When torch is unavailable
(e.g. the deployed environment skips heavy ML wheels), this module exposes
None sentinels so the FastAPI app can boot and the UncertaintyService falls
back to its non-BNN code path. Consuming code already guards on `torch is None`.
"""

from __future__ import annotations

try:
    from .bnn_ensemble_impl import (
        BNNEnsembleMember,
        MCDropoutBNN,
        UncertaintyOutput,
        edl_nll_loss,
    )

    _BNN_AVAILABLE = True
except ImportError:
    _BNN_AVAILABLE = False

    BNNEnsembleMember = None  # type: ignore[assignment]
    MCDropoutBNN = None  # type: ignore[assignment]
    UncertaintyOutput = None  # type: ignore[assignment]

    def edl_nll_loss(*_args, **_kwargs):  # type: ignore[misc]
        raise RuntimeError(
            "torch is not installed; BNN training/inference is disabled. "
            "Install torch to enable Phase 6 BNN features."
        )


__all__ = [
    "BNNEnsembleMember",
    "MCDropoutBNN",
    "UncertaintyOutput",
    "edl_nll_loss",
    "_BNN_AVAILABLE",
]
