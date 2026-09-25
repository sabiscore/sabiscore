"""G18 market-residual research track — development folds only.

Implements ``reports/research/g18-market-residual-protocol.json`` and records its
SHA-256; every parameter is read from that file, so the run cannot drift from
what was registered. Season 2526 is physically excluded: its files are never
copied into the loader's input directory. Research only — nothing here is served.

Run from ``backend/``:  PYTHONPATH=. python scripts/research_g18_market_residual.py
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import minimize

_SCRIPTS = Path(__file__).resolve().parent
BACKEND = _SCRIPTS.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(BACKEND))

from train_on_real_matches import load_matches  # noqa: E402

from src.features.elo_replay import compute_elo_training_columns  # noqa: E402
from src.models.calibration import _compute_brier_multiclass  # noqa: E402
from src.models.evaluation.market_baseline import devig  # noqa: E402
from src.models.evaluation.metrics import (  # noqa: E402
    log_loss_multiclass,
    ranked_probability_score_rowwise,
    week_cluster_ci,
)

RESEARCH = BACKEND / "reports" / "research"
PROTOCOL_PATH = RESEARCH / "g18-market-residual-protocol.json"
OUT_JSON = RESEARCH / "g18-market-residual-development.json"
OUT_MD = RESEARCH / "g18-market-residual-development.md"
CACHE = BACKEND / "data" / "cache"
CANDIDATES = ("R1_intercepts", "R2_longshot", "R3_residual")
N_PARAMS = {"R1_intercepts": 2, "R2_longshot": 4, "R3_residual": 8}


def load_protocol() -> tuple[dict, str]:
    raw = PROTOCOL_PATH.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def load_development_matches(excluded: str) -> tuple[list[dict], dict]:
    files = sorted(CACHE.glob("fd_*.csv"))
    used = [p for p in files if p.stem.split("_")[2] != excluded]
    with tempfile.TemporaryDirectory() as tmp:
        for p in used:
            shutil.copy2(p, Path(tmp) / p.name)
        matches = load_matches(Path(tmp))
    if any(m["season"] == excluded for m in matches):
        raise SystemExit(f"a {excluded} row reached the loader -- refusing to continue")
    return matches, {
        "files_never_opened": sorted({p.name for p in files} - {p.name for p in used}),
        "seasons_loaded": sorted({m["season"] for m in matches}),
    }


def build_rows(matches: list[dict], protocol: dict) -> tuple[dict[str, np.ndarray], dict]:
    """One chronological pass: Elo and form are read before the match updates them."""
    bench = protocol["benchmark"]
    lo, hi = bench["overround_bounds"]
    min_prior = bench["min_prior_league_matches_per_team"]
    leagues = set(protocol["data"]["leagues"])
    elo = compute_elo_training_columns(matches).rows

    points: dict[tuple[str, str], deque] = defaultdict(lambda: deque(maxlen=5))
    played: dict[tuple[str, str], int] = defaultdict(int)
    funnel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    cols: dict[str, list] = defaultdict(list)

    for i, m in enumerate(matches):
        league, home, away = m["league"], (m["league"], m["home"]), (m["league"], m["away"])
        hg, ag = m["hg"], m["ag"]
        key = f"{m['league']}/{m['season']}"
        funnel[key]["loaded"] += 1
        form_h = float(np.mean(points[home])) if points[home] else None
        form_a = float(np.mean(points[away])) if points[away] else None
        eligible = (
            league in leagues
            and m["odds"] is not None
            and played[home] >= min_prior
            and played[away] >= min_prior
            and bool(elo[i])
        )
        if eligible:
            overround = sum(1.0 / o for o in m["odds"])
            eligible = lo <= overround <= hi
        if eligible:
            funnel[key]["eligible"] += 1
            implied = [1.0 / o for o in m["odds"]]
            p = np.array(implied) / sum(implied)
            cols["league"].append(league)
            cols["season"].append(m["season"])
            cols["date"].append(m["date"])
            cols["y"].append(0 if hg > ag else (1 if hg == ag else 2))
            cols["p_market"].append(p)
            cols["p_shin"].append(devig(m["odds"], method="shin").probabilities)
            cols["elo_difference"].append(elo[i]["elo_difference"])
            cols["form_difference"].append(form_h - form_a)
        # Update strictly after the row is emitted.
        points[home].append(3 if hg > ag else (1 if hg == ag else 0))
        points[away].append(3 if ag > hg else (1 if hg == ag else 0))
        played[home] += 1
        played[away] += 1

    rows = {k: np.asarray(v) for k, v in cols.items() if k != "date"}
    rows["date"] = np.asarray(cols["date"], dtype=object)
    rows["p_market"] = np.asarray(cols["p_market"], dtype=np.float64)
    rows["p_shin"] = np.asarray(cols["p_shin"], dtype=np.float64)
    return rows, {k: dict(v) for k, v in sorted(funnel.items())}


def log_ratios(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return np.log(p[:, 0] / p[:, 2]), np.log(p[:, 1] / p[:, 2])


def design(kind: str, m_own: np.ndarray, cov: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """Design matrix for one equation and its penalty mask (intercept unpenalised)."""
    parts = [np.ones((len(m_own), 1))]
    if kind in ("R2_longshot", "R3_residual"):
        parts.append(m_own[:, None])
    if kind == "R3_residual":
        parts.append(cov)
    x = np.hstack(parts)
    penalty = np.ones(x.shape[1])
    penalty[0] = 0.0
    return x, penalty


def softmax_offset(mh, md, xh, xd, beta_h, beta_d) -> np.ndarray:
    z = np.column_stack([mh + xh @ beta_h, md + xd @ beta_d, np.zeros(len(mh))])
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit(kind: str, mh, md, cov, y, l2: float, fit_cfg: dict) -> tuple[np.ndarray, np.ndarray]:
    xh, pen = design(kind, mh, cov)
    xd, _ = design(kind, md, cov)
    k, n = xh.shape[1], len(y)
    yh, yd = (y == 0).astype(float), (y == 1).astype(float)

    def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
        bh, bd = theta[:k], theta[k:]
        p = softmax_offset(mh, md, xh, xd, bh, bd)
        nll = -np.mean(np.log(np.clip(p[np.arange(n), y], 1e-15, 1.0)))
        reg = 0.5 * l2 * (np.sum(pen * bh**2) + np.sum(pen * bd**2)) / n
        gh = xh.T @ (p[:, 0] - yh) / n + l2 * pen * bh / n
        gd = xd.T @ (p[:, 1] - yd) / n + l2 * pen * bd / n
        return nll + reg, np.concatenate([gh, gd])

    res = minimize(
        objective,
        np.zeros(2 * k),
        jac=True,
        method="L-BFGS-B",
        options={"gtol": fit_cfg["gtol"], "maxiter": fit_cfg["maxiter"]},
    )
    if not res.success:
        raise SystemExit(f"{kind} fit did not converge: {res.message}")
    return res.x[:k], res.x[k:]


def predict(kind, beta_h, beta_d, mh, md, cov) -> np.ndarray:
    xh, _ = design(kind, mh, cov)
    xd, _ = design(kind, md, cov)
    return softmax_offset(mh, md, xh, xd, beta_h, beta_d)


def scores(y: np.ndarray, p: np.ndarray) -> dict:
    return {
        "n": int(len(y)),
        "rps": float(ranked_probability_score_rowwise(y, p).mean()),
        "log_loss": float(log_loss_multiclass(y, p)),
        "brier": float(_compute_brier_multiclass(y, p)),
    }


def run() -> dict:
    protocol, protocol_sha = load_protocol()
    excluded = protocol["data"]["physically_excluded_season"]
    matches, provenance = load_development_matches(excluded)
    rows, funnel = build_rows(matches, protocol)
    l2 = protocol["fit"]["l2"]
    fit_cfg = {"gtol": 1e-9, "maxiter": 1000}
    n_boot = int(protocol["metrics"]["ci"].split(", ")[1].split()[0])
    seed = 42

    y, league, season, dates = rows["y"], rows["league"], rows["season"], rows["date"]
    mh, md = log_ratios(rows["p_market"])
    raw_cov = np.column_stack([rows["elo_difference"], rows["form_difference"]])
    rps_market = ranked_probability_score_rowwise(y, rows["p_market"])

    folds = []
    probs_all = {c: np.full((len(y), 3), np.nan) for c in CANDIDATES}
    tested = np.zeros(len(y), dtype=bool)
    for test_season in protocol["folds"]["test_seasons"]:
        train = season < test_season
        test = season == test_season
        mu, sd = raw_cov[train].mean(axis=0), raw_cov[train].std(axis=0)
        cov = (raw_cov - mu) / sd
        fold: dict[str, Any] = {
            "test_season": test_season,
            "n_train": int(train.sum()),
            "n_test": int(test.sum()),
            "covariate_standardisation": {"mean": mu.tolist(), "sd": sd.tolist()},
            "coefficients": {},
        }
        for c in CANDIDATES:
            bh, bd = fit(c, mh[train], md[train], cov[train], y[train], l2, fit_cfg)
            fold["coefficients"][c] = {"home": bh.tolist(), "draw": bd.tolist()}
            probs_all[c][test] = predict(c, bh, bd, mh[test], md[test], cov[test])
        tested |= test
        folds.append(fold)

    idx = np.flatnonzero(tested)
    per_candidate: dict[str, Any] = {}
    groups = {"POOLED": idx, **{lg: idx[league[idx] == lg] for lg in protocol["data"]["leagues"]}}
    groups.update({f"season {s}": idx[season[idx] == s] for s in protocol["folds"]["test_seasons"]})
    per_candidate["M0_market"] = {g: scores(y[r], rows["p_market"][r]) for g, r in groups.items()}
    per_candidate["M0_market_shin_sensitivity"] = {
        g: scores(y[r], rows["p_shin"][r]) for g, r in groups.items()
    }
    for c in CANDIDATES:
        delta = ranked_probability_score_rowwise(y[idx], probs_all[c][idx]) - rps_market[idx]
        by_row = dict(zip(idx.tolist(), delta.tolist()))
        per_candidate[c] = {
            g: {
                **scores(y[r], probs_all[c][r]),
                "vs_market": week_cluster_ci(
                    np.asarray([by_row[i] for i in r.tolist()]), dates[r], n_boot, seed
                ),
            }
            for g, r in groups.items()
        }

    promising = [c for c in CANDIDATES if per_candidate[c]["POOLED"]["vs_market"]["beats_market"]]
    selected = (
        min(promising, key=lambda c: (per_candidate[c]["POOLED"]["rps"], N_PARAMS[c]))
        if promising
        else None
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=BACKEND
    ).stdout.strip()
    return {
        "report": "g18-market-residual-development",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_head": head,
        "protocol_path": PROTOCOL_PATH.relative_to(BACKEND).as_posix(),
        "protocol_sha256": protocol_sha,
        "no_2526_read": provenance,
        "environment": {
            "python": sys.version.split()[0],
            **{lib: importlib.metadata.version(lib) for lib in ("numpy", "scipy")},
        },
        "eligibility_funnel": funnel,
        "folds": folds,
        "results": per_candidate,
        "decision": {
            "promising": promising,
            "selected_for_confirmation": selected,
            "confirmation_run": False,
            "reading": (
                "No candidate's pooled development CI is below zero: negative result, "
                "2526 stays unread (protocol decision_rule.if_none_promising)."
                if selected is None
                else f"{selected} is selected; the 2526 confirmation is a separate, single run."
            ),
        },
    }


def render_md(r: dict) -> str:
    groups = ["POOLED", "EPL", "LA_LIGA", "SERIE_A", "BUNDESLIGA", "LIGUE_1"]
    lines = [
        "# G18 market-residual track — development folds",
        "",
        f"Generated {r['generated_at']} at `{r['git_head'][:10]}`. Protocol "
        f"`{r['protocol_path']}` sha256 `{r['protocol_sha256']}` (frozen before this run). "
        f"Test seasons {', '.join(f['test_season'] for f in r['folds'])}; 2526 never opened "
        f"({len(r['no_2526_read']['files_never_opened'])} files excluded).",
        "",
        "## Mean RPS (lower is better)",
        "",
        "| group | n | M0 market | M0 Shin (sensitivity) | R1 intercepts | R2 longshot | R3 residual |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    res = r["results"]
    for g in groups:
        lines.append(
            f"| {g} | {res['M0_market'][g]['n']} | {res['M0_market'][g]['rps']:.5f} | "
            f"{res['M0_market_shin_sensitivity'][g]['rps']:.5f} | "
            + " | ".join(f"{res[c][g]['rps']:.5f}" for c in CANDIDATES)
            + " |"
        )
    lines += [
        "",
        "## ΔRPS vs market (candidate − market), 95% CI, ISO-week cluster bootstrap",
        "",
        "\"beats\" = CI entirely below zero; \"worse\" = CI entirely above zero.",
        "",
        "| group | R1 intercepts | R2 longshot | R3 residual |",
        "| --- | --- | --- | --- |",
    ]
    for g in groups + [f"season {f['test_season']}" for f in r["folds"]]:
        cells = []
        for c in CANDIDATES:
            v = res[c][g]["vs_market"]
            tag = " (beats)" if v["beats_market"] else (" (worse)" if v["worse_than_market"] else "")
            cells.append(f"{v['delta_rps']:+.5f} [{v['ci95'][0]:+.5f}, {v['ci95'][1]:+.5f}]{tag}")
        lines.append(f"| {g} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Decision (pre-registered rule)",
        "",
        f"- Promising (pooled CI below zero): {', '.join(r['decision']['promising']) or 'none'}",
        f"- Selected for 2526 confirmation: {r['decision']['selected_for_confirmation'] or 'none'}",
        f"- {r['decision']['reading']}",
        "",
        "Eredivisie is not in development: the corpus holds no Eredivisie season before 2526.",
        "Full numbers, eligibility funnel and per-fold coefficients: "
        "`g18-market-residual-development.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    report = run()
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(render_md(report), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(BACKEND)} and {OUT_MD.relative_to(BACKEND)}")
    print(report["decision"]["reading"])


if __name__ == "__main__":
    main()
