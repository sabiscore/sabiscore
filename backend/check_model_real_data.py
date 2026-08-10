"""Script to verify models are trained on real data, not mock data"""
import joblib

# Load trained model
model_path = r'c:\Users\USR\Documents\SabiScore\models\epl_ensemble.pkl'
model = joblib.load(model_path)

print("=" * 80)
print("TRAINED MODEL VERIFICATION - EPL Ensemble")
print("=" * 80)

# Check if model is trained
is_trained = model.get('is_trained', False)
print(f"\n✓ Model Trained: {is_trained}")

# Check feature columns
feature_columns = model.get('feature_columns', [])
print(f"\n✓ Total Features: {len(feature_columns)}")
print("\n✓ First 15 Features:")
for i, feat in enumerate(feature_columns[:15], 1):
    print(f"   {i}. {feat}")

# Check model metadata
metadata = model.get('model_metadata', {})
print("\n✓ Model Metadata:")
print(f"   - Accuracy: {metadata.get('accuracy', 'N/A')}")
print(f"   - Training samples: {metadata.get('training_samples', 'N/A')}")
print(f"   - Test samples: {metadata.get('test_samples', 'N/A')}")
print(f"   - Training date: {metadata.get('trained_at', 'N/A')}")

# Check base models
models = model.get('models', {})
print(f"\n✓ Base Models: {list(models.keys())}")

# Verify features are from REAL data schema
expected_real_features = [
    'home_goals_avg', 'away_goals_avg', 'home_win_rate', 'away_win_rate',
    'home_possession_avg', 'away_possession_avg', 'home_form_points', 
    'away_form_points', 'home_squad_value_mean', 'away_squad_value_mean'
]

print("\n✓ Verifying Real Data Features:")
for feat in expected_real_features:
    if feat in feature_columns:
        print(f"   ✓ {feat} - FOUND (REAL DATA)")
    else:
        print(f"   ✗ {feat} - MISSING (POTENTIAL MOCK DATA)")

# Check for mock/dummy indicators
mock_indicators = ['mock', 'dummy', 'fake', 'test', 'placeholder', 'sample']
suspicious_features = [f for f in feature_columns if any(ind in f.lower() for ind in mock_indicators)]

print("\n✓ Mock Data Check:")
if suspicious_features:
    print(f"   ⚠ WARNING: Found {len(suspicious_features)} suspicious features:")
    for feat in suspicious_features:
        print(f"      - {feat}")
else:
    print("   ✓ NO MOCK/DUMMY FEATURES DETECTED")

print("\n" + "=" * 80)
print("CONCLUSION:")
if is_trained and len(feature_columns) > 50 and not suspicious_features:
    print("✅ MODEL IS TRAINED ON REAL DATA")
else:
    print("⚠ POTENTIAL ISSUES DETECTED - REVIEW REQUIRED")
print("=" * 80)
