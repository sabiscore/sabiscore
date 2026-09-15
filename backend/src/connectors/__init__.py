"""Data connectors for SabiScore.

This package contains two generations of connectors that coexist
side-by-side:

V4 / Phase 9 candidate primitives (additive)
---------------------------------------------
Async-first, side-effect-free building blocks for the V4 source layer.
They can be introduced behind feature flags without modifying the Phase 8
inference path.

Quick import reference
~~~~~~~~~~~~~~~~~~~~~~~
.. code-block:: python

    # Odds normalisation + EV / CLV features (safe at request time)
    from src.connectors import (
        OddsMarketSnapshot,
        normalize_decimal_odds,
        implied_probabilities,
        power_method_probs,
        bookmaker_margin,
        compute_market_features,
    )

    # Source registry (config-driven catalogue)
    from src.connectors import build_source_registry, enabled_source_names

"""

# ---------------------------------------------------------------------------
# V4 / Phase 9 candidate primitives (additive)
# ---------------------------------------------------------------------------
from .odds_market import (
    OddsMarketSnapshot,
    bookmaker_margin,
    compute_market_features,
    implied_probabilities,
    is_complete_market,
    normalize_decimal_odds,
    power_method_probs,
)
from .source_registry import (
    SourceDescriptor,
    build_source_registry,
    enabled_source_names,
    offline_sources,
    registry_summary,
    request_time_safe_sources,
)

__all__ = [
    # Odds / market
    "OddsMarketSnapshot",
    "bookmaker_margin",
    "compute_market_features",
    "implied_probabilities",
    "is_complete_market",
    "normalize_decimal_odds",
    "power_method_probs",
    # Source registry
    "SourceDescriptor",
    "build_source_registry",
    "enabled_source_names",
    "offline_sources",
    "registry_summary",
    "request_time_safe_sources",
]
