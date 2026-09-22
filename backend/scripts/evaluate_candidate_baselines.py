#!/usr/bin/env python3
"""Evaluate a served model generation's walk-forward baseline from real
settled predictions, and report -- never automate -- the calibrator-binding
decision that follows a passing candidate.

Corrections applied relative to the original request, recorded here rather
than silently:

1. **Does not reimplement walk-forward evaluation.** A real, tested
   implementation already exists: ``models.model_registry.ModelRegistry
   .walk_forward_validate()`` (temporal folds, RPS/Brier, a documented
   10-record floor per docs/DEBT.md item 88, malformed-record skipping
   rather than a crash) -- already wired end-to-end in
   ``services.settlement_service.run_settlement_pass()``:
   ``get_settled_predictions() -> walk_forward_validate()``. This script is
   a thin, read-only CLI wrapper around exactly that pattern (it does not
   call ``sync_settled_results``/``sync_elo_from_finished_matches`` --
   those refresh data from a live provider, which a read-only evaluation
   CLI shouldn't trigger as a side effect). Writing a second implementation
   here would be the "two implementations of the same statistic quietly
   drift apart" failure class this repository's own history documents
   repeatedly (team-name normalizers, league vocabularies, feature remaps).
2. **Never fits or serializes a calibrator** (the request's own stated
   Invariant 1). ``docs/DEBT.md`` item 83 is explicit: "Blocked pending a
   candidate model passing promotion gates -- building the wiring before
   anything is promotable would be infrastructure ahead of evidence."
   The "Prompt for Calibrator Binding" step in the request's lock-step is
   therefore implemented as a *reported status field*, never a call into
   any fitting/serialization code -- there is no such code path in this
   script, by design, not by omission.
3. **``--save-candidate`` writes an evaluation *report*, not model
   weights.** This script does not train anything -- there is no weight
   set to "freeze". It reuses the existing ``backend/models/candidate/``
   convention (``comparison_report_<tag>.json`` and friends already live
   there) and writes a JSON evaluation report under that same directory.
   It never writes a ``.pkl`` artifact.
4. **``--split-date`` maps onto ``get_settled_predictions(ended_at=...)``**
   -- i.e. "evaluate only on settled predictions up to this date" -- since
   ``walk_forward_validate`` performs its own internal chronological
   n-fold split and has no single "split date" parameter to receive.

Usage:

    cd backend
    PYTHONPATH=. python scripts/evaluate_candidate_baselines.py \\
        --league EPL --split-date 2026-06-01 --save-candidate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
CANDIDATE_DIR = BACKEND_ROOT / "models" / "candidate"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


async def _evaluate(
    *, model_version: str, league: str | None, split_date: datetime | None
) -> dict[str, Any]:
    from src.db.session import AsyncSessionLocal
    from src.repositories.fixtures import get_settled_predictions
    from src.services.settlement_service import get_walk_forward_registry

    if AsyncSessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured / DB session factory unavailable -- failing closed per INV-02."
        )

    async with AsyncSessionLocal() as session:
        records = await get_settled_predictions(
            session, model_version=model_version, league=league, ended_at=split_date
        )

    return get_walk_forward_registry().walk_forward_validate(records)


def _no_calibrator_binding_note(validation: dict[str, Any]) -> dict[str, Any]:
    """The lock-step's third stage, reporting-only. See module docstring
    point 2 -- this function calls nothing that fits or serializes anything."""
    skipped = bool(validation.get("skipped"))
    passed_gate = (not skipped) and validation.get("rps_overall") is not None
    return {
        "calibrator_binding": "NOT_AUTOMATED",
        "reason": (
            "Evaluation was skipped or inconclusive; no candidate to gate."
            if skipped
            else "docs/DEBT.md item 83: calibrator fitting/serialization stays "
            "blocked until an operator reviews this baseline against the full "
            "certification_policy.py promotion gates (no_league_regression, "
            "market_baseline, serving_feature_availability, etc.) -- a "
            "walk-forward RPS pass alone is not sufficient authorization."
        ),
        "baseline_produced_a_result": passed_gate,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Walk-forward baseline evaluation for a served model generation (reporting only -- never fits/binds a calibrator)"
    )
    ap.add_argument(
        "--model-version",
        required=True,
        help="e.g. v5_phase7. Required: pooling generations is a zero-fabrication violation (see repositories.fixtures.build_settled_predictions_query docstring).",
    )
    ap.add_argument(
        "--league",
        default=None,
        help="Canonical league id filter, e.g. EPL. Omit for all leagues.",
    )
    ap.add_argument(
        "--split-date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d"),
        default=None,
        help="YYYY-MM-DD. Evaluate only on settled predictions up to this date (get_settled_predictions(ended_at=...)).",
    )
    ap.add_argument(
        "--save-candidate",
        action="store_true",
        help="Write the evaluation report to backend/models/candidate/ (report only -- never writes a .pkl).",
    )
    args = ap.parse_args()

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        validation = asyncio.run(
            _evaluate(
                model_version=args.model_version,
                league=args.league,
                split_date=args.split_date,
            )
        )
        status = "EVALUATED"
    except Exception as exc:
        validation = {"skipped": True, "reason": str(exc)}
        status = "BLOCKED"

    report = {
        "report_kind": "candidate_baseline_evaluation",
        "generated_at": generated_at,
        "model_version": args.model_version,
        "league_filter": args.league,
        "split_date": args.split_date.strftime("%Y-%m-%d") if args.split_date else None,
        "status": status,
        "walk_forward_validation": validation,
        "next_step": _no_calibrator_binding_note(validation),
    }
    print(json.dumps(report, indent=2, sort_keys=True))

    if args.save_candidate:
        CANDIDATE_DIR.mkdir(parents=True, exist_ok=True)
        out = (
            CANDIDATE_DIR
            / f"candidate_baseline_evaluation_{args.model_version}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Saved: {out.relative_to(REPO_ROOT)}", file=sys.stderr)

    return 0 if status == "EVALUATED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
