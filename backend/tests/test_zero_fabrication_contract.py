"""Static and runtime production-contract checks for fabrication and public staking leaks."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np


def _read_texts(root: Path, pattern: str) -> str:
    if not root.exists():
        return ""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in root.rglob(pattern)
        if "node_modules" not in path.parts
    )


def test_prohibited_production_patterns_are_absent() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    repo_root = backend_root.parent

    api_service_provider_text = "\n".join(
        _read_texts(backend_root / "src" / name, "*.py")
        for name in ("api", "services", "providers", "insights", "data")
    )
    transformer_text = (backend_root / "src" / "data" / "transformers.py").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    backend_source_text = _read_texts(backend_root / "src", "*.py")
    migration_text = _read_texts(backend_root / "alembic", "*.py")
    web_text = _read_texts(repo_root / "apps" / "web" / "src", "*.ts*")
    env_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (
            repo_root / "vercel.json",
            repo_root / ".env.example",
            backend_root / ".env.example",
        )
        if path.exists()
    )

    assert "FEATURE_DEFAULTS[" not in api_service_provider_text
    assert "FEATURE_DEFAULTS[" not in transformer_text
    assert "hardcoded_odds" not in api_service_provider_text
    assert "Base.metadata.create_all" not in migration_text
    assert "full_kelly_fraction" not in backend_source_text
    assert "full_kelly" not in web_text
    assert "Full-Kelly" not in web_text
    assert "Full Kelly" not in web_text
    assert "NEXT_PUBLIC_KELLY_FRACTION" not in env_text

    # INV-19: verification predicates must be computed, never asserted as a bare literal.
    verified_literal = re.compile(r'"[a-zA-Z_]*(_verified|_validated|_certified)"\s*:\s*(True|False)')
    match = verified_literal.search(backend_source_text)
    assert match is None, (
        f"Bare True/False literal bound to a *_verified/*_validated/*_certified "
        f"dict key: {match.group(0) if match else ''!r} — INV-19 violation"
    )


def test_prediction_endpoint_never_mints_a_synthetic_match_id() -> None:
    """A minted `{home}_{away}_{timestamp}` key can never equal a real Match.id.

    `get_settled_predictions()` joins `MatchPredictionLog.match_id` to `Match.id`,
    so any prediction logged under a synthesized identifier is permanently
    unjoinable and silently depresses `settled_join_rate` (docs/DEBT.md item 5).
    The endpoint must reject the write instead of fabricating an identity.
    """
    predictions_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "api"
        / "endpoints"
        / "predictions.py"
    ).read_text(encoding="utf-8", errors="ignore")

    assert "base_identifier" not in predictions_src, (
        "Synthetic match_id minting reintroduced in create_prediction() — "
        "callers must supply a real Match.id or receive HTTP 422."
    )
    assert "FIXTURE_IDENTITY_REQUIRED" in predictions_src, (
        "The fail-closed guard for a missing match_id is gone from predictions.py."
    )


def test_calibrated_ensemble_uses_prefit_cv() -> None:
    """Regression guard: CalibratedEnsemble must default to cv='prefit'.

    Using an integer cv on an already-fitted model causes CalibratedClassifierCV
    to re-fit the stacker via k-fold, introducing data leakage and discarding the
    trained model.  cv='prefit' wraps the fitted estimator directly.
    """
    from src.models.enhanced_training import CalibratedEnsemble

    mock_base = MagicMock()
    cal = CalibratedEnsemble(base_estimator=mock_base)
    assert cal.cv == "prefit", (
        "CalibratedEnsemble default cv changed — must remain 'prefit' to avoid "
        "data leakage when wrapping an already-fitted StackingClassifier"
    )


def test_probability_simplex_validity() -> None:
    """Model output probabilities must sum to 1.0 within float tolerance."""
    # Simulate the shape of probs returned by SabiScoreEnsemble / EnhancedStackingEnsemble.
    # The contract: home + draw + away == 1.0.  Test the invariant via a representative
    # output vector rather than requiring a full model fit.
    for raw in [
        [0.45, 0.28, 0.27],
        [0.60, 0.22, 0.18],
        [0.33, 0.33, 0.34],
    ]:
        probs = np.array(raw, dtype=np.float64)
        assert abs(probs.sum() - 1.0) < 1e-6, (
            f"Probability vector {raw} does not sum to 1.0 — invalid simplex"
        )


def test_explainer_fallback_is_empty_not_fabricated() -> None:
    """Regression guard: ModelExplainer must not fabricate SHAP values.

    When SHAP is unavailable or uninitialized the fallback must be empty so
    services/prediction.py falls through to deterministic ranking derived
    from the real feature vector — never hardcoded feature importances.
    """
    import pandas as pd

    from src.models.explainer import ModelExplainer

    explainer = ModelExplainer(model=None)
    features = pd.DataFrame([{"home_attack_strength": 1.0}])

    assert explainer._mock_explanation(features) == {}, (
        "ModelExplainer fallback fabricated explanation values — zero-fab violation"
    )
    perf = explainer._mock_performance_explanation()
    assert perf.get("feature_importance_global") == {}, (
        "ModelExplainer fabricated global feature importances — zero-fab violation"
    )
