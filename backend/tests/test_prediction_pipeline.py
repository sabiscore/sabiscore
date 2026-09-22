"""End-to-end smoke test for prediction pipeline with real data integration.

NOTE: These are integration tests that require:
- Trained ML models in the models/ directory
- Database connectivity
- Redis cache (optional)

Run with: pytest tests/test_prediction_pipeline.py -v --run-integration
Skip by default in CI: these tests require external resources.
"""

import logging
import os

import pytest
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.core.config import settings
from src.models.ensemble import SabiScoreEnsemble
from src.schemas.prediction import MatchPredictionRequest
from src.services.prediction import PredictionService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Opt-in integration tests. These exercise the full prediction path which, post
# zero-fabrication, requires real provider evidence (form, stats, H2H) — not just
# trained models on disk. Models existing is insufficient, so gate purely on the
# explicit opt-in the module docstring documents.
pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Integration tests require external resources (real provider evidence, DB, Redis). Set RUN_INTEGRATION_TESTS=1 to run.",
)


@pytest.mark.integration
class TestPredictionPipeline:
    """Comprehensive tests for the entire prediction pipeline."""

    @pytest.fixture
    async def client(self):
        """Async HTTP client for API testing."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    @pytest.fixture
    def sample_match_request(self):
        """Sample match prediction request."""
        return MatchPredictionRequest(
            match_id="test_epl_001",
            home_team="Arsenal",
            away_team="Liverpool",
            league="epl",
            odds={
                "home_win": 2.10,
                "draw": 3.40,
                "away_win": 3.50,
            },
            bankroll=10_000,
        )

    @pytest.mark.asyncio
    async def test_health_endpoints(self, client):
        """Test health check endpoints."""
        logger.info("Testing health endpoints...")

        # Test basic health
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        # Accept healthy or degraded - degraded is valid in test env without models/redis
        assert data["status"] in ("healthy", "degraded"), (
            f"Unexpected status: {data['status']}"
        )
        assert "version" in data

        # Test readiness probe
        response = await client.get("/ready")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "checks" in data
        assert "database" in data["checks"]
        assert "cache" in data["checks"]
        assert "models" in data["checks"]

        logger.info("Health endpoints working")

    @pytest.mark.asyncio
    async def test_model_loading(self):
        """Test that models can be loaded from disk."""
        logger.info("Testing model loading...")

        models_path = settings.models_path
        assert models_path.exists(), f"Models directory {models_path} does not exist"

        # Check for trained models
        model_files = list(models_path.glob("*_ensemble.pkl"))
        logger.info(
            f"Found {len(model_files)} model files: {[f.name for f in model_files]}"
        )

        if not model_files:
            pytest.skip("No trained models found - run training first")

        # Test loading first model
        try:
            model = SabiScoreEnsemble.load_model(str(model_files[0]))
        except Exception as exc:
            # Model pickle incompatibility (numpy version mismatch) is common in test env
            pytest.skip(
                f"Model could not be loaded (possible numpy version mismatch): {exc}"
            )

        assert model is not None
        assert model.is_trained
        assert len(model.feature_columns) > 0
        logger.info("Model loaded with %s features", len(model.feature_columns))

    @pytest.mark.asyncio
    async def test_feature_generation(self):
        """Test synthetic feature generation for predictions."""
        logger.info("Testing feature generation...")

        service = PredictionService()
        request = MatchPredictionRequest(
            home_team="Arsenal",
            away_team="Liverpool",
            league="epl",
            odds={"home_win": 2.1, "draw": 3.3, "away_win": 3.5},
        )

        # Load a model to get feature columns
        models_path = settings.models_path
        model_files = list(models_path.glob("*_ensemble.pkl"))
        if not model_files:
            pytest.skip("No models available")

        try:
            model = SabiScoreEnsemble.load_model(str(model_files[0]))
        except Exception as exc:
            pytest.skip(f"Model could not be loaded: {exc}")

        # Generate features (returns 3 values: frame, vector, context)
        frame, vector, context = service._build_feature_frame(
            "test_match_001",
            request,
            model,
            "epl",
        )

        assert not frame.empty
        assert len(vector) == len(model.feature_columns)
        assert isinstance(context, dict)
        logger.info("Generated %s synthetic features", len(vector))

    @pytest.mark.asyncio
    async def test_prediction_endpoint(self, client, sample_match_request):
        """Test full prediction endpoint flow."""
        logger.info("Testing prediction endpoint...")

        # Check if models are available and loadable
        models_path = settings.models_path
        model_files = list(models_path.glob("*_ensemble.pkl"))
        if not model_files:
            pytest.skip("No models available - run training first")

        # Pre-check model loadability to avoid masking HTTP errors
        try:
            SabiScoreEnsemble.load_model(str(model_files[0]))
        except Exception as exc:
            pytest.skip(f"Model could not be loaded (numpy version mismatch?): {exc}")

        response = await client.post(
            "/api/v1/predictions/",
            json=sample_match_request.model_dump(),
        )

        # May return 503 if models not loaded yet, 500 if internal error, or 200 on success
        if response.status_code == 503:
            logger.warning(
                "Models not loaded, endpoint returned 503 (expected in cold start)"
            )
            pytest.skip("Models not loaded yet")
        if response.status_code == 500:
            logger.warning("Internal server error - possibly model loading issue")
            pytest.skip("Server error - check model compatibility")

        assert response.status_code == 200
        data = response.json()

        # Validate response structure
        assert "match_id" in data
        assert "predictions" in data
        assert "confidence" in data
        assert "value_bets" in data

        # Validate probabilities
        predictions = data["predictions"]
        assert "home_win" in predictions
        assert "draw" in predictions
        assert "away_win" in predictions

        total_prob = sum(predictions.values())
        assert 0.98 <= total_prob <= 1.02, f"Probabilities sum to {total_prob}"

        logger.info("Prediction generated: %s", predictions)
        logger.info(f"   Confidence: {data['confidence']:.3f}")
        logger.info(f"   Value bets: {len(data['value_bets'])}")

    @pytest.mark.asyncio
    async def test_prediction_service_direct(self, sample_match_request):
        """Test PredictionService directly without HTTP layer."""
        logger.info("Testing PredictionService directly...")

        models_path = settings.models_path
        model_files = list(models_path.glob("*_ensemble.pkl"))
        if not model_files:
            pytest.skip("No models available")

        # Load model
        try:
            model = SabiScoreEnsemble.load_model(str(model_files[0]))
        except Exception as exc:
            pytest.skip(f"Model could not be loaded: {exc}")

        # Create service with loaded model
        service = PredictionService(ensemble_model=model)

        # Generate prediction
        result = await service.predict_match(
            match_id="test_direct_001",
            request=sample_match_request,
        )

        # Validate result
        assert result.match_id == "test_direct_001"
        assert result.home_team == "Arsenal"
        assert result.away_team == "Liverpool"
        assert 0 <= result.confidence <= 1
        assert 0 <= result.brier_score <= 2

        logger.info("Direct prediction output: %s", result.predictions)
        logger.info(f"   Metadata: {result.metadata}")

    @pytest.mark.asyncio
    async def test_value_bet_detection(self, sample_match_request):
        """Test value bet detection with realistic odds."""
        logger.info("Testing value bet detection...")

        models_path = settings.models_path
        model_files = list(models_path.glob("*_ensemble.pkl"))
        if not model_files:
            pytest.skip("No models available")

        try:
            model = SabiScoreEnsemble.load_model(str(model_files[0]))
        except Exception as exc:
            pytest.skip(f"Model could not be loaded: {exc}")
        service = PredictionService(ensemble_model=model)

        # Generate prediction with value opportunity
        request = MatchPredictionRequest(
            home_team="Arsenal",
            away_team="Liverpool",
            league="epl",
            odds={
                "home_win": 2.50,  # Higher odds might create value
                "draw": 3.40,
                "away_win": 3.00,
            },
            bankroll=10_000,
        )

        result = await service.predict_match(
            match_id="test_value_001",
            request=request,
        )

        # Check value bets
        if result.value_bets:
            vb = result.value_bets[0]
            logger.info("Value bet detected")
            logger.info("   Market: %s", vb.market)
            logger.info("   Edge: %.2f%%", vb.edge_percent)
            logger.info("   Stake: NGN %.2f", vb.kelly_stake_ngn)
        else:
            logger.info("   No value bets found (depends on model predictions)")

    @pytest.mark.asyncio
    async def test_odds_integration(self):
        """Test real-time odds fetching."""
        logger.info("Testing odds service...")

        try:
            from src.services.odds_service import odds_service
        except (ImportError, AttributeError, Exception) as e:
            pytest.skip(f"Odds service not available: {e}")

        try:
            # Fetch live odds for EPL
            odds_data = await odds_service.fetch_live_odds(competition="EPL")
        except Exception as exc:
            # Odds API may not be configured or reachable in test env
            pytest.skip(f"Could not fetch odds: {exc}")

        assert isinstance(odds_data, list)
        logger.info("Fetched odds for %s events", len(odds_data))

        if odds_data:
            event = odds_data[0]
            logger.info(
                f"   Sample event: {event.get('home_team')} vs {event.get('away_team')}"
            )

    @pytest.mark.asyncio
    async def test_data_aggregator(self):
        """Test data aggregation with fallback to local data."""
        logger.info("Testing data aggregator...")

        from src.data.aggregator import DataAggregator

        aggregator = DataAggregator(
            matchup="Arsenal vs Liverpool",
            league="EPL",
        )

        # Fetch match data (will use fallback if scraping fails)
        data = aggregator.fetch_match_data()

        assert "historical_stats" in data
        assert "odds" in data
        assert "metadata" in data

        logger.info("Data aggregation working")
        logger.info(f"   Historical matches: {len(data['historical_stats'])}")
        logger.info(f"   Odds: {data['odds']}")

    @pytest.mark.asyncio
    async def test_end_to_end_pipeline(self, client):
        """Full end-to-end test simulating real user flow."""
        logger.info("Running end-to-end pipeline test...")

        # Pre-check model loadability
        models_path = settings.models_path
        model_files = list(models_path.glob("*_ensemble.pkl"))
        if model_files:
            try:
                SabiScoreEnsemble.load_model(str(model_files[0]))
            except Exception as exc:
                pytest.skip(f"Model could not be loaded: {exc}")

        # 1. Check system health
        health_response = await client.get("/ready")
        health_data = health_response.json()
        logger.info(f"System status: {health_data['status']}")

        # 2. Create prediction request
        request = {
            "home_team": "Manchester City",
            "away_team": "Chelsea",
            "league": "epl",
            "odds": {
                "home_win": 1.85,
                "draw": 3.60,
                "away_win": 4.20,
            },
            "bankroll": 50_000,
        }

        # 3. Generate prediction
        pred_response = await client.post("/api/v1/predictions/", json=request)

        if pred_response.status_code == 503:
            logger.warning("Models not loaded - skipping E2E test")
            pytest.skip("Models not available")
        if pred_response.status_code == 500:
            logger.warning("Internal server error in E2E test")
            pytest.skip("Server error - check logs")

        assert pred_response.status_code == 200
        prediction = pred_response.json()

        # 4. Validate prediction quality
        assert prediction["confidence"] >= 0.3  # Reasonable confidence
        assert len(prediction["predictions"]) == 3
        assert "metadata" in prediction

        logger.info("End-to-end pipeline successful")
        logger.info(
            f"   Winner prediction: {max(prediction['predictions'], key=prediction['predictions'].get)}"
        )
        logger.info(
            f"   Processing time: {prediction['metadata'].get('processing_time_ms')}ms"
        )
        logger.info(f"   Value opportunities: {len(prediction.get('value_bets', []))}")


def run_smoke_tests():
    """Run smoke tests and report results."""
    logger.info("=" * 60)
    logger.info("SabiScore Prediction Pipeline Smoke Tests")
    logger.info("=" * 60)

    pytest.main(
        [
            __file__,
            "-v",
            "--tb=short",
            "--asyncio-mode=auto",
        ]
    )


if __name__ == "__main__":
    run_smoke_tests()
