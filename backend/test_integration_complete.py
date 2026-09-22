#!/usr/bin/env python3
"""
Direct integration tests for SabiScore API functionality
"""

import sys
from pathlib import Path
import json
import time
from datetime import datetime

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT.parent
SRC_PATH = BACKEND_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))
sys.path.insert(0, str(BACKEND_ROOT))


def test_database_connectivity():
    """Test database connectivity and data integrity"""
    try:
        from core.database import SessionLocal, League, Team, Match

        print("[TEST] Testing database connectivity...")

        with SessionLocal() as session:
            # Test leagues
            leagues = session.query(League).all()
            assert len(leagues) >= 5, f"Expected at least 5 leagues, got {len(leagues)}"
            print(f"✓ Found {len(leagues)} leagues")

            # Test teams
            teams = session.query(Team).all()
            assert len(teams) >= 80, f"Expected at least 80 teams, got {len(teams)}"
            print(f"✓ Found {len(teams)} teams")

            # Test matches
            matches = session.query(Match).filter(Match.status == "finished").all()
            assert len(matches) >= 1000, (
                f"Expected at least 1000 matches, got {len(matches)}"
            )
            print(f"✓ Found {len(matches)} finished matches")

        print("[PASS] Database connectivity test")
        return True

    except Exception as e:
        print(f"[FAIL] Database connectivity test: {e}")
        return False


def test_model_loading():
    """Test model loading and basic functionality"""
    try:
        from models.ensemble import SabiScoreEnsemble

        print("[TEST] Testing model loading...")

        # Test loading the EPL model
        model = SabiScoreEnsemble.load_latest_model(PROJECT_ROOT / "models")
        assert model is not None, "Failed to load model"
        assert model.is_trained, "Model is not trained"
        print("✓ Model loaded successfully")

        # Test basic prediction
        import pandas as pd

        test_data = pd.DataFrame(
            {
                "home_goals_avg": [1.8],
                "away_goals_avg": [1.2],
                "home_win_rate": [0.6],
                "away_win_rate": [0.4],
                # Add other required features with dummy values
                **{f"feature_{i}": [1.0] for i in range(45)},
            }
        )

        predictions = model.predict(test_data)
        assert "home_win_prob" in predictions.columns, (
            "Missing home_win_prob in predictions"
        )
        assert "prediction" in predictions.columns, "Missing prediction in predictions"
        print("✓ Model prediction test passed")

        print("[PASS] Model loading test")
        return True

    except Exception as e:
        print(f"[FAIL] Model loading test: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_insights_engine():
    """Test insights engine with real data"""
    try:
        from insights.engine import InsightsEngine
        from models.ensemble import SabiScoreEnsemble

        print("[TEST] Testing insights engine...")

        # Load model
        model = SabiScoreEnsemble.load_latest_model(PROJECT_ROOT / "models")
        engine = InsightsEngine(model=model)

        # Generate insights for a real match
        from core.database import SessionLocal, Match

        with SessionLocal() as session:
            # Get a real match
            match = (
                session.query(Match)
                .filter(Match.league_id == "EPL", Match.status == "finished")
                .first()
            )

            if not match:
                print("[SKIP] No real matches found for testing")
                return True

            matchup = f"{match.home_team.name} vs {match.away_team.name}"

            # Generate insights
            start_time = time.time()
            insights = engine.generate_match_insights(matchup, "EPL")
            duration = time.time() - start_time

            # Validate response structure
            required_keys = [
                "matchup",
                "league",
                "metadata",
                "predictions",
                "xg_analysis",
                "value_analysis",
                "monte_carlo",
                "scenarios",
                "explanation",
                "risk_assessment",
                "narrative",
                "generated_at",
                "confidence_level",
            ]

            for key in required_keys:
                assert key in insights, f"Missing required key: {key}"

            # Validate predictions
            pred = insights["predictions"]
            assert "home_win_prob" in pred, "Missing home_win_prob"
            assert "draw_prob" in pred, "Missing draw_prob"
            assert "away_win_prob" in pred, "Missing away_win_prob"
            assert (
                abs(
                    pred["home_win_prob"]
                    + pred["draw_prob"]
                    + pred["away_win_prob"]
                    - 1.0
                )
                < 0.01
            ), "Probabilities don't sum to 1"

            print(f"✓ Insights generated in {duration:.2f} seconds")
            print(f"✓ Generated insights for: {matchup}")
            print(
                f"✓ Prediction: {pred['prediction']} (confidence: {pred['confidence']:.3f})"
            )

        print("[PASS] Insights engine test")
        return True

    except Exception as e:
        print(f"[FAIL] Insights engine test: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_api_serialization():
    """Test API response serialization"""
    try:
        from schemas.responses import InsightsResponse

        print("[TEST] Testing API serialization...")

        # Create a complete response
        response_data = {
            "matchup": "Test Team vs Other Team",
            "league": "EPL",
            "metadata": {
                "matchup": "Test Team vs Other Team",
                "league": "EPL",
                "home_team": "Test Team",
                "away_team": "Other Team",
            },
            "predictions": {
                "home_win_prob": 0.6,
                "draw_prob": 0.2,
                "away_win_prob": 0.2,
                "prediction": "home_win",
                "confidence": 0.8,
            },
            "xg_analysis": {
                "home_xg": 1.8,
                "away_xg": 1.2,
                "total_xg": 3.0,
                "xg_difference": 0.6,
            },
            "value_analysis": {
                "bets": [],
                "edges": {},
                "best_bet": None,
                "summary": "No value bets found",
            },
            "monte_carlo": {
                "simulations": 10000,
                "distribution": {"home_win": 0.65, "draw": 0.20, "away_win": 0.15},
                "confidence_intervals": {"home_win": [0.63, 0.67]},
            },
            "scenarios": [
                {
                    "name": "Most Likely",
                    "probability": 0.6,
                    "home_score": 2,
                    "away_score": 1,
                    "result": "home_win",
                }
            ],
            "explanation": {
                "type": "model_based",
                "description": "Prediction based on team statistics and form",
            },
            "risk_assessment": {
                "risk_level": "low",
                "confidence_score": 0.78,
                "value_available": True,
                "recommendation": "Proceed",
                "distribution": {"home_win": 0.65, "draw": 0.20, "away_win": 0.15},
                "best_bet": None,
            },
            "narrative": "Test Team has a 60% chance of winning based on current form and statistics.",
            "generated_at": datetime.utcnow(),
            "confidence_level": 0.8,
        }

        # Create Pydantic model
        response = InsightsResponse(**response_data)

        # Test JSON serialization
        json_str = response.model_dump_json()
        assert len(json_str) > 100, "JSON response too short"

        # Test deserialization
        parsed = json.loads(json_str)
        assert parsed["matchup"] == "Test Team vs Other Team", "Matchup not preserved"

        print("✓ API serialization test passed")
        print("[PASS] API serialization test")
        return True

    except Exception as e:
        print(f"[FAIL] API serialization test: {e}")
        import traceback

        traceback.print_exc()
        return False


def run_all_tests():
    """Run all integration tests"""
    print("=" * 60)
    print("SabiScore Integration Tests")
    print("=" * 60)

    tests = [
        test_database_connectivity,
        test_model_loading,
        test_insights_engine,
        test_api_serialization,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        print()
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[ERROR] Test {test_func.__name__} crashed: {e}")
            failed += 1

    print()
    print("=" * 60)
    print(f"Test Results: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("Some tests failed. Please check the output above.")
        return False
    else:
        print("All tests passed! SabiScore is ready for production.")
        return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
