#!/usr/bin/env python3
"""Score the incumbent and candidate artifacts on one identical temporal holdout.

CLAUDE.md: "Retain one certified champion. New models remain SHADOW or RESEARCH
unless they demonstrate measurable temporal out-of-sample improvement." This is
the measurement that decision requires — same fixtures, same feature vectors,
same metrics, both models.

RPS is the promotion metric (lower is better), matching model_registry's own
default. Accuracy is reported but is not the gate: a model that always predicts
the home team can look competitive on accuracy while being useless for pricing.

Usage:
    PYTHONPATH=. python scripts/compare_candidate_vs_incumbent.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from collections.abc import Sequence
from typing import Any

import numpy as np

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from scripts.train_on_real_matches import (  # noqa: E402
    _LEAGUE_TO_SLUG,
    _SCHEMAS,
    _schema_for,
    _build_meta_features,
    build_dataset,
    derive_apex_market_features,
    evaluate,
    load_matches,
)
from src.models.promotion_evidence import (  # noqa: E402
    validate_promotion_feature_evidence,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("compare")

HOLDOUT_SEASON = "2526"
_DEFAULT_SCHEMA = "apex_v1_68"

# docs/DEBT.md item 81: the SERVING manifest (active_generation.json,
# v5_phase7-20260808) was trained on season 2526 while declaring holdout 2425,
# so it memorised the very holdout this script scores against. Every
# candidate-vs-incumbent verdict produced against it — including the
# no_league_regression failures across the v3/v4/v5/v8/v10 generations — was
# measured against a baseline that had seen the test set.
#
# The default incumbent is therefore the clean-split EVALUATION baseline, not
# the serving manifest. Serving is deliberately left on its own generation
# (flipping it is the separately-gated item 37/49 schema transition).
_DEFAULT_INCUMBENT_MANIFEST = (
    _BACKEND_ROOT / "models" / "evaluation_baseline" / "manifest.json"
)


def _repo_relative(path: Path) -> str:
    """Repo-relative, so a committed report is portable across checkouts."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(_BACKEND_ROOT.parent).as_posix()
    except ValueError:
        return resolved.name


def _load_incumbent_baseline(manifest_path: Path) -> dict:
    """Resolve the incumbent's directory, artifact suffix and feature contract.

    Fails closed on a temporal mismatch: an incumbent whose own metadata does
    not declare HOLDOUT_SEASON cannot be compared on it, because the holdout
    would be inside its training data — which is exactly the defect item 81
    records.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = str(
        manifest.get("temporal_split", {}).get("holdout_season")
        or manifest.get("holdout_season")
        or ""
    )
    if declared != HOLDOUT_SEASON:
        raise ValueError(
            f"incumbent baseline {manifest.get('generation')!r} declares holdout "
            f"season {declared!r}, but this comparison scores on {HOLDOUT_SEASON!r}. "
            "Scoring a model on a season it was trained on is docs/DEBT.md item 81; "
            "point --incumbent-manifest at a baseline held out on "
            f"{HOLDOUT_SEASON} or retrain one."
        )
    artifacts = manifest.get("artifacts") or {}
    suffixes = {
        str(entry["artifact"]).rsplit("_ensemble_", 1)[-1].removesuffix(".pkl")
        for entry in artifacts.values()
    }
    if len(suffixes) != 1:
        raise ValueError(
            f"incumbent manifest names {len(suffixes)} artifact suffixes {sorted(suffixes)}; "
            "expected exactly one"
        )
    return {
        "generation": manifest.get("generation"),
        "role": manifest.get("role", "SERVING"),
        "directory": manifest_path.parent,
        "suffix": suffixes.pop(),
        "feature_schema_version": manifest.get("feature_schema_version"),
        "served_head": manifest.get("served_head"),
        "holdout_season": declared,
    }


def _predict(bundle: dict, X: np.ndarray) -> np.ndarray:
    """Score the exact stacked head served by strict startup inference."""
    models = bundle["models"]
    meta_model = bundle.get("meta_model")
    if meta_model is None:
        raise ValueError("artifact has no served meta_model")
    return meta_model.predict_proba(_build_meta_features(models, X))


def _coherent_price_perturbation(
    bundle: dict, reference: np.ndarray, candidate_features: Sequence[str]
) -> dict[str, Any]:
    """Require sensible movement between coherent home- and away-favourite books.

    ``candidate_features`` is the candidate's OWN contract, not a hardcoded
    APEX_FEATURES_68. The two agree today for every registered schema (the
    Apex market block sits at the same positions in all of them), but reading
    the market-feature index out of a different list than the row was built
    from is precisely the class of positional error that this repository has
    already served two months of fallback predictions for.
    """
    schema = list(candidate_features)
    if len(schema) != reference.shape[0]:
        raise ValueError(
            f"probe row has {reference.shape[0]} columns, contract has {len(schema)}"
        )
    home_probe = reference.copy()
    away_probe = reference.copy()
    for feature, value in derive_apex_market_features(1.45, 4.50, 7.00).items():
        home_probe[schema.index(feature)] = value
    for feature, value in derive_apex_market_features(7.00, 4.50, 1.45).items():
        away_probe[schema.index(feature)] = value
    home_probs = _predict(bundle, home_probe.reshape(1, -1))[0]
    away_probs = _predict(bundle, away_probe.reshape(1, -1))[0]
    return {
        "home_favourite_probabilities": home_probs.tolist(),
        "away_favourite_probabilities": away_probs.tolist(),
        "max_probability_change": float(np.max(np.abs(home_probs - away_probs))),
        "directionally_coherent": bool(
            home_probs[0] > away_probs[0] and away_probs[2] > home_probs[2]
        ),
    }


def main() -> int:
    import joblib

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=_BACKEND_ROOT / "models" / "candidate" / "comparison_report.json",
    )
    parser.add_argument(
        "--candidate-schema",
        choices=sorted(_SCHEMAS),
        default=_DEFAULT_SCHEMA,
        help=(
            "The feature contract the candidate artifacts were trained on. The "
            "INCUMBENT is always scored on its own CANONICAL_FEATURES_68 vector "
            "(X_incumbent) — that is the point of the comparison; only the "
            "candidate side follows this flag."
        ),
    )
    parser.add_argument(
        "--per-match-output",
        type=Path,
        default=None,
        help=(
            "Persist per-match holdout probabilities (candidate, incumbent, "
            "de-vigged market) plus labels to this .npz. Nothing else in the "
            "repository stores them, which is why block_bootstrap_ci has never "
            "been run on a candidate-vs-market difference."
        ),
    )
    parser.add_argument(
        "--incumbent-manifest",
        type=Path,
        default=_DEFAULT_INCUMBENT_MANIFEST,
        help=(
            "Manifest naming the incumbent baseline. Defaults to the clean-split "
            "evaluation baseline (models/evaluation_baseline), NOT the serving "
            "manifest — see docs/DEBT.md item 81."
        ),
    )
    parser.add_argument(
        "--availability-report",
        type=Path,
        default=None,
        help="Defaults to <candidate-dir>/feature_availability_matrix[_<suffix>].json",
    )
    args = parser.parse_args()

    candidate_features, candidate_suffix = _schema_for(args.candidate_schema)
    baseline = _load_incumbent_baseline(args.incumbent_manifest)
    incumbent_dir = baseline["directory"]
    incumbent_suffix = baseline["suffix"]
    candidate_dir = _BACKEND_ROOT / "models" / "candidate"
    logger.info(
        "Incumbent baseline: %s (%s) from %s — schema %s, holdout %s",
        baseline["generation"],
        baseline["role"],
        incumbent_dir.relative_to(_BACKEND_ROOT),
        baseline["feature_schema_version"],
        baseline["holdout_season"],
    )
    training_report_name = {
        "apex_v1_68": "training_report_real.json",
        "apex_v1_89": "training_report_real_phase8.json",
    }.get(args.candidate_schema, f"training_report_real_{candidate_suffix}.json")
    training_report = json.loads(
        (candidate_dir / training_report_name).read_text(encoding="utf-8")
    )

    # Fail closed on temporal mismatch. Both sides must have held out the SAME
    # season, or the comparison silently pits an out-of-sample model against an
    # in-sample one — item 81 in the other direction.
    candidate_manifest_path = candidate_dir / "training_manifest.json"
    if candidate_manifest_path.exists():
        candidate_holdout = str(
            json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
            .get("training_config", {})
            .get("holdout_season", "")
        )
        if candidate_holdout != HOLDOUT_SEASON:
            raise ValueError(
                f"candidate declares holdout season {candidate_holdout!r} but this "
                f"comparison scores on {HOLDOUT_SEASON!r}, which the incumbent "
                f"baseline {baseline['generation']!r} also holds out. Retrain the "
                f"candidate with --holdout-season {HOLDOUT_SEASON}."
            )
    else:
        raise ValueError(
            f"candidate has no training_manifest.json at {candidate_manifest_path}; "
            "its holdout season cannot be verified and the comparison cannot be "
            "shown to be temporally sound"
        )
    availability_path = args.availability_report or (
        candidate_dir / "feature_availability_matrix.json"
        if args.candidate_schema == _DEFAULT_SCHEMA
        else candidate_dir / f"feature_availability_matrix_{candidate_suffix}.json"
    )
    availability_report = validate_promotion_feature_evidence(
        json.loads(availability_path.read_text(encoding="utf-8"))
    )

    # One dataset serves both sides: `X` follows --candidate-schema while
    # `X_incumbent` is always the 68-wide legacy vector the shipped artifacts
    # were trained on. Under a schema that drops rows (apex_v2_71 drops every
    # fixture with no honest xG answer), BOTH sides are scored on that same
    # reduced holdout — the comparison stays like-for-like on identical
    # fixtures, which is the property the gate depends on.
    dataset = build_dataset(
        load_matches(_BACKEND_ROOT / "data" / "cache"),
        schema=args.candidate_schema,
    )

    header = f"{'league':<12} {'model':<10} {'acc':>7} {'RPS':>8} {'Brier':>8} {'logloss':>8}"
    logger.info("\n%s", header)
    logger.info("-" * len(header))

    verdicts = {}
    per_match: dict[str, np.ndarray] = {}
    report: dict[str, Any] = {
        "holdout_season": HOLDOUT_SEASON,
        "incumbent_baseline": {
            "generation": baseline["generation"],
            "role": baseline["role"],
            "manifest": _repo_relative(args.incumbent_manifest),
            "feature_schema_version": baseline["feature_schema_version"],
            "holdout_season": baseline["holdout_season"],
            "declared_served_head": baseline["served_head"],
            "scored_through": (
                "meta_model (stacked head) — unchanged convention. NOTE: the "
                "request path is _ensemble_predict_dict, a base-learner average; "
                "see docs/DEBT.md item 81."
            ),
        },
        "candidate_schema": args.candidate_schema,
        "candidate_feature_count": len(candidate_features),
        "served_head": True,
        "leagues": {},
        "gates": {},
    }
    for league in sorted(dataset):
        slug = _LEAGUE_TO_SLUG[league]
        data = dataset[league]
        seasons = np.asarray(data["seasons"])
        mask = seasons == HOLDOUT_SEASON
        if mask.sum() < 50:
            logger.info("%-12s (no %s holdout — skipped)", league, HOLDOUT_SEASON)
            continue

        candidate_X = np.asarray(data["X"], dtype=np.float32)[mask]
        # The incumbent is scored on ITS OWN declared contract, not a constant.
        # v5_phase7 was legacy (X_incumbent); the clean evaluation baseline is
        # apex_v1_68 (X). Hardcoding either silently scores a model on a vector
        # it was never trained on.
        incumbent_key = (
            "X"
            if baseline["feature_schema_version"] == args.candidate_schema
            else "X_incumbent"
        )
        incumbent_X = np.asarray(data[incumbent_key], dtype=np.float32)[mask]
        y = np.asarray(data["y"], dtype=np.int64)[mask]

        row = {}
        candidate_bundle = None
        league_probs: dict[str, np.ndarray] = {}
        for label, directory, suffix in (
            ("incumbent", incumbent_dir, incumbent_suffix),
            ("candidate", candidate_dir, candidate_suffix),
        ):
            path = directory / f"{slug}_ensemble_{suffix}.pkl"
            if not path.exists():
                logger.info("%-12s %-10s (artifact absent)", league, label)
                continue
            bundle = joblib.load(path)
            if label == "candidate":
                candidate_bundle = bundle
            X = incumbent_X if label == "incumbent" else candidate_X
            if X.shape[1] != len(bundle.get("feature_columns") or []):
                raise ValueError(
                    f"{label} {league}: artifact expects "
                    f"{len(bundle.get('feature_columns') or [])} features but the "
                    f"{label} vector supplies {X.shape[1]} — refusing to score a "
                    "model on a contract it was not trained on"
                )
            probabilities = _predict(bundle, X)
            league_probs[label] = probabilities
            metrics = evaluate(y, probabilities)
            row[label] = metrics
            logger.info(
                "%-12s %-10s %7.4f %8.4f %8.4f %8.4f",
                league,
                label,
                metrics["accuracy"],
                metrics["rps"],
                metrics["brier"],
                metrics["log_loss"],
            )

        if "incumbent" in row and "candidate" in row:
            delta = row["incumbent"]["rps"] - row["candidate"]["rps"]
            # `.get(league, training_report["POOLED"])` evaluated the default
            # eagerly, so a run that trained every league individually — and
            # therefore wrote no POOLED entry — raised KeyError even for
            # leagues that were present. Latent until apex_v2_71, whose
            # row-dropping leaves no league needing the pooled fallback.
            candidate_evidence = training_report.get(league) or training_report.get(
                "POOLED"
            )
            if candidate_evidence is None:
                raise KeyError(
                    f"training report has neither a {league!r} entry nor a POOLED fallback"
                )
            verdicts[league] = delta
            report["leagues"][league] = {
                "incumbent": row["incumbent"],
                "candidate": row["candidate"],
                "candidate_rps_improvement": delta,
                "candidate_wins": delta > 0,
                "market_baseline_rps": candidate_evidence["baseline_rps_market"],
                # Which market price this bar is. Older training reports predate
                # the label, so fall back to stating that rather than asserting a
                # quote the report never recorded.
                "market_baseline_quote": candidate_evidence.get(
                    "baseline_rps_market_quote", "unlabelled_pre_2026_09_report"
                ),
                "candidate_beats_market_baseline": (
                    row["candidate"]["rps"] < candidate_evidence["baseline_rps_market"]
                ),
                "responsive_features": candidate_evidence["responsive_features"],
                "coherent_price_perturbation": _coherent_price_perturbation(
                    candidate_bundle,
                    candidate_X[0].copy(),
                    candidate_features,
                ),
            }
            logger.info(
                "%-12s %-10s RPS %+0.4f  -> %s",
                "",
                "delta",
                -delta,
                "CANDIDATE BETTER" if delta > 0 else "incumbent better",
            )
            if args.per_match_output is not None:
                # The de-vigged market probabilities are columns of the
                # candidate's OWN holdout matrix, not a separate source. This
                # is the same slice train_on_real_matches uses for
                # `baseline_rps_market` (X_test[:, market_columns]), so the
                # rows are paired with the model probabilities by construction
                # -- same fixtures, same order, no join, no re-derivation.
                market_columns = [
                    candidate_features.index(name)
                    for name in (
                        "market_prob_home",
                        "market_prob_draw",
                        "market_prob_away",
                    )
                ]
                per_match[f"{league}__y"] = y
                per_match[f"{league}__candidate"] = league_probs["candidate"]
                per_match[f"{league}__incumbent"] = league_probs["incumbent"]
                per_match[f"{league}__market"] = candidate_X[:, market_columns].astype(
                    np.float64
                )
        logger.info("")

    if verdicts:
        better = sum(1 for d in verdicts.values() if d > 0)
        mean_improvement = float(np.mean(list(verdicts.values())))
        logger.info("Candidate wins on RPS in %d of %d leagues.", better, len(verdicts))
        logger.info("Mean RPS improvement: %+0.4f", mean_improvement)
        report["candidate_league_wins"] = better
        report["leagues_compared"] = len(verdicts)
        report["mean_rps_improvement"] = mean_improvement
        report["no_league_regression"] = better == len(verdicts)
        league_rows = list(report["leagues"].values())
        report["gates"] = {
            "valid_probability_simplex": {
                "status": "PASS",
                "evidence": "evaluate() rejected no candidate holdout probability row",
            },
            "input_responsiveness": {
                "status": (
                    "PASS"
                    if all(row["responsive_features"] > 0 for row in league_rows)
                    else "FAIL"
                ),
                "minimum_responsive_features": min(
                    row["responsive_features"] for row in league_rows
                ),
            },
            "coherent_price_perturbation": {
                "status": (
                    "PASS"
                    if all(
                        row["coherent_price_perturbation"]["directionally_coherent"]
                        for row in league_rows
                    )
                    else "FAIL"
                ),
            },
            "serving_feature_availability": {
                "status": availability_report["promotion_gate"],
                "summary": availability_report["summary"],
            },
            "primary_metric_improvement": {
                "status": "PASS" if mean_improvement > 0 else "FAIL",
                "mean_rps_improvement": mean_improvement,
            },
            "no_league_regression": {
                "status": "PASS" if better == len(verdicts) else "FAIL",
                "league_wins": better,
                "leagues_compared": len(verdicts),
            },
            "market_baseline": {
                "status": (
                    "PASS"
                    if all(
                        row["candidate_beats_market_baseline"] for row in league_rows
                    )
                    else "FAIL"
                ),
                "leagues_beating_market": sum(
                    row["candidate_beats_market_baseline"] for row in league_rows
                ),
                # Surfaced at gate level so a PASS/FAIL can never be read
                # without knowing which price it was measured against.
                "quote": sorted({row["market_baseline_quote"] for row in league_rows}),
            },
        }
        report["promotion_permitted"] = all(
            gate["status"] == "PASS" for gate in report["gates"].values()
        )
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.per_match_output is not None:
        if not per_match:
            logger.error("no league produced both heads; nothing to persist")
            return 1
        args.per_match_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            args.per_match_output,
            candidate_schema=np.asarray(args.candidate_schema),
            holdout_season=np.asarray(HOLDOUT_SEASON),
            **per_match,
        )
        logger.info(
            "per-match holdout probabilities -> %s (%d leagues)",
            args.per_match_output,
            len(per_match) // 4,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
