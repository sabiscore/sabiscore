"""Tests for ML ensemble model."""
from unittest.mock import patch
import pandas as pd
import pytest

from src.models.ensemble import SabiScoreEnsemble


@pytest.fixture
def sample_training_data():
    """Sample training data for model testing."""
    return pd.DataFrame({
        "home_goals_avg": [1.8, 2.1, 1.5, 2.2, 1.9, 1.7, 2.0, 1.6, 2.3, 1.4],
        "away_goals_avg": [1.2, 1.8, 1.9, 1.3, 1.6, 1.4, 1.5, 1.7, 1.1, 2.0],
        "home_win_rate": [0.6, 0.7, 0.4, 0.8, 0.5, 0.6, 0.7, 0.4, 0.8, 0.5],
        "away_win_rate": [0.4, 0.5, 0.6, 0.3, 0.4, 0.5, 0.6, 0.4, 0.3, 0.5],
        "result": ["home_win", "draw", "away_win", "home_win", "draw", "away_win", "home_win", "draw", "away_win", "home_win"]
    })


def test_ensemble_initialization():
    """Test ensemble model can be initialized."""
    model = SabiScoreEnsemble()
    assert model.models == {}
    assert not model.is_trained


def test_ensemble_predict_untrained(sample_training_data):
    """Test prediction fails gracefully when model is untrained."""
    model = SabiScoreEnsemble()
    
    with pytest.raises(Exception):  # Should raise an error for untrained model
        model.predict(sample_training_data.drop("result", axis=1))


def test_ensemble_basic_functionality():
    """Test basic ensemble functionality with minimal mocking."""
    model = SabiScoreEnsemble()
    
    # Test that we can save/load (even if not trained)
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # Mock the joblib and json operations
        with patch("joblib.dump") as mock_dump, \
             patch("json.dump") as mock_json_dump:
            
            model.save_model(tmpdir, "test_model")
            assert mock_dump.called
            assert mock_json_dump.called
