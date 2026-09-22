"""
Data Preprocessing Pipeline - Generate training datasets from raw data

This script:
1. Fetches historical match data from database
2. Engineers 220+ features using FeatureEngineer
3. Generates league-specific training datasets
4. Saves to data/processed/{league}_training.csv

Run with: python -m backend.src.cli.preprocess_data
"""

import sys
import logging
from typing import List, Dict
from datetime import datetime, timezone, timedelta

import pandas as pd
import numpy as np
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ..core.logging import configure_logging
from ..core.database import get_db, Match, League
from ..core.config import settings
from ..data.enrichment.feature_engineer import FeatureEngineer

configure_logging()
logger = logging.getLogger(__name__)


class DataPreprocessor:
    """Generate training datasets from historical matches"""

    LEAGUES = {
        "EPL": ["Premier League", "English Premier League"],
        "Bundesliga": ["Bundesliga", "German Bundesliga"],
        "La Liga": ["La Liga", "Spanish La Liga", "LaLiga"],
        "Serie A": ["Serie A", "Italian Serie A"],
        "Ligue 1": ["Ligue 1", "French Ligue 1"],
    }

    def __init__(self):
        # Align with training path so both read/write the same directory
        self.data_path = settings.data_path
        self.data_path.mkdir(parents=True, exist_ok=True)

        self.db_session: Session = next(get_db())
        self.feature_engineer = FeatureEngineer(self.db_session)

    def preprocess_all(self):
        """Generate training datasets for all leagues"""
        results = {}

        for league_code, league_names in self.LEAGUES.items():
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Processing {league_code}")
            logger.info(f"{'=' * 60}")

            try:
                result = self._preprocess_league(league_code, league_names)
                results[league_code] = result
                logger.info(
                    f"✓ {league_code}: {result['samples']} samples, {result['features']} features"
                )
            except Exception as e:
                logger.error(f"✗ {league_code}: {e}", exc_info=True)
                results[league_code] = {"error": str(e)}

        return results

    def _preprocess_league(self, league_code: str, league_names: List[str]) -> Dict:
        """Generate training dataset for a single league"""

        # Fetch historical matches
        logger.info(f"Fetching matches for {league_names}")

        # Date range: last 3 years for training data
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=3 * 365)

        # Get league IDs first
        leagues = (
            self.db_session.query(League).filter(League.name.in_(league_names)).all()
        )

        if not leagues:
            logger.warning(f"No leagues found matching {league_names}")
            return self._generate_mock_dataset(league_code)

        league_ids = [lg.id for lg in leagues]

        matches = (
            self.db_session.query(Match)
            .filter(
                and_(
                    Match.league_id.in_(league_ids),
                    Match.match_date < datetime.now(timezone.utc),  # Past matches only
                    Match.match_date > cutoff_date,
                    Match.home_score.isnot(None),  # Completed matches
                    Match.away_score.isnot(None),
                )
            )
            .order_by(Match.match_date)
            .all()
        )

        if not matches:
            # If no database matches, use mock data for development
            logger.warning(
                f"No database matches found for {league_code}, generating mock data"
            )
            return self._generate_mock_dataset(league_code)

        logger.info(f"Found {len(matches)} matches")

        # Generate features for each match
        training_samples = []

        for i, match in enumerate(matches):
            if i % 100 == 0:
                logger.info(f"Processing match {i}/{len(matches)}")

            try:
                features = self.feature_engineer.generate_features(match.id)

                # Add target variable (result: 0=home win, 1=draw, 2=away win)
                if match.home_score > match.away_score:
                    result = 0
                elif match.home_score == match.away_score:
                    result = 1
                else:
                    result = 2

                features["result"] = result
                features["match_id"] = match.id
                features["match_date"] = match.match_date

                training_samples.append(features)

            except Exception as e:
                logger.warning(f"Failed to engineer features for match {match.id}: {e}")
                continue

        # Convert to DataFrame
        df = pd.DataFrame(training_samples)

        # Save to CSV
        output_path = (
            self.data_path / f"{league_code.lower().replace(' ', '_')}_training.csv"
        )
        df.to_csv(output_path, index=False)

        logger.info(f"Saved to {output_path}")

        return {
            "samples": len(df),
            "features": len(df.columns) - 3,  # Exclude match_id, match_date, result
            "path": str(output_path),
        }

    def _generate_mock_dataset(self, league_code: str) -> Dict:
        """Generate mock training dataset when no database matches available"""
        logger.info(f"Generating mock dataset for {league_code}")

        # Create 500 mock samples with 220 features
        np.random.seed(42)

        num_samples = 500
        num_features = 220

        # Generate random features
        data = {}

        # Form metrics (20)
        for i in range(20):
            data[f"form_{i}"] = np.random.uniform(-1, 1, num_samples)

        # xG metrics (30)
        for i in range(30):
            data[f"xg_{i}"] = np.random.uniform(0, 3, num_samples)

        # Fatigue (10)
        for i in range(10):
            data[f"fatigue_{i}"] = np.random.uniform(0, 1, num_samples)

        # Home advantage (15)
        for i in range(15):
            data[f"home_adv_{i}"] = np.random.uniform(-0.5, 0.5, num_samples)

        # Momentum (15)
        for i in range(15):
            data[f"momentum_{i}"] = np.random.uniform(-1, 1, num_samples)

        # Market indicators (25)
        for i in range(25):
            data[f"market_{i}"] = np.random.uniform(0, 5, num_samples)

        # H2H (15)
        for i in range(15):
            data[f"h2h_{i}"] = np.random.uniform(-1, 1, num_samples)

        # Squad strength (20)
        for i in range(20):
            data[f"squad_{i}"] = np.random.uniform(0, 100, num_samples)

        # Weather (5)
        for i in range(5):
            data[f"weather_{i}"] = np.random.uniform(0, 1, num_samples)

        # Elo (10)
        for i in range(10):
            data[f"elo_{i}"] = np.random.uniform(1000, 2000, num_samples)

        # Tactical (25)
        for i in range(25):
            data[f"tactical_{i}"] = np.random.uniform(0, 1, num_samples)

        # Scoring patterns (20)
        for i in range(20):
            data[f"scoring_{i}"] = np.random.uniform(0, 3, num_samples)

        # Defensive (15)
        for i in range(15):
            data[f"defensive_{i}"] = np.random.uniform(0, 2, num_samples)

        # Set pieces (10)
        for i in range(10):
            data[f"setpiece_{i}"] = np.random.uniform(0, 1, num_samples)

        # Target (result: 0=home, 1=draw, 2=away)
        # Biased toward home wins (45% home, 25% draw, 30% away)
        data["result"] = np.random.choice([0, 1, 2], num_samples, p=[0.45, 0.25, 0.30])

        # Create DataFrame
        df = pd.DataFrame(data)

        # Save
        output_path = (
            self.data_path / f"{league_code.lower().replace(' ', '_')}_training.csv"
        )
        df.to_csv(output_path, index=False)

        logger.info(f"Generated {len(df)} mock samples with {num_features} features")
        logger.info(f"Saved to {output_path}")

        return {
            "samples": len(df),
            "features": num_features,
            "path": str(output_path),
            "mock": True,
        }


def main():
    """Main entry point"""
    logger.info("=== SabiScore Data Preprocessing ===")

    try:
        preprocessor = DataPreprocessor()
        results = preprocessor.preprocess_all()

        # Print summary
        logger.info("\n" + "=" * 60)
        logger.info("PREPROCESSING SUMMARY")
        logger.info("=" * 60)

        for league, result in results.items():
            if "error" in result:
                logger.error(f"✗ {league}: {result['error']}")
            else:
                mock_label = " (MOCK)" if result.get("mock") else ""
                logger.info(f"✓ {league}{mock_label}:")
                logger.info(f"  - Samples: {result['samples']:,}")
                logger.info(f"  - Features: {result['features']}")
                logger.info(f"  - Path: {result['path']}")

        logger.info("=" * 60)

    except KeyboardInterrupt:
        logger.info("Preprocessing interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Preprocessing failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
