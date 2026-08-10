"""Test model predictions with balanced features"""
import joblib
import pandas as pd

# Load model using joblib (not pickle)
model_data = joblib.load('../models/epl_ensemble.pkl')
feature_columns = model_data['feature_columns']
meta_model = model_data['meta_model']
models = model_data['models']

print(f"Model has {len(feature_columns)} features")
print(f"Feature columns: {feature_columns[:10]}...")

# Load the full ensemble class to use predict method
from src.models.ensemble import SabiScoreEnsemble  # noqa: E402 - diagnostic script loads data first
ensemble = SabiScoreEnsemble.load_model('../models/epl_ensemble.pkl')

# Check what the model predicts for perfectly balanced features
balanced = {feat: 0.5 for feat in feature_columns}

# Set key features to league averages
balanced['home_elo'] = 1500
balanced['away_elo'] = 1500
balanced['elo_difference'] = 0
balanced['home_form_5'] = 0.5
balanced['away_form_5'] = 0.5
balanced['home_win_odds'] = 2.5
balanced['draw_odds'] = 3.3
balanced['away_win_odds'] = 2.8
balanced['home_goals_scored_5'] = 7.5
balanced['away_goals_scored_5'] = 7.5

df = pd.DataFrame([balanced])
pred = ensemble.predict(df)
print('\nBalanced match prediction:')
print(pred[['home_win_prob', 'draw_prob', 'away_win_prob', 'prediction', 'confidence']])

# Now test with slight home advantage (typical EPL match)
home_advantage = balanced.copy()
home_advantage['home_elo'] = 1550
home_advantage['away_elo'] = 1500
home_advantage['elo_difference'] = 50
home_advantage['home_form_5'] = 0.6
home_advantage['away_form_5'] = 0.5
home_advantage['home_home_strength'] = 1.15
home_advantage['away_away_strength'] = 0.9

df2 = pd.DataFrame([home_advantage])
pred2 = ensemble.predict(df2)
print('\nHome advantage prediction:')
print(pred2[['home_win_prob', 'draw_prob', 'away_win_prob', 'prediction', 'confidence']])
