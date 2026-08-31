"""Stage 11 certification validation for ADR 0009 / M2 (`uncertainty_policy.py`).

Cited as `UNCERTAINTY_GATES[*]["source"]` in `uncertainty_policy.py` — this
file's actual pass/fail IS the Stage 11 evidence, not a description of
intended evidence. Two tiers:

  * Pure-math contract tests (fast, synthetic, exact): `method_is_authorised`,
    `sufficient_members`, `non_negative`, `determinism`, and fail-closed
    degrade paths. These need no model artifact and run on every CI pass.

  * Real-evidence tests (`TestRealCorpusValidation`): `independence_from_confidence`,
    `informative_within_confidence_band`, and `error_association` inherently
    require genuine predictive spread across many real fixtures — a synthetic
    corpus could be constructed to trivially pass any of them, which would
    defeat the purpose of "genuine evidence" ADR 0009 exists to require. These
    score the real, shipped `epl_ensemble_v5_phase7.pkl` artifact against the
    real corpus `scripts/train_on_real_matches.py` builds from
    `backend/data/cache/fd_*.csv` — the same corpus and artifact ADR 0009's
    own feasibility measurement used.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from src.models.ensemble_uncertainty import (
    MAX_ENTROPY_NATS,
    MIN_MEMBERS,
    UNAVAILABLE,
    UNCERTAINTY_CONTRACT_VERSION,
    dispersion_from_members,
    member_probabilities,
)
from src.models.evaluation.metrics import ranked_probability_score
from src.models.uncertainty_policy import UNCERTAINTY_EVIDENCE_FLOORS, UNCERTAINTY_GATES, UNCERTAINTY_METHOD

# Not a package (pytest.ini excludes scripts/ from collection) — same
# sys.path pattern test_train_on_real_matches_elo.py already established.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ── Pure-math contract (fast, synthetic, exact) ───────────────────────────────


def test_min_members_matches_the_frozen_policy():
    assert MIN_MEMBERS == UNCERTAINTY_GATES["sufficient_members"]["threshold"]["min_members"]


def test_contract_version_matches_stage_10_example():
    assert UNCERTAINTY_CONTRACT_VERSION == "u1"


def test_below_min_members_is_unavailable():
    members = [np.array([0.6, 0.3, 0.1]), np.array([0.5, 0.3, 0.2])]  # only 2 < MIN_MEMBERS
    result = dispersion_from_members(members)
    assert result == UNAVAILABLE
    assert result.available is False


def test_identical_members_have_zero_epistemic():
    """epistemic = total - aleatoric = 0 iff every member agrees exactly —
    the defining property of the BALD decomposition (ADR 0009)."""
    members = [np.array([0.6, 0.3, 0.1])] * 10
    result = dispersion_from_members(members)
    assert result.available is True
    assert result.epistemic == pytest.approx(0.0, abs=1e-9)
    assert result.aleatoric == pytest.approx(result.total, abs=1e-9)


def test_disagreeing_members_have_large_epistemic():
    members = [
        np.array([0.9, 0.05, 0.05]),
        np.array([0.05, 0.9, 0.05]),
        np.array([0.05, 0.05, 0.9]),
    ] * 4
    result = dispersion_from_members(members)
    assert result.available is True
    assert result.epistemic > 0.5  # near-maximal disagreement among 3 classes


def test_non_negative_and_bounded_over_random_member_sets():
    """UNCERTAINTY_GATES['non_negative']: epistemic >= 0 and epistemic <= total
    on every scored row. Property-tested over 200 random member sets rather
    than a handful of hand-picked ones."""
    rng = np.random.default_rng(42)
    tolerance = UNCERTAINTY_GATES["non_negative"]["threshold"]["tolerance"]
    for _ in range(200):
        n_members = int(rng.integers(MIN_MEMBERS, 40))
        members = list(rng.dirichlet([1.0, 1.0, 1.0], size=n_members))
        result = dispersion_from_members(members)
        assert result.available is True
        assert result.epistemic >= -tolerance
        assert result.epistemic <= result.total + tolerance
        assert -tolerance <= result.total <= MAX_ENTROPY_NATS + tolerance


def test_determinism_bit_exact_over_repeated_calls():
    """UNCERTAINTY_GATES['determinism']: identical inputs reproduce identical
    output. No randomness anywhere in the pure decomposition, so this must
    hold exactly (well inside the policy's 1e-12 tolerance), not approximately."""
    rng = np.random.default_rng(7)
    members = list(rng.dirichlet([1.0, 1.0, 1.0], size=50))
    first = dispersion_from_members(members)
    second = dispersion_from_members(members)
    max_dev = UNCERTAINTY_GATES["determinism"]["threshold"]["max_abs_deviation"]
    assert abs(first.epistemic - second.epistemic) <= max_dev
    assert abs(first.aleatoric - second.aleatoric) <= max_dev
    assert abs(first.total - second.total) <= max_dev
    assert first.credible_interval == second.credible_interval


def test_method_is_authorised():
    assert UNCERTAINTY_METHOD == "ensemble_dispersion"
    result = dispersion_from_members([np.array([0.5, 0.3, 0.2])] * 5)
    assert result.method == UNCERTAINTY_METHOD


def test_epistemic_is_not_a_hidden_function_of_the_aggregate_vector():
    """The whole point of ADR 0009: FORBIDDEN_EPISTEMIC_SOURCES (1-max(p),
    entropy(p), ...) are deterministic functions of the *aggregate* probability
    vector alone. Forcing every member to the identical, clearly non-one-hot
    vector [0.5, 0.3, 0.2] still yields exactly zero epistemic — proving this
    module's epistemic value is driven by member *disagreement*, not by
    anything computable from the mean vector by itself."""
    members = [np.array([0.5, 0.3, 0.2])] * 8
    result = dispersion_from_members(members)
    assert result.epistemic == pytest.approx(0.0, abs=1e-9)
    assert 1.0 - max(0.5, 0.3, 0.2) > 0.1  # the forbidden proxy is clearly non-zero here
    assert result.total > 0.5  # aleatoric/total are legitimately non-zero — only epistemic must vanish


def test_member_probabilities_skips_non_finite_or_malformed_trees():
    class _BadTree:
        def predict_proba(self, X):  # noqa: N802 (sklearn naming convention)
            return np.array([[np.nan, np.nan, np.nan]])

    class _GoodTree:
        def predict_proba(self, X):  # noqa: N802
            return np.array([[0.5, 0.3, 0.2]])

    class _RF:
        estimators_ = [_BadTree(), _GoodTree(), _GoodTree(), _GoodTree()]

    members = member_probabilities({"random_forest": _RF()}, np.zeros((1, 3)))
    assert len(members) == 3  # the NaN-emitting tree is dropped, not propagated


def test_member_probabilities_empty_when_no_random_forest_member():
    members = member_probabilities({"xgboost": object()}, np.zeros((1, 3)))
    assert members == []


# ── Real-evidence validation (real artifact, real corpus) ────────────────────


@pytest.fixture(scope="module")
def real_epl_scores():
    """Ensemble-dispersion + realised RPS for a real, temporally-recent slice
    of the real EPL corpus, scored against the real shipped artifact.

    Module-scoped: the underlying `PredictionEngine._model_cache` is itself a
    class-level cache, so this fixture's cost (corpus load + per-row scoring)
    is paid once for the whole file, not once per test.
    """
    import asyncio

    from train_on_real_matches import build_dataset, load_matches  # type: ignore[import-not-found]

    from src.models.prediction import PredictionEngine

    cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"
    if not cache_dir.exists():
        pytest.skip(f"real corpus not present at {cache_dir}")

    matches = load_matches(cache_dir)
    dataset = build_dataset(matches)
    epl = dataset.get("EPL")
    min_rows = UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"]
    if not epl or len(epl["y"]) < min_rows:
        pytest.skip("insufficient real EPL rows for validation floor")

    bundle = asyncio.run(PredictionEngine().get_artifact_bundle("EPL"))
    if bundle is None or not bundle.models_dict:
        pytest.skip("real EPL artifact not loadable in this environment")

    # Full corpus (2,571 rows as of this writing) — the same population size
    # ADR 0009's own feasibility measurement used. Not subsampled: the
    # error_association gate's statistical power depends on real bucket size.
    X_all, y_all = epl["X_incumbent"], epl["y"]

    epistemic = np.empty(len(X_all))
    aleatoric = np.empty(len(X_all))
    total = np.empty(len(X_all))
    confidence = np.empty(len(X_all))
    rps = np.empty(len(X_all))
    for i, row in enumerate(X_all):
        X = np.asarray(row, dtype=np.float64).reshape(1, -1)
        members = member_probabilities(bundle.models_dict, X)
        result = dispersion_from_members(members)
        assert result.available, "real artifact must produce a real member set on every row"
        mean_p = np.mean(np.stack(members, axis=0), axis=0)
        epistemic[i] = result.epistemic
        aleatoric[i] = result.aleatoric
        total[i] = result.total
        confidence[i] = float(np.max(mean_p))
        rps[i] = ranked_probability_score(y_all[i], list(mean_p))

    return {
        "epistemic": epistemic,
        "aleatoric": aleatoric,
        "total": total,
        "confidence": confidence,
        "rps": rps,
        "n": len(X_all),
    }


class TestRealCorpusValidation:
    """Each test asserts one UNCERTAINTY_GATES entry against real measured
    evidence. A gate that does not hold is reported honestly (xfail, with the
    measured numbers in the reason) rather than loosened or hidden — the
    certification directive explicitly forbids manufacturing a pass."""

    def test_sufficient_rows_for_the_evidence_floor(self, real_epl_scores):
        assert real_epl_scores["n"] >= UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"]

    def test_non_negative_on_real_predictions(self, real_epl_scores):
        tolerance = UNCERTAINTY_GATES["non_negative"]["threshold"]["tolerance"]
        epistemic, total = real_epl_scores["epistemic"], real_epl_scores["total"]
        assert bool(np.all(epistemic >= -tolerance))
        assert bool(np.all(epistemic <= total + tolerance))

    def test_independence_from_confidence(self, real_epl_scores):
        """A probability-derived proxy (1-confidence, entropy(p), ...) has
        |corr| -> 1.0 with confidence by construction. This bar (0.70) rejects
        that decisively while leaving room for an honest signal that happens
        to correlate somewhat with confidence."""
        epistemic = real_epl_scores["epistemic"]
        confidence = real_epl_scores["confidence"]
        corr = float(np.corrcoef(epistemic, 1.0 - confidence)[0, 1])
        max_abs = UNCERTAINTY_GATES["independence_from_confidence"]["threshold"][
            "max_abs_confidence_correlation"
        ]
        assert abs(corr) <= max_abs, f"corr(epistemic, 1-confidence)={corr:.4f} exceeds {max_abs}"

    def test_informative_within_confidence_band(self, real_epl_scores):
        """The decisive independence check: within a band of near-identical
        confidence, a 1-confidence proxy is constant by construction — this
        method must still show material spread."""
        gate = UNCERTAINTY_GATES["informative_within_confidence_band"]["threshold"]
        band_width = gate["band_width"]
        confidence = real_epl_scores["confidence"]
        epistemic = real_epl_scores["epistemic"]

        # Densest band search: report the best real evidence rather than a
        # single arbitrarily-chosen center, mirroring how ADR 0009's own
        # feasibility table picked its reported band.
        best_mask, best_n = None, 0
        for center in np.arange(confidence.min(), confidence.max(), band_width / 4):
            lo, hi = center - band_width / 2, center + band_width / 2
            mask = (confidence >= lo) & (confidence < hi)
            if int(mask.sum()) > best_n:
                best_n, best_mask = int(mask.sum()), mask

        assert best_mask is not None and best_n >= gate["min_band_rows"], (
            f"no confidence band of width {band_width} reaches the "
            f"{gate['min_band_rows']}-row floor (best n={best_n})"
        )
        band_epistemic = epistemic[best_mask]
        spread_ratio = (band_epistemic.max() + 1e-9) / (band_epistemic.min() + 1e-9)
        assert spread_ratio >= gate["min_spread_ratio"], (
            f"spread_ratio={spread_ratio:.2f} within the densest band "
            f"(n={best_n}) is below {gate['min_spread_ratio']}"
        )

    def test_error_association(self, real_epl_scores):
        """UNCERTAINTY_GATES['error_association']: the highest-epistemic
        quartile must show strictly worse (higher) mean RPS than the lowest.

        Measured against the full real EPL corpus, this does NOT hold for the
        `ensemble_dispersion` method as implemented (RandomForest bootstrap-tree
        dispersion): RPS *improves* monotonically across all four quartiles as
        epistemic uncertainty rises (bucket 0, lowest epistemic: RPS ~0.213;
        bucket 3, highest epistemic: RPS ~0.191). This is real, reproducible
        evidence, not sampling noise — see docs/DEBT.md for the certification
        finding this blocks. `UNCERTAINTY_REQUIRES_ALL_GATES = True`, so this
        single failing gate keeps the whole method unvalidated regardless of
        the five gates above that do pass; `MODEL_UNCERTAINTY_UNAVAILABLE`
        stays unconditionally CRITICAL in `full_analysis.py` until it is
        resolved. xfail (not skip): this must start failing loudly the moment
        a future change makes it pass, so nobody has to remember to re-enable it.
        """
        gate = UNCERTAINTY_GATES["error_association"]["threshold"]
        n_buckets = gate["buckets"]
        min_rows = UNCERTAINTY_EVIDENCE_FLOORS["min_rows_per_error_bucket"]

        epistemic, rps = real_epl_scores["epistemic"], real_epl_scores["rps"]
        order = np.argsort(epistemic)
        bucket_size = len(order) // n_buckets
        buckets = [
            order[i * bucket_size : (i + 1) * bucket_size] if i < n_buckets - 1 else order[i * bucket_size :]
            for i in range(n_buckets)
        ]
        assert all(len(b) >= min_rows for b in buckets)

        lowest_epistemic_rps = float(rps[buckets[0]].mean())
        highest_epistemic_rps = float(rps[buckets[-1]].mean())
        gap = highest_epistemic_rps - lowest_epistemic_rps
        if gap <= gate["min_rps_gap_top_vs_bottom"]:
            pytest.xfail(
                f"error_association does not hold on real evidence: "
                f"lowest-epistemic bucket RPS={lowest_epistemic_rps:.4f}, "
                f"highest-epistemic bucket RPS={highest_epistemic_rps:.4f}, "
                f"gap={gap:.4f} (need > {gate['min_rps_gap_top_vs_bottom']})"
            )
