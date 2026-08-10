#!/usr/bin/env python3
"""Train per-league ensembles on the real football-data.co.uk corpus.

WHY THIS EXISTS
---------------
The incumbent ``*_ensemble_v5_phase7.pkl`` artifacts were trained on
``backend/data/processed/*_training.csv`` — 500 rows of ``np.random.randn()``
noise under column names (``form_0``, ``xg_7``, ``fatigue_3``) that do not even
appear in the canonical feature registry. A per-feature sensitivity sweep showed
the resulting models respond to only 4 of 68 inputs, and because the two
enrichment parquets feeding those 4 are keyed by synthetic placeholder team ids
that never join to a real fixture, every live fixture received a byte-identical
prediction.

This script retrains on the 12,765 real matches committed under
``backend/data/cache/fd_*.csv``.

TRAIN/SERVE CONSISTENCY IS THE WHOLE GAME
-----------------------------------------
A model must only be trained on features that are genuinely resolved at serving
time. Training on a feature that is a registry default in production is worse
than useless: the model learns to lean on a signal that will be constant when it
matters, which yields confident, wrong, and undifferentiated output — precisely
the failure being fixed here.

So this script computes exactly the feature set
``UpcomingMatchFeatureProjector`` resolves, using the *same* shared helpers
(``derive_last5_form_features``, ``derive_temporal_features``,
``derive_league_features``, ``derive_combination_features``) and replicating
``_get_team_stats``'s window semantics verbatim:

  * last **20** finished matches strictly before kickoff, **all venues** (the
    ``home_``/``away_`` prefix is a naming convention, not a venue filter),
  * ``form_5``  = sum(points over the newest 5) / 15.0,
  * ``goals_per_match_5`` / ``goals_conceded_per_match_5`` / ``gd_avg_5``
    = mean over the newest 5,
  * real integer ``wins_5`` / ``draws_5`` / ``losses_5`` counts.

Every other canonical slot is written as its registry default — identical to
what serving supplies — so the learners cannot attach weight to it.

NO LEAKAGE
----------
Team history is accumulated strictly forward in date order, and a match's
features are computed from the state *before* that match is appended. The
holdout is temporal (the most recent season), never random, so a model cannot
be scored on matches that preceded its own training data.

PROMOTION IS NOT AUTOMATIC
--------------------------
Artifacts are written to ``--out-dir`` (default: a ``candidate/`` subdirectory).
Promotion over the certified champion is a separate, deliberate step —
CLAUDE.md requires measurable temporal out-of-sample improvement first, and this
script prints the incumbent-vs-candidate comparison needed to make that call.

Usage:
    PYTHONPATH=. python scripts/train_on_real_matches.py [--out-dir DIR] [--holdout-season 2425]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_FEATURE_SPEC = importlib.util.spec_from_file_location(
    "sabiscore_feature_registry",
    _BACKEND_ROOT / "src" / "models" / "feature_registry.py",
)
if _FEATURE_SPEC is None or _FEATURE_SPEC.loader is None:
    raise RuntimeError("Unable to load the canonical feature registry")
_FEATURE_REGISTRY = importlib.util.module_from_spec(_FEATURE_SPEC)
_FEATURE_SPEC.loader.exec_module(_FEATURE_REGISTRY)
APEX_FEATURES_68 = _FEATURE_REGISTRY.APEX_FEATURES_68
CANONICAL_FEATURES_68 = _FEATURE_REGISTRY.CANONICAL_FEATURES_68
DEFAULT_FEATURE_VALUES_68 = _FEATURE_REGISTRY.DEFAULT_FEATURE_VALUES_68
derive_combination_features = _FEATURE_REGISTRY.derive_combination_features
derive_last5_form_features = _FEATURE_REGISTRY.derive_last5_form_features
derive_league_features = _FEATURE_REGISTRY.derive_league_features
derive_apex_market_features = _FEATURE_REGISTRY.derive_apex_market_features
derive_market_features = _FEATURE_REGISTRY.derive_market_features
derive_temporal_features = _FEATURE_REGISTRY.derive_temporal_features

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("retrain")

# football-data.co.uk division code -> canonical SabiScore league id / model slug.
_DIV_TO_LEAGUE = {
    "E0": "EPL",
    "SP1": "LA_LIGA",
    "D1": "BUNDESLIGA",
    "I1": "SERIE_A",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}
_LEAGUE_TO_SLUG = {
    "EPL": "epl",
    "LA_LIGA": "la_liga",
    "BUNDESLIGA": "bundesliga",
    "SERIE_A": "serie_a",
    "LIGUE_1": "ligue_1",
    "EREDIVISIE": "eredivisie",
}

# Serving reads the newest 20 finished matches and derives its last-5 window
# from that list (upcoming_match_feature_service._get_team_stats).
_HISTORY_WINDOW = 20
_FORM_WINDOW = 5
# Both sides must have a full last-5 window, matching the branch serving takes
# when it has real history; below that serving falls into a different estimate.
_MIN_HISTORY = 5


class TeamHistory:
    """Rolling per-team result history, appended strictly in date order."""

    def __init__(self) -> None:
        self._by_team: Dict[str, Deque[Tuple[int, int]]] = defaultdict(
            lambda: deque(maxlen=_HISTORY_WINDOW)
        )

    def stats(self, team: str, *, is_home: bool) -> Optional[Dict[str, float]]:
        """Mirror _get_team_stats(). Newest-first, exactly as the DB query orders."""
        history = self._by_team.get(team)
        if not history or len(history) < _MIN_HISTORY:
            return None

        newest_first = list(history)[::-1]
        goals_for = [gf for gf, _ in newest_first]
        goals_against = [ga for _, ga in newest_first]
        points = [3 if gf > ga else 1 if gf == ga else 0 for gf, ga in newest_first]

        prefix = "home" if is_home else "away"
        window = slice(0, _FORM_WINDOW)
        return {
            f"{prefix}_form_5": sum(points[window]) / 15.0,
            f"{prefix}_win_rate_5": sum(1 for p in points[window] if p == 3) / 5.0,
            "wins_5": float(sum(1 for p in points[window] if p == 3)),
            "draws_5": float(sum(1 for p in points[window] if p == 1)),
            "losses_5": float(sum(1 for p in points[window] if p == 0)),
            f"{prefix}_goals_per_match_5": float(np.mean(goals_for[window])),
            f"{prefix}_goals_conceded_per_match_5": float(np.mean(goals_against[window])),
            f"{prefix}_gd_avg_5": float(
                np.mean([gf - ga for gf, ga in zip(goals_for[window], goals_against[window])])
            ),
        }

    def append(self, team: str, goals_for: int, goals_against: int) -> None:
        self._by_team[team].append((goals_for, goals_against))


def _parse_date(raw: str) -> Optional[datetime]:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


# WP-A: opening 1X2 odds, one fallback tier per bookmaker,
# clean-schema name paired with its raw-schema equivalent per tier. A given
# CSV's DictReader.fieldnames only ever contains one name per pair, so the
# miss on the absent one is just a dict .get() returning None. Bet365 is
# preferred and Pinnacle is the fallback. Cross-bookmaker averages are
# excluded because they are not one coherent bookmaker snapshot. Opening
# lines only — see build_dataset's
# docstring note for why closing lines are deliberately never read.
_ODDS_COLUMNS: Tuple[Tuple[str, str, str], ...] = (
    ("bet365_home", "bet365_draw", "bet365_away"),
    ("B365H", "B365D", "B365A"),
    ("pinnacle_home", "pinnacle_draw", "pinnacle_away"),
    ("PSH", "PSD", "PSA"),
)


def _parse_odds_row(row: dict) -> Optional[Tuple[float, float, float]]:
    """First COMPLETE (home, draw, away) triple across the tier list, else
    None. Atomic per tier — never mixes columns from two different
    bookmakers/tiers for one row, matching the "coherent single-bookmaker
    snapshot" principle OddsMarketRecord already enforces for live odds."""
    for h_col, d_col, a_col in _ODDS_COLUMNS:
        h, d, a = row.get(h_col), row.get(d_col), row.get(a_col)
        if h in (None, "") or d in (None, "") or a in (None, ""):
            continue
        try:
            prices = (float(h), float(d), float(a))
            if not all(np.isfinite(price) and price > 1.0 for price in prices):
                continue
            return prices
        except (TypeError, ValueError):
            continue
    return None


def load_matches(cache_dir: Path) -> List[dict]:
    """Every parseable finished match, ascending by kickoff."""
    rows: List[dict] = []
    for path in sorted(cache_dir.glob("fd_*.csv")):
        parts = path.stem.split("_")
        if len(parts) < 3:
            continue
        league = _DIV_TO_LEAGUE.get(parts[1])
        if league is None:
            continue
        season = parts[2]
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                date = _parse_date(row.get("date") or row.get("Date") or "")
                home = (row.get("home_team") or row.get("HomeTeam") or "").strip()
                away = (row.get("away_team") or row.get("AwayTeam") or "").strip()
                raw_hg = row.get("home_goals") or row.get("FTHG") or ""
                raw_ag = row.get("away_goals") or row.get("FTAG") or ""
                if not (date and home and away and raw_hg != "" and raw_ag != ""):
                    continue
                try:
                    hg, ag = int(float(raw_hg)), int(float(raw_ag))
                except (TypeError, ValueError):
                    continue
                rows.append({
                    "league": league, "season": season, "date": date,
                    "home": home, "away": away, "hg": hg, "ag": ag,
                    "odds": _parse_odds_row(row),
                })
    rows.sort(key=lambda r: r["date"])
    return rows


def build_dataset(matches: List[dict]) -> Dict[str, dict]:
    """Walk forward in time, emitting one feature row per match with enough history.

    History is keyed per (league, team) and updated only AFTER the row is
    emitted, so a match never sees its own result.

    WP-A: the 14 market features are populated from each row's OPENING 1X2
    price (see _ODDS_COLUMNS) when one was parsed, else left at their
    registry default like every other unresolved feature. Opening, not
    closing: live serving fetches odds hours-to-days before kickoff and can
    never see a closing line for a future fixture, so training on closing
    prices would teach the model to lean on a systematically more-informed
    signal than serving can ever supply.
    """
    histories: Dict[str, TeamHistory] = defaultdict(TeamHistory)
    out: Dict[str, dict] = defaultdict(
        lambda: {"X": [], "X_incumbent": [], "y": [], "seasons": [], "dates": []}
    )
    skipped = 0
    odds_rows = 0
    total_rows = 0

    for m in matches:
        league, hist = m["league"], histories[m["league"]]
        home_stats = hist.stats(m["home"], is_home=True)
        away_stats = hist.stats(m["away"], is_home=False)

        if home_stats is not None and away_stats is not None:
            features = dict(DEFAULT_FEATURE_VALUES_68)

            features.update(derive_last5_form_features(
                home_stats["home_form_5"], home_stats["home_win_rate_5"], is_home=True,
                wins_5=home_stats["wins_5"], draws_5=home_stats["draws_5"],
                losses_5=home_stats["losses_5"],
            ))
            features["home_goals_for_avg"] = home_stats["home_goals_per_match_5"]
            features["home_goals_against_avg"] = home_stats["home_goals_conceded_per_match_5"]
            features["home_gd_recent"] = home_stats["home_gd_avg_5"]

            features.update(derive_last5_form_features(
                away_stats["away_form_5"], away_stats["away_win_rate_5"], is_home=False,
                wins_5=away_stats["wins_5"], draws_5=away_stats["draws_5"],
                losses_5=away_stats["losses_5"],
            ))
            features["away_goals_for_avg"] = away_stats["away_goals_per_match_5"]
            features["away_goals_against_avg"] = away_stats["away_goals_conceded_per_match_5"]
            features["away_gd_recent"] = away_stats["away_gd_avg_5"]

            features.update(derive_temporal_features(m["date"]))
            features.update(derive_league_features(league))
            features.update(derive_combination_features(
                home_goals_for_avg=features["home_goals_for_avg"],
                home_goals_against_avg=features["home_goals_against_avg"],
                away_goals_for_avg=features["away_goals_for_avg"],
                away_goals_against_avg=features["away_goals_against_avg"],
            ))

            market_features = None
            if m.get("odds") is not None:
                try:
                    market_features = derive_apex_market_features(*m["odds"])
                except ValueError:
                    market_features = None
            total_rows += 1

            if market_features is not None:
                incumbent_features = dict(features)
                incumbent_features.update(derive_market_features(*m["odds"]))
                features.update(market_features)
                odds_rows += 1
                label = 0 if m["hg"] > m["ag"] else 1 if m["hg"] == m["ag"] else 2
                out[league]["X"].append([features[name] for name in APEX_FEATURES_68])
                out[league]["X_incumbent"].append(
                    [incumbent_features[name] for name in CANONICAL_FEATURES_68]
                )
                out[league]["y"].append(label)
                out[league]["seasons"].append(m["season"])
                out[league]["dates"].append(m["date"])
        else:
            skipped += 1

        hist.append(m["home"], m["hg"], m["ag"])
        hist.append(m["away"], m["ag"], m["hg"])

    logger.info("Rows skipped for insufficient history (both sides need %d): %d", _MIN_HISTORY, skipped)
    logger.info(
        "Rows with real market odds: %d/%d (%.0f%%)",
        odds_rows, total_rows, 100.0 * odds_rows / max(total_rows, 1),
    )
    return out


# ── Metrics ────────────────────────────────────────────────────────────────────

def ranked_probability_score(y_true: np.ndarray, probs: np.ndarray) -> float:
    """Ordered-outcome RPS over [home, draw, away]. Lower is better."""
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((np.cumsum(probs, axis=1) - np.cumsum(onehot, axis=1)) ** 2, axis=1) / 2.0))


def multiclass_brier(y_true: np.ndarray, probs: np.ndarray) -> float:
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y_true)), y_true] = 1.0
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))


def evaluate(y_true: np.ndarray, probs: np.ndarray) -> Dict[str, float]:
    probs = np.asarray(probs, dtype=np.float64)
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError(f"expected an (n, 3) probability matrix, got {probs.shape}")
    if not np.all(np.isfinite(probs)) or np.any(probs < 0.0) or np.any(probs > 1.0):
        raise ValueError("model emitted non-finite or out-of-bounds probabilities")
    if not np.allclose(probs.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("model probability rows do not sum to one")
    confidence = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == y_true).astype(np.float64)
    calibration_error = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        mask = (confidence >= lower) & (confidence < lower + 0.1)
        if mask.any():
            calibration_error += float(mask.mean()) * abs(
                float(correct[mask].mean()) - float(confidence[mask].mean())
            )
    return {
        "accuracy": float((probs.argmax(axis=1) == y_true).mean()),
        "rps": ranked_probability_score(y_true, probs),
        "brier": multiclass_brier(y_true, probs),
        "log_loss": float(-np.mean(np.log(np.maximum(probs[np.arange(len(y_true)), y_true], 1e-12)))),
        "calibration_error": calibration_error,
        "n": int(len(y_true)),
    }


def _sensitivity(models: dict, X_ref: np.ndarray) -> int:
    """How many of the 68 inputs actually move the output. The incumbent scores 4."""
    def predict(x):
        return np.mean([m.predict_proba(x)[0] for m in models.values()], axis=0)

    base = predict(X_ref.reshape(1, -1))
    moved = 0
    for i in range(X_ref.shape[0]):
        probe = X_ref.copy()
        probe[i] = probe[i] + (abs(probe[i]) * 2.0 + 1.0)
        if np.abs(predict(probe.reshape(1, -1)) - base).max() > 1e-6:
            moved += 1
    return moved


def _served_sensitivity(models: dict, meta_model: Any, X_ref: np.ndarray) -> int:
    def predict(x: np.ndarray) -> np.ndarray:
        return meta_model.predict_proba(_build_meta_features(models, x))[0]

    base = predict(X_ref.reshape(1, -1))
    moved = 0
    for index in range(X_ref.shape[0]):
        probe = X_ref.copy()
        probe[index] += abs(probe[index]) * 2.0 + 1.0
        if np.abs(predict(probe.reshape(1, -1)) - base).max() > 1e-6:
            moved += 1
    return moved


def _build_meta_features(models: dict, X: np.ndarray) -> Any:
    """Reproduce SabiScoreEnsemble._create_meta_features() exactly.

    Column names and order must match what that method emits at inference —
    it iterates ``self.models.items()`` and appends
    ``{name}_prob_home`` / ``_prob_draw`` / ``_prob_away`` per model.
    """
    import pandas as pd

    frame = pd.DataFrame()
    for name, model in models.items():
        probs = model.predict_proba(X)
        frame[f"{name}_prob_home"] = probs[:, 0]
        frame[f"{name}_prob_draw"] = probs[:, 1]
        frame[f"{name}_prob_away"] = probs[:, 2]
    return frame


def _fit_meta_model(models: dict, X_train: np.ndarray, y_train: np.ndarray):
    """Stacking meta-learner over out-of-fold base predictions.

    REQUIRED, not optional: two independent loaders read these artifacts.
    `PredictionEngine._ensemble_predict_dict` averages the base learners and
    ignores this, but `SabiScoreEnsemble.predict()` — the strict startup path
    behind `/health/ready` — calls `meta_model.predict_proba()` and raises
    "Meta model is not initialized" on None, which aborts application startup.

    Meta features come from `cross_val_predict`, never from base models scoring
    their own training rows: an in-sample fit would hand the meta-learner
    near-perfect inputs it will never see again and teach it to trust whichever
    base model overfits hardest.
    """
    import pandas as pd
    from sklearn.base import clone
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import TimeSeriesSplit

    from src.core.meta_model import SoftmaxMetaModel

    if len(X_train) < 300:
        raise ValueError("at least 300 chronological rows are required for temporal stacking")
    cv = TimeSeriesSplit(n_splits=5)
    columns = [
        f"{name}_prob_{outcome}"
        for name in models
        for outcome in ("home", "draw", "away")
    ]
    oof_values = np.full((len(X_train), len(columns)), np.nan, dtype=np.float64)
    for train_index, validation_index in cv.split(X_train):
        if len(np.unique(y_train[train_index])) != 3:
            continue
        offset = 0
        for model in models.values():
            fold_model = clone(model)
            fold_model.fit(X_train[train_index], y_train[train_index])
            probabilities = fold_model.predict_proba(X_train[validation_index])
            if list(fold_model.classes_) != [0, 1, 2]:
                raise ValueError("temporal fold did not produce all three outcome classes")
            oof_values[validation_index, offset : offset + 3] = probabilities
            offset += 3

    usable = np.all(np.isfinite(oof_values), axis=1)
    if usable.sum() < 100:
        raise ValueError("insufficient expanding-window OOF rows for stacking")
    oof = pd.DataFrame(oof_values[usable], columns=columns)

    # multinomial is the default for multiclass in sklearn >= 1.5; the explicit
    # multi_class kwarg was removed in 1.8.
    fitted = LogisticRegression(max_iter=1000, random_state=42)
    fitted.fit(oof, y_train[usable])

    # The fitted estimator is NOT what gets pickled. Production runs
    # scikit-learn 1.3.2 against artifacts built here on 1.8, and 1.3.2's
    # LogisticRegression.predict_proba reads self.multi_class — an attribute 1.8
    # no longer sets — so the unpickled estimator raises AttributeError inside
    # the strict startup check and the release fails to deploy. Carry the fitted
    # coefficients across in a type this repo owns instead.
    return SoftmaxMetaModel.from_sklearn(fitted, feature_names=list(oof.columns))


def _fit_temperature(meta_model: Any, meta_features: Any, y_calibration: np.ndarray):
    """Fit one temperature on a later, untouched chronological slice."""

    from scipy.optimize import minimize_scalar
    from src.core.meta_model import TemperatureScaledMetaModel

    raw = meta_model.predict_proba(meta_features)

    def objective(temperature: float) -> float:
        logits = np.log(np.maximum(raw, 1e-12)) / temperature
        logits -= logits.max(axis=1, keepdims=True)
        exp = np.exp(logits)
        probabilities = exp / exp.sum(axis=1, keepdims=True)
        return float(
            -np.mean(
                np.log(np.maximum(probabilities[np.arange(len(y_calibration)), y_calibration], 1e-12))
            )
        )

    result = minimize_scalar(objective, bounds=(0.25, 4.0), method="bounded")
    if not result.success or not np.isfinite(result.x):
        raise ValueError("temperature calibration failed")
    return TemperatureScaledMetaModel(meta_model, float(result.x))


def train_league(league: str, data: dict, holdout_season: str) -> Optional[dict]:
    from lightgbm import LGBMClassifier
    from sklearn.ensemble import RandomForestClassifier
    from xgboost import XGBClassifier

    X = np.asarray(data["X"], dtype=np.float32)
    y = np.asarray(data["y"], dtype=np.int64)
    seasons = np.asarray(data["seasons"])
    dates = np.asarray(data["dates"], dtype=object)

    test_mask = seasons == holdout_season
    if test_mask.sum() < 50:
        logger.warning("  %s: insufficient split (train=%d test=%d) — skipped",
                       league, int((~test_mask).sum()), int(test_mask.sum()))
        return None

    holdout_start = min(dates[test_mask])
    holdout_end = max(dates[test_mask])
    if any(date > holdout_end for date in dates[~test_mask]):
        raise ValueError(
            f"holdout season {holdout_season} is not the latest season for {league}"
        )
    pretest_mask = np.asarray([date < holdout_start for date in dates], dtype=bool)
    if pretest_mask.sum() < 200:
        logger.warning("  %s: insufficient pre-holdout rows (%d)", league, int(pretest_mask.sum()))
        return None

    pretest_seasons = list(dict.fromkeys(seasons[pretest_mask].tolist()))
    pretest_seasons.sort(key=lambda season: max(dates[seasons == season]))
    if len(pretest_seasons) < 2:
        logger.warning("  %s: no independent calibration season — skipped", league)
        return None
    calibration_season = pretest_seasons[-1]
    calibration_mask = (seasons == calibration_season) & pretest_mask
    core_mask = pretest_mask & ~calibration_mask
    if calibration_mask.sum() < 50 or core_mask.sum() < 300:
        logger.warning(
            "  %s: insufficient core/calibration split (core=%d calibration=%d) — skipped",
            league, int(core_mask.sum()), int(calibration_mask.sum()),
        )
        return None

    X_train, y_train = X[core_mask], y[core_mask]
    X_calibration, y_calibration = X[calibration_mask], y[calibration_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=300, max_depth=8, min_samples_leaf=15,
            random_state=42, n_jobs=-1,
        ),
        "xgboost": XGBClassifier(
            n_estimators=250, max_depth=4, learning_rate=0.05,
            subsample=0.85, colsample_bytree=0.85, reg_lambda=2.0,
            objective="multi:softprob", num_class=3, random_state=42,
            tree_method="hist", eval_metric="mlogloss",
        ),
        "lightgbm": LGBMClassifier(
            n_estimators=250, max_depth=5, learning_rate=0.05,
            subsample=0.85, colsample_bytree=0.85, reg_lambda=2.0,
            objective="multiclass", num_class=3, random_state=42, verbose=-1,
        ),
    }
    meta_model = _fit_meta_model(models, X_train, y_train)
    for model in models.values():
        model.fit(X_train, y_train)
    meta_model = _fit_temperature(
        meta_model,
        _build_meta_features(models, X_calibration),
        y_calibration,
    )

    probs = np.mean([m.predict_proba(X_test) for m in models.values()], axis=0)
    metrics = evaluate(y_test, probs)
    # The stacked head is what SabiScoreEnsemble.predict() serves, so it is
    # scored here too rather than assumed equivalent to the averaged base.
    metrics["stacked"] = evaluate(
        y_test, meta_model.predict_proba(_build_meta_features(models, X_test))
    )
    metrics["train_n"] = int(len(y_train))
    metrics["calibration_n"] = int(len(y_calibration))
    metrics["evaluation_n"] = int(len(y_test))
    metrics["responsive_features"] = _served_sensitivity(models, meta_model, X_test[0].copy())

    # Always-predict-home baseline: the bar any real model must clear.
    home_rate = float((y_test == 0).mean())
    prior = np.tile(np.bincount(y_train, minlength=3) / len(y_train), (len(y_test), 1))
    metrics["baseline_accuracy_home"] = home_rate
    metrics["baseline_rps_trainprior"] = ranked_probability_score(y_test, prior)
    market_columns = [APEX_FEATURES_68.index(name) for name in (
        "market_prob_home", "market_prob_draw", "market_prob_away"
    )]
    metrics["baseline_rps_market"] = ranked_probability_score(y_test, X_test[:, market_columns])
    metrics["calibration_season"] = calibration_season
    metrics["holdout_season"] = holdout_season
    metrics["training_window"] = {
        "start": min(dates[core_mask]).date().isoformat(),
        "end": max(dates[core_mask]).date().isoformat(),
    }
    metrics["calibration_window"] = {
        "start": min(dates[calibration_mask]).date().isoformat(),
        "end": max(dates[calibration_mask]).date().isoformat(),
    }
    metrics["evaluation_window"] = {
        "start": holdout_start.date().isoformat(),
        "end": holdout_end.date().isoformat(),
    }

    logger.info(
        "  %-12s train=%5d test=%4d | avg: acc=%.4f rps=%.4f | stacked: acc=%.4f rps=%.4f "
        "| home-only %.4f prior-rps %.4f market-rps %.4f responsive=%d/68",
        league, metrics["train_n"], metrics["n"], metrics["accuracy"], metrics["rps"],
        metrics["stacked"]["accuracy"], metrics["stacked"]["rps"],
        metrics["baseline_accuracy_home"], metrics["baseline_rps_trainprior"],
        metrics["baseline_rps_market"],
        metrics["responsive_features"],
    )

    return {
        "models": models,
        "meta_model": meta_model,
        "feature_columns": list(APEX_FEATURES_68),
        "is_trained": True,
        "model_metadata": {
            "accuracy": metrics["stacked"]["accuracy"],
            "brier_score": metrics["stacked"]["brier"],
            "log_loss": metrics["stacked"]["log_loss"],
            "rps": metrics["stacked"]["rps"],
            "calibration_error": metrics["stacked"]["calibration_error"],
            "trained_at": datetime.now().isoformat(),
            "feature_count": len(APEX_FEATURES_68),
            "feature_schema_version": "apex_v1_68",
            "served_head": "stacked_logistic_regression",
            "validation_status": "UNVERIFIED_CANDIDATE",
            "training_samples": metrics["train_n"],
            "holdout_samples": metrics["n"],
            "holdout_season": holdout_season,
            "calibration_season": calibration_season,
            "training_window": {
                "start": min(dates[core_mask]).date().isoformat(),
                "end": max(dates[core_mask]).date().isoformat(),
            },
            "calibration_window": metrics["calibration_window"],
            "evaluation_window": metrics["evaluation_window"],
            "calibration_samples": metrics["calibration_n"],
            "market_baseline_rps": metrics["baseline_rps_market"],
            "league_prior_baseline_rps": metrics["baseline_rps_trainprior"],
            "data_source": "football-data.co.uk (real matches)",
            "responsive_features": metrics["responsive_features"],
        },
        "_metrics": metrics,
    }


def train_pooled(dataset: Dict[str, dict], holdout_season: str) -> Optional[dict]:
    """One model over every league, for leagues too small to train alone.

    Eredivisie has a single committed season (306 matches, none in the holdout),
    which is far too little to fit and impossible to validate temporally. Rather
    than leave it on the degenerate incumbent — it is the league with live
    fixtures right now — it gets a model trained on the full corpus. The league
    one-hot block is part of the feature vector, so the learners can still
    condition on competition; Eredivisie simply presents an all-zero block, which
    is exactly what it presents at serving time too.
    """
    pooled = {"X": [], "y": [], "seasons": [], "dates": []}
    for league, data in dataset.items():
        for key in pooled:
            pooled[key].extend(data[key])
    logger.info("\nPooled model over %d leagues, %d rows", len(dataset), len(pooled["y"]))
    return train_league("POOLED", pooled, holdout_season)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=_BACKEND_ROOT / "data" / "cache")
    ap.add_argument("--out-dir", type=Path, default=_BACKEND_ROOT / "models" / "candidate")
    ap.add_argument("--holdout-season", default="2526")
    args = ap.parse_args()

    import joblib

    matches = load_matches(args.cache_dir)
    logger.info("Loaded %d real matches from %s", len(matches), args.cache_dir)
    if not matches:
        logger.error("No matches parsed — nothing to train on.")
        return 1

    dataset = build_dataset(matches)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("\nTemporal holdout: season %s\n", args.holdout_season)
    report: Dict[str, dict] = {}
    trained: set = set()
    for league in sorted(dataset):
        bundle = train_league(league, dataset[league], args.holdout_season)
        if bundle is None:
            continue
        report[league] = bundle.pop("_metrics")
        trained.add(league)
        joblib.dump(bundle, args.out_dir / f"{_LEAGUE_TO_SLUG[league]}_ensemble_v5_phase7.pkl")

    # Cover whatever was too small to fit on its own.
    uncovered = sorted(set(dataset) - trained)
    if uncovered:
        pooled_bundle = train_pooled(dataset, args.holdout_season)
        if pooled_bundle is not None:
            report["POOLED"] = pooled_bundle.pop("_metrics")
            pooled_bundle["model_metadata"]["pooled_fallback_for"] = uncovered
            pooled_bundle["model_metadata"]["note"] = (
                "Trained on all leagues; used for competitions with too little "
                "history to fit or validate independently."
            )
            for league in uncovered:
                joblib.dump(
                    pooled_bundle, args.out_dir / f"{_LEAGUE_TO_SLUG[league]}_ensemble_v5_phase7.pkl"
                )
                logger.info("  %s -> pooled model (own history: %d rows, no holdout)",
                            league, len(dataset[league]["y"]))

    (args.out_dir / "training_report_real.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    logger.info("\nWrote artifacts for %d leagues to %s", len(trained) + len(uncovered), args.out_dir)
    logger.info("NOT promoted — compare against the incumbent before replacing it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
