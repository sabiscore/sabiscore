"""The market baseline must be an OPENING quote, and must say so.

Two invariants, both currently asserted only in prose:

1. `train_on_real_matches._ODDS_COLUMNS` contains no closing-line column.
   `build_dataset`'s docstring explains why -- "serving fetches odds
   hours-to-days before kickoff and can never see a closing line for a future
   fixture, so training on closing prices would teach the model to lean on a
   systematically more-informed signal than serving can ever supply" -- but
   nothing enforced it. Adding `B365CH` to that tuple would silently introduce
   train/serve skew AND inflate the market bar the promotion gate is measured
   against.

2. The emitted evidence names which quote it used. Portfolio E measured the
   closing quote at 0.00085 RPS better than the opening one pooled -- larger
   than the candidate effects `market_baseline` adjudicates -- so a PASS/FAIL
   read without knowing the quote is ambiguous in a way that matters.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from train_on_real_matches import _ODDS_COLUMNS  # noqa: E402

# football-data.co.uk marks closing lines with a `C` after the bookmaker code
# (B365H -> B365CH, PSH -> PSCH) or a `_closing_` infix in the clean schema.
_CLOSING_MARKERS = ("B365C", "PSC", "MaxC", "AvgC", "BFEC", "_closing_")


def test_odds_columns_contain_no_closing_line():
    flat = [col for tier in _ODDS_COLUMNS for col in tier]
    offenders = [c for c in flat if any(marker in c for marker in _CLOSING_MARKERS)]
    assert offenders == [], (
        f"closing-line columns in _ODDS_COLUMNS: {offenders}. Serving can never "
        "see a closing price for a future fixture -- training on one is "
        "train/serve skew and inflates the market_baseline bar."
    )


def test_odds_columns_are_coherent_per_bookmaker_triples():
    # Each tier must be a complete (home, draw, away) triple from ONE
    # bookmaker. Mixing books inside a tier would de-vig an incoherent price.
    for tier in _ODDS_COLUMNS:
        assert len(tier) == 3


def test_market_baseline_quote_label_is_declared_as_opening():
    # The label the training script stamps onto its own evidence. Pinned so a
    # future change to _ODDS_COLUMNS cannot leave a stale "opening" claim
    # attached to a closing-line bar.
    source = (
        Path(__file__).resolve().parents[2] / "scripts" / "train_on_real_matches.py"
    ).read_text(encoding="utf-8")
    assert 'metrics["baseline_rps_market_quote"]' in source
    assert "opening_1x2" in source


def test_comparison_report_falls_back_rather_than_asserting_a_quote():
    # Training reports produced before the label existed must not be silently
    # assigned a quote they never recorded.
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "compare_candidate_vs_incumbent.py"
    ).read_text(encoding="utf-8")
    assert "unlabelled_pre_2026_09_report" in source
