#!/usr/bin/env python3
import sys

sys.path.append("src")
from models.ensemble import SabiScoreEnsemble
import pandas as pd
import numpy as np

# Create mock data
np.random.seed(42)
n_samples = 100
features = ["home_goals_avg", "away_goals_avg", "home_win_rate", "away_win_rate"]
data = {f: np.random.uniform(0, 5, n_samples) for f in features}
data["result"] = np.random.choice(["home_win", "draw", "away_win"], n_samples)

df = pd.DataFrame(data)
X = df[features]
y = df[["result"]]

# Encode target
y_encoded = y.copy()
y_encoded["result"] = y_encoded["result"].map({"home_win": 0, "draw": 1, "away_win": 2})

ensemble = SabiScoreEnsemble()
ensemble.feature_columns = features
ensemble.build_ensemble(X, y_encoded)

print("Training successful")
print(f"Is trained: {ensemble.is_trained}")
print(f"Meta model: {ensemble.meta_model is not None}")
