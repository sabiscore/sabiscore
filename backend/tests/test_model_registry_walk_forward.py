"""Regression guard for the walk-forward RPS validation call path.

model_registry.walk_forward_validate() used to pass a one-hot list to
ranked_probability_score(), which expects a plain int outcome. That raised a
TypeError on every scored record, silently swallowed by a bare except, so the
function always returned {"skipped": True, "reason": "no_valid_folds"} no
matter how much data was supplied. These tests pin the fixed call convention.
"""
from __future__ import annotations

import os
from contextlib import nullcontext
from types import SimpleNamespace

os.environ["ALLOW_SQLITE_FALLBACK"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["REDIS_ENABLED"] = "false"

import numpy as np
import pytest

from src.models.evaluation.metrics import brier_score_decomposition, ranked_probability_score
from src.models import model_registry
from src.models.model_registry import ModelRegistry


def test_registry_does_not_import_mlflow_without_tracking_uri(monkeypatch, tmp_path) -> None:
    def fail_if_called():
        raise AssertionError("MLflow must remain off the API path when unconfigured")

    monkeypatch.setattr(model_registry, "_load_mlflow", fail_if_called)

    registry = ModelRegistry(registry_path=str(tmp_path))

    assert registry.mlflow_enabled is False


def test_registry_enables_mlflow_without_logging_secret_uri(monkeypatch, caplog, tmp_path) -> None:
    configured: list[tuple[str, str]] = []
    fake_mlflow = SimpleNamespace(
        set_tracking_uri=lambda uri: configured.append(("uri", uri)),
        set_experiment=lambda name: configured.append(("experiment", name)),
        start_run=lambda **_kwargs: nullcontext(),
        log_params=lambda _params: None,
        log_metrics=lambda _metrics: None,
        set_tags=lambda _tags: None,
        sklearn=SimpleNamespace(log_model=lambda _model, _name: None),
    )
    secret_uri = "https://user:super-secret@example.invalid/mlflow?token=hidden"
    monkeypatch.setattr(model_registry, "_load_mlflow", lambda: fake_mlflow)

    with caplog.at_level("INFO"):
        registry = ModelRegistry(
            registry_path=str(tmp_path),
            mlflow_tracking_uri=secret_uri,
        )

    assert registry.mlflow_enabled is True
    assert configured[0] == ("uri", secret_uri)
    assert secret_uri not in caplog.text
    assert "super-secret" not in caplog.text
    assert "token=hidden" not in caplog.text


def test_local_registry_cannot_promote_model(tmp_path) -> None:
    registry = ModelRegistry(registry_path=str(tmp_path))

    with pytest.raises(RuntimeError, match="active generation"):
        registry.promote_to_production("candidate_v1")

    assert registry.metadata["production_model"] is None


def test_ranked_probability_score_perfect_prediction_is_zero() -> None:
    assert ranked_probability_score(0, [1.0, 0.0, 0.0]) == 0.0


def test_ranked_probability_score_worst_prediction_is_one() -> None:
    assert ranked_probability_score(2, [1.0, 0.0, 0.0]) == 1.0


def test_brier_decomposition_perfect_forecast_is_all_zero_reliability() -> None:
    # Forecast always matches the outcome exactly -> reliability 0, brier_score 0.
    y_true = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2, 0])
    y_proba = np.eye(3)[y_true]
    result = brier_score_decomposition(y_true, y_proba)
    assert result["mean"]["brier_score"] == 0.0
    assert result["mean"]["reliability"] == 0.0


def test_brier_decomposition_uninformative_forecast_has_zero_resolution() -> None:
    # Every forecast is identical (the base rate) -> the model conveys no
    # information beyond the class frequency, so resolution must be 0.
    y_true = np.array([0, 1, 2] * 4)
    y_proba = np.tile([1 / 3, 1 / 3, 1 / 3], (12, 1))
    result = brier_score_decomposition(y_true, y_proba)
    assert result["mean"]["resolution"] == 0.0


def test_brier_decomposition_reports_bin_counts_summing_to_sample_size() -> None:
    y_true = np.array([0, 1, 2, 0, 1, 2, 0, 1, 2, 0, 1, 2])
    y_proba = np.tile([0.6, 0.25, 0.15], (12, 1))
    result = brier_score_decomposition(y_true, y_proba, n_bins=5)
    for counts in result["bin_counts"].values():
        assert sum(counts) == 12
    assert result["n_samples"] == 12


def _synthetic_records(n: int = 20) -> list[dict]:
    outcomes = [0, 1, 2]
    return [
        {
            "date": f"2026-01-{(i % 28) + 1:02d}",
            "outcome": outcomes[i % 3],
            "probs": [0.5, 0.3, 0.2],
        }
        for i in range(n)
    ]


def test_walk_forward_validate_skips_when_too_few_records(tmp_path) -> None:
    registry = ModelRegistry(registry_path=str(tmp_path))
    result = registry.walk_forward_validate(_synthetic_records(4), n_splits=5)
    assert result["skipped"] is True


def test_walk_forward_validate_produces_folds_for_real_data(tmp_path) -> None:
    """Regression guard: this must not fall back to no_valid_folds/skipped."""
    registry = ModelRegistry(registry_path=str(tmp_path))
    result = registry.walk_forward_validate(_synthetic_records(20), n_splits=5)

    assert result["skipped"] is False
    assert result["n_splits"] == 5
    assert len(result["folds"]) == 5
    assert 0.0 <= result["rps_overall"] <= 1.0
    for fold in result["folds"]:
        assert 0.0 <= fold["rps_mean"] <= 1.0


def test_walk_forward_validate_skips_invalid_records_without_changing_shape(tmp_path) -> None:
    records = _synthetic_records(20)
    records[4]["outcome"] = 3
    records[7]["outcome"] = "invalid"
    records[10]["probs"] = [0.8, 0.8, -0.6]
    records[13]["probs"] = [float("nan"), 0.5, 0.5]

    registry = ModelRegistry(registry_path=str(tmp_path))
    result = registry.walk_forward_validate(records, n_splits=5)

    assert set(result) == {
        "skipped",
        "n_splits",
        "total_records",
        "rps_overall",
        "rps_std",
        "accuracy_overall",
        "brier_overall",
        "brier_decomposition",
        "folds",
        "validated_at",
    }
    assert result["skipped"] is False
    assert result["total_records"] == 20
    assert all(fold["test_size"] <= 3 for fold in result["folds"])
    # accuracy is scored over exactly the records RPS accepted (correct / len(rps_scores)),
    # so the two metrics always describe one population even as invalid records are
    # dropped around them.
    assert 0.0 <= result["accuracy_overall"] <= 1.0
    assert all(0.0 <= fold["accuracy"] <= 1.0 for fold in result["folds"])
    assert all("brier_mean" in fold for fold in result["folds"])
    # 20 synthetic records minus the 4 deliberately invalid ones = 16 pooled,
    # comfortably above the 10-record decomposition floor.
    assert result["brier_decomposition"].get("skipped") is not True
    assert "mean" in result["brier_decomposition"]


def test_walk_forward_validate_skips_brier_decomposition_below_pooled_floor(tmp_path) -> None:
    # n_splits=2 -> min_records=4; exactly at the RPS floor but below the
    # decomposition's own 10-pooled-record minimum, so RPS/accuracy still run
    # while brier_decomposition honestly reports its own skip reason.
    registry = ModelRegistry(registry_path=str(tmp_path))
    result = registry.walk_forward_validate(_synthetic_records(4), n_splits=2)

    assert result["skipped"] is False
    assert result["brier_decomposition"]["skipped"] is True
    assert "brier_overall" in result


def test_walk_forward_validate_reports_no_valid_folds_for_invalid_records(tmp_path) -> None:
    records = _synthetic_records(20)
    for record in records:
        record["probs"] = [0.6, 0.6, -0.2]

    registry = ModelRegistry(registry_path=str(tmp_path))

    assert registry.walk_forward_validate(records, n_splits=5) == {
        "skipped": True,
        "reason": "no_valid_folds",
    }
