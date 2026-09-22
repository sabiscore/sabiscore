"""Directive §25 structural baselines — evaluation-only reference instruments.

§25 asks for reference models the research programme can score candidates
against: historical frequency, league-adjusted frequency, Elo, dynamic Elo,
Poisson, Dixon-Coles, market implied probability. Elo and dynamic Elo already
exist (E6 and its ablation); the market baseline already exists (every Stage 3
study uses it). This script adds the three that did not exist as reference
instruments: **historical frequency**, **league-adjusted frequency**, and
**Dixon-Coles**.

⚠️ These are instruments, not candidates. §25: "They are not automatically
production candidates." Nothing here touches a feature contract, a model
artifact, a promotion gate, or a serving path.

Design decisions that matter
----------------------------
**Same split as every other study.** Train on seasons 2223+2324, test on 2425,
five leagues. That is the split Portfolio B, Portfolio E, Portfolio F and E6
all used, so these numbers are directly comparable to theirs rather than being
a fourth incomparable frame.

**Same scoring code as every other study.** `devig`, `mean_rps` and
`paired_rps_diff_bootstrap` are imported from `_incremental_value_harness`
(docs/DEBT.md item 67, "one implementation, three studies") rather than
reimplemented. A reference instrument scored by different arithmetic than the
candidates it is meant to anchor would be worse than no instrument.

**Strictly paired.** Dixon-Coles cannot predict a team it never saw in
training (a promoted side), and some fixtures lack Bet365 quotes. Rather than
letting each model score whichever rows it happens to cover -- which silently
compares models on different fixture sets -- the eligible set is the
intersection where *every* instrument can predict, and all of them are scored
on exactly those rows. The excluded count is reported, not absorbed.

**No ΔBrier gate.** §19 forbids a hard-coded universal threshold. This script
reports paired confidence intervals and never asserts a pass/fail threshold.

Usage
-----
    .venv/Scripts/python.exe backend/scripts/evaluate_structural_baselines.py
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

from _incremental_value_harness import (  # noqa: E402
    devig,
    mean_rps,
    paired_rps_diff_bootstrap,
)

REPO_ROOT = _SCRIPTS.parents[1]
CACHE = REPO_ROOT / "backend" / "data" / "cache"
OUT_JSON = REPO_ROOT / "reports" / "research" / "structural-baselines-report.json"

TRAIN_SEASONS = [2223, 2324]
TEST_SEASON = 2425
LEAGUES = ["EPL", "LA_LIGA", "SERIE_A", "BUNDESLIGA", "LIGUE_1"]

# Outcome encoding used across this repo: 0 = home win, 1 = draw, 2 = away win.
HOME, DRAW, AWAY = 0, 1, 2

ODDS_COLS = ("bet365_home", "bet365_draw", "bet365_away")
REQUIRED_COLS = (
    "date",
    "season",
    "league",
    "home_team",
    "away_team",
    "home_goals",
    "away_goals",
    *ODDS_COLS,
)


def _load_canonical_league_id() -> Any:
    """Borrow production's league normalizer without importing the app.

    ⚠️ TWO LEAGUE VOCABULARIES. The corpus `league` column carries
    ``Bundesliga`` / ``La_Liga`` / ``Ligue_1`` / ``Serie_A`` / ``EPL``; the rest
    of this repo speaks canonical ``BUNDESLIGA`` / ``LA_LIGA`` / ... A string
    comparison between the two silently keeps **only EPL**, because EPL is the
    one league spelled identically in both. That is exactly what the first run
    of this script did -- five leagues in, one league scored, and the tell was
    `frequency` and `league_frequency` returning byte-identical numbers, which
    can only happen when there is a single league. CLAUDE.md records five prior
    instances of this same trap. Normalize, never compare.

    ⚠️ ``spec_from_file_location`` alone is not enough here: `league_policy`
    uses dataclasses, and dataclasses resolves types via
    ``sys.modules[cls.__module__]``, so the module must be registered *before*
    ``exec_module`` or it raises ``AttributeError: 'NoneType' object has no
    attribute '__dict__'``. Loading it standalone (rather than importing
    ``src.core``) avoids `core/database.py` opening a connection at import time
    (docs/DEBT.md item 7).
    """
    import importlib.util

    path = REPO_ROOT / "backend" / "src" / "core" / "league_policy.py"
    spec = importlib.util.spec_from_file_location("_sb_league_policy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_sb_league_policy"] = module
    spec.loader.exec_module(module)
    return module.canonical_league_id


def load_corpus() -> pl.DataFrame:
    """Load the normalized corpus files. Polars per §35's memory policy.

    Six of the 36 cache files (all season 2526) are raw football-data.co.uk
    exports with a different schema and no `season`/`league` column. They are
    outside this study's window and are skipped explicitly rather than being
    silently coerced.

    The `league` column is normalized through production's own
    `canonical_league_id` on the way in -- see `_load_canonical_league_id`.
    """
    frames: list[pl.DataFrame] = []
    skipped: list[str] = []
    for path in sorted(glob.glob(str(CACHE / "fd_*.csv"))):
        frame = pl.read_csv(path, infer_schema_length=3000)
        if not set(REQUIRED_COLS).issubset(frame.columns):
            skipped.append(Path(path).name)
            continue
        frames.append(frame.select(REQUIRED_COLS))
    if not frames:
        raise SystemExit("no normalized corpus files found")
    corpus = pl.concat(frames, how="vertical_relaxed")

    canonical_league_id = _load_canonical_league_id()
    raw_vocab = sorted(set(corpus["league"].to_list()))
    corpus = corpus.with_columns(
        pl.col("league")
        .map_elements(
            lambda v: canonical_league_id(v) if v else None, return_dtype=pl.Utf8
        )
        .alias("league")
    )
    canonical_vocab = sorted({v for v in corpus["league"].to_list() if v})
    print(
        f"loaded {corpus.height} rows from {len(frames)} files "
        f"({len(skipped)} skipped for schema: {', '.join(skipped) or 'none'})"
    )
    print(f"league vocabulary normalized: {raw_vocab} -> {canonical_vocab}")
    return corpus


def outcome_of(home_goals: int, away_goals: int) -> int:
    if home_goals > away_goals:
        return HOME
    if home_goals == away_goals:
        return DRAW
    return AWAY


def frequency_baseline(train: pl.DataFrame) -> list[float]:
    """§25 (1) historical frequency: the training base rates, globally."""
    outcomes = [
        outcome_of(h, a)
        for h, a in zip(train["home_goals"], train["away_goals"], strict=True)
    ]
    counts = np.bincount(outcomes, minlength=3).astype(float)
    return (counts / counts.sum()).tolist()


def league_frequency_baselines(train: pl.DataFrame) -> dict[str, list[float]]:
    """§25 (2) league-adjusted frequency: base rates per competition."""
    out: dict[str, list[float]] = {}
    for league in train["league"].unique().to_list():
        sub = train.filter(pl.col("league") == league)
        out[league] = frequency_baseline(sub)
    return out


def fit_dixon_coles(train: pl.DataFrame) -> Any:
    """§25 (6) Dixon-Coles, via penaltyblog (research dependency, §35)."""
    import penaltyblog as pb

    model = pb.models.DixonColesGoalModel(
        train["home_goals"].to_list(),
        train["away_goals"].to_list(),
        train["home_team"].to_list(),
        train["away_team"].to_list(),
    )
    model.fit()
    return model


def dixon_coles_probs(model: Any, home: str, away: str) -> list[float] | None:
    """1X2 probabilities for one fixture, or None if a team is unseen."""
    try:
        grid = model.predict(home, away)
    except Exception:
        return None
    triple = list(grid.home_draw_away)
    total = sum(triple)
    if not np.isfinite(total) or total <= 0:
        return None
    return [p / total for p in triple]


def main() -> int:
    corpus = load_corpus()
    corpus = corpus.filter(pl.col("league").is_in(LEAGUES))

    train = corpus.filter(pl.col("season").is_in(TRAIN_SEASONS))
    test = corpus.filter(pl.col("season") == TEST_SEASON)
    print(
        f"train n={train.height} (seasons {TRAIN_SEASONS})  "
        f"test n={test.height} (season {TEST_SEASON})"
    )

    # ---- cross-study anchor ----------------------------------------------
    # Score the market on the FULL test season with this script's own de-vig
    # and RPS code. Portfolio B independently reported 0.19463 for exactly this
    # slice. Reproducing it proves these instruments are scored by the same
    # arithmetic as every existing study rather than being a fourth
    # incomparable frame -- which is the only thing that makes a "reference
    # instrument" worth anything.
    full_y = np.array(
        [
            outcome_of(h, a)
            for h, a in zip(test["home_goals"], test["away_goals"], strict=True)
        ]
    )
    full_market = np.array(
        [devig(h, d, a) for h, d, a in zip(*(test[c] for c in ODDS_COLS), strict=True)]
    )
    anchor_rps = mean_rps(full_y, full_market)
    anchor = {
        "slice": f"full test season {TEST_SEASON}, all {len(full_y)} fixtures",
        "market_rps_here": anchor_rps,
        "portfolio_b_reported": 0.19463,
        "agrees": abs(anchor_rps - 0.19463) < 5e-5,
    }
    print(
        f"cross-study anchor: market RPS on full test season = {anchor_rps:.5f} "
        f"(Portfolio B reported 0.19463 — "
        f"{'AGREES' if anchor['agrees'] else 'DISAGREES'})"
    )

    print("fitting Dixon-Coles ...")
    dc_model = fit_dixon_coles(train)

    global_freq = frequency_baseline(train)
    league_freq = league_frequency_baselines(train)
    print(
        f"historical frequency (H/D/A): "
        f"{global_freq[0]:.4f} / {global_freq[1]:.4f} / {global_freq[2]:.4f}"
    )

    # ---- build the paired eligible set -----------------------------------
    rows: list[dict[str, Any]] = []
    excluded = {"missing_odds": 0, "dixon_coles_unseen_team": 0, "unknown_league": 0}

    for row in test.iter_rows(named=True):
        odds = [row[c] for c in ODDS_COLS]
        if any(o is None or not np.isfinite(o) or o <= 1.0 for o in odds):
            excluded["missing_odds"] += 1
            continue
        dc = dixon_coles_probs(dc_model, row["home_team"], row["away_team"])
        if dc is None:
            excluded["dixon_coles_unseen_team"] += 1
            continue
        if row["league"] not in league_freq:
            excluded["unknown_league"] += 1
            continue
        rows.append(
            {
                "date": row["date"],
                "league": row["league"],
                "y": outcome_of(row["home_goals"], row["away_goals"]),
                "market": devig(*odds),
                "dixon_coles": dc,
                "frequency": global_freq,
                "league_frequency": league_freq[row["league"]],
            }
        )

    if not rows:
        raise SystemExit("no eligible test fixtures")

    rows.sort(key=lambda r: r["date"])  # temporal order matters for block bootstrap
    y_true = np.array([r["y"] for r in rows])
    instruments = {
        name: np.array([r[name] for r in rows])
        for name in ("market", "dixon_coles", "frequency", "league_frequency")
    }

    print(f"\neligible paired fixtures: {len(rows)} (excluded: {excluded})")

    # ---- score ------------------------------------------------------------
    results: dict[str, Any] = {}
    for name, proba in instruments.items():
        results[name] = {
            "rps": mean_rps(y_true, proba),
            "accuracy": float((proba.argmax(axis=1) == y_true).mean()),
        }

    # Paired CIs against the market, which is the reference every candidate in
    # this repo is ultimately measured against (§6, Rule 6).
    for name, proba in instruments.items():
        if name == "market":
            continue
        paired = paired_rps_diff_bootstrap(y_true, proba, instruments["market"])
        results[name]["vs_market"] = paired

    # Per-league, to expose heterogeneity rather than pool it away (§18).
    per_league: dict[str, Any] = {}
    for league in sorted({r["league"] for r in rows}):
        idx = np.array([i for i, r in enumerate(rows) if r["league"] == league])
        per_league[league] = {
            "n": int(len(idx)),
            **{
                name: {"rps": mean_rps(y_true[idx], proba[idx])}
                for name, proba in instruments.items()
            },
        }

    report = {
        "study": "Directive §25 structural baselines (evaluation-only)",
        "generated_at": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "role": (
            "Reference instruments. NOT production candidates (§25). No feature "
            "contract, model artifact, promotion gate or serving path is touched."
        ),
        "split": {
            "train_seasons": TRAIN_SEASONS,
            "test_season": TEST_SEASON,
            "leagues": LEAGUES,
            "train_n": train.height,
            "test_n_raw": test.height,
            "test_n_eligible_paired": len(rows),
            "excluded": excluded,
            "split_note": (
                "Identical to Portfolio B / E / F and E6, so these instruments "
                "are directly comparable to those studies."
            ),
        },
        "scoring": {
            "primary_metric": "mean RPS (lower is better)",
            "implementation": "backend/scripts/_incremental_value_harness.py",
            "bootstrap": "non-overlapping block bootstrap, paired per fixture",
            "threshold_policy": (
                "No absolute gate. §19 forbids a hard-coded universal ΔBrier or "
                "ΔRPS threshold; only paired CIs are reported."
            ),
        },
        "cross_study_anchor": anchor,
        "pooled": results,
        "per_league": per_league,
        "historical_frequency_rates": {
            "global": {
                "home": global_freq[0],
                "draw": global_freq[1],
                "away": global_freq[2],
            },
            "per_league": league_freq,
        },
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    # ---- print ------------------------------------------------------------
    print("\n" + "=" * 68)
    print(f"{'instrument':<22}{'RPS':>10}{'acc':>9}   vs market (95% CI)")
    print("-" * 68)
    for name in ("market", "dixon_coles", "league_frequency", "frequency"):
        r = results[name]
        vs = r.get("vs_market")
        ci = ""
        if vs:
            lo, hi = vs.get("ci_lower"), vs.get("ci_upper")
            ci = (
                f"   {vs['point_estimate']:+.5f} [{lo:+.5f}, {hi:+.5f}]"
                if lo is not None and hi is not None
                else "   (CI unavailable)"
            )
        print(f"{name:<22}{r['rps']:>10.5f}{r['accuracy']:>9.3f}{ci}")
    print("=" * 68)
    print(f"\nwrote {OUT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
