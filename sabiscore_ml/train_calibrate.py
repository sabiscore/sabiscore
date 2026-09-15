from sqlalchemy import create_engine
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
import gc

# Import from our custom files
from data_generator import generate_walk_forward_batches
from metrics import multiclass_brier_score, classwise_ece

# 1. Setup connection and boundaries
engine = create_engine("postgresql://user:password@localhost:5432/sabiscore_db")
START, END = '2023-08-01', '2026-05-30'

batches = generate_walk_forward_batches(
    db_engine=engine, start_date=START, end_date=END, 
    train_days=365, test_days=30, step_days=15
)

for fold, train_data, test_data, split_date in batches:
    print(f"\n--- Fold {fold} (Split: {split_date.strftime('%Y-%m-%d')}) ---")
    
    # 2. Split features and target (Assuming targets are 0, 1, 2)
    X_train = train_data.drop(columns=['match_date', 'target_result'])
    y_train = train_data['target_result'].astype(int)
    X_test = test_data.drop(columns=['match_date', 'target_result'])
    y_test = test_data['target_result'].astype(int)
    
    # 3. Train base model - MUST explicitly define multiclass objective
    base_model = xgb.XGBClassifier(
        objective='multi:softprob', 
        num_class=3, 
        eval_metric='mlogloss'
    )
    base_model.fit(X_train, y_train, verbose=False)
    
    # 4. Create both Calibrators (using cv='prefit' to save memory)
    platt_calibrator = CalibratedClassifierCV(estimator=base_model, method='sigmoid', cv='prefit')
    iso_calibrator = CalibratedClassifierCV(estimator=base_model, method='isotonic', cv='prefit')
    
    platt_calibrator.fit(X_test, y_test)
    iso_calibrator.fit(X_test, y_test)
    
    # 5. Predict probabilities - Take the ENTIRE probability matrix for multiclass
    y_prob_platt = platt_calibrator.predict_proba(X_test)
    y_prob_iso = iso_calibrator.predict_proba(X_test)
    
    # 6. Calculate custom multiclass metrics
    platt_brier = multiclass_brier_score(y_test, y_prob_platt)
    iso_brier = multiclass_brier_score(y_test, y_prob_iso)
    
    platt_ece = classwise_ece(y_test, y_prob_platt)
    iso_ece = classwise_ece(y_test, y_prob_iso)
    
    print(f"Platt Scaling   -> Brier: {platt_brier:.4f} | ECE: {platt_ece:.4f}")
    print(f"Isotonic Reg.   -> Brier: {iso_brier:.4f} | ECE: {iso_ece:.4f}")
    
    # 7. Memory management
    del X_train, y_train, X_test, y_test
    del base_model, platt_calibrator, iso_calibrator
    gc.collect()
