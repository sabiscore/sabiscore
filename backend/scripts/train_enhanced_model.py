#!/usr/bin/env python3
"""
SabiScore Production Training Script
=====================================

Complete pipeline to train the enhanced ML model:
1. Download 5+ years of historical data
2. Engineer 150+ predictive features
3. Train stacked ensemble model
4. Validate with time-series cross-validation
5. Save production-ready model

Usage:
    python train_enhanced_model.py
    
Expected Results:
- Training accuracy: 48-55% (realistic for 3-class sports prediction)
- Positive ROI potential with value betting
- Proper probability calibration
"""

import asyncio
import logging
import sys
from pathlib import Path
from datetime import datetime
import json

# Add parent paths
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from ml_ultra.enhanced_data_pipeline import EnhancedDataPipeline, DATA_DIR

# Define directories
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = PROJECT_ROOT / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

from ml_ultra.production_ml_model import (  # noqa: E402 - directories are initialized first
    ProductionMLModel,
    evaluate_model_realistically,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(MODEL_DIR / 'training_log.txt', mode='w')
    ]
)
logger = logging.getLogger(__name__)


async def main():
    """
    Main training pipeline.
    
    Steps:
    1. Download historical data from football-data.co.uk
    2. Engineer ML features
    3. Prepare train/test splits
    4. Train production model
    5. Evaluate and save
    """
    
    start_time = datetime.now()
    
    logger.info("="*80)
    logger.info("🚀 SABISCORE ENHANCED ML TRAINING PIPELINE")
    logger.info("="*80)
    logger.info(f"Started: {start_time.isoformat()}")
    
    # Configuration
    config = {
        "leagues": ["EPL", "La_Liga", "Bundesliga", "Serie_A", "Ligue_1"],
        "seasons": ["2425", "2324", "2223", "2122", "2021", "1920"],
        "min_games_threshold": 5,
        "test_size": 0.15,
        "random_state": 42
    }
    
    logger.info(f"Configuration: {json.dumps(config, indent=2)}")
    
    # Step 1: Download and process data
    logger.info("\n" + "="*60)
    logger.info("STEP 1: DATA ACQUISITION")
    logger.info("="*60)
    
    data_path = PROCESSED_DIR / "enhanced_training_data.csv"
    force_download = False  # Set True to re-download
    
    if not data_path.exists() or force_download:
        async with EnhancedDataPipeline() as pipeline:
            # Download historical data
            df = await pipeline.download_all_historical_data(
                leagues=config["leagues"],
                seasons=config["seasons"]
            )
            
            logger.info(f"Downloaded {len(df)} raw matches")
            
            # Engineer features
            df = pipeline.engineer_ml_features(df)
            
            # Prepare training data
            X, y = pipeline.prepare_training_data(df)
            feature_names = list(X.columns)
            
            # Save processed data
            import pandas as pd
            training_df = pd.concat([X, y.rename("target")], axis=1)
            training_df.to_csv(data_path, index=False)
            
            # Save feature names
            with open(PROCESSED_DIR / "feature_names.json", "w") as f:
                json.dump(feature_names, f, indent=2)
                
            # Keep odds data for evaluation
            odds_cols = [c for c in df.columns if 'pinnacle' in c.lower() or 'odds' in c.lower()]
            if odds_cols:
                odds_df = df[odds_cols + ['result']].iloc[-len(X):]
                odds_df.to_csv(PROCESSED_DIR / "odds_data.csv", index=False)
                
    else:
        logger.info(f"📂 Loading cached data from {data_path}")
        import pandas as pd
        training_df = pd.read_csv(data_path)
        y = training_df['target'].astype(int)
        X = training_df.drop(columns=['target'])
        
        with open(PROCESSED_DIR / "feature_names.json", "r") as f:
            feature_names = json.load(f)
            
    logger.info(f"✅ Dataset ready: {len(X)} samples, {len(X.columns)} features")
    logger.info(f"   Target distribution: {dict(y.value_counts().sort_index())}")
    
    # Step 2: Train/Test Split
    logger.info("\n" + "="*60)
    logger.info("STEP 2: TRAIN/TEST SPLIT")
    logger.info("="*60)
    
    # Use last 15% for testing (time-series aware)
    test_size = int(len(X) * config["test_size"])
    
    X_train = X.iloc[:-test_size]
    X_test = X.iloc[-test_size:]
    y_train = y.iloc[:-test_size]
    y_test = y.iloc[-test_size:]
    
    logger.info(f"Training set: {len(X_train)} samples")
    logger.info(f"Test set: {len(X_test)} samples")
    
    # Step 3: Train Model
    logger.info("\n" + "="*60)
    logger.info("STEP 3: MODEL TRAINING")
    logger.info("="*60)
    
    model = ProductionMLModel(
        model_name="sabiscore_production_v2",
        n_folds=5,
        random_state=config["random_state"]
    )
    
    training_metrics = model.train(X_train, y_train, validate=True)
    
    # Step 4: Evaluate on Test Set
    logger.info("\n" + "="*60)
    logger.info("STEP 4: TEST SET EVALUATION")
    logger.info("="*60)
    
    # Load odds if available
    import pandas as pd
    odds_path = PROCESSED_DIR / "odds_data.csv"
    odds_test = None
    if odds_path.exists():
        odds_df = pd.read_csv(odds_path)
        if len(odds_df) >= len(X_test):
            odds_test = odds_df.iloc[-len(X_test):].reset_index(drop=True)
            
    evaluation = evaluate_model_realistically(
        model, X_test, y_test, odds_test
    )
    
    # Step 5: Save Model
    logger.info("\n" + "="*60)
    logger.info("STEP 5: SAVE MODEL")
    logger.info("="*60)
    
    model_path = model.save()
    
    # Save comprehensive report
    report = {
        "config": config,
        "data": {
            "total_samples": len(X),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "n_features": len(feature_names),
            "feature_names": feature_names[:50]  # Top 50
        },
        "training_metrics": training_metrics,
        "evaluation": evaluation,
        "model_path": str(model_path),
        "training_time": str(datetime.now() - start_time)
    }
    
    report_path = MODEL_DIR / "training_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
        
    logger.info(f"✅ Training report saved to {report_path}")
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("🎉 TRAINING COMPLETE")
    logger.info("="*80)
    
    duration = datetime.now() - start_time
    
    logger.info(f"""
Summary:
--------
• Training Duration: {duration}
• Dataset Size: {len(X)} matches
• Features: {len(feature_names)}
• CV Accuracy: {training_metrics.get('cv_accuracy_mean', 'N/A'):.4f}
• Test Accuracy: {evaluation.get('accuracy', 'N/A'):.4f}
• Test Log Loss: {evaluation.get('log_loss', 'N/A'):.4f}
• Model Path: {model_path}

Important Notes:
----------------
• Sports prediction accuracy above 55% is exceptional
• Market odds already incorporate most available information
• Focus on value (edge over market) rather than raw accuracy
• Use probability calibration for betting decisions
""")
    
    return model, report


if __name__ == "__main__":
    asyncio.run(main())
