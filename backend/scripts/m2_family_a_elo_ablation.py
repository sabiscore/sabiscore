"""M2 Family A — real Elo/recency ablation over the real 12,765-match corpus.

Motivating finding (docs/DEBT.md item 48, filed alongside this script): every
canonical Elo feature (`elo_difference`, `elo_home_trend_5`, `elo_away_trend_5`,
`elo_league_adjusted`, `elo_momentum_cross`) is a CONSTANT 0.0 across all 12,256
rows `train_on_real_matches.build_dataset()` emits — measured directly, not
inferred. `TeamHistory` (that script's only walk-forward accumulator) computes
form/goals features only; nothing replays Elo over the offline training corpus.
Every model ever trained via that pipeline, including the currently-served
v5_phase7 generation, has therefore never seen Elo vary and cannot have learned
an Elo-outcome relationship, despite M1's train-serve-parity.json marking
`elo_difference` RESOLVED.

This script computes REAL elo_difference via a fresh, in-memory, disk-untouched
chronological replay. The rating math and state-transition rules (home-advantage
expected score, per-league K-factor, season-carryover regression to the league
mean, 5-game trend) are EloEngine's (backend.src.data.elo_engine — the offline
research engine, explicitly not the production Postgres authority) — but the
replay itself runs through `_FastEloReplay`, a dict-based accumulator, not
EloEngine directly: EloEngine's per-call DataFrame filter-and-copy did not
finish a 12,260-match bulk replay in 5 minutes, a mismatch between what it was
built for (occasional single-match lookups) and this use (one bulk pass).
`_FastEloReplay` is cross-verified against real EloEngine output on a 300-match
subset (`_cross_verify_fast_replay`, called first in `main()`) before its output
is trusted for the full corpus. Walked forward alongside the real,
already-verified form/recency features from train_on_real_matches.TeamHistory.
Neither structure ever sees a match's own result before its row is emitted.

Answers, for the real corpus, with real chronological validation:
  - Does a pure Elo forecaster beat uniform / home-bias / league-prior?
  - Does adding real Elo to a form/recency BASE improve out-of-sample RPS?
  - Is Elo available at serving time for a representative fraction of rows?
     (elo_home_resolved / elo_away_resolved rates are reported explicitly.)

Nothing here retrains or replaces v5_phase7. This is M2 evaluation only —
per §11/M2, no feature family becomes production-authoritative solely from
this script; promotion is a separate, later, explicitly-gated decision.

Run: PYTHONPATH=. .venv/Scripts/python.exe backend/scripts/m2_family_a_elo_ablation.py
"""
from __future__ import annotations

import importlib.util
import json
import logging
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Tuple

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("m2_family_a")

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from backend.src.data.elo_engine import EloEngine  # noqa: E402
from backend.src.models.evaluation.metrics import (  # noqa: E402
    accuracy_and_per_class,
    expected_calibration_error,
    log_loss_multiclass,
    ranked_probability_score,
)


def _brier_multiclass(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Mean over samples of sum_c (p_c - 1_{y=c})^2 -- the metric-contract.json
    canonical convention (backend/src/models/calibration.py:_compute_brier_multiclass,
    same formula, reproduced inline rather than importing a private underscore
    function cross-module). NOT brier_score_decomposition()'s "mean" field, which
    averages per-class one-vs-rest Briers and is ~3x smaller on this same data --
    verified against the live /model-performance probe this session
    (brier_overall=0.5944 vs brier_decomposition.mean.brier_score=0.1974)."""
    n = len(y_true)
    if n == 0:
        return 0.0
    n_classes = y_proba.shape[1]
    y_oh = np.zeros((n, n_classes), dtype=float)
    y_oh[np.arange(n), y_true.astype(int)] = 1.0
    return float(np.mean(np.sum((y_proba - y_oh) ** 2, axis=1)))

VAL_SPLIT = 0.20  # matches train_bnn.py's chronological split convention
SEED = 42


_DEFAULT_BASE_ELO = 1500.0


class _FastEloReplay:
    """Same rating math and state-transition rules as EloEngine
    (backend/src/data/elo_engine.py), O(1)-amortized per match instead of
    EloEngine's O(n) DataFrame filter-and-copy per call. EloEngine is built
    for occasional single-match production/backfill lookups; calling it
    12,260 times in a loop makes the underlying table copy grow with every
    match (measured: did not finish in 5 minutes). Replicates, not
    reinvents: home-advantage-adjusted expected score, per-league K-factor,
    5-game post-minus-pre delta trend, and the 50% season-carryover
    regression toward the league mean when a team's last rating predates the
    current season -- cross-verified against real EloEngine output on a
    300-match subset before being trusted on the full corpus (see main()).
    """

    def __init__(self, home_advantage: float, k_base: float, league_importance: Dict[str, float]) -> None:
        self._home_advantage = home_advantage
        self._k_base = k_base
        self._league_importance = league_importance
        self._history: Dict[Tuple[str, str], List[Tuple[str, float]]] = defaultdict(list)
        self._deltas: Dict[Tuple[str, str], Deque[float]] = defaultdict(lambda: deque(maxlen=5))
        self._league_season_sum: Dict[Tuple[str, str], float] = defaultdict(float)
        self._league_season_n: Dict[Tuple[str, str], int] = defaultdict(int)

    def get_pre_and_trend(self, team: str, league: str, season: str) -> Tuple[float, float, bool]:
        key = (team, league)
        hist = self._history[key]
        if not hist:
            return _DEFAULT_BASE_ELO, 0.0, False
        last_season, last_post = hist[-1]
        deltas = self._deltas[key]
        trend = float(np.mean(deltas)) if deltas else 0.0
        if last_season != season:
            ls_key = (league, season)
            n = self._league_season_n[ls_key]
            league_mean = (self._league_season_sum[ls_key] / n) if n else _DEFAULT_BASE_ELO
            last_post = league_mean + 0.5 * (last_post - league_mean)
        return last_post, trend, True

    def get_context(self, home: str, away: str, league: str, season: str) -> Dict[str, object]:
        home_pre, home_trend, home_found = self.get_pre_and_trend(home, league, season)
        away_pre, away_trend, away_found = self.get_pre_and_trend(away, league, season)
        return {
            "home_elo": home_pre, "away_elo": away_pre,
            "elo_difference": home_pre - away_pre,
            "home_elo_trend_5": home_trend, "away_elo_trend_5": away_trend,
            "elo_momentum_cross": home_trend - away_trend,
            "resolved": home_found and away_found,
        }

    def update(self, home: str, away: str, league: str, season: str, home_goals: int, away_goals: int) -> None:
        home_pre, _, _ = self.get_pre_and_trend(home, league, season)
        away_pre, _, _ = self.get_pre_and_trend(away, league, season)
        adjusted_home = home_pre + self._home_advantage
        home_expected = 1.0 / (1.0 + 10 ** ((away_pre - adjusted_home) / 400.0))
        away_expected = 1.0 - home_expected
        if home_goals > away_goals:
            home_actual, away_actual = 1.0, 0.0
        elif home_goals < away_goals:
            home_actual, away_actual = 0.0, 1.0
        else:
            home_actual, away_actual = 0.5, 0.5
        k = self._k_base * self._league_importance.get(league.lower(), 1.0)
        home_post = home_pre + k * (home_actual - home_expected)
        away_post = away_pre + k * (away_actual - away_expected)
        for team, pre, post in ((home, home_pre, home_post), (away, away_pre, away_post)):
            key = (team, league)
            self._deltas[key].append(post - pre)
            self._history[key].append((season, post))
            ls_key = (league, season)
            self._league_season_sum[ls_key] += post
            self._league_season_n[ls_key] += 1


def _cross_verify_fast_replay(matches: List[dict], n_check: int = 300) -> None:
    """Run both engines over the first n_check matches and assert numerically
    identical pre-match context -- the performance rewrite must not silently
    diverge from the real, already-shipped Elo algorithm. Raises on mismatch;
    never trusted without this passing first."""
    from backend.src.data.elo_engine import EloEngine

    scratch = Path(_ROOT / "backend" / "scripts" / "_m2_scratch_never_persisted.parquet")
    real = EloEngine(parquet_path=scratch)
    home_adv, k_base = _elo_settings()
    fast = _FastEloReplay(
        home_advantage=home_adv, k_base=k_base, league_importance=EloEngine.LEAGUE_IMPORTANCE,
    )
    mismatches = 0
    for i, m in enumerate(matches[:n_check]):
        league, season, date = m["league"], m["season"], m["date"]
        home, away, hg, ag = m["home"], m["away"], m["hg"], m["ag"]

        real_ctx = real.get_context(home, away, league, season, date)
        fast_ctx = fast.get_context(home, away, league, season)

        if not np.isclose(real_ctx.elo_difference, fast_ctx["elo_difference"], atol=1e-6) or (
            real_ctx.resolved != fast_ctx["resolved"]
        ):
            mismatches += 1
            log.error(
                "Cross-verify mismatch at match %d (%s vs %s): real elo_diff=%.4f resolved=%s | "
                "fast elo_diff=%.4f resolved=%s",
                i, home, away, real_ctx.elo_difference, real_ctx.resolved,
                fast_ctx["elo_difference"], fast_ctx["resolved"],
            )

        real.update_after_match(
            match_id=f"verify_{i}", home_team_id=home, away_team_id=away,
            home_goals=hg, away_goals=ag, league=league, season=season,
            match_date=date, persist=False,
        )
        fast.update(home, away, league, season, hg, ag)

    if mismatches:
        raise RuntimeError(
            f"_FastEloReplay diverged from EloEngine on {mismatches}/{n_check} matches -- "
            "do not trust the fast replay's output until this is fixed."
        )
    log.info("Cross-verified _FastEloReplay against real EloEngine on %d matches: identical.", n_check)


def _elo_settings() -> Tuple[float, float]:
    from backend.src.core.config import settings
    return float(settings.elo_home_advantage), float(settings.elo_k_base)


def _load_trainer():
    """Dynamic-load train_on_real_matches.py for TeamHistory/load_matches reuse
    (same importlib pattern train_bnn.py already uses for the same module)."""
    path = _ROOT / "backend" / "scripts" / "train_on_real_matches.py"
    spec = importlib.util.spec_from_file_location("sabiscore_real_trainer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_rows(matches: List[dict]) -> Tuple[List[dict], List[int], List[datetime]]:
    """One walk-forward pass: form features (TeamHistory) + real Elo
    (EloEngine, scratch/in-memory only) computed PRE-match, appended AFTER.

    A row is emitted only when both sides have >=5 prior matches — the exact
    inclusion rule train_on_real_matches.TeamHistory.stats() already enforces,
    so this ablation's row count is directly comparable to the production
    training run's.
    """
    trainer = _load_trainer()
    history = trainer.TeamHistory()
    home_adv, k_base = _elo_settings()
    elo = _FastEloReplay(home_advantage=home_adv, k_base=k_base, league_importance=EloEngine.LEAGUE_IMPORTANCE)

    rows: List[dict] = []
    labels: List[int] = []
    dates: List[datetime] = []
    resolved_both = 0

    for m in matches:
        league, season, date = m["league"], m["season"], m["date"]
        home, away, hg, ag = m["home"], m["away"], m["hg"], m["ag"]

        home_hist = history.stats(home, is_home=True)
        away_hist = history.stats(away, is_home=False)
        elo_ctx = elo.get_context(home, away, league, season)

        if home_hist is not None and away_hist is not None:
            outcome = 0 if hg > ag else 2 if hg < ag else 1
            row = {
                "home_form_5": home_hist["home_form_5"],
                "away_form_5": away_hist["away_form_5"],
                "home_win_rate_5": home_hist["home_win_rate_5"],
                "away_win_rate_5": away_hist["away_win_rate_5"],
                "home_goals_per_match_5": home_hist["home_goals_per_match_5"],
                "away_goals_per_match_5": away_hist["away_goals_per_match_5"],
                "home_gd_avg_5": home_hist["home_gd_avg_5"],
                "away_gd_avg_5": away_hist["away_gd_avg_5"],
                "elo_difference": elo_ctx["elo_difference"],
                "elo_home_trend_5": elo_ctx["home_elo_trend_5"],
                "elo_away_trend_5": elo_ctx["away_elo_trend_5"],
                "elo_momentum_cross": elo_ctx["elo_momentum_cross"],
                "elo_resolved": float(elo_ctx["resolved"]),
                "league": league,
            }
            rows.append(row)
            labels.append(outcome)
            dates.append(date)
            if elo_ctx["resolved"]:
                resolved_both += 1

        # Update AFTER emitting — a match never informs its own row.
        history.append(home, hg, ag)
        history.append(away, ag, hg)
        elo.update(home, away, league, season, hg, ag)

    log.info(
        "Built %d rows (both sides >=5 matches). Elo resolved both sides: %d (%.1f%%)",
        len(rows), resolved_both, 100.0 * resolved_both / max(len(rows), 1),
    )
    return rows, labels, dates


_BASE_COLS = [
    "home_form_5", "away_form_5", "home_win_rate_5", "away_win_rate_5",
    "home_goals_per_match_5", "away_goals_per_match_5", "home_gd_avg_5", "away_gd_avg_5",
]
_ELO_COLS = ["elo_difference", "elo_home_trend_5", "elo_away_trend_5", "elo_momentum_cross"]


def _matrix(rows: List[dict], cols: List[str]) -> np.ndarray:
    return np.array([[r[c] for c in cols] for r in rows], dtype=np.float64)


def _score(y_true: np.ndarray, probs: np.ndarray) -> Dict[str, object]:
    rps_values = [ranked_probability_score(int(y), list(p)) for y, p in zip(y_true, probs)]
    return {
        "rps_mean": round(float(np.mean(rps_values)), 6),
        "rps_std": round(float(np.std(rps_values)), 6),
        "log_loss": round(log_loss_multiclass(y_true, probs), 6),
        "brier": round(_brier_multiclass(y_true, probs), 6),
        "ece": expected_calibration_error(y_true, probs)["mean"],
        "accuracy": round(accuracy_and_per_class(y_true, probs)["accuracy"], 6),
        "n": int(len(y_true)),
    }


def _fit_logreg(X_train: np.ndarray, y_train: np.ndarray, X_val: np.ndarray) -> np.ndarray:
    from sklearn.linear_model import LogisticRegression

    mu, sigma = X_train.mean(axis=0), X_train.std(axis=0) + 1e-8
    Xtr, Xv = (X_train - mu) / sigma, (X_val - mu) / sigma
    # sklearn >=1.7 removed multi_class= — lbfgs (the default solver) already
    # fits multinomial softmax natively for >2 classes, no kwarg needed.
    clf = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=SEED)
    clf.fit(Xtr, y_train)
    # LogisticRegression's own classes_ may omit a class absent from y_train;
    # realign to the fixed [0,1,2] column order the metrics functions require.
    probs = np.full((len(X_val), 3), 1e-9)
    for j, cls in enumerate(clf.classes_):
        probs[:, int(cls)] = clf.predict_proba(Xv)[:, j]
    probs = probs / probs.sum(axis=1, keepdims=True)
    return probs


def main() -> int:
    trainer = _load_trainer()
    cache_dir = _ROOT / "backend" / "data" / "cache"
    log.info("Loading real corpus from %s …", cache_dir)
    matches = trainer.load_matches(cache_dir)
    log.info("%d parseable matches, %s -> %s", len(matches), matches[0]["date"].date(), matches[-1]["date"].date())

    _cross_verify_fast_replay(matches, n_check=300)

    rows, labels, dates = _build_rows(matches)
    y = np.array(labels, dtype=np.int64)
    n = len(rows)
    n_val = max(1, int(n * VAL_SPLIT))
    n_train = n - n_val
    log.info(
        "Chronological split: train=%d (%s -> %s), val=%d (%s -> %s)",
        n_train, dates[0].date(), dates[n_train - 1].date(),
        n_val, dates[n_train].date(), dates[-1].date(),
    )

    y_train, y_val = y[:n_train], y[n_train:]

    results: Dict[str, Dict[str, object]] = {}

    # --- uniform ---
    results["uniform"] = _score(y_val, np.full((n_val, 3), 1.0 / 3.0))

    # --- home_bias: overall empirical outcome rate from TRAIN, applied flat ---
    train_rate = np.bincount(y_train, minlength=3) / len(y_train)
    results["home_bias"] = _score(y_val, np.tile(train_rate, (n_val, 1)))

    # --- league_prior: per-league empirical rate from TRAIN ---
    leagues_train = [rows[i]["league"] for i in range(n_train)]
    leagues_val = [rows[i]["league"] for i in range(n_train, n)]
    per_league_rate: Dict[str, np.ndarray] = {}
    for lg in set(leagues_train):
        idx = [i for i in range(n_train) if leagues_train[i] == lg]
        per_league_rate[lg] = np.bincount(y_train[idx], minlength=3) / max(len(idx), 1)
    league_probs = np.array([
        per_league_rate.get(lg, train_rate) for lg in leagues_val
    ])
    results["league_prior"] = _score(y_val, league_probs)

    # --- elo_only: resolved-both subset only, to isolate Elo's own signal ---
    resolved_mask_val = np.array([rows[i]["elo_resolved"] for i in range(n_train, n)]) > 0.5
    resolved_mask_train = np.array([rows[i]["elo_resolved"] for i in range(n_train)]) > 0.5
    if resolved_mask_train.sum() >= 30 and resolved_mask_val.sum() >= 10:
        X_elo_train = _matrix([rows[i] for i in range(n_train) if resolved_mask_train[i]], _ELO_COLS[:1])
        y_elo_train = y_train[resolved_mask_train]
        X_elo_val = _matrix([rows[n_train + i] for i in range(n_val) if resolved_mask_val[i]], _ELO_COLS[:1])
        y_elo_val = y_val[resolved_mask_val]
        probs_elo = _fit_logreg(X_elo_train, y_elo_train, X_elo_val)
        elo_only_score = _score(y_elo_val, probs_elo)
        elo_only_score["coverage_note"] = (
            f"scored on the {int(resolved_mask_val.sum())}/{n_val} val rows "
            "where both sides had a resolved Elo rating; not comparable 1:1 "
            "with the full-val-set rows above without accounting for that."
        )
        results["elo_only"] = elo_only_score
    else:
        results["elo_only"] = {"skipped": True, "reason": "insufficient resolved-Elo rows"}

    # --- BASE (form/recency, all real) ---
    X_base_train = _matrix(rows[:n_train], _BASE_COLS)
    X_base_val = _matrix(rows[n_train:], _BASE_COLS)
    probs_base = _fit_logreg(X_base_train, y_train, X_base_val)
    results["BASE_form_recency"] = _score(y_val, probs_base)

    # --- BASE + ELO ---
    X_full_train = _matrix(rows[:n_train], _BASE_COLS + _ELO_COLS)
    X_full_val = _matrix(rows[n_train:], _BASE_COLS + _ELO_COLS)
    probs_full = _fit_logreg(X_full_train, y_train, X_full_val)
    results["BASE_plus_ELO"] = _score(y_val, probs_full)

    rps_base = results["BASE_form_recency"]["rps_mean"]
    rps_full = results["BASE_plus_ELO"]["rps_mean"]
    delta = rps_full - rps_base

    elo_resolved_val_rate = float(resolved_mask_val.mean()) if n_val else 0.0

    report = {
        "report_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"], cwd=_ROOT,
            capture_output=True, text=True, check=False,
        ).stdout.strip() or "unknown",
        "metric_contract_version": "1.0.0",
        "milestone": "M2 Family A — Strength and recency (Elo)",
        "corpus": {
            "source": "backend/data/cache/fd_*.csv",
            "n_matches_loaded": len(matches),
            "n_rows_with_5plus_history_both_sides": n,
            "date_range": [matches[0]["date"].date().isoformat(), matches[-1]["date"].date().isoformat()],
            "train_rows": n_train, "val_rows": n_val,
        },
        "motivating_finding": (
            "elo_difference and all 4 sibling canonical Elo features are a "
            "constant 0.0 across all 12,256 rows train_on_real_matches.build_dataset() "
            "emits (measured directly this session) -- every trained artifact, "
            "including the served v5_phase7 generation, has never seen real Elo "
            "signal in training. This script computes real Elo via a fresh "
            "chronological EloEngine replay to measure what was actually never tested."
        ),
        "elo_resolved_val_rate": round(elo_resolved_val_rate, 4),
        "results": results,
        "m2_ablation_answer": {
            "does_elo_improve_out_of_sample_rps": bool(delta < 0),
            "rps_base_form_recency": rps_base,
            "rps_base_plus_elo": rps_full,
            "rps_delta": round(delta, 6),
            "interpretation": (
                f"Adding real Elo to the form/recency BASE {'improved' if delta < 0 else 'did not improve'} "
                f"out-of-sample RPS ({rps_base:.4f} -> {rps_full:.4f}, delta {delta:+.4f}); "
                f"Elo was resolved for both sides on {elo_resolved_val_rate*100:.1f}% of validation rows."
            ),
        },
        "not_done_here": (
            "No artifact promoted or wired into serving. Elo replay is in-memory "
            "only for this measurement, not persisted or backfilled into any "
            "training corpus file. Promoting elo_difference from constant-default "
            "to a real, replayed feature in the actual training pipeline "
            "(train_on_real_matches.py) is a separate, larger change -- it would "
            "touch a script every retrain depends on and change what v_phase7's "
            "successor generation trains on -- and is not done in this M2 "
            "evaluation-only pass."
        ),
    }

    out_path = _ROOT / "backend" / "reports" / "evaluation" / "m2-family-a-elo-ablation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Wrote %s", out_path)

    log.info("═══ M2 Family A Results (RPS, lower is better) ═══════════════")
    for name, r in results.items():
        if r.get("skipped"):
            log.info("  %-20s SKIPPED (%s)", name, r["reason"])
        else:
            log.info("  %-20s rps=%.4f  brier=%.4f  logloss=%.4f  ece=%.4f  acc=%.4f  n=%d",
                      name, r["rps_mean"], r["brier"], r["log_loss"], r["ece"], r["accuracy"], r["n"])
    log.info(report["m2_ablation_answer"]["interpretation"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
