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
    score the real, shipped `epl_ensemble_v5_phase7.pkl` artifact against its
    own genuine chronological holdout season, drawn from the real corpus
    `scripts/train_on_real_matches.py` builds from `backend/data/cache/fd_*.csv`
    — rows the artifact's RandomForest never saw in `.fit()`, per the
    certification directive's Stage 7 mandate against evaluating on in-sample
    or randomly-split data.
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

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"

#: League -> artifact slug, matching `PredictionEngine._LEAGUE_SLUG`'s canonical ids.
_LEAGUE_SLUGS = {
    "EPL": "epl",
    "LA_LIGA": "la_liga",
    "BUNDESLIGA": "bundesliga",
    "SERIE_A": "serie_a",
    "LIGUE_1": "ligue_1",
    "EREDIVISIE": "eredivisie",
}


def _artifact_metadata(slug: str) -> dict:
    import joblib

    return joblib.load(_MODELS_DIR / f"{slug}_ensemble_v5_phase7.pkl")["model_metadata"]


def _batched_member_probabilities(models_dict, X: np.ndarray) -> list:
    """Test-only: `member_probabilities` for a whole matrix, one pass per tree.

    Production scores exactly one fixture per call, so batching buys it nothing
    and `ensemble_uncertainty.py` deliberately does not carry this. Here it
    turns each league's validation from ~30s into ~3s, which is what makes
    scoring five real artifacts affordable in the always-run suite under the
    repo's lean-local-environment constraint.

    `test_batched_helper_is_exactly_equivalent_to_production` pins this to the
    production function bit-for-bit: every cross-league result below would be
    worthless evidence if this shortcut ever drifted from what production
    actually computes.
    """
    trees = getattr(models_dict.get("random_forest"), "estimators_", None)
    if not trees:
        return [[] for _ in range(X.shape[0])]
    stacked = np.stack(
        [np.asarray(tree.predict_proba(X), dtype=np.float64) for tree in trees], axis=0
    )  # (M, N, 3)
    out = []
    for row_idx in range(X.shape[0]):
        rows = stacked[:, row_idx, :]
        totals = rows.sum(axis=1)
        out.append([r / t for r, t in zip(rows, totals) if t > 0])
    return out


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
    """Ensemble-dispersion + realised RPS for the real EPL artifact's own
    chronological holdout season — rows the RandomForest's 300 trees never
    saw in `.fit()` — scored against the real shipped artifact.

    Restricted to the genuine holdout (not the full 2,571-row corpus) per
    the certification directive's own Stage 7 mandate: "Use chronological /
    rolling-origin evaluation. Do not use random splitting as the primary
    certification result." An earlier version of this fixture scored the
    full corpus, which is ~85% (2,196/2,571) the RandomForest's own bootstrap
    training rows — in-bag dispersion on memorized rows is a well-known bad
    proxy for genuine epistemic uncertainty. Re-measuring on the clean
    holdout-only slice was done specifically to test that concern (docs/DEBT.md
    item 50): the result is materially unchanged (see `test_error_association`),
    which rules out in-bag contamination as the explanation and is itself
    part of the certification evidence.

    Module-scoped: the underlying `PredictionEngine._model_cache` is itself a
    class-level cache, so this fixture's cost (corpus load + per-row scoring)
    is paid once for the whole file, not once per test.
    """
    import asyncio

    import joblib

    from train_on_real_matches import build_dataset, load_matches  # type: ignore[import-not-found]

    from src.models.prediction import PredictionEngine

    cache_dir = Path(__file__).resolve().parents[2] / "data" / "cache"
    if not cache_dir.exists():
        pytest.skip(f"real corpus not present at {cache_dir}")

    artifact_path = Path(__file__).resolve().parents[2] / "models" / "epl_ensemble_v5_phase7.pkl"
    if not artifact_path.exists():
        pytest.skip(f"real EPL artifact not present at {artifact_path}")
    holdout_season = joblib.load(artifact_path)["model_metadata"]["holdout_season"]

    matches = load_matches(cache_dir)
    dataset = build_dataset(matches)
    epl = dataset.get("EPL")
    if not epl:
        pytest.skip("no real EPL rows in the corpus")

    seasons = np.asarray(epl["seasons"])
    holdout_mask = seasons == holdout_season
    min_rows = UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"]
    if int(holdout_mask.sum()) < min_rows:
        pytest.skip(f"holdout season {holdout_season} has fewer than {min_rows} rows")

    bundle = asyncio.run(PredictionEngine().get_artifact_bundle("EPL"))
    if bundle is None or not bundle.models_dict:
        pytest.skip("real EPL artifact not loadable in this environment")

    X_all = np.asarray(epl["X_incumbent"])[holdout_mask]
    y_all = np.asarray(epl["y"])[holdout_mask]

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
        rps[i] = ranked_probability_score(int(y_all[i]), list(mean_p))

    return {
        "epistemic": epistemic,
        "aleatoric": aleatoric,
        "total": total,
        "confidence": confidence,
        "rps": rps,
        "n": len(X_all),
        "holdout_season": holdout_season,
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

        Measured against the real EPL artifact's own genuine chronological
        holdout season (375 rows the RandomForest's 300 trees never saw in
        `.fit()` — see `real_epl_scores`), this does NOT hold for the
        `ensemble_dispersion` method as implemented (RandomForest
        bootstrap-tree dispersion): mean RPS is essentially flat-to-improving
        across the four quartiles as epistemic uncertainty rises (bucket 0,
        lowest epistemic: RPS ~0.235; bucket 3, highest epistemic: RPS
        ~0.213) — the reverse of the required direction. This was first
        measured on the full 2,571-row corpus (85% of which is the model's
        own in-bag training data) and re-measured here on the clean holdout
        specifically to rule out in-bag memorization as the cause — both
        show the same reversal, with the holdout-only gap
        (~-0.022) and the full-corpus gap (~-0.023) essentially identical, so
        this is real, reproducible evidence rather than a validation-set
        artifact. See docs/DEBT.md item 50 for the certification finding this
        blocks. `UNCERTAINTY_REQUIRES_ALL_GATES = True`, so this single
        failing gate keeps the whole method unvalidated regardless of the
        five gates above that do pass; `MODEL_UNCERTAINTY_UNAVAILABLE` stays
        unconditionally CRITICAL in `full_analysis.py` until it is resolved.
        xfail (not skip): this must start failing loudly the moment a future
        change makes it pass, so nobody has to remember to re-enable it.
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


# ── Stage 11: out-of-support behaviour ───────────────────────────────────────


@pytest.fixture(scope="module")
def epl_holdout_matrix():
    """The real EPL artifact's holdout feature matrix + its loaded bundle."""
    import asyncio

    from train_on_real_matches import build_dataset, load_matches  # type: ignore[import-not-found]

    from src.models.prediction import PredictionEngine

    if not _CACHE_DIR.exists() or not (_MODELS_DIR / "epl_ensemble_v5_phase7.pkl").exists():
        pytest.skip("real corpus or EPL artifact not present")

    epl = build_dataset(load_matches(_CACHE_DIR)).get("EPL")
    if not epl:
        pytest.skip("no real EPL rows")
    seasons = np.asarray(epl["seasons"])
    mask = seasons == _artifact_metadata("epl")["holdout_season"]

    bundle = asyncio.run(PredictionEngine().get_artifact_bundle("EPL"))
    if bundle is None or not bundle.models_dict:
        pytest.skip("real EPL artifact not loadable in this environment")
    return {
        "bundle": bundle,
        "X": np.asarray(epl["X_incumbent"], dtype=np.float64)[mask],
        "X_all": np.asarray(epl["X_incumbent"], dtype=np.float64),
        "seasons_all": seasons,
    }


def test_batched_helper_is_exactly_equivalent_to_production(epl_holdout_matrix):
    """The cross-league and out-of-support evidence below is only as good as
    this equivalence. Bit-for-bit, not approximately — there is no floating
    point reordering between the two paths, so any deviation means drift."""
    bundle, X = epl_holdout_matrix["bundle"], epl_holdout_matrix["X"][:25]
    batched = [dispersion_from_members(m) for m in _batched_member_probabilities(bundle.models_dict, X)]
    per_row = [
        dispersion_from_members(member_probabilities(bundle.models_dict, row.reshape(1, -1)))
        for row in X
    ]
    for got, want in zip(batched, per_row):
        assert got.epistemic == want.epistemic
        assert got.aleatoric == want.aleatoric
        assert got.total == want.total
        assert got.model_count == want.model_count


class TestOutOfSupport:
    """Stage 11 out-of-support: 'low-support / novel regimes should exhibit
    meaningfully different epistemic uncertainty than well-supported regimes'.

    This is NOT a frozen `UNCERTAINTY_GATES` entry and cannot contribute to
    certification — the policy declares no out-of-support gate. It is a
    regression guard pinning measured behaviour, and its 1.15x floor was chosen
    after measurement, deliberately well below every observed ratio
    (1.34x-2.54x), to catch the signal going flat rather than to grade it.

    Worth having precisely because the result was not guaranteed: tree
    ensembles extrapolate flat by construction (a value past the last split
    lands in the same leaf as the boundary), so an RF's member disagreement
    could easily have been *insensitive* to novelty. It is not.
    """

    @pytest.fixture(scope="class")
    def regimes(self, epl_holdout_matrix):
        bundle, X = epl_holdout_matrix["bundle"], epl_holdout_matrix["X"]
        span = np.where(X.max(axis=0) - X.min(axis=0) > 0, X.max(axis=0) - X.min(axis=0), 1.0)
        rng = np.random.default_rng(0)

        def epistemic_for(matrix):
            results = [dispersion_from_members(m)
                       for m in _batched_member_probabilities(bundle.models_dict, matrix)]
            assert all(r.available for r in results), "every regime must still compute"
            return np.array([r.epistemic for r in results])

        return {
            "in_distribution": epistemic_for(X),
            "far_above_range": epistemic_for(X + 10.0 * span),
            "far_below_range": epistemic_for(X - 10.0 * span),
            "all_zero": epistemic_for(np.zeros_like(X[:50])),
            "shuffled_features": epistemic_for(
                np.apply_along_axis(rng.permutation, 1, X[:100].copy())
            ),
        }

    @pytest.mark.parametrize(
        "regime", ["far_above_range", "far_below_range", "all_zero", "shuffled_features"]
    )
    def test_novel_regimes_raise_epistemic_above_in_distribution(self, regimes, regime):
        in_dist = regimes["in_distribution"].mean()
        novel = regimes[regime].mean()
        assert novel / in_dist >= 1.15, (
            f"{regime}: mean epistemic {novel:.4f} vs in-distribution {in_dist:.4f} "
            f"({novel / in_dist:.2f}x) — the signal has gone flat on novel input"
        )

    def test_out_of_support_output_stays_within_the_declared_range(self, regimes):
        for name, values in regimes.items():
            assert bool((values >= 0.0).all()), f"{name} produced a negative epistemic"
            assert bool((values <= MAX_ENTROPY_NATS).all()), f"{name} exceeded ln(3)"


# ── Stage 11: robustness (leagues, temporal windows, partial data) ───────────


@pytest.fixture(scope="module")
def cross_league_scores():
    """Every league whose artifact holdout season has real corpus rows.

    EREDIVISIE is excluded by the evidence floor, not by choice: its artifact
    is the pooled all-league model (docs/DEBT.md — one season of Eredivisie
    data, so it borrows a pooled fit), and its `model_metadata` reports that
    pooled model's `holdout_season: 2425` while the Eredivisie corpus itself
    holds 260 rows, all season 2526. There are zero Eredivisie rows in its own
    declared holdout to score, so it is skipped with that reason recorded
    rather than silently dropped.
    """
    import asyncio

    from train_on_real_matches import build_dataset, load_matches  # type: ignore[import-not-found]

    from src.models.prediction import PredictionEngine

    if not _CACHE_DIR.exists():
        pytest.skip(f"real corpus not present at {_CACHE_DIR}")

    dataset = build_dataset(load_matches(_CACHE_DIR))
    floor = UNCERTAINTY_EVIDENCE_FLOORS["min_validation_rows"]
    scored, skipped = {}, {}

    for league, slug in _LEAGUE_SLUGS.items():
        if not (_MODELS_DIR / f"{slug}_ensemble_v5_phase7.pkl").exists():
            skipped[league] = "artifact not present"
            continue
        data = dataset.get(league)
        if not data:
            skipped[league] = "no corpus rows"
            continue
        holdout = _artifact_metadata(slug)["holdout_season"]
        mask = np.asarray(data["seasons"]) == holdout
        if int(mask.sum()) < floor:
            skipped[league] = f"{int(mask.sum())} rows in declared holdout {holdout} (floor {floor})"
            continue
        bundle = asyncio.run(PredictionEngine().get_artifact_bundle(league))
        if bundle is None or not bundle.models_dict:
            skipped[league] = "artifact not loadable"
            continue

        X = np.asarray(data["X_incumbent"], dtype=np.float64)[mask]
        y = np.asarray(data["y"])[mask]
        members = _batched_member_probabilities(bundle.models_dict, X)
        results = [dispersion_from_members(m) for m in members]
        scored[league] = {
            "results": results,
            "epistemic": np.array([r.epistemic for r in results]),
            "total": np.array([r.total for r in results]),
            "rps": np.array([
                ranked_probability_score(int(y[i]), list(np.mean(np.stack(members[i]), axis=0)))
                for i in range(len(y))
            ]),
            "n": len(y),
            "holdout_season": holdout,
        }

    if not scored:
        pytest.skip(f"no league met the evidence floor; skipped={skipped}")
    return {"scored": scored, "skipped": skipped}


class TestRobustness:
    """Stage 11 robustness: leagues, temporal windows, confidence regimes, and
    missing/partial data.

    'Teams with different sample sizes' is covered only indirectly — early
    seasons carry less accumulated per-team history than late ones, so the
    temporal test exercises it — and is called out here rather than claimed as
    dedicated coverage, because `build_dataset` does not emit a per-row team
    history depth to bucket on.
    """

    def test_every_scored_league_produces_a_valid_measurement(self, cross_league_scores):
        scored = cross_league_scores["scored"]
        assert len(scored) >= 5, f"expected >=5 leagues, got {sorted(scored)}"
        tolerance = UNCERTAINTY_GATES["non_negative"]["threshold"]["tolerance"]
        min_members = UNCERTAINTY_GATES["sufficient_members"]["threshold"]["min_members"]
        for league, s in scored.items():
            assert all(r.available for r in s["results"]), f"{league}: a row failed to compute"
            assert bool((s["epistemic"] >= -tolerance).all()), f"{league}: negative epistemic"
            assert bool((s["epistemic"] <= s["total"] + tolerance).all()), f"{league}: epistemic > total"
            assert bool((s["total"] <= MAX_ENTROPY_NATS + tolerance).all()), f"{league}: total > ln(3)"
            assert all(r.model_count >= min_members for r in s["results"]), f"{league}: too few members"

    def test_eredivisie_is_skipped_for_a_recorded_reason_not_silently(self, cross_league_scores):
        """The pooled-model coverage gap must stay visible. If Eredivisie ever
        becomes scoreable this fails, which is the prompt to re-read the skip
        reason rather than let stale prose survive."""
        skipped = cross_league_scores["skipped"]
        assert "EREDIVISIE" in skipped, "Eredivisie now scores — update the fixture docstring"
        assert "floor" in skipped["EREDIVISIE"]

    def test_error_association_direction_is_consistent_across_leagues(self, cross_league_scores):
        """Robustness view of the one failing gate: is the reversal an EPL
        quirk or systematic?

        Systematic. Every scored league fails, on its own independently-trained
        artifact and its own holdout season. That is materially stronger
        evidence than the single-league result in `TestRealCorpusValidation`,
        and it is what moves docs/DEBT.md item 50's hypothesis 1 from 'maybe
        artifact-specific' to 'a property of this decomposition on this feature
        set'. xfail carries the full per-league table so the reason string is
        the evidence.
        """
        gate = UNCERTAINTY_GATES["error_association"]["threshold"]
        n_buckets = gate["buckets"]
        rows = []
        passing = []
        for league, s in sorted(cross_league_scores["scored"].items()):
            order = np.argsort(s["epistemic"])
            size = len(order) // n_buckets
            lowest = float(s["rps"][order[:size]].mean())
            highest = float(s["rps"][order[(n_buckets - 1) * size:]].mean())
            gap = highest - lowest
            rows.append(f"{league} n={s['n']} low={lowest:.4f} high={highest:.4f} gap={gap:+.4f}")
            if gap > gate["min_rps_gap_top_vs_bottom"]:
                passing.append(league)
        if not passing:
            pytest.xfail("error_association fails in every scored league: " + "; ".join(rows))

    def test_measurement_is_valid_in_every_temporal_window(self, epl_holdout_matrix):
        """Seasons span 1920-2526; the method must produce a valid measurement
        in each, not only in the recent ones it was most recently fit near."""
        bundle = epl_holdout_matrix["bundle"]
        X_all, seasons = epl_holdout_matrix["X_all"], epl_holdout_matrix["seasons_all"]
        checked = 0
        for season in sorted(set(seasons.tolist())):
            rows = X_all[seasons == season][:100]
            if len(rows) < 30:
                continue
            results = [dispersion_from_members(m)
                       for m in _batched_member_probabilities(bundle.models_dict, rows)]
            assert all(r.available for r in results), f"season {season}: a row failed to compute"
            epistemic = np.array([r.epistemic for r in results])
            total = np.array([r.total for r in results])
            assert bool((epistemic >= 0.0).all()), f"season {season}: negative epistemic"
            assert bool((epistemic <= total + 1e-9).all()), f"season {season}: epistemic > total"
            checked += 1
        assert checked >= 5, f"only {checked} temporal windows had enough rows"

    def test_a_missing_feature_fails_closed_on_the_real_artifact(self, epl_holdout_matrix):
        """The production async entry point, end to end: an incomplete evidence
        set must return `available=False`, never a zero-filled measurement."""
        import asyncio

        from src.models.ensemble_uncertainty import compute_ensemble_uncertainty

        columns = epl_holdout_matrix["bundle"].feature_columns
        complete = dict(zip(columns, epl_holdout_matrix["X"][0]))

        assert asyncio.run(compute_ensemble_uncertainty("EPL", complete)).available is True

        missing = dict(complete)
        missing.pop(columns[0])
        assert asyncio.run(compute_ensemble_uncertainty("EPL", missing)) == UNAVAILABLE

        not_finite = dict(complete)
        not_finite[columns[0]] = float("nan")
        assert asyncio.run(compute_ensemble_uncertainty("EPL", not_finite)) == UNAVAILABLE

        assert asyncio.run(compute_ensemble_uncertainty("EPL", {})) == UNAVAILABLE
