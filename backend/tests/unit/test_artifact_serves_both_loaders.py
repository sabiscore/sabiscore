"""Every committed artifact must satisfy BOTH loaders, not just one.

Two independent code paths read the same `*_ensemble_v5_phase7.pkl` files and
they need different things from them:

1. `PredictionEngine._load_from_disk` / `_ensemble_predict_dict` — averages the
   base learners in `models` and never touches `meta_model`. This is the request
   path (`/upcoming/matches`, `/full-analysis`).
2. `SabiScoreEnsemble.load_model` → `.predict()` — stacks through
   `meta_model.predict_proba()` and raises "Meta model is not initialized" if it
   is None. This runs at **startup** via `_startup_load_models_strict`, and a
   failure there aborts the lifespan: uvicorn never binds, the container exits,
   Render restarts it, and the service is hard-down.

A retrain that satisfied only (1) shipped `meta_model: None` and took production
offline on deploy — every artifact loaded and predicted correctly in the request
path while the strict startup check rejected all six. These tests exercise the
real committed artifacts through both paths, using the same smoke test the
startup code runs.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

from src.core.model_fetcher import _smoke_test_ensemble_model
from src.models.ensemble import SabiScoreEnsemble
from src.models.feature_registry import CANONICAL_FEATURES_68, DEFAULT_FEATURE_VALUES_68
from src.models.prediction import PredictionEngine

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
_LEAGUES = ["epl", "la_liga", "bundesliga", "serie_a", "ligue_1", "eredivisie"]


def _artifact(league: str) -> Path:
    return _MODELS_DIR / f"{league}_ensemble_v5_phase7.pkl"


@pytest.mark.parametrize("league", _LEAGUES)
def test_strict_startup_path_accepts_artifact(league: str):
    """The exact check `_startup_load_models_strict` performs on boot."""
    path = _artifact(league)
    if not path.exists():
        pytest.skip(f"{path.name} not present in this checkout")

    model = SabiScoreEnsemble.load_model(str(path))
    assert model.meta_model is not None, (
        f"{path.name} has meta_model=None — SabiScoreEnsemble.predict() raises "
        "'Meta model is not initialized', which aborts application startup"
    )
    # Raises on any contract violation; that raise is what takes prod down.
    _smoke_test_ensemble_model(model, league=league, artifact_name=path.name)


@pytest.mark.parametrize("league", _LEAGUES)
def test_stacked_head_returns_a_valid_simplex(league: str):
    path = _artifact(league)
    if not path.exists():
        pytest.skip("artifact not present in this checkout")

    import pandas as pd

    model = SabiScoreEnsemble.load_model(str(path))
    row = {name: DEFAULT_FEATURE_VALUES_68[name] for name in CANONICAL_FEATURES_68}
    result = model.predict(pd.DataFrame([row]))

    probs = [
        float(result["home_win_prob"].iloc[0]),
        float(result["draw_prob"].iloc[0]),
        float(result["away_win_prob"].iloc[0]),
    ]
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert abs(sum(probs) - 1.0) < 1e-6


@pytest.mark.parametrize("league", ["EPL", "LA_LIGA"])
def test_request_path_still_serves_the_same_artifact(league: str):
    """Both loaders must work off one file — fixing one must not break the other."""
    if not _artifact(league.lower()).exists():
        pytest.skip("artifact not present in this checkout")

    vector = np.array(
        [DEFAULT_FEATURE_VALUES_68[f] for f in CANONICAL_FEATURES_68], dtype=np.float32
    )
    result = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        PredictionEngine().predict(features=vector, league=league)
    )
    assert result.model_version != "fallback"
    assert abs((result.home_win + result.draw + result.away_win) - 1.0) < 1e-3


@pytest.mark.parametrize("league", _LEAGUES)
def test_meta_head_carries_no_sklearn_version_coupling(league: str):
    """Artifacts are built on a different library stack than they are served on.

    Production runs scikit-learn 1.3.2 (Python 3.11); these artifacts are built
    on 1.8. scikit-learn only guarantees pickle compatibility within one version:
    a LogisticRegression fitted on 1.8 deserialises fine under 1.3.2 but dies in
    predict_proba, which reads `self.multi_class` — an attribute 1.8 stopped
    setting. That raise happens inside the strict startup check, so the release
    cannot deploy at all.

    The meta head must therefore be a type this repository owns, not an sklearn
    estimator. Base learners are exempt: they were verified to load and score
    under the production versions.
    """
    path = _artifact(league)
    if not path.exists():
        pytest.skip("artifact not present in this checkout")

    from src.core.meta_model import SoftmaxMetaModel

    meta = SabiScoreEnsemble.load_model(str(path)).meta_model
    assert isinstance(meta, SoftmaxMetaModel), (
        f"{path.name} meta_model is {type(meta).__module__}.{type(meta).__name__}; "
        "an sklearn estimator here re-introduces the cross-version unpickle failure"
    )
    assert not type(meta).__module__.startswith("sklearn")


def test_softmax_meta_model_matches_sklearn_output():
    """The hand-rolled head must reproduce what sklearn would have returned —
    it carries sklearn's fitted coefficients, so any drift is a bug here."""
    pytest.importorskip("sklearn")
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    from src.core.meta_model import SoftmaxMetaModel

    rng = np.random.default_rng(0)
    X = rng.normal(size=(200, 9))
    y = rng.integers(0, 3, size=200)
    fitted = LogisticRegression(max_iter=1000, random_state=42).fit(X, y)

    ported = SoftmaxMetaModel.from_sklearn(fitted)
    np.testing.assert_allclose(
        ported.predict_proba(X), fitted.predict_proba(X), rtol=1e-9, atol=1e-9
    )


def test_softmax_meta_model_rejects_a_meta_feature_count_mismatch():
    """Silent truncation here would mis-weight base models rather than fail."""
    import numpy as np

    from src.core.meta_model import SoftmaxMetaModel

    meta = SoftmaxMetaModel(
        coef=np.zeros((3, 9)), intercept=np.zeros(3), classes=np.array([0, 1, 2])
    )
    with pytest.raises(ValueError, match="expected 9 meta features"):
        meta.predict_proba(np.zeros((1, 6)))
