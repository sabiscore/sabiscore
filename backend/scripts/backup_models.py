"""
Backup trained model weights to file
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import joblib
from pathlib import Path
from datetime import datetime
from src.models.orchestrator import orchestrator


def backup_models():
    """
    Save all trained models to disk
    """
    print("=" * 80)
    print("MODEL BACKUP")
    print("=" * 80)

    backup_dir = Path("models/weights")
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    for league_key, model in orchestrator.models.items():
        if not model.is_trained:
            print(f"⏭️  Skipping {league_key} (not trained)")
            continue

        try:
            filename = backup_dir / f"{league_key}_model_{timestamp}.joblib"

            # Save model, scaler, and metadata
            model_data = {
                "models": model.models,
                "scaler": model.scaler,
                "ensemble_weights": model.ensemble_weights,
                "is_trained": model.is_trained,
                "timestamp": timestamp,
            }

            joblib.dump(model_data, filename)
            print(f"✅ Backed up {league_key} → {filename}")

        except Exception as e:
            print(f"❌ Error backing up {league_key}: {e}")

    print(f"\n✅ Backup complete: {backup_dir.absolute()}")


if __name__ == "__main__":
    backup_models()
