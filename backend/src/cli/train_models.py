"""
Training CLI - Execute model training for all leagues
Run with: python -m backend.src.cli.train_models
"""

import sys
import logging
from pathlib import Path

from ..core.logging import configure_logging
from ..models.training import ModelTrainer

configure_logging()
logger = logging.getLogger(__name__)


def main():
    """Main entry point for model training"""
    logger.info("=== SabiScore Model Training ===")

    # Define leagues to train
    leagues = ["EPL", "Bundesliga", "La Liga", "Serie A", "Ligue 1"]

    logger.info(f"Training models for {len(leagues)} leagues: {', '.join(leagues)}")

    try:
        trainer = ModelTrainer()

        # Check for training data
        logger.info(f"Data path: {trainer.data_path}")
        logger.info(f"Models path: {trainer.models_path}")

        if not trainer.data_path.exists():
            logger.error(f"Data directory not found: {trainer.data_path}")
            logger.error("Please run data processing pipeline first")
            sys.exit(1)

        # Train all models
        results = trainer.train_league_models(leagues)

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("TRAINING SUMMARY")
        logger.info("=" * 60)

        successful = 0
        failed = 0

        for league, result in results.items():
            if "error" in result:
                logger.error(f"[FAIL] {league}: {result['error']}")
                failed += 1
            else:
                logger.info(f"[OK] {league}:")
                logger.info(f"  - Accuracy: {result.get('accuracy', 0):.2%}")
                logger.info(f"  - Brier Score: {result.get('brier_score', 0):.4f}")
                logger.info(f"  - Features: {result.get('feature_count', 0)}")
                logger.info(f"  - Samples: {result.get('training_samples', 0):,}")
                logger.info(f"  - Model: {Path(result.get('model_path', '')).name}")
                successful += 1

        logger.info("=" * 60)
        logger.info(f"Successful: {successful}/{len(leagues)}")
        logger.info(f"Failed: {failed}/{len(leagues)}")
        logger.info("=" * 60)

        # Update metadata
        trainer.update_model_metadata()
        logger.info("Model metadata updated")

        if failed > 0:
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Training interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Training failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
