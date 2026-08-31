"""Brier-score measurement-integrity contract (M0).

WHY THIS EXISTS
    `PredictionResponse.brier_score` was populated by three different services
    using three different formulas, on scales differing by up to 3x:

        prediction.py:681              sum(p*(1-p))/C   -> per-class-MEAN form
        ultra_prediction.py:345        1 - max(p)       -> not a Brier score at all
        ultra_prediction_service.py    1 - sum(p^2)     -> SUM form (correct)

    All three fed the SAME response field. Only one convention can be right, and
    `1 - max(p)` is not one of them (its own comment conceded "actual Brier score
    needs ground truth" while publishing the value anyway).

    Separately, metric-contract.json asserted that `_compute_brier_multiclass`
    and `brier_score_decomposition` "both use MEAN" and therefore agreed. Both
    take a mean, but over different axes, so they differ by exactly the class
    count. These tests pin that relationship so the corrected contract cannot
    silently drift back.

Source-level assertions are used for the "one authority" guard because importing
the service modules requires a live PostgreSQL (core/database.py raises at module
scope), so a request-level test would never run in CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import numpy as np
import pytest

from src.models.calibration import _compute_brier_multiclass
from src.models.evaluation.metrics import brier_score_decomposition, expected_brier_score

BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC = BACKEND_ROOT / "src"


# ── The canonical pre-kickoff quantity ────────────────────────────────────────


def test_expected_brier_is_one_minus_sum_of_squares():
    """E[sum_c (p_c - 1{y=c})^2] collapses to 1 - sum_c p_c^2 when sum(p) == 1."""
    probs = {"home_win": 0.55, "draw": 0.27, "away_win": 0.18}
    expected = 1.0 - sum(p * p for p in probs.values())
    assert expected_brier_score(probs) == pytest.approx(expected)

    # Derived independently by Monte Carlo against the sum-form definition,
    # so the closed form is checked rather than merely restated.
    rng = np.random.default_rng(11)
    values = np.array(list(probs.values()))
    draws = rng.choice(3, size=200_000, p=values)
    onehot = np.zeros((draws.size, 3))
    onehot[np.arange(draws.size), draws] = 1.0
    empirical = float(np.mean(np.sum((values - onehot) ** 2, axis=1)))
    assert expected_brier_score(probs) == pytest.approx(empirical, abs=5e-3)


def test_expected_brier_bounds_for_three_outcomes():
    """Max at a uniform forecast (2/3 for C=3), zero at a point mass."""
    third = 1.0 / 3.0
    assert expected_brier_score([third, third, third]) == pytest.approx(2 / 3)
    assert expected_brier_score([1.0, 0.0, 0.0]) == pytest.approx(0.0)


def test_expected_brier_stays_inside_the_published_field_range():
    """schemas/prediction.py declares brier_score with ge=0, le=2."""
    rng = np.random.default_rng(3)
    for row in rng.dirichlet([1.0, 1.0, 1.0], 500):
        assert 0.0 <= expected_brier_score(list(row)) <= 2.0


@pytest.mark.parametrize(
    "bad",
    [
        {"home_win": 0.5, "draw": 0.2, "away_win": 0.1},   # sums to 0.8
        {"home_win": 1.2, "draw": -0.1, "away_win": -0.1},  # out of [0,1]
        {"home_win": float("nan"), "draw": 0.5, "away_win": 0.5},
        {},
    ],
)
def test_expected_brier_fails_closed_on_invalid_input(bad):
    """A malformed distribution raises rather than publishing a plausible number."""
    with pytest.raises(ValueError):
        expected_brier_score(bad)


# ── The two realized-Brier conventions differ by exactly the class count ───────


def test_sum_and_per_class_mean_conventions_differ_by_class_count():
    """Pins the corrected `brier_convention` note in metric-contract.json.

    The previous note claimed these two agreed. They do not: one means over
    samples of the sum over classes, the other means over classes.
    """
    rng = np.random.default_rng(7)
    y = rng.integers(0, 3, 400)
    proba = rng.dirichlet([2.0, 2.0, 2.0], 400)

    sum_form = _compute_brier_multiclass(y, proba)
    per_class_mean = brier_score_decomposition(y, proba)["mean"]["brier_score"]

    assert sum_form == pytest.approx(per_class_mean * 3, rel=1e-3)
    assert sum_form > per_class_mean  # never silently interchangeable


# ── One authority ─────────────────────────────────────────────────────────────

_SERVICES_THAT_PUBLISH_BRIER = (
    "services/prediction.py",
    "services/ultra_prediction.py",
    "services/ultra_prediction_service.py",
)

# Inline arithmetic that indicates a re-implemented Brier rather than a delegation.
_INLINE_BRIER_PATTERNS = (
    re.compile(r"1\s*-\s*max\("),
    re.compile(r"sum\([^)]*\*\s*\(\s*1(\.0)?\s*-"),          # sum(p * (1 - p) ...)
    re.compile(r"1\.?0?\s*-\s*sum\([^)]*\*\*\s*2"),           # 1 - sum(p ** 2)
)


def _executable_body(path: Path, func_name: str) -> str:
    """Source of `func_name` with its docstring removed.

    Scanning raw text would match the *explanatory* docstrings that document
    which formula each site used to carry — the guard must read code, not prose.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            body = list(node.body)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                body = body[1:]
            return "\n".join(ast.unparse(stmt) for stmt in body)
    raise AssertionError(f"{path.name} has no function named {func_name}")


@pytest.mark.parametrize("relative", _SERVICES_THAT_PUBLISH_BRIER)
def test_services_delegate_brier_to_the_single_authority(relative):
    """No service may re-implement Brier inline; all three share one function."""
    path = SRC / relative
    assert "expected_brier_score" in path.read_text(encoding="utf-8"), (
        f"{relative} must import and delegate to metrics.expected_brier_score()"
    )

    body = _executable_body(path, "_calculate_brier_score")
    assert "expected_brier_score" in body, (
        f"{relative}::_calculate_brier_score must delegate to the shared authority"
    )
    for pattern in _INLINE_BRIER_PATTERNS:
        assert not pattern.search(body), (
            f"{relative} re-implements Brier inline ({pattern.pattern}); "
            "delegate to metrics.expected_brier_score() instead"
        )


# ── The three services must now agree numerically, not just textually ─────────
#
# The source-level guard above proves each site *delegates*; these prove the
# delegation actually executes and that all three return the SAME number. That
# is the defect itself: they previously differed by up to 3x on one shared
# response field. `_calculate_brier_score` never touches `self`, so it is called
# unbound — instantiating these services would require live PostgreSQL/Redis.

_PROBS = {"home_win": 0.55, "draw": 0.27, "away_win": 0.18}
_EXPECTED = 1.0 - (0.55**2 + 0.27**2 + 0.18**2)


def _unbound_brier(module_path: str, class_name: str):
    module = pytest.importorskip(
        module_path,
        reason="optional ML extra unavailable on this interpreter (e.g. catboost on 3.14)",
    )
    return getattr(module, class_name).__dict__["_calculate_brier_score"]


@pytest.mark.parametrize(
    ("module_path", "class_name"),
    [
        ("src.services.prediction", "PredictionService"),
        ("src.services.ultra_prediction", "UltraPredictionService"),
        ("src.services.ultra_prediction_service", "UltraPredictionService"),
    ],
)
def test_each_service_returns_the_canonical_expected_brier(module_path, class_name):
    fn = _unbound_brier(module_path, class_name)
    assert fn(None, _PROBS) == pytest.approx(_EXPECTED)


def test_all_services_agree_with_each_other():
    """The regression that mattered: one field, three scales, up to 3x apart."""
    values = []
    for module_path, class_name in (
        ("src.services.prediction", "PredictionService"),
        ("src.services.ultra_prediction", "UltraPredictionService"),
        ("src.services.ultra_prediction_service", "UltraPredictionService"),
    ):
        try:
            values.append(_unbound_brier(module_path, class_name)(None, _PROBS))
        except pytest.skip.Exception:
            continue

    assert len(values) >= 2, "need at least two importable services to compare"
    assert max(values) - min(values) < 1e-12, f"services disagree: {values}"
    assert values[0] == pytest.approx(expected_brier_score(_PROBS))


def test_metric_contract_records_the_corrected_convention():
    """The contract must not reassert the false equivalence it once carried."""
    import json

    contract = json.loads(
        (BACKEND_ROOT / "reports/evaluation/metric-contract.json").read_text(
            encoding="utf-8"
        )
    )
    convention = contract["brier_convention"]
    assert "per_class_mean_convention" in convention, (
        "contract must document the divide-by-C convention alongside the sum form"
    )
    assert "/ C" in convention["per_class_mean_convention"]["formula"]
    # The note may *cite* the retired claim, but must mark it corrected — a bare
    # reassertion of the equivalence would not contain these markers.
    note = convention.get("note", "")
    assert "CORRECTED" in note and "FALSE" in note, (
        "brier_convention.note must record that the previous equivalence claim "
        "was false, not silently reassert it"
    )
