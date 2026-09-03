#!/usr/bin/env python3
"""Measure ATE of xG-derived candidate features on the REAL Understat corpus.

Why this exists
---------------
``feature_registry.py`` records the reason ``shot_quality_diff`` is a permanent
``PHASE7_FEATURES_ALWAYS_DATA_GAP`` member:

    "proxy ATE unreliable without real StatsBomb shot-map data. Proxy derived
     from xg_avg_5 difference collapses to q75=0 ON SYNTHETIC TRAINING DATA,
     making ATE estimates non-discriminative. Permanent DATA_GAP until real
     StatsBomb event-level shots corpus confirms ATE >= 0.02"

The blocking clause was *synthetic training data*. As of 2026-09-03 a real
Understat corpus exists (``data/processed/v4_sources``, 12,560 matches across 35
league-seasons), so the proxy can be re-measured against real observations for
the first time. This script performs that measurement and prints the result
verbatim.

⚠️ This script MEASURES ONLY. It does not edit the feature registry, does not
remove anything from ``PHASE7_FEATURES_ALWAYS_DATA_GAP``, and does not touch any
gate. Acting on the number is a separate, authorised decision — see
``docs/DEBT.md`` item 56 and APEX section 23.

⚠️ It also does NOT measure ``shot_quality_diff`` itself. That feature is
defined on post-shot xG (PSxG minus xG); Understat publishes xG but not PSxG,
and its match frame carries no shot counts either. What is measurable here is
the xG-derived *proxy family* the registry's own note refers to.

Run
---
    cd backend && PYTHONPATH=. ../.venv-ml/Scripts/python.exe \
        scripts/measure_xg_feature_ate.py
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_PATH = Path(__file__).resolve()
BACKEND_ROOT = SCRIPT_PATH.parents[1]
for _p in (str(BACKEND_ROOT), str(BACKEND_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_causal_selector():
    """Load ``causal_selector`` without importing ``src.models`` as a package.

    ``src/models/__init__.py`` eagerly imports ``core.database`` (sqlalchemy) and
    ``base_model`` (sklearn), dragging in the entire serving + ML stack for a
    module that needs only numpy and pandas. This mirrors the pattern
    ``scripts/verify_active_artifacts.py`` already uses for the same reason, so
    this measurement runs in a lean research venv.

    A synthetic parent package is registered first because
    ``causal_selector.py`` does ``from .feature_registry import ...``; a bare
    ``spec_from_file_location`` cannot resolve a relative import.
    """
    import importlib.util
    import types

    models_dir = BACKEND_ROOT / "src" / "models"
    pkg_name = "_sabi_models_standalone"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(models_dir)]  # type: ignore[attr-defined]
    sys.modules[pkg_name] = pkg

    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.causal_selector", models_dir / "causal_selector.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError("could not load causal_selector.py standalone")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.CausalFeatureSelector


CausalFeatureSelector = _load_causal_selector()

WINDOW = 5
PRACTICAL_ATE = 0.02  # the registry's own threshold


def load_corpus(sources_dir: Path) -> pd.DataFrame:
    """Load every Understat match parquet into one frame, dropping unplayed rows."""
    frames = []
    for path in sorted(glob.glob(str(sources_dir / "understat_matches_*.parquet"))):
        stem = os.path.basename(path)[len("understat_matches_") : -len(".parquet")]
        league, season = stem.rsplit("_", 1)
        frame = pd.read_parquet(path)
        frame["sabi_league"] = league
        frame["sabi_season"] = int(season)
        frames.append(frame)
    if not frames:
        raise SystemExit(f"No Understat parquet found under {sources_dir}")

    corpus = pd.concat(frames, ignore_index=True)

    # ⚠️ Ligue 1 2019/20 carries 101 fixtures France cancelled for COVID, flagged
    # has_data=False with null xG. They are unplayed matches, not missing
    # measurements — drop them. Default-filling would fabricate xG for games that
    # never happened (docs/DEBT.md item 56).
    before = len(corpus)
    corpus = corpus[corpus["home_xg"].notna() & corpus["away_xg"].notna()]
    if "has_data" in corpus.columns:
        corpus = corpus[corpus["has_data"].astype(bool)]
    dropped = before - len(corpus)

    corpus = corpus.sort_values("date", kind="stable").reset_index(drop=True)
    print(f"corpus: {len(corpus)} played matches ({dropped} unplayed rows dropped)")
    return corpus


def build_features(corpus: pd.DataFrame) -> pd.DataFrame:
    """Attach leak-free shift(1) rolling xG/goal features per side.

    Rolling windows are computed WITHIN a (league, season) partition so no
    value ever crosses a season boundary, and shift(1) guarantees the value at
    match M uses only matches strictly before M.
    """
    long = pd.concat(
        [
            pd.DataFrame(
                {
                    "key": corpus.index,
                    "part": corpus["sabi_league"] + "|" + corpus["sabi_season"].astype(str),
                    "team": corpus["home_team"],
                    "side": "home",
                    "xg_for": corpus["home_xg"].astype(float),
                    "xg_against": corpus["away_xg"].astype(float),
                    "goals_for": corpus["home_goals"].astype(float),
                }
            ),
            pd.DataFrame(
                {
                    "key": corpus.index,
                    "part": corpus["sabi_league"] + "|" + corpus["sabi_season"].astype(str),
                    "team": corpus["away_team"],
                    "side": "away",
                    "xg_for": corpus["away_xg"].astype(float),
                    "xg_against": corpus["home_xg"].astype(float),
                    "goals_for": corpus["away_goals"].astype(float),
                }
            ),
        ],
        ignore_index=True,
    ).sort_values("key", kind="stable")

    grouped = long.groupby(["part", "team"], sort=False)
    for src in ("xg_for", "xg_against", "goals_for"):
        long[f"roll_{src}"] = grouped[src].transform(
            lambda s: s.shift(1).rolling(WINDOW, min_periods=3).mean()
        )

    wide = long.pivot_table(
        index="key",
        columns="side",
        values=["roll_xg_for", "roll_xg_against", "roll_goals_for"],
    )
    wide.columns = [f"{side}_{stat}" for stat, side in wide.columns]

    out = corpus.join(wide)

    # Candidate features, all from strictly pre-match information.
    out["xg_differential"] = (out["home_roll_xg_for"] - out["home_roll_xg_against"]) - (
        out["away_roll_xg_for"] - out["away_roll_xg_against"]
    )
    out["finishing_efficiency_gap"] = (
        out["home_roll_goals_for"] - out["home_roll_xg_for"]
    ) - (out["away_roll_goals_for"] - out["away_roll_xg_for"])
    out["xg_attack_diff"] = out["home_roll_xg_for"] - out["away_roll_xg_for"]
    out["xg_defense_diff"] = out["away_roll_xg_against"] - out["home_roll_xg_against"]

    # 0 = home win, 1 = draw, 2 = away win — the CausalFeatureSelector convention.
    out["match_result"] = np.where(
        out["home_goals"] > out["away_goals"], 0,
        np.where(out["home_goals"] == out["away_goals"], 1, 2),
    )
    return out


CANDIDATES = [
    "xg_differential",
    "finishing_efficiency_gap",
    "xg_attack_diff",
    "xg_defense_diff",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources",
        type=Path,
        default=BACKEND_ROOT / "data" / "processed" / "v4_sources",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    corpus = load_corpus(args.sources)
    frame = build_features(corpus)

    # Cold-start rows (fewer than 3 prior matches) have NaN rolling values.
    # Dropped, never imputed: an imputed value would be a fabricated observation
    # feeding a causal estimate whose whole purpose is to detect real signal.
    usable = frame.dropna(subset=CANDIDATES + ["match_result"])
    print(
        f"usable rows: {len(usable)} of {len(frame)} "
        f"({len(frame) - len(usable)} cold-start rows dropped, not imputed)"
    )

    results = CausalFeatureSelector(practical_ate=PRACTICAL_ATE).analyze(
        usable, outcome_col="match_result", feature_cols=CANDIDATES
    )

    print(f"\nATE vs home win (threshold |ATE| >= {PRACTICAL_ATE})")
    print(f"{'feature':<28}{'ate_win':>10}{'ate_draw':>10}{'p':>10}  {'verdict':<18}class")
    payload = []
    for r in sorted(results, key=lambda x: -abs(x.ate_win)):
        verdict = "PASS" if abs(r.ate_win) >= PRACTICAL_ATE else "below threshold"
        print(
            f"{r.name:<28}{r.ate_win:>10.4f}{r.ate_draw:>10.4f}"
            f"{r.p_value:>10.4f}  {verdict:<18}{r.classification}"
        )
        payload.append(
            {
                "feature": r.name,
                "ate_win": r.ate_win,
                "ate_draw": r.ate_draw,
                "ate_ci": list(r.ate_ci),
                "p_value": r.p_value,
                "classification": r.classification,
                "meets_practical_ate": bool(abs(r.ate_win) >= PRACTICAL_ATE),
            }
        )

    print(
        "\nNOTE: shot_quality_diff itself is NOT measured here — it is defined on "
        "post-shot xG, which Understat does not publish. These are the xG-derived "
        "proxies the registry note refers to."
    )
    print("This script changes no gate and no registry entry.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    "corpus_matches": int(len(corpus)),
                    "usable_rows": int(len(usable)),
                    "window": WINDOW,
                    "practical_ate": PRACTICAL_ATE,
                    "results": payload,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
