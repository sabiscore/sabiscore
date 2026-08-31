from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np


def expected_calibration_error(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, float]:
    """Compute multiclass ECE and return per-class plus mean values."""
    if y_proba.ndim != 2:
        raise ValueError("y_proba must be a 2D array shaped (n_samples, n_classes)")
    if len(y_true) != y_proba.shape[0]:
        raise ValueError("y_true length must match y_proba rows")

    n_classes = y_proba.shape[1]
    n = max(len(y_true), 1)
    bins = np.linspace(0.0, 1.0, n_bins + 1)

    ece_per_class: Dict[str, float] = {}
    for cls in range(n_classes):
        binary = (y_true == cls).astype(float)
        probs = y_proba[:, cls]
        ece = 0.0

        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (probs > lo) & (probs <= hi)
            if np.any(mask):
                ece += mask.sum() * abs(binary[mask].mean() - probs[mask].mean())

        ece_per_class[f"class_{cls}"] = round(float(ece / n), 4)

    ece_per_class["mean"] = round(
        float(np.mean([ece_per_class[f"class_{i}"] for i in range(n_classes)])), 4
    )
    return ece_per_class


def expected_brier_score(probabilities: Dict[str, float] | List[float]) -> float:
    """Expected multiclass Brier score under the model's *own* predictive
    distribution, for a fixture whose outcome is not yet known.

    A realized Brier score needs ground truth. Before kickoff there is none, so
    the only defensible quantity is the expectation of the Brier score taken
    over the model's own distribution:

        E[ sum_c (p_c - 1{y=c})^2 ]  =  1 - sum_c p_c^2

    (the algebra collapses because sum_c p_c = 1). This is a *sharpness*
    reading — how concentrated the forecast is — not a calibration measurement,
    and it can never reward or punish the model for being right.

    Convention: SUM over classes, matching ``brier_convention.aggregation`` in
    ``backend/reports/evaluation/metric-contract.json`` and the sum-form used by
    ``calibration._compute_brier_multiclass``. Range [0, 1 - 1/C]; for C=3 the
    maximum is 2/3 at a uniform forecast, and 0 at a point-mass forecast.

    ⚠️ Do NOT compare this against the per-class-mean values reported by
    ``brier_score_decomposition()['mean']``, ``base_model``, ``ensemble`` or
    ``enhanced_training``: those divide by the class count, so they are this
    quantity / C. See the ``brier_convention`` block in the metric contract.
    """
    values = (
        list(probabilities.values())
        if isinstance(probabilities, dict)
        else list(probabilities)
    )
    if not values:
        raise ValueError("probabilities must be non-empty")
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("probabilities must be finite")
    if (arr < 0).any() or (arr > 1).any():
        raise ValueError("probabilities must lie in [0, 1]")
    total = float(arr.sum())
    if abs(total - 1.0) > 1e-4:
        raise ValueError(f"probabilities must sum to 1 (got {total:.6f})")
    return float(max(0.0, 1.0 - float(np.sum(arr**2))))


def ranked_probability_score(y_true_outcome: int, probs: list[float]) -> float:
    """Ranked Probability Score for a 3-outcome match (0=home, 1=draw, 2=away).

    Lower is better. Range [0, 1].
    """
    cumprobs = [sum(probs[: i + 1]) for i in range(3)]
    cumtrue = [1.0 if y_true_outcome <= i else 0.0 for i in range(3)]
    return sum((p - t) ** 2 for p, t in zip(cumprobs, cumtrue)) / 2.0


def brier_score_decomposition(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    n_bins: int = 10,
) -> Dict[str, Any]:
    """Multiclass Brier score with its Murphy (1973) three-term decomposition
    (``brier_score = reliability - resolution + uncertainty``), scored
    one-vs-rest per class and averaged. Same binning convention as
    ``expected_calibration_error`` above, so the two are bin-for-bin
    comparable.

    - ``reliability``: distance between predicted probability and observed
      frequency within each bin. Lower is better; fixable by recalibrating
      on the features the model already has.
    - ``resolution``: how far each bin's observed rate is pulled from the
      overall base rate. Higher is better; low resolution means the model
      is genuinely uninformative and needs new signal, not a calibrator.
    - ``uncertainty``: irreducible variance of the outcome itself
      (``base_rate * (1 - base_rate)``) — a property of the data, not the
      model.

    Every bin's sample count is returned in ``bin_counts`` — this is never
    meant to back a reliability curve without also showing its counts.
    """
    if y_proba.ndim != 2:
        raise ValueError("y_proba must be a 2D array shaped (n_samples, n_classes)")
    if len(y_true) != y_proba.shape[0]:
        raise ValueError("y_true length must match y_proba rows")

    n_classes = y_proba.shape[1]
    n = max(len(y_true), 1)
    bins = np.linspace(0.0, 1.0, n_bins + 1)

    per_class: Dict[str, Dict[str, float]] = {}
    bin_counts: Dict[str, list] = {}

    for cls in range(n_classes):
        binary = (y_true == cls).astype(float)
        probs = y_proba[:, cls]
        base_rate = float(binary.mean()) if n else 0.0

        reliability = 0.0
        resolution = 0.0
        counts_for_class: list = []
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (probs > lo) & (probs <= hi)
            count = int(mask.sum())
            counts_for_class.append(count)
            if count == 0:
                continue
            p_j = float(probs[mask].mean())
            o_j = float(binary[mask].mean())
            reliability += count * (p_j - o_j) ** 2
            resolution += count * (o_j - base_rate) ** 2

        key = f"class_{cls}"
        bin_counts[key] = counts_for_class
        per_class[key] = {
            "brier_score": round(float(np.mean((probs - binary) ** 2)), 4),
            "reliability": round(reliability / n, 4),
            "resolution": round(resolution / n, 4),
            "uncertainty": round(base_rate * (1.0 - base_rate), 4),
        }

    mean = {
        component: round(
            float(np.mean([per_class[f"class_{i}"][component] for i in range(n_classes)])), 4
        )
        for component in ("brier_score", "reliability", "resolution", "uncertainty")
    }

    return {
        "per_class": per_class,
        "mean": mean,
        "bin_counts": bin_counts,
        "n_bins": n_bins,
        "n_samples": n,
    }


def log_loss_multiclass(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    eps: float = 1e-15,
) -> float:
    """Multiclass log loss (negative mean log-likelihood).

    Convention: mean over samples of -log(p_c) where c is the true class.
    Lower is better. Equivalent to sklearn's log_loss with normalise=True.

    Args:
        y_true: Integer class labels [0, 1, 2] shape (n_samples,).
        y_proba: Predicted probabilities shape (n_samples, n_classes).
        eps: Probability clipping floor to avoid log(0).

    Returns:
        Non-negative float. Perfect model → 0.0.
    """
    if y_proba.ndim != 2:
        raise ValueError("y_proba must be 2D shaped (n_samples, n_classes)")
    n = len(y_true)
    if n == 0:
        return 0.0
    clipped = np.clip(y_proba[np.arange(n), y_true.astype(int)], eps, 1.0)
    return float(-np.mean(np.log(clipped)))


def accuracy_and_per_class(
    y_true: np.ndarray,
    y_proba: np.ndarray,
) -> Dict[str, Any]:
    """Overall accuracy plus per-class precision, recall, and F1.

    Argmax prediction is used (hard classification). Does NOT require
    scipy or sklearn — pure numpy implementation.

    Returns a dict with keys:
        accuracy        – float [0, 1]
        per_class       – dict keyed by 'class_0', 'class_1', 'class_2' each with:
                            precision, recall, f1, support (int)
        macro_precision – float
        macro_recall    – float
        macro_f1        – float
        n_samples       – int
    """
    if y_proba.ndim != 2:
        raise ValueError("y_proba must be 2D shaped (n_samples, n_classes)")
    n = len(y_true)
    if n == 0:
        return {"accuracy": 0.0, "per_class": {}, "macro_precision": 0.0,
                "macro_recall": 0.0, "macro_f1": 0.0, "n_samples": 0}

    y_pred = np.argmax(y_proba, axis=1)
    accuracy = float(np.mean(y_pred == y_true))

    n_classes = y_proba.shape[1]
    per_class: Dict[str, Any] = {}
    precisions: List[float] = []
    recalls: List[float] = []
    f1s: List[float] = []

    for cls in range(n_classes):
        tp = int(np.sum((y_pred == cls) & (y_true == cls)))
        fp = int(np.sum((y_pred == cls) & (y_true != cls)))
        fn = int(np.sum((y_pred != cls) & (y_true == cls)))
        support = int(np.sum(y_true == cls))

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if (precision + recall) > 0 else 0.0)

        per_class[f"class_{cls}"] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)

    return {
        "accuracy": round(accuracy, 4),
        "per_class": per_class,
        "macro_precision": round(float(np.mean(precisions)), 4),
        "macro_recall": round(float(np.mean(recalls)), 4),
        "macro_f1": round(float(np.mean(f1s)), 4),
        "n_samples": n,
    }


def block_bootstrap_ci(
    y_true: np.ndarray,
    y_proba: np.ndarray,
    metric_fn: Any,
    *,
    n_bootstrap: int = 1000,
    block_size: int = 10,
    ci_level: float = 0.95,
    rng_seed: int = 42,
) -> Dict[str, Any]:
    """Block-bootstrap confidence interval for a scalar metric function.

    Uses non-overlapping block resampling (Künsch 1989) rather than iid bootstrap
    because consecutive football matches within a season share temporal
    dependence — a block of matches is a more honest resampling unit than a
    single random prediction.

    Args:
        y_true: Integer class labels (n_samples,).
        y_proba: Predicted probability matrix (n_samples, n_classes).
        metric_fn: Callable(y_true, y_proba) → float.
        n_bootstrap: Number of bootstrap replicates.
        block_size: Number of consecutive samples per block.
        ci_level: Confidence level (e.g. 0.95 → 95% CI).
        rng_seed: Random seed for reproducibility.

    Returns:
        Dict with keys: point_estimate, ci_lower, ci_upper, ci_level,
        n_bootstrap, block_size, n_samples. Typed ``Any`` rather than ``float``
        because ci_lower/ci_upper are ``None`` when no replicate scored, and an
        under-sampled call adds a string ``note``.
    """
    n = len(y_true)
    point = metric_fn(y_true, y_proba)

    if n < block_size * 2:
        # Too few samples for meaningful block resampling.
        return {
            "point_estimate": round(float(point), 4),
            "ci_lower": round(float(point), 4),
            "ci_upper": round(float(point), 4),
            "ci_level": ci_level,
            "n_bootstrap": 0,
            "block_size": block_size,
            "n_samples": n,
            "note": "insufficient_samples_for_block_bootstrap",
        }

    rng = np.random.default_rng(rng_seed)
    # Build non-overlapping blocks.
    n_blocks = n // block_size
    blocks: List[Tuple[int, int]] = [(i * block_size, (i + 1) * block_size)
                                     for i in range(n_blocks)]

    replicates: List[float] = []
    for _ in range(n_bootstrap):
        chosen = rng.choice(len(blocks), size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(blocks[b][0], blocks[b][1]) for b in chosen])
        idx = idx[:n]  # trim to original length
        try:
            val = metric_fn(y_true[idx], y_proba[idx])
            replicates.append(float(val))
        except Exception:
            continue

    if not replicates:
        return {"point_estimate": round(float(point), 4), "ci_lower": None,
                "ci_upper": None, "ci_level": ci_level, "n_bootstrap": 0,
                "block_size": block_size, "n_samples": n}

    alpha = (1.0 - ci_level) / 2.0
    ci_lower = float(np.quantile(replicates, alpha))
    ci_upper = float(np.quantile(replicates, 1.0 - alpha))

    return {
        "point_estimate": round(float(point), 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "ci_level": ci_level,
        "n_bootstrap": len(replicates),
        "block_size": block_size,
        "n_samples": n,
    }
