import sys
from pathlib import Path
import numpy as np
from xgboost import XGBClassifier

sys.path.insert(0, str(Path("backend").resolve()))
from backend.scripts.train_on_real_matches import build_dataset, load_matches, ranked_probability_score
from backend.src.models.feature_registry import CANONICAL_FEATURES_68
from backend.src.models.evaluation.market_baseline import shin_devig

dataset = build_dataset(load_matches(Path("backend/data/cache")))
league = "EPL"
X_train = np.array(dataset[league]["X_incumbent"])
y_train = np.array(dataset[league]["y"])

idx_loh = CANONICAL_FEATURES_68.index("log_odds_home")
idx_lod = CANONICAL_FEATURES_68.index("log_odds_draw")
idx_loa = CANONICAL_FEATURES_68.index("log_odds_away")

log_odds = X_train[:, [idx_loh, idx_lod, idx_loa]]
raw_odds = np.exp(log_odds)

base_margins = []
for odds in raw_odds:
    try:
        p = shin_devig(tuple(odds)).fair_probs
    except:
        p = (0.333, 0.333, 0.334)
    base_margins.append(np.log(p))

base_margins = np.array(base_margins)

model = XGBClassifier(objective="multi:softprob", num_class=3, n_estimators=50, max_depth=3)
model.fit(X_train, y_train, base_margin=base_margins)
p_model = model.predict_proba(X_train, base_margin=base_margins)

print(p_model[:5])
print("RPS:", ranked_probability_score(y_train, p_model))
