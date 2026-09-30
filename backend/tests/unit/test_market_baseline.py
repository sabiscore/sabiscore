"""Compatibility alias for market baseline unit tests (Directive V13 Verification Matrix).

Aggregates test_market_baseline_shin and test_market_baseline_quote_contract
so running `pytest backend/tests/unit/test_market_baseline.py` executes the full suite.
"""

from .test_market_baseline_quote_contract import *  # noqa: F401, F403
from .test_market_baseline_shin import *  # noqa: F401, F403
