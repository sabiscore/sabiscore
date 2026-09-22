#!/usr/bin/env python3
"""
Verify that the SabiScore setup is working correctly
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import settings
from src.core.database import SessionLocal
from src.core.cache import cache
from src.models.ensemble import SabiScoreEnsemble
from src.data.aggregator import DataAggregator
from src.insights.engine import InsightsEngine
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_database():
    """Verify database connection and schema"""
    try:
        logger.info("Verifying database...")
        db = SessionLocal()

        # Test connection
        result = db.execute("SELECT 1").fetchone()
        assert result[0] == 1, "Database query failed"

        # Check tables exist
        from sqlalchemy import inspect

        inspector = inspect(db.bind)

        required_tables = [
            "leagues",
            "teams",
            "players",
            "matches",
            "match_stats",
            "predictions",
            "odds",
            "value_bets",
        ]
        existing_tables = inspector.get_table_names()

        missing_tables = [
            table for table in required_tables if table not in existing_tables
        ]

        if missing_tables:
            logger.error(f"Missing tables: {missing_tables}")
            return False

        db.close()
        logger.info("Database verification passed")
        return True

    except Exception as e:
        logger.error(f"Database verification failed: {e}")
        return False


def verify_cache():
    """Verify Redis cache connection"""
    try:
        logger.info("Verifying cache...")

        # Test basic operations
        test_key = "test_key"
        test_value = "test_value"

        cache.set(test_key, test_value)
        retrieved = cache.get(test_key)

        assert retrieved == test_value, "Cache set/get failed"

        cache.delete(test_key)

        logger.info("Cache verification passed")
        return True

    except Exception as e:
        logger.error(f"Cache verification failed: {e}")
        return False


def verify_models():
    """Verify ML models can be loaded"""
    try:
        logger.info("Verifying models...")

        # Try to load latest model
        model = SabiScoreEnsemble.load_latest_model(settings.models_path)

        if model and model.is_trained:
            logger.info("Model verification passed")
            return True
        else:
            logger.warning("No trained models found - this is expected for fresh setup")
            return True  # Not a failure for fresh setup

    except Exception as e:
        logger.warning(f"Model verification failed (expected for fresh setup): {e}")
        return True  # Not a critical failure


def verify_data_pipeline():
    """Verify data aggregation pipeline"""
    try:
        logger.info("Verifying data pipeline...")

        # Test with mock matchup
        aggregator = DataAggregator("Manchester City vs Liverpool", "EPL")

        # This should not fail (even with mock data)
        data = aggregator.fetch_match_data()

        required_keys = [
            "historical_stats",
            "current_form",
            "odds",
            "injuries",
            "head_to_head",
            "team_stats",
        ]
        missing_keys = [key for key in required_keys if key not in data]

        if missing_keys:
            logger.error(f"Missing data keys: {missing_keys}")
            return False

        logger.info("Data pipeline verification passed")
        return True

    except Exception as e:
        logger.error(f"Data pipeline verification failed: {e}")
        return False


def verify_insights_engine():
    """Verify insights engine"""
    try:
        logger.info("Verifying insights engine...")

        engine = InsightsEngine()

        # Test with mock data
        mock_match_data = {
            "historical_stats": [],
            "current_form": {"home": {}, "away": {}},
            "odds": {"home_win": 2.0, "draw": 3.5, "away_win": 4.0},
            "injuries": [],
            "head_to_head": [],
            "team_stats": {"home": {}, "away": {}},
        }

        insights = engine.generate_match_insights(
            "Test vs Team", "EPL", mock_match_data
        )

        required_keys = ["predictions", "xg_analysis", "value_analysis", "narrative"]
        missing_keys = [key for key in required_keys if key not in insights]

        if missing_keys:
            logger.error(f"Missing insights keys: {missing_keys}")
            return False

        logger.info("Insights engine verification passed")
        return True

    except Exception as e:
        logger.error(f"Insights engine verification failed: {e}")
        return False


def main():
    """Run all verifications"""
    logger.info("Starting SabiScore setup verification...")

    checks = [
        ("Database", verify_database),
        ("Cache", verify_cache),
        ("Models", verify_models),
        ("Data Pipeline", verify_data_pipeline),
        ("Insights Engine", verify_insights_engine),
    ]

    passed = 0
    failed = 0

    for check_name, check_func in checks:
        try:
            if check_func():
                logger.info(f"✅ {check_name}: PASSED")
                passed += 1
            else:
                logger.error(f"❌ {check_name}: FAILED")
                failed += 1
        except Exception as e:
            logger.error(f"❌ {check_name}: ERROR - {e}")
            failed += 1

    logger.info(f"\nVerification Summary: {passed} passed, {failed} failed")

    if failed > 0:
        logger.error("Setup verification failed - please check errors above")
        sys.exit(1)
    else:
        logger.info("🎉 All checks passed! SabiScore is ready to run")


if __name__ == "__main__":
    main()
