#!/usr/bin/env python3
"""
Train Ultra ML Model for SabiScore
Uses existing training data from data/processed/*.csv
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Add project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def load_all_training_data() -> pd.DataFrame:
    """Load and combine all league training data"""

    data_dir = PROJECT_ROOT.parent / "data" / "processed"

    training_files = [
        "epl_training.csv",
        "bundesliga_training.csv",
        "la_liga_training.csv",
        "serie_a_training.csv",
        "ligue_1_training.csv",
    ]

    all_data = []

    for filename in training_files:
        filepath = data_dir / filename
        if filepath.exists():
            try:
                df = pd.read_csv(filepath)
                logger.info(f"✓ Loaded {filename}: {len(df)} samples")
                all_data.append(df)
            except Exception as e:
                logger.warning(f"⚠ Failed to load {filename}: {e}")
        else:
            logger.warning(f"⚠ File not found: {filename}")

    if not all_data:
        raise ValueError("No training data found!")

    combined = pd.concat(all_data, ignore_index=True)
    logger.info(f"📊 Total training samples: {len(combined)}")

    return combined


def prepare_features(df: pd.DataFrame) -> tuple:
    """Prepare features and target for training"""

    # Define the target column
    target_col = "result"

    # Columns to exclude from features
    exclude_cols = [
        "result",
        "match_id",
        "match_date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "league",
        "season",
        "id",
    ]

    # Get feature columns
    feature_cols = [
        c for c in df.columns if c not in exclude_cols and not c.startswith("Unnamed")
    ]

    # Clean feature columns (remove any with all NaN)
    feature_cols = [c for c in feature_cols if df[c].notna().any()]

    logger.info(f"📋 Using {len(feature_cols)} features")

    # Extract features
    X = df[feature_cols].copy()

    # Fill NaN values with 0 or median
    for col in X.columns:
        if X[col].dtype in ["float64", "int64"]:
            X[col] = X[col].fillna(X[col].median() if X[col].notna().any() else 0)
        else:
            X[col] = X[col].fillna(0)

    # Handle result column
    if target_col in df.columns:
        y = df[target_col].copy()

        # Map results to numeric (0=away, 1=draw, 2=home)
        result_map = {
            0: 0,
            1: 1,
            2: 2,  # Already numeric
            "A": 0,
            "away_win": 0,
            "away": 0,
            "D": 1,
            "draw": 1,
            "H": 2,
            "home_win": 2,
            "home": 2,
        }
        y = y.map(result_map)

        # Remove rows with NaN target
        valid_idx = y.notna()
        X = X[valid_idx]
        y = y[valid_idx].astype(int)

        logger.info(f"📊 Valid samples: {len(y)}")
        logger.info(f"📊 Class distribution: {dict(y.value_counts().sort_index())}")
    else:
        y = None

    return X, y, feature_cols


def train_model(X_train, y_train, X_test, y_test):
    """Train the Ultra ML ensemble"""

    try:
        from ml_ultra.meta_learner import DiverseEnsemble
    except ImportError:
        logger.error(
            "Could not import DiverseEnsemble. Make sure you're in the backend directory."
        )
        return None, {}

    logger.info("🔧 Training DiverseEnsemble...")

    # Create and train ensemble
    ensemble = DiverseEnsemble(random_state=42)
    ensemble.fit(X_train, y_train)

    # Evaluate
    logger.info("📈 Evaluating model...")
    y_pred_proba = ensemble.predict_proba(X_test)
    y_pred = np.argmax(y_pred_proba, axis=1)

    from sklearn.metrics import accuracy_score, classification_report, log_loss

    accuracy = accuracy_score(y_test, y_pred)
    logloss = log_loss(y_test, y_pred_proba)

    logger.info(f"✅ Test Accuracy: {accuracy:.4f} ({accuracy * 100:.2f}%)")
    logger.info(f"📉 Log Loss: {logloss:.4f}")

    # Classification report
    target_names = ["Away Win", "Draw", "Home Win"]
    report = classification_report(y_test, y_pred, target_names=target_names)
    logger.info(f"\n{report}")

    # Model weights
    weights = ensemble.get_model_weights()
    logger.info(f"📊 Model Weights: {weights}")

    metrics = {
        "accuracy": float(accuracy),
        "log_loss": float(logloss),
        "model_weights": weights,
        "n_test_samples": len(y_test),
        "target_achieved": accuracy >= 0.90,
    }

    return ensemble, metrics


def save_model(ensemble, feature_names, metrics):
    """Save the trained model and metadata"""
    import json

    output_dir = PROJECT_ROOT / "models" / "ultra"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save ensemble
    model_path = output_dir / "ensemble_ultra.pkl"
    ensemble.save(model_path)
    logger.info(f"✅ Model saved to {model_path}")

    # Convert numpy types to native Python types for JSON serialization
    def convert_to_native(obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        elif isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_to_native(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_to_native(i) for i in obj]
        return obj

    # Save metadata
    metadata = {
        "model_version": "ultra_v1.0",
        "training_date": datetime.now().isoformat(),
        "feature_names": list(feature_names),
        "n_features": len(feature_names),
        "metrics": convert_to_native(metrics),
    }

    metadata_path = output_dir / "metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)
    logger.info(f"✅ Metadata saved to {metadata_path}")

    # Save feature names
    features_path = output_dir / "features.txt"
    with open(features_path, "w") as f:
        f.write("\n".join(feature_names))
    logger.info(f"✅ Features saved to {features_path}")

    return output_dir


def main():
    """Main training pipeline"""
    print("=" * 70)
    print("SABISCORE ULTRA - ML MODEL TRAINING")
    print("=" * 70)

    try:
        # Step 1: Load data
        print("\n[1/4] Loading training data...")
        df = load_all_training_data()

        # Step 2: Prepare features
        print("\n[2/4] Preparing features...")
        X, y, feature_names = prepare_features(df)

        if y is None or len(y) == 0:
            logger.error("No valid target values found!")
            return

        # Step 3: Split data (time-based)
        print("\n[3/4] Splitting data...")
        split_idx = int(len(X) * 0.8)
        X_train = X.iloc[:split_idx]
        X_test = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        logger.info(f"📊 Train: {len(X_train)}, Test: {len(X_test)}")

        # Step 4: Train model
        print("\n[4/4] Training model...")
        ensemble, metrics = train_model(X_train, y_train, X_test, y_test)

        if ensemble is None:
            logger.error("Training failed!")
            return

        # Save model
        print("\n[5/5] Saving model...")
        output_dir = save_model(ensemble, feature_names, metrics)

        print("\n" + "=" * 70)
        print("✅ TRAINING COMPLETE!")
        print(f"   Model saved to: {output_dir}")
        print(f"   Accuracy: {metrics['accuracy'] * 100:.2f}%")
        print("=" * 70)

    except Exception as e:
        logger.error(f"Training failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
