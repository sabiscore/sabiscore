#!/usr/bin/env python3
"""Generate deterministic candidate train/serve promotion evidence.

The report is derived from the exact candidate matrices produced by
``train_on_real_matches.build_dataset`` and the current positional serving
contract. It is evidence only: generation never promotes a model, alters
certification state, or changes production data.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.train_on_real_matches import _SCHEMAS, build_dataset, load_matches  # noqa: E402
from src.models.feature_registry import resolve_feature_schema  # noqa: E402
from src.models.promotion_evidence import (  # noqa: E402
    build_promotion_feature_evidence,
    render_promotion_feature_evidence_markdown,
    validate_promotion_feature_evidence,
)

_DEFAULT_SCHEMA = "apex_v1_68"


def generate(cache_dir: Path, schema: str = _DEFAULT_SCHEMA) -> dict[str, Any]:
    """Build one mechanically derived rich feature-evidence report.

    ``schema`` must name a contract registered in
    ``feature_registry.FEATURE_SCHEMA_VERSIONS``; the candidate matrices and the
    contract the evidence is scored against are then guaranteed to be the same
    list, rather than the second being assumed to be APEX_FEATURES_68.

    ⚠️ A candidate WIDER than the active generation's serving contract (e.g.
    apex_v2_71 against a 68-wide active generation) necessarily reports its
    extra positions as SCHEMA_MISMATCH, because serving has nothing at those
    positions yet. That is the honest reading, not a defect: the gate can only
    clear once `active_generation.json` declares the wider contract, which is
    itself a promotion decision.
    """

    dataset = build_dataset(load_matches(cache_dir), schema=schema)
    contract = resolve_feature_schema(schema)
    report = build_promotion_feature_evidence(dataset, candidate_features=contract)
    validate_promotion_feature_evidence(report, candidate_features=contract)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=BACKEND_ROOT / "data" / "cache")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    parser.add_argument("--schema", choices=sorted(_SCHEMAS), default=_DEFAULT_SCHEMA)
    args = parser.parse_args()

    report = generate(args.cache_dir, args.schema)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(
        render_promotion_feature_evidence_markdown(report),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
