"""Contract tests for the staleness split and the live-market wiring.

Two defects both showed up as a permanent critical gap on every fixture:

1. ``staleness_seconds`` measures only the offline StatsBomb enrichment parquet
   (frozen 2024-06-02), but was compared against the league's 3600s *live-feature*
   TTL and emitted as STALE_REQUIRED_EVIDENCE — a critical gap. It therefore fired
   on 100% of requests forever, forcing PARTIAL / no bet regardless of evidence.
2. ``live["odds"]`` was never populated on any success path, so
   ``_odds_edge_from_features`` always returned None and
   COHERENT_1X2_MARKET_UNAVAILABLE was likewise unconditional.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.api.endpoints import full_analysis as endpoint
from src.services.upcoming_match_feature_service import _model_input_staleness_seconds


# --------------------------------------------------------------------------- #
# Model-input staleness — the measure that keeps the critical gate
# --------------------------------------------------------------------------- #


def _ts(days_ago: float) -> float:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).timestamp()


def test_model_input_staleness_is_none_when_no_history_on_either_side():
    """Absent inputs are REQUIRED_MODEL_INPUTS_UNAVAILABLE, not a staleness case."""
    assert _model_input_staleness_seconds(None, None) is None
    assert _model_input_staleness_seconds({}, {}) is None


def test_model_input_staleness_uses_the_older_of_the_two_sides():
    """Both sides must be usable, so the weaker side governs."""
    home = {"last_finished_match_ts": _ts(2)}
    away = {"last_finished_match_ts": _ts(30)}
    staleness = _model_input_staleness_seconds(home, away)
    assert staleness is not None
    assert 29 * 86400 < staleness < 31 * 86400


def test_model_input_staleness_never_negative_for_a_future_timestamp():
    assert (
        _model_input_staleness_seconds({"last_finished_match_ts": _ts(-5)}, None) == 0.0
    )


# --------------------------------------------------------------------------- #
# The gate split, through the real endpoint
# --------------------------------------------------------------------------- #


def _live(**overrides) -> dict:
    base = {
        "features": [0.0] * 58,
        "features_dict": {},
        "data_gaps": [],
        "critical_gaps": [],
        "advisory_gaps": [],
        "conflicts": [],
        "fixture_identity_verified": True,
        "identity_resolution": {"home_team_resolved": True, "away_team_resolved": True},
        "data_quality": {"is_synthetic": False},
        "is_reduced_evidence_baseline": False,
        # ~811 days — the real production value from the frozen StatsBomb parquet.
        "staleness_seconds": 70_021_110,
        "model_input_staleness_seconds": 3 * 86400,  # form from 3 days ago
        "league": "EPL",
        "home_team": "Arsenal FC",
        "away_team": "Chelsea FC",
        "odds": None,
    }
    base.update(overrides)
    return base


class _ValidPredictionEngine:
    async def predict(self, **_kwargs):
        return SimpleNamespace(
            to_dict=lambda: {
                "home_win": 0.45,
                "draw": 0.28,
                "away_win": 0.27,
                "model_version": "v5_phase7",
                "calibration_method": "isotonic",
            }
        )


def _install(monkeypatch, live: dict, *, odds=None):
    class FakeProjector:
        def __init__(self, **_kwargs):
            pass

        async def build_live_feature_vector(self, **_kwargs):
            return live

    async def _fake_odds(**_kwargs):
        return odds

    monkeypatch.setattr(endpoint, "UpcomingMatchFeatureProjector", FakeProjector)
    monkeypatch.setattr(endpoint, "PredictionEngine", _ValidPredictionEngine)
    monkeypatch.setattr(endpoint, "cache", None)
    monkeypatch.setattr(endpoint, "_fetch_market_odds", _fake_odds)


@pytest.mark.asyncio
async def test_stale_enrichment_is_advisory_and_never_blocks(monkeypatch):
    """An 811-day-old enrichment artifact must not force PARTIAL when the model's
    own inputs are fresh. This is the regression that kept every fixture at no-bet."""
    _install(monkeypatch, _live())

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )
    quality = payload["evidence_quality"]

    assert "STALE_ENRICHMENT_EVIDENCE" in quality["advisory_gaps"]
    assert "STALE_REQUIRED_EVIDENCE" not in quality["critical_gaps"]


@pytest.mark.asyncio
async def test_genuinely_old_model_inputs_still_force_a_critical_gap(monkeypatch):
    """Form older than a full season describes a different squad — still critical."""
    _install(monkeypatch, _live(model_input_staleness_seconds=500 * 86400))

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )
    assert "STALE_REQUIRED_EVIDENCE" in payload["evidence_quality"]["critical_gaps"]


@pytest.mark.asyncio
async def test_absent_model_input_staleness_does_not_invent_a_gap(monkeypatch):
    """No history at all is reported as missing inputs, never as stale ones."""
    _install(monkeypatch, _live(model_input_staleness_seconds=None))

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )
    assert "STALE_REQUIRED_EVIDENCE" not in payload["evidence_quality"]["critical_gaps"]


# --------------------------------------------------------------------------- #
# Live market wiring
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_market_gap_clears_when_a_coherent_price_is_available(monkeypatch):
    """The whole point of wiring the odds fetch: with a real market the edge is
    computed and COHERENT_1X2_MARKET_UNAVAILABLE stops firing."""
    # Priced so the model genuinely disagrees with the market on the home side:
    # de-vigged fair home prob is ~0.390 against a model prob of 0.45, and
    # EV = 0.45 * 2.50 - 1 = +0.125. An edge only exists when both hold — a market
    # that merely differs is not a signal.
    _install(
        monkeypatch,
        _live(),
        odds={"home_win": 2.50, "draw": 3.30, "away_win": 3.10},
    )

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )
    assert (
        "COHERENT_1X2_MARKET_UNAVAILABLE"
        not in payload["evidence_quality"]["critical_gaps"]
    )
    assert payload["odds_edge"] is not None


@pytest.mark.asyncio
async def test_market_gap_still_fires_when_no_price_exists(monkeypatch):
    """Fail closed — an odds outage must not fabricate an edge."""
    _install(monkeypatch, _live(), odds=None)

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )
    assert (
        "COHERENT_1X2_MARKET_UNAVAILABLE"
        in payload["evidence_quality"]["critical_gaps"]
    )
    assert payload["odds_edge"] is None


@pytest.mark.asyncio
async def test_fetch_market_odds_degrades_to_none_on_provider_failure(monkeypatch):
    """A market is optional evidence; an outage degrades the analysis, never breaks it."""

    class Boom:
        async def get_match_odds(self, **_kwargs):
            raise RuntimeError("provider down")

    import src.services.odds_service as odds_module

    monkeypatch.setattr(odds_module, "OddsService", lambda *a, **k: Boom())
    result = await endpoint._fetch_market_odds(
        home_team="Arsenal FC", away_team="Chelsea FC", league="EPL"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_market_odds_rejects_the_services_unavailable_shape(monkeypatch):
    """OddsService returns a sentinel dict rather than raising when no market exists."""

    class Unavailable:
        async def get_match_odds(self, **_kwargs):
            return {
                "source": "unavailable",
                "reason": "coherent_1x2_market_snapshot_not_found",
            }

    import src.services.odds_service as odds_module

    monkeypatch.setattr(odds_module, "OddsService", lambda *a, **k: Unavailable())
    result = await endpoint._fetch_market_odds(
        home_team="Arsenal FC", away_team="Chelsea FC", league="EPL"
    )
    assert result is None


@pytest.mark.asyncio
async def test_fetch_market_odds_skips_lookup_without_team_names():
    assert (
        await endpoint._fetch_market_odds(home_team=None, away_team="X", league="EPL")
        is None
    )


# --------------------------------------------------------------------------- #
# Directive v9 U1: "no value at this price" is not "no market"
# --------------------------------------------------------------------------- #

# The model agrees with the market exactly, with a 6% book margin on top:
# de-vigged fair probabilities equal the model's, so no outcome has positive EV.
_FAIR_PRICED = {
    outcome: 1.0 / (p * 1.06)
    for outcome, p in (("home_win", 0.45), ("draw", 0.28), ("away_win", 0.27))
}


@pytest.mark.asyncio
async def test_a_coherent_market_without_value_is_not_reported_missing(monkeypatch):
    """COHERENT_1X2_MARKET_UNAVAILABLE fired whenever odds_edge was None, which
    also covers a coherent market with no positive-EV outcome. That reported
    PASS ("no value at this price") as WITHHELD ("no market")."""
    _install(monkeypatch, _live(), odds=_FAIR_PRICED)

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )

    assert "COHERENT_1X2_MARKET_UNAVAILABLE" not in payload["evidence_quality"]["critical_gaps"]
    assert payload["odds_edge"] is None
    assert payload["field_availability"]["market"] is True
    # Still no stake: the gap used to be what held the gate closed here.
    assert payload["stake_permitted"] is False
    assert payload["rl_recommendation"]["abstain"] is True
    market = payload["market"]
    assert [row["outcome"] for row in market["outcomes"]] == ["home_win", "draw", "away_win"]
    assert market["overround"] == pytest.approx(1.06)
    assert [row["fair"] for row in market["outcomes"]] == pytest.approx([0.45, 0.28, 0.27])
    _validates(payload)


@pytest.mark.asyncio
async def test_an_uncertified_generation_never_publishes_expected_value(monkeypatch):
    _install(
        monkeypatch,
        _live(),
        odds={"home_win": 2.50, "draw": 3.30, "away_win": 3.10},
    )

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )

    assert payload["market"]["evaluable"] is False
    assert all(row["expected_value"] is None for row in payload["market"]["outcomes"])
    # The model-vs-fair gap is still shown (neutral) for a WITHHELD fixture.
    assert payload["market"]["outcomes"][0]["edge"] == pytest.approx(0.45 - 0.39, abs=0.01)
    _validates(payload)


@pytest.mark.asyncio
async def test_the_first_sighting_is_read_for_the_same_fixture_and_bookmaker(monkeypatch):
    """Directive v10 U6: the counter-case's price-movement line comes from the
    earliest captured price of the SAME book for this fixture."""
    kickoff = "2026-10-09T18:00:00+00:00"
    _install(
        monkeypatch,
        _live(kickoff_utc=kickoff),
        odds={"home_win": 2.50, "draw": 3.30, "away_win": 3.10, "bookmaker": "pinnacle"},
    )
    seen = {
        "bookmaker": "pinnacle",
        "captured_at": "2026-10-09T13:00:00+00:00",
        "home_win": 2.40,
        "draw": 3.40,
        "away_win": 3.20,
    }
    calls = []

    async def _recorded(_db, **kwargs):
        calls.append(kwargs)
        return seen

    monkeypatch.setattr(endpoint, "_first_sighting", _recorded)

    payload = await endpoint.get_full_analysis("real-fixture-1", league="EPL", db=object())

    assert calls == [
        {
            "match_id": "real-fixture-1",
            "bookmaker": "pinnacle",
            "kickoff": endpoint._utc_aware_datetime(kickoff),
        }
    ]
    assert payload["market"]["first_seen"] == seen
    _validates(payload)


def _validates(payload: dict) -> None:
    """The route declares this schema as its response_model; hold the payload to it."""
    from src.schemas.full_analysis import FullMatchAnalysisResponseSchema

    FullMatchAnalysisResponseSchema.model_validate(payload)


def test_market_block_publishes_expected_value_only_when_evaluable():
    probs = {"home_win": 0.45, "draw": 0.28, "away_win": 0.27}
    odds = {"home_win": 2.50, "draw": 3.30, "away_win": 3.10}

    withheld = endpoint._market_block(odds, model_probs=probs, evaluable=False)
    evaluable = endpoint._market_block(odds, model_probs=probs, evaluable=True)
    no_forecast = endpoint._market_block(odds, model_probs=None, evaluable=True)

    assert [r["expected_value"] for r in withheld["outcomes"]] == [None, None, None]
    assert evaluable["outcomes"][0]["expected_value"] == pytest.approx(0.45 * 2.50 - 1)
    # No forecast: market facts only, never a gap against the diagnostic prior.
    assert no_forecast["evaluable"] is False
    assert all(r["model_prob"] is None and r["edge"] is None for r in no_forecast["outcomes"])
    assert endpoint._market_block({"home_win": 1.0, "draw": 3, "away_win": 3}, model_probs=probs, evaluable=True) is None


def test_schema_refuses_expected_value_on_a_non_evaluable_market():
    from src.schemas.full_analysis import FullMatchMarketResponse

    block = endpoint._market_block(
        {"home_win": 2.50, "draw": 3.30, "away_win": 3.10},
        model_probs={"home_win": 0.45, "draw": 0.28, "away_win": 0.27},
        evaluable=True,
    )
    block["evaluable"] = False
    with pytest.raises(ValueError, match="only when evaluable"):
        FullMatchMarketResponse.model_validate(block)


@pytest.mark.asyncio
async def test_no_value_at_the_price_abstains_even_with_every_gate_open(monkeypatch):
    """With the old false gap gone, the explicit no-value abstain is what keeps a
    stake off a market where no outcome has positive EV. Open every other gate
    (certified generation, a measured uncertainty) so only that guard remains."""
    from src.services.uncertainty_service import UncertaintyBreakdown

    async def _measured(*_args, **_kwargs):
        return UncertaintyBreakdown(0.05, 0.2, 10.0, (0.35, 0.55))

    _install(monkeypatch, _live(), odds=_FAIR_PRICED)
    monkeypatch.setattr(endpoint, "active_generation_is_certified", lambda: True)
    monkeypatch.setattr(endpoint, "_uncertainty_from_features", _measured)

    payload = await endpoint.get_full_analysis(
        "real-fixture-1", league="EPL", db=object()
    )

    assert payload["evidence_quality"]["critical_gaps"] == []
    assert payload["rl_recommendation"]["abstain"] is True
    assert payload["rl_recommendation"]["reason"] == (
        "Abstained: no outcome offers value at the current price"
    )
    assert payload["stake_permitted"] is False
    # Evaluable (PASS): the negative expected return is shown, not withheld.
    assert payload["market"]["evaluable"] is True
    assert all(r["expected_value"] < 0 for r in payload["market"]["outcomes"])
    _validates(payload)
