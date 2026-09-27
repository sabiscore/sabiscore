"""C6 was frozen on 2026-09-27 (O8). The registry records the protocol's sha256;
any edit to the frozen protocol, or a registry entry naming another hash, fails
here. Changing the protocol after freezing is forbidden by the protocol itself."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "reports/research/c6-served-generation-vs-close-protocol.json"
REGISTRY = REPO / "reports/research/experiment_registry.yaml"


def _c6_entry() -> str:
    text = REGISTRY.read_text(encoding="utf-8")
    start = text.index("- experiment_id: C6")
    end = text.find("\n  - experiment_id:", start + 1)
    return text[start : end if end != -1 else None]


def test_the_registry_records_the_frozen_protocols_hash() -> None:
    digest = hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()
    recorded = re.findall(r"\b[0-9a-f]{64}\b", _c6_entry())
    assert digest in recorded, "C6 protocol changed after freezing, or the registry names another hash"


def test_the_protocol_is_pre_registered_with_the_operators_answers() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["status"].startswith("PRE-REGISTERED")
    assert protocol["approval"]["approved_at"] == "2026-09-27"
    assert set(protocol["approval"]["answers"]) == {
        "a_writers", "b_replicates_seed", "c_sample_cut", "d_interim_display", "e_closing_book", "f_looks",
    }
    assert (protocol["inference"]["replicates"], protocol["inference"]["seed"]) == (10000, 42)
    assert "capture_trigger='interactive_full_analysis'" in protocol["inference"]["exact_call"]
    assert "alpha=0.05 / 3" in protocol["inference"]["exact_call"]
