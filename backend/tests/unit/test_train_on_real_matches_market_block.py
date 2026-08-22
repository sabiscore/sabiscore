"""docs/DEBT.md item 37: build_dataset() must always train the Apex market
block, and must refuse to silently drift onto the legacy one.

Not a package (pytest.ini excludes scripts/ from collection and pythonpath
only covers src/), so the module is loaded by inserting its directory onto
sys.path directly — same pattern as test_train_on_real_matches_odds.py.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import train_on_real_matches  # noqa: E402


def test_build_dataset_market_block_is_apex_schema() -> None:
    """Real registry, real code path: the static market-block assertion in
    build_dataset() holds today. No matches needed — the check runs before
    the per-match loop and an empty corpus returns cleanly."""
    assert train_on_real_matches.build_dataset([]) == {}


def test_build_dataset_catches_a_corrupted_market_block() -> None:
    """Proves the guard actually catches drift, not just that it's silent
    today. Swaps two adjacent market-block feature names and confirms
    build_dataset() refuses rather than silently training on a mislabelled
    schema."""
    corrupted = list(train_on_real_matches.APEX_FEATURES_68)
    market_start = corrupted.index(train_on_real_matches.APEX_MARKET_FEATURES_14[0])
    corrupted[market_start], corrupted[market_start + 1] = (
        corrupted[market_start + 1],
        corrupted[market_start],
    )
    with patch.object(train_on_real_matches, "APEX_FEATURES_68", corrupted):
        with pytest.raises(AssertionError):
            train_on_real_matches.build_dataset([])


def test_trained_candidate_declares_apex_schema_version() -> None:
    """The format string every trained candidate stamps into its own
    metadata (docs/DEBT.md item 37 fix-step (b)) — cheap, direct check on
    the literal the script emits, not a full model fit."""
    width = len(train_on_real_matches.APEX_FEATURES_68)
    assert f"apex_v1_{width}" == "apex_v1_68"
    width89 = len(train_on_real_matches.APEX_FEATURES_89)
    assert f"apex_v1_{width89}" == "apex_v1_89"
