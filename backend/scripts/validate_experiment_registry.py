"""Validate `reports/research/experiment_registry.yaml` against directive §38.

Why this exists
---------------
A registry that nothing checks drifts exactly the way the "Portfolio C" label
drifted: a study was filed under the wrong portfolio letter, three other
documents cited the wrong letter, two file paths went stale, and nothing
noticed for a day. §47 Action 9 says "no research result exists unless it is
reproducible from the registry" -- which is only true if the registry's own
pointers are known to resolve.

What it enforces
----------------
1. Every experiment declares the full §38 field set. A missing field is an
   error; an unrecorded one must say ``UNDECLARED`` out loud.
2. ``state`` is a §39 state, ``decision`` is a §51 decision, and
   ``source_license_class`` is a §12 class (or null).
3. ``experiment_id`` values are unique.
4. **Every provenance pointer resolves.** ``reports/...`` and ``backend/...``
   paths must exist on disk; ``docs/DEBT.md#N`` must name a real ledger item.
   This is the check that catches a rename nobody propagated.
5. No field is an empty string. Empty is not a declaration -- ``UNDECLARED``
   and ``null`` are the two honest ways to say "no value", and they mean
   different things.

Exit code 0 = valid, 1 = at least one error. Warnings never fail the run.

Usage
-----
    .venv/Scripts/python.exe backend/scripts/validate_experiment_registry.py
    .venv/Scripts/python.exe backend/scripts/validate_experiment_registry.py --strict
        (--strict also fails on warnings)
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "reports" / "research" / "experiment_registry.yaml"
DEBT_PATH = REPO_ROOT / "docs" / "DEBT.md"

# §38's field list, verbatim. Every experiment must carry all of them.
REQUIRED_FIELDS: tuple[str, ...] = (
    "experiment_id",
    "hypothesis",
    "information_source",
    "source_version",
    "source_license_class",
    "source_coverage",
    "historical_window",
    "prediction_cutoff",
    "dataset_version",
    "feature_version",
    "representation_version",
    "model_version",
    "parameters",
    "seed",
    "training_window",
    "validation_windows",
    "final_holdout",
    "baseline_models",
    "market_baseline",
    "primary_metrics",
    "secondary_metrics",
    "bootstrap_method",
    "statistical_test",
    "multiple_testing_family",
    "effect_size",
    "confidence_interval",
    "sample_size",
    "result",
    "robustness",
    "failure_modes",
    "compute",
    "peak_rss",
    "runtime",
    "decision",
    "artifact_location",
    "provenance",
    "reviewer",
    "certification_status",
)

UNDECLARED = "UNDECLARED"
DEBT_REF = re.compile(r"^docs/DEBT\.md#(\d+)$")


def _debt_item_numbers() -> set[int]:
    """Every `## N.` heading number present in the debt ledger."""
    if not DEBT_PATH.exists():
        return set()
    text = DEBT_PATH.read_text(encoding="utf-8", errors="replace")
    return {int(m) for m in re.findall(r"^## (\d+)\. ", text, flags=re.MULTILINE)}


def _check_provenance(
    entry_id: str, provenance: Any, debt_items: set[int]
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(provenance, list) or not provenance:
        errors.append(f"{entry_id}: provenance must be a non-empty list")
        return errors, warnings

    for ref in provenance:
        if not isinstance(ref, str) or not ref.strip():
            errors.append(f"{entry_id}: provenance entry is not a non-empty string")
            continue
        debt_match = DEBT_REF.match(ref)
        if debt_match:
            item = int(debt_match.group(1))
            if item not in debt_items:
                errors.append(
                    f"{entry_id}: provenance '{ref}' names a debt item that "
                    "does not exist in docs/DEBT.md"
                )
            continue
        # Path reference. Strip any trailing "§x" section pointer.
        path_part = ref.split(" §")[0].strip()
        if not (REPO_ROOT / path_part).exists():
            errors.append(
                f"{entry_id}: provenance path '{path_part}' does not exist on disk"
            )
    return errors, warnings


def validate(registry: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Pure -- does no I/O beyond path existence."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(registry, dict):
        return (
            [f"registry root must be a mapping, got {type(registry).__name__}"],
            warnings,
        )

    valid_states = set(registry.get("states") or [])
    valid_decisions = set(registry.get("decisions") or [])
    valid_licenses = set(registry.get("license_classes") or [])
    if not (valid_states and valid_decisions and valid_licenses):
        errors.append(
            "registry must declare non-empty 'states', 'decisions' and "
            "'license_classes' vocabularies"
        )

    experiments = registry.get("experiments")
    if not isinstance(experiments, list) or not experiments:
        errors.append("registry must declare a non-empty 'experiments' list")
        return errors, warnings

    debt_items = _debt_item_numbers()
    seen_ids: set[str] = set()
    undeclared_counts: dict[str, int] = {}

    for index, entry in enumerate(experiments):
        if not isinstance(entry, dict):
            errors.append(f"experiments[{index}] is not a mapping")
            continue
        entry_id = str(entry.get("experiment_id") or f"<experiments[{index}]>")

        if entry_id in seen_ids:
            errors.append(f"{entry_id}: duplicate experiment_id")
        seen_ids.add(entry_id)

        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            errors.append(f"{entry_id}: missing §38 field(s): {', '.join(missing)}")

        for field, value in entry.items():
            if isinstance(value, str) and not value.strip():
                errors.append(
                    f"{entry_id}: field '{field}' is an empty string. Use "
                    "UNDECLARED (not recorded) or null (not applicable)."
                )

        state = entry.get("state")
        if state is None:
            errors.append(f"{entry_id}: missing 'state' (§39)")
        elif valid_states and state not in valid_states:
            errors.append(f"{entry_id}: state '{state}' is not a §39 state")

        decision = entry.get("decision")
        if valid_decisions and decision is not None and decision not in valid_decisions:
            errors.append(f"{entry_id}: decision '{decision}' is not a §51 decision")

        license_class = entry.get("source_license_class")
        if (
            license_class is not None
            and valid_licenses
            and license_class not in valid_licenses
        ):
            errors.append(
                f"{entry_id}: source_license_class '{license_class}' is not a §12 class"
            )

        prov_errors, prov_warnings = _check_provenance(
            entry_id, entry.get("provenance"), debt_items
        )
        errors.extend(prov_errors)
        warnings.extend(prov_warnings)

        undeclared = sum(1 for f in REQUIRED_FIELDS if entry.get(f) == UNDECLARED)
        undeclared_counts[entry_id] = undeclared
        # A retrospectively migrated study is expected to have gaps. A NEW
        # experiment declaring half its fields UNDECLARED is a process failure,
        # because it could have recorded them at run time.
        if (
            not entry.get("migrated_retrospectively")
            and undeclared > len(REQUIRED_FIELDS) // 3
        ):
            warnings.append(
                f"{entry_id}: {undeclared} UNDECLARED fields on an experiment "
                "not marked migrated_retrospectively — record these at run time"
            )

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="fail on warnings too")
    parser.add_argument("--path", default=str(REGISTRY_PATH))
    args = parser.parse_args()

    path = pathlib.Path(args.path)
    if not path.exists():
        print(f"FAIL: registry not found at {path}")
        return 1

    registry = yaml.safe_load(path.read_text(encoding="utf-8"))
    errors, warnings = validate(registry)

    count = len(registry.get("experiments") or []) if isinstance(registry, dict) else 0
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")

    if errors or (args.strict and warnings):
        print(f"\nFAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"OK: {count} experiment(s) valid against §38 ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
