import gc
import json
import numpy as np
from pathlib import Path
from mapie.classification import SplitConformalClassifier
from src.models.evaluation.metrics import ranked_probability_score
from scripts.evaluate_split_conformal import load_artifact
from train_on_real_matches import build_dataset, load_matches
from scipy.stats import spearmanr
from sklearn.metrics import log_loss, brier_score_loss

CACHE = Path("backend/data/cache")

dataset = build_dataset(load_matches(CACHE))

def _brier(y, p):
    oh = np.eye(3)[y]
    return np.mean(np.sum((p - oh)**2, axis=1))

for league, payload in dataset.items():
    model = load_artifact(league)
    if not model: continue
    X = np.asarray(payload["X"], dtype=float)
    y = np.asarray(payload["y"], dtype=int)
    dates = list(payload["dates"])
    
    order = np.argsort(np.asarray(dates))
    X, y = X[order], y[order]
    
    split = len(y) // 2
    if split < 20 or len(y) - split < 20: continue
    
    X_cal, y_cal = X[:split], y[:split]
    X_test, y_test = X[split:], y[split:]
    
    conformal = SplitConformalClassifier(
        estimator=model,
        confidence_level=[0.90],
        conformity_score="raps",
        prefit=True
    )
    conformal.conformalize(X_cal, y_cal)
    
    # RAPS set sizes
    _, y_sets = conformal.predict_set(X_test)
    set_sizes = y_sets[:, :, 0].sum(axis=1)
    
    # Error metrics
    proba = model.predict_proba(X_test)
    
    oh = np.eye(3)[y_test]
    brier_contrib = np.sum((proba - oh)**2, axis=1) # sample-wise Brier
    
    # RAPS scores (conformity score mapping - smaller is more conforming)
    # The true RAPS score isn't directly exposed per-sample without true labels, 
    # but we are evaluating whether set sizes (or max prob) correlate with errors.
    
    r_size_brier, p_size_brier = spearmanr(set_sizes, brier_contrib)
    print(f"{league:12}: Set Size vs Brier - Spearman: {r_size_brier:7.4f} (p={p_size_brier:7.4f})")
