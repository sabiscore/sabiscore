"""
Model Training Script
Run: python -m src.scripts.train_models
Expected runtime: 60-90 minutes for all 6 leagues
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.core.database import SessionLocal
from src.models.orchestrator import orchestrator
from datetime import datetime


def main():
    print("=" * 80)
    print("SABISCORE MODEL TRAINING PIPELINE v3.0")
    print("=" * 80)
    print(f"Started: {datetime.utcnow().isoformat()}")
    print()

    db = SessionLocal()

    try:
        # Train all league models
        orchestrator.train_all_models(db)

        print("\n" + "=" * 80)
        print("✅ TRAINING COMPLETE")
        print("=" * 80)
        print(f"Finished: {datetime.utcnow().isoformat()}")
        print()
        print("Next steps:")
        print("1. Start the API: uvicorn src.api.main:app --reload")
        print(
            "2. Test predictions: curl -X POST http://localhost:8000/api/v1/predictions/predict"
        )
        print("3. Monitor Brier scores in Redis: redis-cli GET model:epl:metadata")

    except Exception as e:
        print(f"\n❌ Training failed: {e}")
        import traceback

        traceback.print_exc()

    finally:
        db.close()


if __name__ == "__main__":
    main()
