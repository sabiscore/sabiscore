"""D6 regression tests: /health/ready's capability probe must actually exercise the
live prediction pipeline (get_full_analysis), never just component liveness (INV-20).

get_next_upcoming_fixture / get_full_analysis are monkeypatched at the monitoring
module level — this module's own logic (fixture-found branching, AVAILABLE + identity
gating, exception handling, 15-minute cache) is what's under test, not the full
prediction stack those two functions front.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import Response

from src.api.endpoints import monitoring


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self.store[key] = value


_FIXTURE = SimpleNamespace(id="fd-1", league_id="epl")


async def test_no_upcoming_fixture_is_unverified_not_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _none())

    result = await monitoring._compute_capability(db=object())

    assert result["status"] == "unverified_no_fixtures"
    assert result["match_id"] is None


async def test_available_prediction_with_verified_identity_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _fixture())
    monkeypatch.setattr(
        monitoring,
        "get_full_analysis",
        lambda **k: _analysis("AVAILABLE", []),
    )

    result = await monitoring._compute_capability(db=object())

    assert result["status"] == "verified"
    assert result["match_id"] == "fd-1"


@pytest.mark.parametrize("prediction_status", ["REDUCED_EVIDENCE_BASELINE", "UNAVAILABLE"])
async def test_thin_evidence_is_unverified_not_failed(
    monkeypatch: pytest.MonkeyPatch, prediction_status: str
) -> None:
    """A fixture days out has no odds or lineups published yet, so the pipeline
    correctly fail-closes. It ran end-to-end — that is not an outage.

    Previously asserted "failed", which painted the readiness ring rose-400 for a
    healthy system. Rewritten deliberately: with the probe horizon now matching the
    14-day sync window, the most common probe subject is a distant fixture, so the
    old mapping would have reported a false outage on nearly every check.
    """
    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _fixture())
    monkeypatch.setattr(
        monitoring,
        "get_full_analysis",
        lambda **k: _analysis(prediction_status, []),
    )

    result = await monitoring._compute_capability(db=object())

    assert result["status"] == "unverified_insufficient_evidence"
    assert result["status"] != "failed"


async def test_probe_horizon_matches_the_fixture_sync_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe must not use a narrower horizon than the sync window, or it has
    nothing to test even when fixtures exist (observed in production 2026-08-08).
    """
    from src.services.fixture_sync_service import SYNC_HORIZON_DAYS

    seen: dict[str, object] = {}

    def _capture(*_args, **kwargs):
        seen.update(kwargs)
        return _none()

    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", _capture)

    await monitoring._compute_capability(db=object())

    assert seen["within_days"] == SYNC_HORIZON_DAYS


async def test_unverified_identity_is_failed_even_when_prediction_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _fixture())
    monkeypatch.setattr(
        monitoring,
        "get_full_analysis",
        lambda **k: _analysis("AVAILABLE", ["FIXTURE_IDENTITY_UNVERIFIED"]),
    )

    result = await monitoring._compute_capability(db=object())

    assert result["status"] == "failed"


async def test_pipeline_exception_is_reported_as_failed_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(monitoring, "cache", None)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _fixture())

    async def _raise(**_k):
        raise RuntimeError("prediction pipeline exploded")

    monkeypatch.setattr(monitoring, "get_full_analysis", _raise)

    result = await monitoring._compute_capability(db=object())

    assert result["status"] == "failed"
    assert "prediction pipeline exploded" in result["message"]


async def test_second_call_within_ttl_is_served_from_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cache = _FakeCache()
    monkeypatch.setattr(monitoring, "cache", fake_cache)
    monkeypatch.setattr(monitoring, "get_next_upcoming_fixture", lambda *a, **k: _fixture())

    calls = {"n": 0}

    async def _counted(**_k):
        calls["n"] += 1
        return {"prediction_status": "AVAILABLE", "evidence_quality": {"critical_gaps": []}}

    monkeypatch.setattr(monitoring, "get_full_analysis", _counted)

    first = await monitoring._check_capability(db=object())
    second = await monitoring._check_capability(db=object())

    assert calls["n"] == 1
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True
    assert second["status"] == "verified"


async def test_readiness_skips_capability_probe_when_core_checks_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = {"capability": 0}

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(monitoring, "engine", _BrokenEngine())
    monkeypatch.setattr(monitoring, "_check_alembic_revision", lambda: {"status": "ready"})

    class _ReadyCache:
        def production_ready(self) -> bool:
            return True

        def metrics_snapshot(self):
            return {
                "tier1_redis_enabled": False,
                "tier1_redis_available": False,
            }

    monkeypatch.setattr(monitoring, "cache", _ReadyCache())
    monkeypatch.setattr(
        monitoring,
        "_discover_model_artifacts",
        lambda: {"count": 1},
    )
    monkeypatch.setattr(
        monitoring,
        "_resolve_required_leagues",
        lambda: ["epl"],
    )

    app = SimpleNamespace(
        state=SimpleNamespace(
            models={"epl": SimpleNamespace(is_trained=True)},
            models_loaded=True,
            leagues_loaded=["epl"],
            model_version="v5_phase7",
            model_load_error_message=None,
            model_load_in_progress=False,
        )
    )
    request = SimpleNamespace(app=app)

    async def _counted(_db):
        called["capability"] += 1
        return {"status": "verified"}

    monkeypatch.setattr(monitoring, "_check_capability", _counted)

    response = Response()
    payload = await monitoring.readiness_check(request, response, db=object())

    assert response.status_code == 503
    assert called["capability"] == 0
    assert payload["capability"]["status"] == "skipped_not_ready"


async def _fixture():
    return _FIXTURE


async def _none():
    return None


async def _analysis(prediction_status: str, critical_gaps: list[str]) -> dict:
    return {
        "prediction_status": prediction_status,
        "evidence_quality": {"critical_gaps": critical_gaps},
    }
