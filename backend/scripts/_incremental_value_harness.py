"""Shared incremental-value evaluation harness for directive Stage 3 studies.

Extracted from `test_player_availability_incremental_value.py` (Portfolio B)
once a second and third consumer appeared (Portfolios E and F). Writing the
same temporal-split / fit / RPS / paired-block-bootstrap pipeline a third
time is exactly the duplication this repository has repeatedly paid for
elsewhere (the three team-name normalizers, the four goals/gd remaps) — one
implementation, three callers.

Answers one question, the same way every time:

    Does adding `candidate_features` to `baseline_features` reduce
    out-of-sample RPS, under a genuine temporal split, by an amount whose
    paired block-bootstrap confidence interval excludes zero?

Deliberately NOT generalized further. It does not choose features, does not
pick the split, and does not decide what the result means — those are the
study's job, and burying them here would make three different research
questions look like one.

Reuses `src/models/evaluation/metrics.py`'s `ranked_probability_score` and
`block_bootstrap_ci` rather than reimplementing either.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.models.evaluation.metrics import (  # noqa: E402
    block_bootstrap_ci,
    expected_calibration_error,
    log_loss_multiclass,
    ranked_probability_score,
)

FeatureFn = Callable[[dict[str, Any]], list[float]]
# A fitter takes (X, y) and returns anything with `.predict_proba` and
# `.classes_`. Defaults to the level-1 logistic model below; a study that
# has already earned an escalation (directive §26) passes its own.
FitFn = Callable[[Any, Any], Any]

# Minimum rows before a slice is scored at all. Below this, a bootstrap CI is
# not meaningfully estimable and reporting one would imply precision the
# sample does not carry (Rule 9).
MIN_SLICE_ROWS = 30


def devig(odds_home: float, odds_draw: float, odds_away: float) -> list[float]:
    """Normalize 1/odds implied probabilities to sum to 1 (remove overround)."""
    raw = np.array([1.0 / odds_home, 1.0 / odds_draw, 1.0 / odds_away])
    return (raw / raw.sum()).tolist()


# The corpus ships in TWO column vocabularies and both are load-bearing:
# seasons up to 2024/25 use `date`/`home_team`/`bet365_home`, while 2025/26
# uses `Date`/`HomeTeam`/`B365H`. A reader that speaks only one silently sees
# an empty season rather than an error — the same two-vocabulary shape this
# repository has already paid for in league ids and team names.
_CORPUS_COLUMNS = (
    ("home", ("HomeTeam", "home_team")),
    ("away", ("AwayTeam", "away_team")),
    ("date", ("Date", "date")),
    ("result", ("FTR", "result")),
    ("odds_home", ("B365H", "bet365_home")),
    ("odds_draw", ("B365D", "bet365_draw")),
    ("odds_away", ("B365A", "bet365_away")),
)

# ranked_probability_score's own ordered 0/1/2 home/draw/away convention.
OUTCOME_CODE = {"H": 0, "D": 1, "A": 2}


def load_fixtures_with_market(path: Path) -> list[dict[str, Any]]:
    """Corpus fixtures carrying a coherent de-vigged Bet365 1X2 price.

    A row with an unparseable date, an unknown result, or any quoted price at
    or below 1.0 is dropped rather than repaired — a price of 1.0 implies a
    certainty no bookmaker offers and is corrupt input, not a long shot.
    """
    import pandas as pd

    if not path.exists():
        return []
    frame = pd.read_csv(path, encoding="utf-8-sig", on_bad_lines="skip")
    resolved: dict[str, str] = {}
    for key, candidates in _CORPUS_COLUMNS:
        match = next((c for c in candidates if c in frame.columns), None)
        if match is None:
            return []
        resolved[key] = match

    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        parsed = pd.to_datetime(row[resolved["date"]], errors="coerce", dayfirst=False)
        result = str(row[resolved["result"]]).strip().upper()
        try:
            odds = tuple(
                float(row[resolved[k]]) for k in ("odds_home", "odds_draw", "odds_away")
            )
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed) or result not in OUTCOME_CODE or min(odds) <= 1.0:
            continue
        rows.append(
            {
                "home_team": str(row[resolved["home"]]).strip(),
                "away_team": str(row[resolved["away"]]).strip(),
                "date": parsed.date(),
                "outcome": OUTCOME_CODE[result],
                "market_probs": devig(*odds),
            }
        )
    return rows


def mean_rps(y_true: np.ndarray, y_proba: np.ndarray) -> float:
    """Mean Ranked Probability Score. Lower is better."""
    return float(
        np.mean(
            [
                ranked_probability_score(int(yt), list(yp))
                for yt, yp in zip(y_true, y_proba)
            ]
        )
    )


def fit_multinomial_logistic(X: np.ndarray, y: np.ndarray) -> Any:
    """Level-1 model on the directive's own escalation ladder (§26).

    Deliberately the simplest defensible classifier: if a candidate signal
    cannot show incremental value here, escalating architecture before the
    information is proven is exactly what Rule 8 forbids.
    """
    from sklearn.linear_model import LogisticRegression

    # `multi_class` was removed in this sklearn version -- the default
    # ('lbfgs', 3+ classes) already fits genuine multinomial (softmax)
    # probabilities; passing the old kwarg raises TypeError here.
    model = LogisticRegression(max_iter=2000)
    model.fit(X, y)
    return model


def paired_rps_diff_bootstrap(
    y_true: np.ndarray,
    proba_candidate: np.ndarray,
    proba_baseline: np.ndarray,
    *,
    ci_level: float = 0.95,
) -> dict[str, Any]:
    """Block-bootstrap CI on the per-fixture RPS difference (candidate - baseline).

    Negative means the candidate is better. Paired per fixture, so the two
    models are compared on identical rows and the comparison is not
    confounded by which fixtures happened to land in a resample.
    """
    per_fixture_diff = np.array(
        [
            ranked_probability_score(int(yt), list(pc))
            - ranked_probability_score(int(yt), list(pb))
            for yt, pc, pb in zip(y_true, proba_candidate, proba_baseline)
        ]
    )
    # block_bootstrap_ci expects (y_true, y_proba, metric_fn); repurpose it to
    # bootstrap a plain 1-D series by passing the diffs as "y_proba" rows of
    # width 1 and a metric_fn that takes the mean -- reuses the existing,
    # already-tested block-resampling machinery (non-overlapping blocks, for
    # the temporal dependence between consecutive fixtures).
    dummy_y_true = np.zeros(len(per_fixture_diff), dtype=int)

    def _mean_metric(_yt: np.ndarray, diffs: np.ndarray) -> float:
        return float(np.mean(diffs))

    return block_bootstrap_ci(
        dummy_y_true,
        per_fixture_diff.reshape(-1, 1),
        _mean_metric,
        block_size=10,
        ci_level=ci_level,
    )


def run_incremental_value_study(
    rows: Sequence[dict[str, Any]],
    *,
    baseline_features: FeatureFn,
    candidate_features: FeatureFn,
    train_seasons: Sequence[int],
    test_season: int,
    outcome_key: str = "outcome",
    season_key: str = "season",
    group_key: str | None = "league",
    raw_reference: FeatureFn | None = None,
    raw_reference_label: str = "rps_raw_reference",
    fit_model: FitFn = fit_multinomial_logistic,
) -> dict[str, Any]:
    """Temporal-split incremental-value test, pooled and per group.

    `raw_reference`, when given, must return a probability triple scored
    directly without any model — the de-vigged market, typically. It is the
    Rule 6 comparison ("the market is mandatory evidence") and is reported
    alongside, never used for fitting.
    """
    train = [r for r in rows if r[season_key] in tuple(train_seasons)]
    test = [r for r in rows if r[season_key] == test_season]
    if len(train) < MIN_SLICE_ROWS or len(test) < MIN_SLICE_ROWS:
        return {
            "error": "insufficient_train_or_test_rows",
            "train_n": len(train),
            "test_n": len(test),
        }

    y_train = np.array([r[outcome_key] for r in train])
    baseline_model = fit_model(np.array([baseline_features(r) for r in train]), y_train)
    candidate_model = fit_model(
        np.array([candidate_features(r) for r in train]), y_train
    )
    # LogisticRegression.classes_ is sorted ascending, which already matches the
    # 0/1/2 home/draw/away encoding ranked_probability_score expects -- asserted
    # rather than assumed, because a silent reordering would corrupt every RPS
    # below while still producing plausible-looking numbers.
    assert list(baseline_model.classes_) == [0, 1, 2]
    assert list(candidate_model.classes_) == [0, 1, 2]

    def _score(slice_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if len(slice_rows) < MIN_SLICE_ROWS:
            return None
        y_true = np.array([r[outcome_key] for r in slice_rows])
        proba_baseline = baseline_model.predict_proba(
            np.array([baseline_features(r) for r in slice_rows])
        )
        proba_candidate = candidate_model.predict_proba(
            np.array([candidate_features(r) for r in slice_rows])
        )
        scored: dict[str, Any] = {
            "n": len(slice_rows),
            "rps_baseline_model": round(mean_rps(y_true, proba_baseline), 5),
            "rps_candidate_model": round(mean_rps(y_true, proba_candidate), 5),
            "candidate_minus_baseline_bootstrap": paired_rps_diff_bootstrap(
                y_true, proba_candidate, proba_baseline
            ),
            # RPS decides; log loss and ECE describe HOW a model is better or
            # worse. A candidate can cut log loss by growing sharper while
            # getting less calibrated, and only the pair shows that.
            "logloss_baseline_model": round(
                log_loss_multiclass(y_true, proba_baseline), 5
            ),
            "logloss_candidate_model": round(
                log_loss_multiclass(y_true, proba_candidate), 5
            ),
            "ece_baseline_model": expected_calibration_error(y_true, proba_baseline)[
                "mean"
            ],
            "ece_candidate_model": expected_calibration_error(y_true, proba_candidate)[
                "mean"
            ],
        }
        if raw_reference is not None:
            reference = np.array([raw_reference(r) for r in slice_rows])
            scored[raw_reference_label] = round(mean_rps(y_true, reference), 5)
            scored["logloss_raw_reference"] = round(
                log_loss_multiclass(y_true, reference), 5
            )
            scored["ece_raw_reference"] = expected_calibration_error(y_true, reference)[
                "mean"
            ]
        return scored

    result: dict[str, Any] = {
        "train_seasons": list(train_seasons),
        "test_season": test_season,
        "train_n": len(train),
        "test_n": len(test),
        "pooled": _score(test),
    }
    if group_key is not None:
        per_group: dict[str, Any] = {}
        for group in sorted({str(r[group_key]) for r in test}):
            group_rows = [r for r in test if str(r[group_key]) == group]
            scored = _score(group_rows)
            per_group[group] = (
                scored
                if scored is not None
                else {"n": len(group_rows), "note": "insufficient_test_sample"}
            )
        result["per_group"] = per_group
    return result
