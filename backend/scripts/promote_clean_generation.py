"""Promote a trained candidate directory to the active generation.

Directive v5 §33 (feature lineage), §39 (state machine). Written for the
`v11_clean2526` remediation (docs/DEBT.md item 81) but parameterised, because
"copy the pkls, write the metadata, rewrite the manifest, recompute the SHAs"
is exactly the mechanical step that gets done by hand and then cannot be
audited afterwards.

What it does NOT do: certify, promote past ACTIVE_FAIL_CLOSED, or overwrite the
outgoing artifacts. The outgoing `active_generation.json` is copied to
`active_generation.prev.json` and the incoming artifacts get their own
generation-suffixed filenames, so the previous generation stays on disk and the
contamination finding stays re-verifiable.

Usage
-----
    cd backend && PYTHONPATH=. python scripts/promote_clean_generation.py \
        --candidate-dir models/candidate_clean2526 --generation v11_clean2526
    # add --dry-run to print the plan and write nothing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

_MODELS = _BACKEND_ROOT / "models"

# slug -> canonical league id. `required` mirrors the outgoing manifest: the
# five scoreable leagues gate startup; Eredivisie does not.
_SLUGS: Dict[str, str] = {
    "bundesliga": "BUNDESLIGA",
    "epl": "EPL",
    "eredivisie": "EREDIVISIE",
    "la_liga": "LA_LIGA",
    "ligue_1": "LIGUE_1",
    "serie_a": "SERIE_A",
}
_REQUIRED = {"bundesliga", "epl", "la_liga", "ligue_1", "serie_a"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _served_head(raw: Dict[str, Any]) -> str:
    # Mirrors PredictionEngine._run_inference: a present meta-model is served,
    # the base-learner average is only its fallback. This was hardcoded to
    # "base_learner_average" and published a false head (docs/DEBT.md item 142).
    return "stacked_meta_model" if raw.get("meta_model") is not None else "base_learner_average"


def build_metadata(
    league: str,
    generation: str,
    artifact: Path,
    manifest: Dict[str, Any],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    import joblib

    raw = joblib.load(artifact)
    config = manifest["training_config"]
    features = manifest["features"]
    pooled = league == "EREDIVISIE"
    metrics = report.get("POOLED" if pooled else league, {})
    head = type(raw.get("meta_model")).__name__

    return {
        "generation": generation,
        "league": league,
        # The loader's _verify_feature_contract reads this and refuses a
        # mismatch against the declared schema width.
        "feature_count": len(raw.get("feature_columns") or []),
        "feature_schema_version": features["feature_schema_version"],
        "data_source": "football-data.co.uk (real matches)",
        "trained_at": manifest["generated_at"],
        "temporal_split": {
            "train_seasons": "1920-2324 (core, disjoint from the calibration season)",
            "calibration_season": "2425",
            "holdout_season": config["holdout_season"],
            "rule": config["split"],
            "calibration_rule": config["calibration"],
        },
        "holdout_season": config["holdout_season"],
        "calibration_season": "2425",
        "holdout_samples": metrics.get("n"),
        "rps": metrics.get("rps"),
        "brier_score": metrics.get("brier"),
        "log_loss": metrics.get("log_loss"),
        "accuracy": metrics.get("accuracy"),
        "calibration_error": metrics.get("calibration_error"),
        "pooled_model": pooled,
        "pooled_reason": (
            "EREDIVISIE has only season 2526 in the corpus, and 2526 is the holdout, "
            "so it has zero pre-holdout training rows and serves the pooled "
            "all-league model."
        )
        if pooled
        else None,
        "in_artifact_calibrator": "calibrator" in raw,
        "in_artifact_calibrator_note": (
            "No 'calibrator' key is written by this training path. PredictionEngine "
            "applies a FittedCalibrator only when the artifact carries one, after the "
            "served head — a calibrator injected later (inject_platt_calibrator.py) is "
            f"applied on top of the {head} stacking head, which PredictionEngine "
            "serves whenever it is present."
        ),
        "served_head": _served_head(raw),
        "stacking_head_present": head,
        "artifact_keys": sorted(raw.keys()),
        "reproducibility_sha256": manifest["reproducibility_sha256"],
        "training_command": (
            "PYTHONPATH=. python scripts/train_on_real_matches.py "
            f"--holdout-season {config['holdout_season']} "
            f"--schema {features['feature_schema_version']} "
            "--out-dir models/candidate_clean2526"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--generation", required=True)
    parser.add_argument(
        "--supersedes-reason",
        default=(
            "v5_phase7-20260808 was trained with holdout_season 2425 while season 2526 was "
            "in its training set. 2526 is the holdout every candidate comparison scores "
            "against, so that generation memorised the test set (docs/DEBT.md item 81). "
            "This generation holds 2526 out strictly."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src = (
        args.candidate_dir
        if args.candidate_dir.is_absolute()
        else _BACKEND_ROOT / args.candidate_dir
    )
    manifest = json.loads((src / "training_manifest.json").read_text(encoding="utf-8"))
    report = json.loads((src / "training_report_real.json").read_text(encoding="utf-8"))
    suffix = manifest["training_config"]["artifact_suffix"]

    artifacts: Dict[str, Dict[str, Any]] = {}
    heads: set[str] = set()
    for slug, league in _SLUGS.items():
        src_pkl = src / f"{slug}_ensemble_{suffix}.pkl"
        if not src_pkl.exists():
            raise FileNotFoundError(f"candidate artifact missing: {src_pkl}")
        dst_pkl = _MODELS / f"{slug}_ensemble_{args.generation}.pkl"
        dst_meta = _MODELS / f"{slug}_ensemble_{args.generation}_metadata.json"

        if args.dry_run:
            print(f"  would write {dst_pkl.name} + {dst_meta.name}")
            continue

        shutil.copy2(src_pkl, dst_pkl)
        metadata = build_metadata(league, args.generation, dst_pkl, manifest, report)
        heads.add(metadata["served_head"])
        dst_meta.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        artifacts[slug] = {
            "artifact": dst_pkl.name,
            "artifact_sha256": _sha256(dst_pkl),
            "metadata": dst_meta.name,
            "metadata_sha256": _sha256(dst_meta),
            "required": slug in _REQUIRED,
        }
        rps = metadata.get("rps")
        print(
            f"  {league:<11} rps={rps:.4f} n={metadata.get('holdout_samples')} -> {dst_pkl.name}"
        )

    if args.dry_run:
        print("dry run — nothing written")
        return 0

    active_path = _MODELS / "active_generation.json"
    previous = json.loads(active_path.read_text(encoding="utf-8"))
    (_MODELS / "active_generation.prev.json").write_text(
        json.dumps(previous, indent=2), encoding="utf-8"
    )

    config = manifest["training_config"]
    payload = {
        "schema_version": 1,
        "generation": f"{args.generation}-{datetime.now(timezone.utc):%Y%m%d}",
        "active_version": args.generation,
        "feature_schema_version": manifest["features"]["feature_schema_version"],
        "served_head": heads.pop() if len(heads) == 1 else "per_league",
        "certification_state": "UNVERIFIED",
        "certified_at": None,
        "promotion_state": "ACTIVE_FAIL_CLOSED",
        "promoted_at": None,
        "supersedes": previous.get("generation"),
        "supersedes_reason": args.supersedes_reason,
        "temporal_split": {
            "train_seasons": "1920-2324",
            "calibration_season": "2425",
            "holdout_season": config["holdout_season"],
            "rule": config["split"],
        },
        "artifacts": artifacts,
    }
    active_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        f"\nactive_generation.json -> {payload['generation']} "
        f"({payload['feature_schema_version']}, holdout {config['holdout_season']})"
    )
    print("previous manifest preserved at models/active_generation.prev.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
