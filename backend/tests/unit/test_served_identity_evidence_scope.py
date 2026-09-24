"""Live evidence must be attributed to the model that actually served it.

Every retrain keeps the family suffix ``v5_phase7``, and prediction logs stored
only that suffix. So the "current generation" scope in settlement, CLV and
calibration silently pooled distinct generations. On 2026-09-24 production
held 88 settled ``v5_phase7`` predictions, all logged by v5_phase7-20260808
(last log 2026-09-20), while /performance labelled them as evidence for
v5_phase7-20260922 (live from 2026-09-22). Even the generation name was not
enough: -20260808 shipped three artifact sets under one name, and -20260922
changed its served features (item 141) without changing an artifact byte.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.core.database import Base, Match
from src.db.models import MatchPredictionLog
from src.models import active_generation
from src.models.active_generation import (
    ActiveGenerationError,
    active_served_identity,
    load_active_generation,
    served_identity,
)
from src.repositories.fixtures import get_settled_predictions
from src.services import prediction_log_service
from src.services.prediction_log_service import (
    PredictionLogCapture,
    persist_prediction_log,
)

KICKOFF = datetime(2026, 10, 10, 15, 0, 0)

MANIFEST = {
    "schema_version": 1,
    "generation": "v5_phase7-20260922",
    "active_version": "v5_phase7",
    "feature_schema_version": "apex_v1_68",
    "served_head": "stacked_meta_model",
    "certification_state": "UNVERIFIED",
    "certified_at": None,
    "promotion_state": "ACTIVE_FAIL_CLOSED",
    "promoted_at": None,
    "artifacts": {
        "epl": {
            "artifact": "epl_ensemble_v5_phase7.pkl",
            "artifact_sha256": "a" * 64,
            "metadata": "epl_ensemble_v5_phase7.json",
            "metadata_sha256": "b" * 64,
            "required": True,
        }
    },
}


def _variant(**changes: object) -> dict:
    manifest = copy.deepcopy(MANIFEST)
    manifest.update(changes)
    return manifest


def _artifact_variant() -> dict:
    manifest = copy.deepcopy(MANIFEST)
    manifest["artifacts"]["epl"]["artifact_sha256"] = "c" * 64
    return manifest


@pytest.mark.parametrize(
    "changed",
    [
        _variant(generation="v5_phase7-20261001"),
        _variant(active_version="v6_phase8"),
        _variant(feature_schema_version="phase7_68"),  # item 141: same bytes
        _variant(served_head="base_learner_average"),
        _artifact_variant(),  # a retrain under the same name
    ],
    ids=["generation", "active_version", "feature_schema", "served_head", "artifact"],
)
def test_identity_changes_with_everything_that_changes_served_output(
    changed: dict,
) -> None:
    assert served_identity(changed) != served_identity(MANIFEST)


def test_identity_ignores_certification_and_promotion_metadata() -> None:
    # Flipping certification changes no prediction, so it must not split the
    # evidence a generation has accumulated.
    changed = _variant(
        certification_state="OPERATOR_OVERRIDE_UNCERTIFIED",
        certified_at="2026-10-01T00:00:00Z",
        promotion_state="PROMOTED",
        promoted_at="2026-10-01T00:00:00Z",
        operator_override={"authorizing_identity": "someone"},
    )
    assert served_identity(changed) == served_identity(MANIFEST)


def test_identity_names_the_generation() -> None:
    generation, digest = served_identity(MANIFEST).split("@")
    assert generation == "v5_phase7-20260922"
    assert len(digest) == 16


def test_verified_and_per_request_paths_agree_on_the_committed_manifest() -> None:
    # The verified copy carries machine-specific paths. If the identity were
    # derived from it, the writer and the readers would disagree on every host.
    assert load_active_generation()["served_identity"] == active_served_identity()


def test_unreadable_manifest_fails_closed(tmp_path) -> None:
    with pytest.raises(ActiveGenerationError):
        active_served_identity(tmp_path)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def manifest(monkeypatch):
    monkeypatch.setattr(
        prediction_log_service, "read_active_manifest", lambda: MANIFEST
    )
    return MANIFEST


async def _settled_match(session: AsyncSession, match_id: str) -> None:
    session.add(
        Match(
            id=match_id,
            league_id="EPL",
            home_team_id="t-home",
            away_team_id="t-away",
            match_date=KICKOFF,
            status="finished",
            home_score=2,
            away_score=0,
        )
    )
    await session.flush()


def _capture(match_id: str, model_version: str) -> PredictionLogCapture:
    return PredictionLogCapture(
        match_id=match_id,
        model_version=model_version,
        home_probability=0.5,
        draw_probability=0.3,
        away_probability=0.2,
        input_hash="same-inputs",
        evaluated_at=KICKOFF - timedelta(days=1),
    )


@pytest.mark.asyncio
async def test_writer_and_reader_agree_on_the_served_identity(
    session: AsyncSession, manifest: dict
) -> None:
    await _settled_match(session, "m-1")
    outcome = await persist_prediction_log(session, _capture("m-1", "v5_phase7"))
    assert outcome == "created"

    records = await get_settled_predictions(
        session, model_version=served_identity(manifest)
    )
    assert [r["probs"] for r in records] == [[0.5, 0.3, 0.2]]


@pytest.mark.asyncio
async def test_previous_generation_rows_are_not_current_evidence(
    session: AsyncSession, manifest: dict
) -> None:
    """The exact production state: legacy rows carry only the family suffix."""

    await _settled_match(session, "m-old")
    session.add(
        MatchPredictionLog(
            match_id="m-old",
            model_version="v5_phase7",
            created_at=KICKOFF - timedelta(days=1),
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
        )
    )
    await session.flush()

    records = await get_settled_predictions(
        session, model_version=served_identity(manifest)
    )
    assert records == []


@pytest.mark.asyncio
async def test_new_generation_is_not_dropped_as_a_duplicate_of_an_old_row(
    session: AsyncSession, manifest: dict
) -> None:
    await _settled_match(session, "m-1")
    session.add(
        MatchPredictionLog(
            match_id="m-1",
            model_version="v5_phase7",
            input_hash="same-inputs",
            created_at=KICKOFF - timedelta(days=2),
            home_probability=0.4,
            draw_probability=0.3,
            away_probability=0.3,
        )
    )
    await session.flush()

    outcome = await persist_prediction_log(session, _capture("m-1", "v5_phase7"))
    assert outcome == "created"


@pytest.mark.asyncio
async def test_a_foreign_family_is_not_stamped_as_the_served_model(
    session: AsyncSession, manifest: dict
) -> None:
    await _settled_match(session, "m-1")
    await persist_prediction_log(session, _capture("m-1", "v6_phase8"))

    stored = (await session.execute(select(MatchPredictionLog.model_version))).scalars()
    assert list(stored) == ["v6_phase8"]


@pytest.mark.asyncio
async def test_an_unreadable_manifest_refuses_to_log(
    session: AsyncSession, monkeypatch
) -> None:
    def _unreadable() -> dict:
        raise ActiveGenerationError("manifest unavailable")

    monkeypatch.setattr(prediction_log_service, "read_active_manifest", _unreadable)
    await _settled_match(session, "m-1")

    outcome = await persist_prediction_log(session, _capture("m-1", "v5_phase7"))
    assert outcome == "ineligible"
    stored = (await session.execute(select(MatchPredictionLog.id))).scalars()
    assert list(stored) == []


def test_module_exports_the_identity_api() -> None:
    for name in ("served_identity", "active_served_identity", "read_active_manifest"):
        assert name in active_generation.__all__
