"""
Load historical CSV data into PostgreSQL database
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from src.core.database import SessionLocal
from src.scrapers.historical_loader import HistoricalDataLoader


def main():
    print("=" * 80)
    print("HISTORICAL DATA LOADER")
    print("=" * 80)

    data_dir = Path("data/historical")

    if not data_dir.exists():
        print("❌ Data directory not found. Run download_historical_data.py first.")
        return

    leagues = {
        "epl": "Premier League",
        "championship": "Championship",
        "laliga": "La Liga",
        "bundesliga": "Bundesliga",
        "seriea": "Serie A",
        "ligue1": "Ligue 1",
        "eredivisie": "Eredivisie",
    }

    db = SessionLocal()
    loader = HistoricalDataLoader(db)

    try:
        for league_code, league_name in leagues.items():
            league_dir = data_dir / league_code

            if not league_dir.exists():
                print(f"\n⏭️  Skipping {league_name} (no data)")
                continue

            print(f"\n{'=' * 80}")
            print(f"Loading {league_name}")
            print(f"{'=' * 80}")

            loader.load_csv_directory(str(league_dir), league_name)

        print("\n" + "=" * 80)
        print("✅ ALL DATA LOADED SUCCESSFULLY")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
