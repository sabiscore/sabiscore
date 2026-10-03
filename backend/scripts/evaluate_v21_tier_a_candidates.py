#!/usr/bin/env python3
"""SabiScore V21 — Quantitative Evaluation, Tier A Signal Discovery & Gate 7 Parity.

Strict adherence to:
- SabiScore V21 Directive & PRODUCTION_EXECUTIVE_DIRECTIVE_V17.md
- Frozen C6 Protocol & reports/research/v21-market-evaluation-protocol.json
- Chronological train/calibration/holdout splits (1920-2324 train, 2425 cal, 2526 holdout)
- CANDIDATE-M (market-independent) vs CANDIDATE-MA (market-aware) separation
- Gate 7 Parity: ISO-week cluster bootstrap (10,000 replicates, seed 42, alpha=0.05/3)
"""

from __future__ import annotations

import csv
import json
import logging
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_v21")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_CACHE = BACKEND_ROOT / "data" / "cache"
REPORTS_ROOT = BACKEND_ROOT.parent / "reports"

LEAGUES = ("EPL", "LA_LIGA", "SERIE_A", "BUNDESLIGA", "LIGUE_1", "EREDIVISIE")
LEAGUE_DIV_MAP = {
    "EPL": "E0",
    "LA_LIGA": "SP1",
    "SERIE_A": "I1",
    "BUNDESLIGA": "D1",
    "LIGUE_1": "F1",
    "EREDIVISIE": "N1",
}
SEASONS_ALL = ("1920", "2021", "2122", "2223", "2324", "2425", "2526")
TRAIN_SEASONS = set(SEASONS_ALL[:5])  # 1920 to 2324
CAL_SEASONS = {"2425"}
HOLDOUT_SEASONS = {"2526"}


def parse_date(date_str: str) -> Optional[datetime]:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def devig_mult(odds: Tuple[float, float, float]) -> Optional[Tuple[float, float, float]]:
    h, d, a = odds
    if h <= 1.0 or d <= 1.0 or a <= 1.0:
        return None
    overround = (1.0 / h) + (1.0 / d) + (1.0 / a)
    if overround < 1.005 or overround > 1.25:
        return None
    return ((1.0 / h) / overround, (1.0 / d) / overround, (1.0 / a) / overround)


def rps_3class(probs: Tuple[float, float, float], outcome: int) -> float:
    """Ranked Probability Score for 3 outcomes (0=Home, 1=Draw, 2=Away)."""
    p_h, p_d, _ = probs
    obs_h = 1.0 if outcome == 0 else 0.0
    obs_d = 1.0 if outcome == 1 else 0.0
    cum_p1 = p_h
    cum_o1 = obs_h
    cum_p2 = p_h + p_d
    cum_o2 = obs_h + obs_d
    return 0.5 * ((cum_p1 - cum_o1) ** 2 + (cum_p2 - cum_o2) ** 2)


def brier_3class(probs: Tuple[float, float, float], outcome: int) -> float:
    y = [1.0 if outcome == i else 0.0 for i in range(3)]
    return sum((probs[i] - y[i]) ** 2 for i in range(3)) / 3.0


def log_loss_3class(probs: Tuple[float, float, float], outcome: int) -> float:
    eps = 1e-15
    p = max(eps, min(1.0 - eps, probs[outcome]))
    return -math.log(p)


def compute_ece(probs: List[Tuple[float, float, float]], outcomes: List[int], n_bins: int = 10) -> float:
    confidences = [max(p) for p in probs]
    predictions = [int(np.argmax(p)) for p in probs]
    accuracies = [1.0 if predictions[i] == outcomes[i] else 0.0 for i in range(len(outcomes))]
    
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(outcomes)
    if n == 0:
        return 0.0
    for i in range(n_bins):
        bin_lower = bin_edges[i]
        bin_upper = bin_edges[i + 1]
        in_bin = [j for j in range(n) if bin_lower <= confidences[j] < bin_upper or (i == n_bins - 1 and confidences[j] == bin_upper)]
        if in_bin:
            bin_acc = np.mean([accuracies[j] for j in in_bin])
            bin_conf = np.mean([confidences[j] for j in in_bin])
            ece += (len(in_bin) / n) * abs(bin_acc - bin_conf)
    return float(ece)


def load_all_fixtures() -> List[Dict[str, Any]]:
    fixtures = []
    for league, div in LEAGUE_DIV_MAP.items():
        for season in SEASONS_ALL:
            csv_path = DATA_CACHE / f"fd_{div}_{season}.csv"
            if not csv_path.exists():
                logger.warning("Missing dataset: %s", csv_path)
                continue
            with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    raw_date = row.get("date") or row.get("Date") or ""
                    date_val = parse_date(raw_date)
                    if not date_val:
                        continue
                    ftr = (row.get("result") or row.get("FTR") or "").strip().upper()
                    if ftr not in ("H", "D", "A"):
                        continue
                    outcome = 0 if ftr == "H" else (1 if ftr == "D" else 2)
                    
                    try:
                        fthg = float(row.get("home_goals") or row.get("FTHG") or 0)
                        ftag = float(row.get("away_goals") or row.get("FTAG") or 0)
                        hs = float(row.get("home_shots") or row.get("HS") or 0) if (row.get("home_shots") or row.get("HS")) else None
                        as_ = float(row.get("away_shots") or row.get("AS") or 0) if (row.get("away_shots") or row.get("AS")) else None
                        hst = float(row.get("home_shots_target") or row.get("HST") or 0) if (row.get("home_shots_target") or row.get("HST")) else None
                        ast = float(row.get("away_shots_target") or row.get("AST") or 0) if (row.get("away_shots_target") or row.get("AST")) else None
                    except ValueError:
                        continue

                    # Pinnacle Closing Odds (Primary Benchmark)
                    psch_val = row.get("pinnacle_closing_home") or row.get("PSCH") or 0
                    pscd_val = row.get("pinnacle_closing_draw") or row.get("PSCD") or 0
                    psca_val = row.get("pinnacle_closing_away") or row.get("PSCA") or 0
                    psch = float(psch_val or 0)
                    pscd = float(pscd_val or 0)
                    psca = float(psca_val or 0)
                    close_devig = devig_mult((psch, pscd, psca)) if psch and pscd and psca else None
                    
                    # Pinnacle Opening Odds
                    psh_val = row.get("pinnacle_home") or row.get("PSH") or 0
                    psd_val = row.get("pinnacle_draw") or row.get("PSD") or 0
                    psa_val = row.get("pinnacle_away") or row.get("PSA") or 0
                    psh = float(psh_val or 0)
                    psd = float(psd_val or 0)
                    psa = float(psa_val or 0)
                    open_devig = devig_mult((psh, psd, psa)) if psh and psd and psa else None

                    # Bet365 fallback if Pinnacle missing
                    b365ch_val = row.get("B365CH") or row.get("b365_closing_home") or row.get("bet365_closing_home") or 0
                    b365cd_val = row.get("B365CD") or row.get("b365_closing_draw") or row.get("bet365_closing_draw") or 0
                    b365ca_val = row.get("B365CA") or row.get("b365_closing_away") or row.get("bet365_closing_away") or 0
                    b365ch = float(b365ch_val or 0)
                    b365cd = float(b365cd_val or 0)
                    b365ca = float(b365ca_val or 0)
                    b365_close = devig_mult((b365ch, b365cd, b365ca)) if b365ch and b365cd and b365ca else None

                    eff_close = close_devig or b365_close
                    close_book = "pinnacle" if close_devig else ("bet365" if b365_close else None)
                    
                    home_t = (row.get("home_team") or row.get("HomeTeam") or "").strip()
                    away_t = (row.get("away_team") or row.get("AwayTeam") or "").strip()
                    
                    fixtures.append({
                        "league": league,
                        "season": season,
                        "date": date_val,
                        "home_team": home_t,
                        "away_team": away_t,
                        "fthg": fthg,
                        "ftag": ftag,
                        "hs": hs,
                        "as": as_,
                        "hst": hst,
                        "ast": ast,
                        "outcome": outcome,
                        "close_odds": (psch, pscd, psca) if psch else None,
                        "close_devig": eff_close,
                        "close_book": close_book,
                        "open_devig": open_devig,
                    })
    fixtures.sort(key=lambda x: x["date"])
    logger.info("Loaded and sorted %d historical fixtures.", len(fixtures))
    return fixtures


def extract_features(fixtures: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chronologically extract Tier A features with strict PIT safety."""
    elo_ratings: Dict[Tuple[str, str], float] = defaultdict(lambda: 1500.0)
    last_played: Dict[Tuple[str, str], datetime] = {}
    team_history: Dict[Tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=5))
    
    K = 20.0
    HOME_ADV = 65.0
    
    dataset = []
    
    for f in fixtures:
        league = f["league"]
        home_key = (league, f["home_team"])
        away_key = (league, f["away_team"])
        dt = f["date"]
        
        # 1. Elo before match
        r_home = elo_ratings[home_key]
        r_away = elo_ratings[away_key]
        elo_diff = (r_home + HOME_ADV) - r_away
        
        # 2. Rest days
        home_rest = (dt - last_played[home_key]).total_seconds() / 86400.0 if home_key in last_played else 7.0
        away_rest = (dt - last_played[away_key]).total_seconds() / 86400.0 if away_key in last_played else 7.0
        rest_diff = min(14.0, max(-14.0, home_rest - away_rest))
        
        # 3. Rolling Form & Attack/Defense (last 5 matches)
        h_hist = list(team_history[home_key])
        a_hist = list(team_history[away_key])
        
        h_form_pts = np.mean([h["pts"] for h in h_hist]) if h_hist else 1.3
        a_form_pts = np.mean([a["pts"] for a in a_hist]) if a_hist else 1.3
        form_diff = float(h_form_pts - a_form_pts)
        
        h_gf_avg = np.mean([h["gf"] for h in h_hist]) if h_hist else 1.4
        h_ga_avg = np.mean([h["ga"] for h in h_hist]) if h_hist else 1.2
        a_gf_avg = np.mean([a["gf"] for a in a_hist]) if a_hist else 1.1
        a_ga_avg = np.mean([a["ga"] for a in a_hist]) if a_hist else 1.5
        
        attack_defense_diff = float((h_gf_avg - a_ga_avg) - (a_gf_avg - h_ga_avg))
        
        f_feat = {
            **f,
            "cold_start": not h_hist or not a_hist,
            "elo_diff": elo_diff,
            "rest_diff": rest_diff,
            "form_diff": form_diff,
            "attack_defense_diff": attack_defense_diff,
        }
        dataset.append(f_feat)
        
        # Post-match state update
        last_played[home_key] = dt
        last_played[away_key] = dt
        
        out = f["outcome"]
        pts_h = 3.0 if out == 0 else (1.0 if out == 1 else 0.0)
        pts_a = 0.0 if out == 0 else (1.0 if out == 1 else 3.0)
        
        team_history[home_key].append({"pts": pts_h, "gf": f["fthg"], "ga": f["ftag"]})
        team_history[away_key].append({"pts": pts_a, "gf": f["ftag"], "ga": f["fthg"]})
        
        # Elo update
        dr = (r_home + HOME_ADV) - r_away
        e_h = 1.0 / (1.0 + 10.0 ** (-dr / 400.0))
        actual_h = 1.0 if out == 0 else (0.5 if out == 1 else 0.0)
        elo_ratings[home_key] += K * (actual_h - e_h)
        elo_ratings[away_key] += K * ((1.0 - actual_h) - (1.0 - e_h))
        
    return dataset


def _score(preds: List[Tuple[float, float, float]], outcomes: List[int]) -> Dict[str, Any]:
    return {
        "mean_rps": float(np.mean([rps_3class(preds[i], outcomes[i]) for i in range(len(outcomes))])),
        "mean_brier": float(np.mean([brier_3class(preds[i], outcomes[i]) for i in range(len(outcomes))])),
        "mean_log_loss": float(np.mean([log_loss_3class(preds[i], outcomes[i]) for i in range(len(outcomes))])),
        "ece": compute_ece(preds, outcomes),
        "sample_size": len(outcomes),
    }


def _week_cluster_ci(deltas: np.ndarray, dates: List[datetime]) -> Dict[str, Any]:
    """Paired ISO-week cluster bootstrap of a mean RPS delta (10,000 reps, seed 42)."""
    weeks = [d.isocalendar()[:2] for d in dates]
    unique_weeks = sorted(set(weeks))
    week_to_indices = {w: [i for i, mw in enumerate(weeks) if mw == w] for w in unique_weeks}
    rng = np.random.default_rng(42)
    boot_means = []
    for _ in range(10_000):
        picked = rng.integers(0, len(unique_weeks), size=len(unique_weeks))
        idx = [i for k in picked for i in week_to_indices[unique_weeks[k]]]
        boot_means.append(float(np.mean(deltas[idx])))
    alpha = 0.05 / 3.0
    return {
        "mean_delta": float(np.mean(deltas)),
        "ci_98_33": [
            float(np.percentile(boot_means, alpha / 2 * 100)),
            float(np.percentile(boot_means, (1 - alpha / 2) * 100)),
        ],
        "ci_95": [float(np.percentile(boot_means, 2.5)), float(np.percentile(boot_means, 97.5))],
        "iso_weeks": len(unique_weeks),
        "n": int(len(deltas)),
    }


def _input_hashes() -> Dict[str, str]:
    import hashlib

    hashes = {}
    for div in LEAGUE_DIV_MAP.values():
        for season in SEASONS_ALL:
            path = DATA_CACHE / f"fd_{div}_{season}.csv"
            if path.exists():
                hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def run_v21_evaluation() -> Dict[str, Any]:
    """Train Candidate-M offline on the frozen split and measure it.

    Writes exactly one file, reports/research/v21-candidate-m-evaluation.json,
    holding only values this script computes. It never writes a certification,
    promotion, rollback, feature-integration or data-quality claim: it measures
    none of those. A measured Gate 7 PASS here is research evidence only and
    cannot certify a generation (the frozen protocol's c6_eligible and
    complete_evidence cohorts are not covered).
    """
    import subprocess

    logger.info("Starting SabiScore V21 Candidate-M evaluation...")
    fixtures = load_all_fixtures()
    data = extract_features(fixtures)

    train_data = [d for d in data if d["season"] in TRAIN_SEASONS]
    cal_data = [d for d in data if d["season"] in CAL_SEASONS]
    holdout_data = [d for d in data if d["season"] in HOLDOUT_SEASONS and d["close_devig"] is not None]
    logger.info("Split sizes: Train=%d, Cal=%d, Holdout=%d", len(train_data), len(cal_data), len(holdout_data))

    feature_sets = {
        "A0_baseline": [],
        "A1_elo": ["elo_diff"],
        "A2_elo_rest": ["elo_diff", "rest_diff"],
        "A3_elo_form": ["elo_diff", "rest_diff", "form_diff"],
        "A4_candidate_m_all_tier_a": ["elo_diff", "rest_diff", "form_diff", "attack_defense_diff"],
    }
    y_train = [d["outcome"] for d in train_data]
    y_holdout = [d["outcome"] for d in holdout_data]
    p_prior = tuple(float(np.mean([1.0 if y == c else 0.0 for y in y_train])) for c in range(3))

    ablation: Dict[str, Any] = {}
    models: Dict[str, Any] = {}
    for name, cols in feature_sets.items():
        if not cols:
            preds = [p_prior for _ in holdout_data]
        else:
            clf = LogisticRegression(max_iter=1000, solver="lbfgs")
            clf.fit(np.array([[d[c] for c in cols] for d in train_data]), y_train)
            models[name] = (clf, cols)
            probs = clf.predict_proba(np.array([[d[c] for c in cols] for d in holdout_data]))
            preds = [tuple(probs[i]) for i in range(len(holdout_data))]
        ablation[name] = {"features": cols, **_score(preds, y_holdout)}
        logger.info("Ablation %s: %s", name, ablation[name])

    # Calibration: fitted on the calibration season only, scored on the untouched holdout.
    clf_m, cols_m = models["A4_candidate_m_all_tier_a"]
    raw_cal = clf_m.predict_proba(np.array([[d[c] for c in cols_m] for d in cal_data]))
    y_cal = [d["outcome"] for d in cal_data]
    raw_hold = clf_m.predict_proba(np.array([[d[c] for c in cols_m] for d in holdout_data]))
    iso_hold = np.zeros_like(raw_hold)
    for c in range(3):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(raw_cal[:, c], [1.0 if y == c else 0.0 for y in y_cal])
        iso_hold[:, c] = iso.transform(raw_hold[:, c])
    iso_hold = iso_hold / np.sum(iso_hold, axis=1, keepdims=True)
    raw_preds = [tuple(raw_hold[i]) for i in range(len(holdout_data))]
    cand_preds = [tuple(iso_hold[i]) for i in range(len(holdout_data))]
    calibration = {"raw": _score(raw_preds, y_holdout), "isotonic": _score(cand_preds, y_holdout)}

    # Gate 7 research measurement against the closing benchmark.
    cand_rps = np.array([rps_3class(cand_preds[i], y_holdout[i]) for i in range(len(holdout_data))])
    close_rps = np.array([rps_3class(d["close_devig"], d["outcome"]) for d in holdout_data])
    closing = _week_cluster_ci(cand_rps - close_rps, [d["date"] for d in holdout_data])
    closing["market_rps"] = float(np.mean(close_rps))
    closing["candidate_rps"] = float(np.mean(cand_rps))
    closing["close_book_counts"] = {
        book: sum(1 for d in holdout_data if d["close_book"] == book) for book in ("pinnacle", "bet365")
    }

    # Opening benchmark only where an opening quote exists: never substitute the close.
    open_idx = [i for i, d in enumerate(holdout_data) if d["open_devig"] is not None]
    open_rps = np.array([rps_3class(holdout_data[i]["open_devig"], y_holdout[i]) for i in open_idx])
    opening = _week_cluster_ci(cand_rps[open_idx] - open_rps, [holdout_data[i]["date"] for i in open_idx])
    opening["market_rps"] = float(np.mean(open_rps))
    opening["candidate_rps"] = float(np.mean(cand_rps[open_idx]))

    regimes = {}
    for league in LEAGUES:
        idx = [i for i, d in enumerate(holdout_data) if d["league"] == league]
        if idx:
            regimes[league] = {
                "n": len(idx),
                "candidate_rps": float(np.mean(cand_rps[idx])),
                "market_close_rps": float(np.mean(close_rps[idx])),
                "delta": float(np.mean(cand_rps[idx] - close_rps[idx])),
            }

    lower, upper = closing["ci_98_33"]
    git_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, capture_output=True, text=True
    ).stdout.strip()
    result = {
        "document": "SABISCORE_V21_CANDIDATE_M_EVALUATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha or None,
        "command": "python backend/scripts/evaluate_v21_tier_a_candidates.py",
        "input_sha256": _input_hashes(),
        "split": {
            "train": sorted(TRAIN_SEASONS),
            "calibration": sorted(CAL_SEASONS),
            "holdout": sorted(HOLDOUT_SEASONS),
        },
        "population": {
            "train": len(train_data),
            "calibration": len(cal_data),
            "holdout_with_closing_quote": len(holdout_data),
            "holdout_with_opening_quote": len(open_idx),
            "cold_start_rows_train": sum(1 for d in train_data if d["cold_start"]),
            "cold_start_rows_holdout": sum(1 for d in holdout_data if d["cold_start"]),
        },
        "candidate": {
            "track": "Candidate-M",
            "model": "multinomial logistic regression + per-class isotonic calibration (fit on calibration season)",
            "features": cols_m,
            "market_inputs": False,
            "serialized": False,
        },
        "ablation": ablation,
        "calibration": calibration,
        "benchmarks": {"closing": closing, "opening": opening},
        "gate_7_research": {
            "status": "PASS" if upper < 0.0 else "FAIL",
            "rule": "98.33% ISO-week cluster CI upper bound of (candidate RPS - closing RPS) < 0",
            "worse_than_market": bool(lower > 0.0),
            "certifies": False,
            "why_not_certifying": (
                "single cohort (closing-quote holdout); the protocol's c6_eligible and "
                "complete_evidence cohorts are not covered"
            ),
        },
        "regimes": regimes,
    }
    out = REPORTS_ROOT / "research" / "v21-candidate-m-evaluation.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Wrote %s", out)
    return result


if __name__ == "__main__":
    run_v21_evaluation()
