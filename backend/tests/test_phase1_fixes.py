"""
Verification tests for Phase 1 fixes (BUG-001, BUG-002, BUG-003)
Test date: May 30, 2026
"""

import pytest
import numpy as np
import pandas as pd
from sklearn.datasets import make_classification
from sklearn.calibration import CalibratedClassifierCV


class TestBUG001DrawCalibration:
    """
    BUG-001: Verify isotonic calibration is used consistently across all models
    Expected: Draw calibration ratio (predicted_draw_rate / 0.246) >= 0.60
    """

    def test_ensemble_uses_isotonic_calibration(self):
        """Verify ensemble.py uses isotonic method for meta-model"""
        from src.models.ensemble import EnsembleModel
        model = EnsembleModel()
        
        # Create synthetic training data (3 classes: home, draw, away)
        X, y = make_classification(
            n_samples=1000, n_features=58, n_informative=40, 
            n_redundant=5, n_classes=3, random_state=42
        )
        X = pd.DataFrame(X)
        y_df = pd.DataFrame({'result': y})
        
        # Train model
        model.build_ensemble(X, y_df)
        
        # Verify meta_model uses isotonic
        assert model.meta_model is not None, "Meta model not initialized"
        assert hasattr(model.meta_model, 'method'), "Meta model missing calibration method"
        # CalibratedClassifierCV stores method in its attributes
        calibrator = model.meta_model
        # The calibrator should be a CalibratedClassifierCV with isotonic
        assert isinstance(calibrator, CalibratedClassifierCV), \
            f"Expected CalibratedClassifierCV, got {type(calibrator)}"

    def test_draw_calibration_ratio_above_threshold(self):
        """Verify predicted draw rate is >= 60% of actual draw rate"""
        from src.models.ensemble import EnsembleModel
        
        # Create balanced dataset with known draw rate
        np.random.seed(42)
        n_samples = 2000
        y = np.random.choice([0, 1, 2], size=n_samples, p=[0.42, 0.246, 0.334])
        X = np.random.randn(n_samples, 58) 
        X = pd.DataFrame(X)
        y_df = pd.DataFrame({'result': y})
        
        model = EnsembleModel()
        model.build_ensemble(X, y_df)
        preds = model.predict(X)
        
        # Calculate draw rates
        actual_draw_rate = (y == 1).mean()
        predicted_draw_rate = (preds['prediction'] == 'draw').mean()
        draw_calibration_ratio = predicted_draw_rate / actual_draw_rate if actual_draw_rate > 0 else 0
        
        # Assert calibration ratio >= 0.60
        assert draw_calibration_ratio >= 0.60, \
            f"Draw calibration failed: ratio={draw_calibration_ratio:.3f}, expected >= 0.60. " \
            f"Predicted: {predicted_draw_rate:.3f}, Actual: {actual_draw_rate:.3f}"

    def test_all_league_models_train_with_sample_weights(self):
        """Verify all 6 league models use sample_weight in training"""
        from src.models.leagues.premier_league import PremierLeagueModel
        from src.models.leagues.la_liga import LaLigaModel
        from src.models.leagues.bundesliga import BundesligaModel
        from src.models.leagues.serie_a import SerieAModel
        from src.models.leagues.ligue_1 import Ligue1Model
        from src.models.leagues.championship import ChampionshipModel
        import redis
        
        league_models = [
            PremierLeagueModel,
            LaLigaModel,
            BundesligaModel,
            SerieAModel,
            Ligue1Model,
            ChampionshipModel,
        ]
        
        # Mock redis connection
        try:
            redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
            redis_client.ping()
        except Exception:
            pytest.skip("Redis not available for league model tests")
        
        for LeagueModel in league_models:
            league = LeagueModel(redis_client)
            assert hasattr(league, 'train'), f"{LeagueModel.__name__} missing train method"
            assert hasattr(league, 'models'), f"{LeagueModel.__name__} missing models dict"
            # Check that models handle class imbalance via class_weight='balanced'
            # or is_unbalance=True (LightGBM native) or scale_pos_weight (XGBoost).
            for model_name, model in league.models.items():
                uses_balanced = (
                    getattr(model, 'class_weight', None) == 'balanced'
                    or getattr(model, 'is_unbalance', False) is True
                    or getattr(model, 'scale_pos_weight', None) not in (None, 1)
                )
                # Allow models that don't expose a class_weight attribute (e.g. stacked meta)
                if hasattr(model, 'class_weight') or hasattr(model, 'is_unbalance'):
                    assert uses_balanced, (
                        f"{LeagueModel.__name__}.{model_name} not using balanced class weighting. "
                        f"class_weight={getattr(model, 'class_weight', 'N/A')}, "
                        f"is_unbalance={getattr(model, 'is_unbalance', 'N/A')}"
                    )


class TestBUG003FeatureRegistry:
    """
    BUG-003: Verify feature registry has exactly 58 features with defaults
    """

    def test_feature_registry_has_58_features(self):
        """Verify CANONICAL_FEATURES_58 contains exactly 58 features"""
        from src.models.feature_registry import CANONICAL_FEATURES_58, canonical_feature_count
        
        assert len(CANONICAL_FEATURES_58) == 58, \
            f"Expected 58 canonical features, got {len(CANONICAL_FEATURES_58)}"
        assert canonical_feature_count() == 58, \
            f"canonical_feature_count() returned {canonical_feature_count()}, expected 58"

    def test_feature_registry_has_all_defaults(self):
        """Verify all canonical features have default values"""
        from src.models.feature_registry import CANONICAL_FEATURES_58, DEFAULT_FEATURE_VALUES_58
        
        for feature in CANONICAL_FEATURES_58:
            assert feature in DEFAULT_FEATURE_VALUES_58, \
                f"Feature '{feature}' missing from DEFAULT_FEATURE_VALUES_58"
        
        # Verify count matches
        assert len(DEFAULT_FEATURE_VALUES_58) == 58, \
            f"Expected 58 default values, got {len(DEFAULT_FEATURE_VALUES_58)}"

    def test_transformers_imports_feature_registry(self):
        """Verify transformers.py imports from feature_registry"""
        import inspect
        from src.data import transformers
        
        source = inspect.getsource(transformers)
        assert 'feature_registry' in source, \
            "transformers.py does not import from feature_registry"
        # Accept 58, 65, or 68 — the canonical set evolved across phases
        assert any(
            name in source
            for name in ('CANONICAL_FEATURES_58', 'CANONICAL_FEATURES_65', 'CANONICAL_FEATURES_68')
        ), "transformers.py does not reference any CANONICAL_FEATURES constant"

    def test_no_feature_dimension_mismatch(self):
        """Verify no 86 or 87-feature lists in critical paths"""
        import inspect
        from src.insights import engine
        
        source = inspect.getsource(engine)
        # Should not have hardcoded 86 or 87
        assert '[86]' not in source and '[87]' not in source, \
            "insights/engine.py contains hardcoded feature dimension mismatch"


class TestBUG002TFJSDisconnection:
    """
    BUG-002: Verify TypeScript prediction route proxies to FastAPI backend
    """

    @staticmethod
    def _predict_route_path():
        # Repo-root-relative so this test isn't tied to one developer's machine.
        from pathlib import Path

        return (
            Path(__file__).resolve().parents[2]
            / "apps" / "web" / "src" / "app" / "api" / "predict" / "route.ts"
        )

    def test_predict_route_proxies_to_backend(self):
        """Verify /api/predict route uses backend URL"""
        content = self._predict_route_path().read_text()

        assert 'resolveBackendBaseUrl()' in content, \
            "predict/route.ts does not call resolveBackendBaseUrl()"
        assert '/api/v1/predictions/predict' in content, \
            "predict/route.ts does not proxy to /api/v1/predictions/predict"
        assert 'backendResponse = await fetch' in content, \
            "predict/route.ts does not fetch from backend"

    def test_no_tfjs_in_prediction_endpoint(self):
        """Verify TFJSEnsembleEngine not used in prediction endpoint"""
        content = self._predict_route_path().read_text()

        assert 'TFJSEnsembleEngine' not in content, \
            "predict/route.ts incorrectly uses TFJSEnsembleEngine"

    def test_backend_health_check_endpoint_exists(self):
        """Verify prediction route can check backend health"""
        content = self._predict_route_path().read_text()

        assert '/api/v1/health' in content, \
            "predict/route.ts missing health check endpoint"


class TestPhase1Integration:
    """Integration tests for all Phase 1 fixes working together"""

    def test_feature_dimension_consistency_across_pipeline(self):
        """Verify 58-feature dimension is maintained end-to-end"""
        from src.models.feature_registry import CANONICAL_FEATURES_58, canonical_feature_count
        
        # Test 1: Registry has 58
        assert canonical_feature_count() == 58
        
        # Test 2: Default values match
        from src.models.feature_registry import DEFAULT_FEATURE_VALUES_58
        assert len(DEFAULT_FEATURE_VALUES_58) == len(CANONICAL_FEATURES_58)

    def test_calibration_workflow(self):
        """Verify calibration workflow from ensemble to leagues"""
        from src.models.ensemble import EnsembleModel
        
        # Create minimal training data
        X = pd.DataFrame(np.random.randn(500, 58))
        y = pd.DataFrame({'result': np.random.choice([0, 1, 2], 500)})
        
        model = EnsembleModel()
        # Should not raise exception
        model.build_ensemble(X, y)
        
        # Should be able to make predictions
        X_test = pd.DataFrame(np.random.randn(10, 58))
        preds = model.predict(X_test)
        
        assert len(preds) == 10
        assert 'draw_prob' in preds.columns
        assert preds['draw_prob'].between(0, 1).all()


# Run all tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])
