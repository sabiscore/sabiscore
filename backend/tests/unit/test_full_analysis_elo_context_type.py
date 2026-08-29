"""Regression: the production Elo context must survive the endpoint's type gate.

`full_analysis` reads `live["elo_context"]` and keeps it only when it passes an
`isinstance` check. Two field-identical context types exist:

* `services.elo_state_service.DurableEloContext` -- what the live projector
  returns, backed by the PostgreSQL ``elo_rating_snapshots`` table (the
  production authority).
* `data.elo_engine.EloContext` -- the offline Parquet research engine.

The gate originally named only the legacy type, so every resolved production
rating was discarded and ``elo_ratings`` was reported as a data gap on every
fixture -- while ``elo.lookup.resolved`` read 100% in production metrics. The
symptom was indistinguishable from genuinely absent Elo history, which is why
it survived the sweep that added the identity-based gate in the first place.
"""

from __future__ import annotations

import inspect

from src.api.endpoints import full_analysis as fa
from src.data.elo_engine import EloContext
from src.services.elo_state_service import DurableEloContext


def _durable() -> DurableEloContext:
    return DurableEloContext(
        home_elo=1612.0,
        away_elo=1498.0,
        elo_difference=114.0,
        home_elo_trend_5=4.5,
        away_elo_trend_5=-2.0,
        elo_momentum_cross=6.5,
        home_resolved=True,
        away_resolved=True,
    )


def test_the_endpoint_gate_accepts_the_production_elo_context() -> None:
    """The exact predicate the endpoint applies to ``live['elo_context']``."""
    source = inspect.getsource(fa)
    assert "isinstance(elo_candidate, (EloContext, DurableEloContext))" in source, (
        "full_analysis must accept DurableEloContext -- the type the live "
        "projector actually returns -- or every resolved rating is dropped"
    )


def test_both_context_types_satisfy_the_gate() -> None:
    accepted = (EloContext, DurableEloContext)
    assert isinstance(_durable(), accepted)
    assert isinstance(
        EloContext(
            home_elo=1500.0,
            away_elo=1500.0,
            elo_difference=0.0,
            home_elo_trend_5=0.0,
            away_elo_trend_5=0.0,
            elo_momentum_cross=0.0,
            home_resolved=True,
            away_resolved=True,
        ),
        accepted,
    )


def test_the_two_context_types_stay_field_compatible() -> None:
    """Consumers read these fields off either type without conversion.

    ``intelligence_synthesizer`` is annotated against the legacy type but is
    handed the durable one, so a field added to only one of them would fail at
    runtime rather than at the gate.
    """
    shared = {
        "home_elo",
        "away_elo",
        "elo_difference",
        "home_elo_trend_5",
        "away_elo_trend_5",
        "elo_momentum_cross",
        "home_resolved",
        "away_resolved",
    }
    for context_type in (EloContext, DurableEloContext):
        fields = set(getattr(context_type, "__dataclass_fields__", {}))
        missing = shared - fields
        assert not missing, f"{context_type.__name__} is missing {sorted(missing)}"
        assert hasattr(context_type, "resolved")


def test_a_durable_context_reports_resolution_from_both_sides() -> None:
    assert _durable().resolved is True
    one_side = DurableEloContext(
        home_elo=1612.0,
        away_elo=1500.0,
        elo_difference=112.0,
        home_elo_trend_5=4.5,
        away_elo_trend_5=0.0,
        elo_momentum_cross=4.5,
        home_resolved=True,
        away_resolved=False,
    )
    assert one_side.resolved is False
