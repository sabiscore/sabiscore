"""Frozen V21 market comparison contract and guard functions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


PROTOCOL = {
    "protocol_id": "sabiscore-v21-market-evaluation-v1",
    "frozen": True,
    "inherited_protocols": [
        {
            "path": "reports/research/v19-evaluation-protocol.json",
            "sha256": "7f106f21c3112b748b3a5312aff0d642fb9193588393d5ed7395c536a60cd16d",
        },
        {
            "path": "reports/research/c6-served-generation-vs-close-protocol.json",
            "sha256": "9d63da25324a79f4f08416d79991281bd45155064ec33fd8f67284b28be46ba7",
        },
    ],
    "candidate_tracks": {
        "Candidate-M": {
            "market_inputs_allowed": False,
            "market_fields_forbidden": [
                "odds",
                "implied_probabilities",
                "devigged_probabilities",
                "market_movement",
                "closing_prices",
            ],
        },
        "Candidate-MA": {"market_inputs_allowed": True, "certified_as_independent_alpha": False},
    },
    "cohorts": [
        "all_holdout_fixtures",
        "market_available_fixtures",
        "c6_eligible_fixtures",
        "complete_evidence_fixtures",
    ],
    "benchmarks": [
        {"name": "opening_market", "reported_separately": True},
        {"name": "closing_market", "reported_separately": True},
    ],
    "comparison_requirements": [
        "same_fixture_ids",
        "same_outcomes",
        "same_timestamp_class",
        "same_benchmark_definition",
        "same_scoring_rule",
        "same_exclusion_rules",
    ],
    "metrics": ["rps", "log_loss", "brier", "ece", "reliability", "classwise_calibration"],
    "gate_7": {
        "rule": "candidate_rps_must_not_exceed_the_corresponding_frozen_market_rps",
        "comparison": "paired_identical_cohort_for_opening_and_closing_benchmarks_reported_separately",
        "market_blend_is_certification_input": False,
    },
    "c6": {
        "protocol_source": "reports/research/c6-served-generation-vs-close-protocol.json",
        "capture_trigger": "interactive_full_analysis",
        "live_sample_target": 200,
        "milestones": [200, 500, 1000],
        "replay_counts": False,
        "milestone_inference": "98.33% ISO-week cluster bootstrap, 10000 replicates, seed 42, alpha=0.05/3",
        "sample_cut": "whole kickoff groups through the Nth joined observation",
    },
}


def protocol_bytes() -> bytes:
    return (json.dumps(PROTOCOL, sort_keys=True, indent=2) + "\n").encode("utf-8")


def protocol_sha256() -> str:
    return hashlib.sha256(protocol_bytes()).hexdigest()


def validate_market_independent_feature_names(names: Iterable[str]) -> tuple[str, ...]:
    """Reject market leakage in Candidate-M's declared input list."""
    ordered = tuple(names)
    if len(ordered) != len(set(ordered)):
        raise ValueError("Candidate-M feature list contains duplicates")
    forbidden_tokens = ("odds", "market", "implied_prob", "closing", "devig", "sharp_money")
    leaked = [name for name in ordered if any(token in name.casefold() for token in forbidden_tokens)]
    if leaked:
        raise ValueError(f"Candidate-M contains market-derived inputs: {', '.join(leaked)}")
    return ordered


def validate_calibration_split(
    *, calibration_fixture_ids: Iterable[str], test_fixture_ids: Iterable[str], c6_fixture_ids: Iterable[str]
) -> None:
    calibration = set(calibration_fixture_ids)
    overlap = calibration & (set(test_fixture_ids) | set(c6_fixture_ids))
    if overlap:
        raise ValueError("calibration fixtures overlap test or C6 evaluation populations")


def evaluate_market_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Score Candidate-M against opening and closing benchmarks on exact rows."""
    from backend.src.models.evaluation.metrics import ranked_probability_score

    records = list(rows)
    ids: list[str] = []
    outcomes: list[int] = []
    candidate_scores: list[float] = []
    opening_scores: list[float] = []
    closing_scores: list[float] = []
    for row in records:
        fixture_id = str(row.get("fixture_id") or "")
        outcome = row.get("outcome")
        if not fixture_id or outcome not in (0, 1, 2):
            raise ValueError("fixture_id and 0/1/2 outcome are required")
        ids.append(fixture_id)
        outcomes.append(int(outcome))
        for key, scores in (
            ("candidate_m_probabilities", candidate_scores),
            ("opening_market_probabilities", opening_scores),
            ("closing_market_probabilities", closing_scores),
        ):
            probabilities = row.get(key)
            if (
                not isinstance(probabilities, (list, tuple))
                or len(probabilities) != 3
                or any(not isinstance(p, (int, float)) or p < 0 or p > 1 for p in probabilities)
                or abs(sum(probabilities) - 1.0) > 1e-6
            ):
                raise ValueError(f"{key} must be a valid 1X2 probability simplex")
            scores.append(float(ranked_probability_score(int(outcome), list(probabilities))))
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("evaluation rows must be non-empty and unique by fixture")
    def mean(s_list: list[float]) -> float:
        return sum(s_list) / len(s_list)

    return {
        "fixture_count": len(ids),
        "fixture_ids_sha256": hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest(),
        "candidate_m_rps": mean(candidate_scores),
        "opening_market_rps": mean(opening_scores),
        "closing_market_rps": mean(closing_scores),
        "gate_7": "PASS" if mean(candidate_scores) <= mean(closing_scores) else "FAIL",
        "opening_is_separate_from_closing": True,
        "market_blend_used_for_certification": False,
    }


def compare_cohorts(
    *,
    candidate_fixture_ids: Iterable[str],
    candidate_outcomes: Iterable[int],
    market_fixture_ids: Iterable[str],
    market_outcomes: Iterable[int],
    candidate_rps: float,
    market_rps: float,
    benchmark: str,
) -> dict[str, Any]:
    """Return an honest comparison only when both sides share the same cohort."""
    candidate_ids = tuple(candidate_fixture_ids)
    market_ids = tuple(market_fixture_ids)
    candidate_y = tuple(candidate_outcomes)
    market_y = tuple(market_outcomes)
    if (
        len(candidate_ids) != len(candidate_y)
        or len(market_ids) != len(market_y)
        or not candidate_ids
        or len(candidate_ids) != len(set(candidate_ids))
        or len(market_ids) != len(set(market_ids))
    ):
        raise ValueError("cohort fixture IDs and outcomes must be non-empty, unique, and aligned")
    candidate_labels = dict(zip(candidate_ids, candidate_y))
    market_labels = dict(zip(market_ids, market_y))
    if candidate_labels != market_labels:
        raise ValueError("candidate and market benchmark cohorts/outcomes differ")
    if benchmark not in {"opening_market", "closing_market"}:
        raise ValueError("benchmark must be opening_market or closing_market")
    if candidate_rps < 0 or market_rps < 0:
        raise ValueError("RPS values must be non-negative")
    return {
        "benchmark": benchmark,
        "fixture_count": len(candidate_ids),
        "fixture_ids_sha256": hashlib.sha256("\n".join(sorted(candidate_ids)).encode()).hexdigest(),
        "candidate_rps": candidate_rps,
        "market_rps": market_rps,
        "gate_7": "PASS" if candidate_rps <= market_rps else "FAIL",
        "market_blend_used_for_certification": False,
    }


__all__ = [
    "PROTOCOL",
    "compare_cohorts",
    "evaluate_market_rows",
    "protocol_bytes",
    "protocol_sha256",
    "validate_calibration_split",
    "validate_market_independent_feature_names",
]
