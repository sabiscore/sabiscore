"""
Validate all trained models on holdout data
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.database import SessionLocal
from src.models.orchestrator import orchestrator


def validate_models():
    """
    Run validation suite on all league models
    """
    print("=" * 80)
    print("MODEL VALIDATION SUITE")
    print("=" * 80)

    db = SessionLocal()

    try:
        # Check if models are trained
        print("\n🔍 Checking model status...")

        all_trained = True
        for league_key, model in orchestrator.models.items():
            status = "✅ Trained" if model.is_trained else "❌ Not trained"
            print(f"   {league_key.upper()}: {status}")
            if not model.is_trained:
                all_trained = False

        if not all_trained:
            print("\n❌ Some models not trained. Run train_models.py first.")
            return

        # Run validation
        print("\n" + "=" * 80)
        print("RUNNING VALIDATION...")
        print("=" * 80)

        orchestrator._run_validation_suite(db)

    finally:
        db.close()


if __name__ == "__main__":
    validate_models()
