"""Derive the low-epistemic (high tree-agreement) danger-zone boundary.

Produces the per-league thresholds hardcoded in
`src/services/risk_guard.py::EPISTEMIC_DANGER_THRESHOLDS` (ADR-0011). Those
constants must be reproducible from measurement rather than taken on trust;
this is how. Re-run after any retrain and update the table in both places.

    cd backend && PYTHONPATH=.:scripts python3 scripts/measure_epistemic_danger_zone.py

The circuit breaker needs a deterministic threshold. That threshold must come
from measurement, not from a plausible-looking constant. This emits, per
league, the 25th-percentile epistemic boundary and the hit-rate/RPS on each
side of it, on each artifact's own chronological holdout.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import joblib
import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "scripts"))

from train_on_real_matches import build_dataset, load_matches  # noqa: E402

from src.models.ensemble_uncertainty import (  # noqa: E402
    dispersion_from_members,
    member_probabilities,
)
from src.models.evaluation.metrics import ranked_probability_score  # noqa: E402
from src.models.prediction import PredictionEngine  # noqa: E402

LEAGUES = ["EPL", "BUNDESLIGA", "LA_LIGA", "LIGUE_1", "SERIE_A"]
SLUG = {
    "EPL": "epl", "BUNDESLIGA": "bundesliga", "LA_LIGA": "la_liga",
    "LIGUE_1": "ligue_1", "SERIE_A": "serie_a",
}

dataset = build_dataset(load_matches(BACKEND / "data" / "cache"))
print(f"{'league':<12} {'n':>5} {'p25':>8} {'p50':>8} "
      f"{'lowQ_hit':>9} {'restHit':>8} {'lowQ_rps':>9} {'rest_rps':>9}")
print("-" * 78)

all_p25 = []
for league in LEAGUES:
    art = BACKEND / "models" / f"{SLUG[league]}_ensemble_v5_phase7.pkl"
    holdout = joblib.load(art)["model_metadata"]["holdout_season"]
    data = dataset.get(league)
    if not data:
        continue
    mask = np.asarray(data["seasons"]) == holdout
    X_all = np.asarray(data["X_incumbent"])[mask]
    y_all = np.asarray(data["y"])[mask]
    bundle = asyncio.run(PredictionEngine().get_artifact_bundle(league))
    if bundle is None or not bundle.models_dict:
        continue

    epi = np.empty(len(X_all))
    rps = np.empty(len(X_all))
    hit = np.empty(len(X_all))
    for i, row in enumerate(X_all):
        X = np.asarray(row, dtype=np.float64).reshape(1, -1)
        members = member_probabilities(bundle.models_dict, X)
        res = dispersion_from_members(members)
        mean_p = np.mean(np.stack(members, axis=0), axis=0)
        epi[i] = res.epistemic
        rps[i] = ranked_probability_score(int(y_all[i]), list(mean_p))
        hit[i] = float(int(np.argmax(mean_p)) == int(y_all[i]))

    p25 = float(np.percentile(epi, 25))
    p50 = float(np.percentile(epi, 50))
    low = epi <= p25
    all_p25.append(p25)
    print(f"{league:<12} {len(epi):>5} {p25:>8.4f} {p50:>8.4f} "
          f"{hit[low].mean():>9.4f} {hit[~low].mean():>8.4f} "
          f"{rps[low].mean():>9.4f} {rps[~low].mean():>9.4f}")

print("-" * 78)
print(f"p25 across leagues: min={min(all_p25):.4f} max={max(all_p25):.4f} "
      f"mean={float(np.mean(all_p25)):.4f}")
print()
print("A single global threshold must be chosen so it does not UNDER-protect a")
print("league whose p25 sits above it. The conservative choice is therefore the")
print(f"MAX of the per-league p25 values: {max(all_p25):.4f}")
