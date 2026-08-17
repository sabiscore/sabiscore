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

from scripts.train_on_real_matches import build_dataset, load_matches  # noqa: E402
from src.models.promotion_evidence import (  # noqa: E402
    build_promotion_feature_evidence,
    render_promotion_feature_evidence_markdown,
    validate_promotion_feature_evidence,
)


def generate(cache_dir: Path) -> dict[str, Any]:
    """Build one mechanically derived rich feature-evidence report."""

    dataset = build_dataset(load_matches(cache_dir))
    report = build_promotion_feature_evidence(dataset)
    validate_promotion_feature_evidence(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=BACKEND_ROOT / "data" / "cache")
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--markdown-out", type=Path, required=True)
    args = parser.parse_args()

    report = generate(args.cache_dir)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(
        render_promotion_feature_evidence_markdown(report),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
