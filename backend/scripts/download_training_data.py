"""
Download training data from Supabase for ML model training
Used by GitHub Actions CI/CD pipeline
"""

import os
import sys
import logging
from pathlib import Path
import pandas as pd
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_training_data():
    """Download historical match data from Supabase"""

    # Get Supabase credentials
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if not supabase_url or not supabase_key:
        logger.error("Missing SUPABASE_URL or SUPABASE_KEY environment variables")
        sys.exit(1)

    try:
        # Initialize Supabase client
        logger.info("Connecting to Supabase...")
        supabase: Client = create_client(supabase_url, supabase_key)

        # Download completed matches with results
        logger.info("Downloading completed matches...")
        response = (
            supabase.table("matches")
            .select("*")
            .eq("status", "COMPLETED")
            .not_.is_("home_goals", "null")
            .not_.is_("away_goals", "null")
            .order("match_date", desc=True)
            .limit(10000)
            .execute()
        )

        matches = response.data
        logger.info(f"Downloaded {len(matches)} completed matches")

        # Convert to DataFrame
        df = pd.DataFrame(matches)

        # Create output directory
        output_dir = Path("data")
        output_dir.mkdir(exist_ok=True)

        # Save to CSV
        output_path = output_dir / "training_data.csv"
        df.to_csv(output_path, index=False)
        logger.info(f"✅ Training data saved to {output_path}")

        # Print statistics
        logger.info(f"Date range: {df['match_date'].min()} to {df['match_date'].max()}")
        logger.info(
            f"Unique teams: {df['home_team_id'].nunique() + df['away_team_id'].nunique()}"
        )
        logger.info(f"Unique leagues: {df['league_id'].nunique()}")

        return output_path

    except Exception as e:
        logger.error(f"❌ Failed to download training data: {e}")
        sys.exit(1)


if __name__ == "__main__":
    download_training_data()
