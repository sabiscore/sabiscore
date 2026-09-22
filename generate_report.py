import numpy as np
from pathlib import Path
from scripts.evaluate_split_conformal import load_artifact
from train_on_real_matches import build_dataset, load_matches
from src.models.evaluation.market_baseline import shin_devig
import os

CACHE = Path("backend/data/cache")
dataset = build_dataset(load_matches(CACHE))

def _rps(y, p):
    truth = np.zeros_like(p)
    truth[np.arange(len(y)), y] = 1.0
    return np.mean((np.cumsum(p, axis=1)[:, :2] - np.cumsum(truth, axis=1)[:, :2])**2, axis=1)

report_lines = [
    "# Phase D & E: Market-Residual Superiority Evaluation",
    "",
    "| League | N (Holdout) | Market RPS | Model RPS | Delta |",
    "|---|---|---|---|---|"
]

for league, payload in dataset.items():
    model = load_artifact(league)
    if not model: continue
    
    holdout = model.metadata.get("holdout_season", "2526")
    seasons = np.asarray(payload.get("seasons", []))
    mask = (seasons == holdout)
    if mask.sum() < 20: continue
    
    X = np.asarray(payload["X"])[mask]
    y = np.asarray(payload["y"])[mask]
    
    proba = model.predict_proba(X)
    rps_model = np.mean(_rps(y, proba))
    
    # Get market RPS from the canonical features
    from src.models.feature_registry import CANONICAL_FEATURES_68
    idx_loh = CANONICAL_FEATURES_68.index("log_odds_home")
    idx_lod = CANONICAL_FEATURES_68.index("log_odds_draw")
    idx_loa = CANONICAL_FEATURES_68.index("log_odds_away")
    
    log_odds = X[:, [idx_loh, idx_lod, idx_loa]]
    raw_odds = np.exp(log_odds)
    
    market_probs = []
    for odds in raw_odds:
        try:
            p = shin_devig(tuple(odds)).fair_probs
        except:
            p = (0.333, 0.333, 0.334)
        p = np.clip(p, 1e-6, 1.0 - 1e-6)
        p = p / np.sum(p)
        market_probs.append(p)
    market_probs = np.array(market_probs)
    
    rps_market = np.mean(_rps(y, market_probs))
    delta = rps_model - rps_market
    
    report_lines.append(f"| {league} | {mask.sum()} | {rps_market:.4f} | {rps_model:.4f} | {delta:+.4f} |")

out_dir = Path("reports/research")
out_dir.mkdir(parents=True, exist_ok=True)
with open(out_dir / "market_residual_superiority.md", "w") as f:
    f.write("\n".join(report_lines))

print("Report generated.")
