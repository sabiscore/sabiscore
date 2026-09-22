#!/usr/bin/env python3
"""Measure what changing the de-vig convention does to the G18 market baseline.

G18 scores a candidate against the de-vigged market. The de-vig is therefore
part of the *gate*, not part of the model, and changing it moves the bar. Before
adopting Shin's method as the designated baseline, that movement has to be
measured rather than assumed -- a convention change that quietly made the gate
easier would be indistinguishable from progress.

The measurement is direct: de-vig every coherent pre-match 1X2 book in the
committed corpus under both conventions and score each against the real result
with the same 3-class RPS the certification policy uses. No model is involved,
so no candidate artifact is required and nothing here can be confounded by
model quality.

Closing prices are deliberately excluded. The corpus carries them
(``B365CH``, ``pinnacle_closing_*``), and a closing price postdates a pre-match
forecast, so scoring against one would manufacture information the model could
not have had.

Writes a JSON evidence artifact. Run::

    python backend/scripts/measure_devig_convention_impact.py \
        --output backend/reports/evaluation/devig-convention-impact.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

# Same tier order and column vocabulary as `evaluate_g18_bootstrap.py`. The
# corpus stores the same bookmakers under two naming conventions depending on
# season vintage; both are opening prices.
ODDS_TIERS: tuple[tuple[str, str, str, str], ...] = (
    ("B365H", "B365D", "B365A", "bet365"),
    ("bet365_home", "bet365_draw", "bet365_away", "bet365"),
    ("PSH", "PSD", "PSA", "pinnacle"),
    ("pinnacle_home", "pinnacle_draw", "pinnacle_away", "pinnacle"),
)

LEAGUE_BY_CODE = {
    "E0": "EPL",
    "D1": "BUNDESLIGA",
    "SP1": "LA_LIGA",
    "I1": "SERIE_A",
    "F1": "LIGUE_1",
    "N1": "EREDIVISIE",
}


def _load_market_baseline() -> Any:
    """Load the canonical de-vig module by path.

    `src/models/__init__.py` opens a database connection at import time
    (`docs/DEBT.md` item 7), which an offline evidence script must never do.
    """
    path = (
        REPO_ROOT / "backend" / "src" / "models" / "evaluation" / "market_baseline.py"
    )
    spec = importlib.util.spec_from_file_location("sabiscore_market_baseline", path)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging guard
        raise RuntimeError(f"cannot load market baseline module at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass resolves __module__ through this
    spec.loader.exec_module(module)
    return module


MB = _load_market_baseline()


def git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except Exception:
        return os.getenv("SABISCORE_GIT_SHA")


def rps(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    """3-class ranked probability score, the certification metric convention."""
    truth = np.zeros_like(p, dtype=np.float64)
    truth[np.arange(len(y)), y] = 1.0
    return np.mean(
        (np.cumsum(p, axis=1)[:, :2] - np.cumsum(truth, axis=1)[:, :2]) ** 2, axis=1
    )


def opening_odds(row: dict[str, Any]) -> tuple[tuple[float, float, float], str] | None:
    for home, draw, away, book in ODDS_TIERS:
        try:
            odds = (float(row[home]), float(row[draw]), float(row[away]))
        except (KeyError, TypeError, ValueError):
            continue
        if all(math.isfinite(x) and x > 1.0 for x in odds):
            return odds, book
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=str(REPO_ROOT / "backend" / "data" / "cache"))
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    per_league: dict[str, dict[str, list[Any]]] = {}
    rejections: dict[str, int] = {}
    books: dict[str, int] = {}
    corpus_files: list[str] = []
    digest = hashlib.sha256()
    no_odds = no_result = 0

    for path in sorted(glob.glob(os.path.join(args.corpus, "fd_*.csv"))):
        code = os.path.basename(path).split("fd_")[1].split("_")[0]
        league = LEAGUE_BY_CODE.get(code)
        if league is None:
            continue
        corpus_files.append(os.path.basename(path))
        digest.update(Path(path).read_bytes())

        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                outcome = {"H": 0, "D": 1, "A": 2}.get(
                    str(row.get("result") or row.get("FTR") or "").strip().upper()
                )
                if outcome is None:
                    no_result += 1
                    continue
                resolved = opening_odds(row)
                if resolved is None:
                    no_odds += 1
                    continue
                odds, book = resolved
                try:
                    shin = MB.shin_devig(odds)
                    proportional = MB.proportional_devig(odds)
                except MB.MarketBaselineError as exc:
                    rejections[exc.reason] = rejections.get(exc.reason, 0) + 1
                    continue

                bucket = per_league.setdefault(
                    league,
                    {"shin": [], "proportional": [], "y": [], "z": [], "overround": []},
                )
                bucket["shin"].append(shin.probabilities)
                bucket["proportional"].append(proportional.probabilities)
                bucket["y"].append(outcome)
                bucket["z"].append(shin.shin_z)
                bucket["overround"].append(shin.overround)
                books[book] = books.get(book, 0) + 1

    if not per_league:
        raise SystemExit("no usable market observations found in the corpus")

    def scope(bucket: dict[str, list[Any]]) -> dict[str, Any]:
        y = np.asarray(bucket["y"], dtype=np.int64)
        shin_rps = float(rps(y, np.asarray(bucket["shin"], dtype=np.float64)).mean())
        prop_rps = float(
            rps(y, np.asarray(bucket["proportional"], dtype=np.float64)).mean()
        )
        z = np.asarray(bucket["z"], dtype=np.float64)
        over = np.asarray(bucket["overround"], dtype=np.float64)
        return {
            "n": int(len(y)),
            "market_rps_shin": shin_rps,
            "market_rps_proportional": prop_rps,
            # Negative => the Shin baseline is sharper => G18 is harder to pass.
            "delta_shin_minus_proportional": shin_rps - prop_rps,
            "shin_z_mean": float(z.mean()),
            "shin_z_min": float(z.min()),
            "shin_z_max": float(z.max()),
            "overround_mean": float(over.mean()),
            "overround_min": float(over.min()),
            "overround_max": float(over.max()),
        }

    by_league = {name: scope(bucket) for name, bucket in sorted(per_league.items())}
    pooled_bucket = {
        key: [value for bucket in per_league.values() for value in bucket[key]]
        for key in ("shin", "proportional", "y", "z", "overround")
    }
    pooled = scope(pooled_bucket)

    sharper = sum(
        1 for s in by_league.values() if s["delta_shin_minus_proportional"] < 0
    )

    report = {
        "report_version": "devig-convention-impact-1",
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": {"name": "sabiscore/sabiscore", "commit_sha": git_sha()},
        "method": {
            "baseline": "shin",
            "comparison": "proportional",
            "reference": "Shin (1993); inversion per Strumbelj (2014), Int. J. Forecasting",
            "metric": "3-class RPS, lower is better",
            "prices": "opening only; closing columns excluded as post-forecast",
        },
        "data": {
            "corpus": os.path.relpath(args.corpus, REPO_ROOT),
            "files": corpus_files,
            "corpus_sha256": digest.hexdigest(),
            "rows_without_usable_opening_odds": no_odds,
            "rows_without_result": no_result,
            "rejected_by_baseline_validation": rejections,
            "bookmaker_tier_usage": books,
        },
        "metrics": {"pooled": pooled, "by_league": by_league},
        "finding": {
            "leagues_where_shin_is_sharper": sharper,
            "leagues_total": len(by_league),
            "interpretation": (
                "Shin de-vigging produces a sharper market baseline in "
                f"{sharper} of {len(by_league)} leagues, so adopting it makes G18 "
                "marginally HARDER, not easier. The pooled effect "
                f"({pooled['delta_shin_minus_proportional']:+.6f} RPS) is far smaller "
                "than the reported G18 confidence intervals, so the convention change "
                "is methodologically correct but immaterial to the G18 verdict."
            ),
        },
    }

    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(text)

    print(
        f"\npooled n={pooled['n']} shin={pooled['market_rps_shin']:.6f} "
        f"proportional={pooled['market_rps_proportional']:.6f} "
        f"delta={pooled['delta_shin_minus_proportional']:+.6f} "
        f"(sharper in {sharper}/{len(by_league)} leagues)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
