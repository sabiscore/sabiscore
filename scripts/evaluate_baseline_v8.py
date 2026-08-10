"""
Phase 8 baseline lock evaluator.

Runs the walk-forward baseline evaluation for every active league model and
writes a date-stamped, immutable JSON report to docs/baseline-metrics/.

Usage:
  python scripts/evaluate_baseline_v8.py \
    --models-dir backend/models \
    --data-dir   backend/data/processed \
    --version    v5_phase7

The script:
  - evaluates one model per league in DEFAULT_LEAGUES order
  - uses walk-forward temporal splits ONLY — no random k-fold CV
  - writes docs/baseline-metrics/baseline_v8_YYYYMMDD.json (immutable)
  - exits non-zero if any acceptance gate fails

Acceptance gates (per brief §1b):
  - Report includes: accuracy_overall, log_loss, brier_score, ece.mean,
    ece.class_0/1/2, draw_precision, draw_recall, per_season, per_league.
  - draw_recall must be present (non-null) for each league.
  - No random k-fold CV is used (enforced by --walk-forward flag).

This file is the canonical entrypoint for Phase 8 baseline locking.
Do NOT modify the output schema without updating CHANGELOG.md and
docs/baseline-metrics/README.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
DOCS_DIR = REPO_ROOT / "docs" / "baseline-metrics"

# Delegates per-league evaluation to the Phase 8 backend evaluator.
EVALUATOR_PATH = BACKEND_ROOT / "scripts" / "evaluate_baseline_v8.py"


def _find_prior_baseline(output_dir: Path, today_str: str) -> "Path | None":
    """Return the most recent baseline report that is not today's, or None."""
    reports = sorted(output_dir.glob("baseline_v8_*.json"), reverse=True)
    for r in reports:
        if r.stem != f"baseline_v8_{today_str}":
            return r
    return None


def _resolve_league_model(models_dir: Path, league: str, version: str) -> Path | None:
    """Locate {league}_ensemble_{version}.pkl under models_dir."""
    candidate = models_dir / f"{league}_ensemble_{version}.pkl"
    if candidate.exists():
        return candidate

    # fallback: any file matching the league
    for f in sorted(models_dir.glob(f"{league}_ensemble*.pkl")):
        return f

    return None


def _resolve_league_data(data_dir: Path, league: str) -> Path | None:
    for suffix in (".parquet", ".csv"):
        candidate = data_dir / f"{league}_training{suffix}"
        if candidate.exists():
            return candidate
    return None


RPS_GATE = 0.210          # aggregate RPS across all domestic leagues must be ≤ this
DRAW_RECALL_MIN = 0.25   # non-null draw_recall required per league

def _validate_report(report: dict[str, Any], league: str) -> list[str]:
    """Return list of missing/invalid fields for the acceptance gate check."""
    failures: list[str] = []
    required_keys = [
        "accuracy_overall",
        "log_loss",
        "brier_score",
        "rps",
        "macro_f1",
        "balanced_accuracy",
        "draw_precision",
        "draw_recall",
        "draw_f1",
        "per_season",
    ]
    for key in required_keys:
        if key not in report:
            failures.append(f"{league}: missing key '{key}'")

    ece = report.get("ece", {})
    for ece_key in ("mean", "class_0", "class_1", "class_2"):
        if ece_key not in ece:
            failures.append(f"{league}: ece missing '{ece_key}'")

    if report.get("draw_recall") is None:
        failures.append(f"{league}: draw_recall is null")

    # Propagate gate failures already computed by the backend evaluator
    gates = report.get("gates", {})
    if gates and not gates.get("passed", True):
        for gf in gates.get("failures", []):
            failures.append(f"{league}: {gf}")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 8 baseline lock — walk-forward evaluation for all active leagues"
    )
    parser.add_argument(
        "--models-dir",
        default=str(BACKEND_ROOT / "models"),
        help="Directory containing league ensemble .pkl files",
    )
    parser.add_argument(
        "--data-dir",
        default=str(BACKEND_ROOT / "data" / "processed"),
        help="Directory containing per-league training data",
    )
    parser.add_argument(
        "--version",
        default="v5_phase7",
        help="Model version suffix (e.g. v5_phase7)",
    )
    parser.add_argument(
        "--leagues",
        default="epl,la_liga,bundesliga,serie_a,ligue_1",
        help="Comma-separated list of leagues to evaluate",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DOCS_DIR),
        help="Directory to write date-stamped report into",
    )
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    version = args.version.strip()
    leagues = [league.strip().lower() for league in args.leagues.split(",") if league.strip()]

    output_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    output_path = output_dir / f"baseline_v8_{today}.json"
    prior_baseline_path = _find_prior_baseline(output_dir, today)

    if output_path.exists():
        print(
            f"[baseline-v8] Report already exists for today: {output_path}",
            file=sys.stderr,
        )
        print(
            "[baseline-v8] To regenerate, delete the existing file first.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[baseline-v8] Starting Phase 8 baseline lock — version={version} leagues={leagues}")
    print("[baseline-v8] NOTE: walk-forward temporal splits only — no random k-fold CV")

    combined: dict[str, Any] = {
        "version": version,
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_method": "walk_forward_temporal_splits",
        "random_kfold": False,
        "leagues": {},
    }

    gate_failures: list[str] = []
    evaluated: list[str] = []

    for league in leagues:
        model_path = _resolve_league_model(models_dir, league, version)
        data_path = _resolve_league_data(data_dir, league)

        if model_path is None:
            print(
                f"[baseline-v8] SKIP {league}: no model artifact for version={version}",
                file=sys.stderr,
            )
            gate_failures.append(f"{league}: model artifact not found")
            continue

        if data_path is None:
            print(
                f"[baseline-v8] SKIP {league}: no training data found under {data_dir}",
                file=sys.stderr,
            )
            gate_failures.append(f"{league}: training data not found")
            continue

        tmp_report = output_dir / f"_tmp_{league}.json"
        try:
            cmd = [
                sys.executable,
                str(EVALUATOR_PATH),
                "--model", str(model_path),
                "--data", str(data_path),
                "--output", str(tmp_report),
                "--walk-forward",
            ]
            if prior_baseline_path:
                cmd += ["--baseline-report", str(prior_baseline_path)]
            print(f"[baseline-v8] Evaluating {league}: {model_path.name} + {data_path.name}")
            result = subprocess.run(cmd, capture_output=False, check=False)

            if result.returncode != 0:
                gate_failures.append(f"{league}: evaluator exited {result.returncode}")
                continue

            if not tmp_report.exists():
                gate_failures.append(f"{league}: evaluator did not write output file")
                continue

            report = json.loads(tmp_report.read_text(encoding="utf-8"))
            tmp_report.unlink(missing_ok=True)

            failures = _validate_report(report, league)
            gate_failures.extend(failures)

            combined["leagues"][league] = report
            evaluated.append(league)

        except Exception as exc:
            gate_failures.append(f"{league}: unexpected error — {exc}")
        finally:
            tmp_report.unlink(missing_ok=True)

    combined["evaluated_leagues"] = evaluated

    # ── aggregate RPS gate ───────────────────────────────────────────────────
    rps_values = [
        combined["leagues"][lg].get("rps")
        for lg in evaluated
        if combined["leagues"].get(lg, {}).get("rps") is not None
    ]
    if rps_values:
        agg_rps = sum(rps_values) / len(rps_values)
        combined["aggregate_rps"] = round(agg_rps, 4)
        combined["rps_gate_threshold"] = RPS_GATE
        combined["rps_gate_passed"] = agg_rps <= RPS_GATE
        print(
            f"[baseline-v8] Aggregate RPS={agg_rps:.4f} "
            f"(gate≤{RPS_GATE}) — {'PASS' if agg_rps <= RPS_GATE else 'FAIL'}"
        )
        if agg_rps > RPS_GATE:
            gate_failures.append(
                f"aggregate RPS gate: {agg_rps:.4f} > {RPS_GATE} "
                "(model not suitable for release)"
            )
    else:
        print("[baseline-v8] WARN: no RPS values available — aggregate gate skipped", file=sys.stderr)

    # ── aggregate metric summary ─────────────────────────────────────────────
    for metric in ("macro_f1", "balanced_accuracy", "draw_f1"):
        vals = [
            combined["leagues"][lg].get(metric)
            for lg in evaluated
            if combined["leagues"].get(lg, {}).get(metric) is not None
        ]
        if vals:
            combined[f"aggregate_{metric}"] = round(sum(vals) / len(vals), 4)

    # ── dated per-league delta report ────────────────────────────────────────
    all_deltas = {
        lg: combined["leagues"][lg].get("per_league_delta", {})
        for lg in evaluated
        if combined["leagues"].get(lg, {}).get("per_league_delta")
    }
    if all_deltas:
        delta_path = output_dir / f"delta_per_league_{today}.json"
        delta_path.write_text(
            json.dumps(
                {
                    "date": today,
                    "version": version,
                    "baseline_compared": str(prior_baseline_path) if prior_baseline_path else None,
                    "per_league_delta": all_deltas,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[baseline-v8] Per-league delta report written to {delta_path}")
    combined["prior_baseline"] = str(prior_baseline_path) if prior_baseline_path else None

    if gate_failures:
        print("[baseline-v8] GATE FAILURES:", file=sys.stderr)
        for f in gate_failures:
            print(f"  - {f}", file=sys.stderr)
        print(
            "[baseline-v8] Baseline lock FAILED — report not written",
            file=sys.stderr,
        )
        sys.exit(1)

    output_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"[baseline-v8] Baseline lock PASSED — report written to {output_path}")
    print(f"[baseline-v8] Evaluated leagues: {', '.join(evaluated)}")


if __name__ == "__main__":
    main()
