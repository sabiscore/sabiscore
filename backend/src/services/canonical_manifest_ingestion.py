"""Fail-closed scraper manifest ingestion into canonical and legacy tables."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import League, Match, Team
from ..db.models import MarketSnapshot
from ..utils.season import canonical_season
from .canonical_identity_service import ensure_canonical_fixture
from .manifest_ingestion import ManifestValidationError, validate_manifest


COMPETITIONS: dict[str, tuple[str, str]] = {
    "EPL": ("Premier League", "England"),
    "CHAMPIONSHIP": ("Championship", "England"),
    "LA_LIGA": ("La Liga", "Spain"),
    "SERIE_A": ("Serie A", "Italy"),
    "BUNDESLIGA": ("Bundesliga", "Germany"),
    "LIGUE_1": ("Ligue 1", "France"),
    "EREDIVISIE": ("Eredivisie", "Netherlands"),
}


@dataclass
class IngestionReport:
    dry_run: bool
    manifest_version: str
    run_id: str
    fixtures_seen: int = 0
    fixtures_inserted: int = 0
    fixtures_existing: int = 0
    market_snapshots_inserted: int = 0
    market_snapshots_existing: int = 0
    feature_eligible: int = 0
    non_feature_eligible: int = 0
    competitions: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _parse_utc(row: dict[str, object]) -> datetime:
    raw_date = str(row.get("match_date") or "").strip()
    raw_time = str(row.get("match_time") or "").strip()
    source_timezone = str(row.get("source_timezone") or "").strip()
    if not raw_date or not raw_time or not source_timezone:
        raise ManifestValidationError(
            "fixture requires match_date, match_time, and source_timezone"
        )
    parsed: datetime | None = None
    for date_format in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(f"{raw_date} {raw_time}", f"{date_format} %H:%M")
            break
        except ValueError:
            continue
    if parsed is None:
        raise ManifestValidationError("fixture event timestamp is invalid")
    try:
        return parsed.replace(tzinfo=ZoneInfo(source_timezone)).astimezone(timezone.utc)
    except ZoneInfoNotFoundError as exc:
        raise ManifestValidationError("fixture source_timezone is unknown") from exc


def _provider_row_id(row: dict[str, object]) -> str:
    native = row.get("source_native_id")
    if isinstance(native, str) and native.strip():
        return native.strip()
    payload = "|".join(
        str(row.get(field) or "")
        for field in ("league", "match_date", "match_time", "home_team", "away_team")
    )
    # The fallback is content-derived, never run-derived, so reacquiring the
    # same source row remains idempotent across manifests.
    return f"fdco-{hashlib.sha256(payload.encode()).hexdigest()[:24]}"


def _legacy_team_id(competition: str, name: str) -> str:
    digest = hashlib.sha256(f"{competition}|{name.casefold()}".encode()).hexdigest()[:20]
    return f"fdco-team-{digest}"


def _fixture_payloads(paths: tuple[Path, ...]) -> list[Path]:
    return [path for path in paths if path.suffix == ".json" and "fixtures-" in path.name]


async def ingest_manifest(
    session: AsyncSession,
    *,
    manifest_path: Path,
    data_root: Path,
    commit: bool = False,
) -> IngestionReport:
    validated = validate_manifest(manifest_path, data_root=data_root)
    manifest = validated.manifest
    report = IngestionReport(
        dry_run=not commit,
        manifest_version=str(manifest["manifest_version"]),
        run_id=str(manifest["run_id"]),
    )
    acquired_at = datetime.fromisoformat(
        str(manifest["completed_at"]).replace("Z", "+00:00")
    ).astimezone(timezone.utc)
    provider = str(manifest["source_id"])

    try:
        for payload_path in _fixture_payloads(validated.payload_paths):
            rows = json.loads(payload_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ManifestValidationError("fixture payload must be a JSON array")
            for row in rows:
                if not isinstance(row, dict):
                    raise ManifestValidationError("fixture payload contains a non-object row")
                report.fixtures_seen += 1
                competition = str(row.get("league") or "")
                if competition not in COMPETITIONS:
                    raise ManifestValidationError(f"unknown competition: {competition or 'missing'}")
                home = str(row.get("home_team") or "").strip()
                away = str(row.get("away_team") or "").strip()
                if not home or not away or home.casefold() == away.casefold():
                    raise ManifestValidationError("fixture teams are missing or ambiguous")
                kickoff = _parse_utc(row)
                scores = (row.get("home_goals"), row.get("away_goals"))
                finished = all(isinstance(score, (int, float)) for score in scores)
                if finished and kickoff > acquired_at:
                    raise ManifestValidationError("finished fixture is future-dated at acquisition")

                competition_name, country = COMPETITIONS[competition]
                if await session.get(League, competition) is None:
                    session.add(League(id=competition, name=competition_name, country=country))
                home_id = _legacy_team_id(competition, home)
                away_id = _legacy_team_id(competition, away)
                for team_id, team_name in ((home_id, home), (away_id, away)):
                    if await session.get(Team, team_id) is None:
                        session.add(Team(id=team_id, name=team_name, league_id=competition))
                await session.flush()

                provider_event_id = _provider_row_id(row)
                legacy_id = provider_event_id
                existing_match = await session.get(Match, legacy_id)
                if existing_match is None:
                    session.add(Match(
                        id=legacy_id,
                        league_id=competition,
                        home_team_id=home_id,
                        away_team_id=away_id,
                        match_date=kickoff.replace(tzinfo=None),
                        season=canonical_season(kickoff),
                        status="finished" if finished else "scheduled",
                        home_score=int(scores[0]) if finished else None,
                        away_score=int(scores[1]) if finished else None,
                    ))
                    report.fixtures_inserted += 1
                else:
                    if (
                        existing_match.home_team_id != home_id
                        or existing_match.away_team_id != away_id
                        or existing_match.match_date != kickoff.replace(tzinfo=None)
                    ):
                        raise ManifestValidationError("duplicate fixture conflicts with persisted identity")
                    report.fixtures_existing += 1

                canonical_id = await ensure_canonical_fixture(
                    session,
                    provider=provider,
                    provider_event_id=provider_event_id,
                    competition_id=competition,
                    competition_name=competition_name,
                    home_provider_id=f"{competition}:{home.casefold()}",
                    home_name=home,
                    away_provider_id=f"{competition}:{away.casefold()}",
                    away_name=away,
                    kickoff_utc=kickoff,
                    season=canonical_season(kickoff),
                    status="finished" if finished else "scheduled",
                    evidence={
                        "source": provider,
                        "run_id": report.run_id,
                        "event_timestamp": kickoff.isoformat(),
                        "provider_timestamp": manifest.get("source_timestamp"),
                        "acquired_at": acquired_at.isoformat(),
                        "persisted_at": datetime.now(timezone.utc).isoformat(),
                        "manifest_version": manifest["manifest_version"],
                        "schema_version": manifest["schema_version"],
                    },
                )

                market = row.get("market")
                if market is not None:
                    if not isinstance(market, dict) or market.get("coherent") is not True:
                        raise ManifestValidationError("market evidence is not a coherent book")
                    odds = market.get("raw_odds")
                    probabilities = market.get("devigged_probabilities")
                    if not isinstance(odds, dict) or not isinstance(probabilities, dict):
                        raise ManifestValidationError("market book is incomplete")
                    values = [odds.get(key) for key in ("home", "draw", "away")]
                    probs = [probabilities.get(key) for key in ("home", "draw", "away")]
                    if not all(isinstance(value, (int, float)) and value > 1 for value in values):
                        raise ManifestValidationError("market odds are malformed")
                    if not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in probs):
                        raise ManifestValidationError("de-vigged probabilities are malformed")
                    if abs(sum(float(value) for value in probs) - 1.0) > 1e-6:
                        raise ManifestValidationError("de-vigged probabilities do not sum to one")
                    bookmaker = str(market.get("bookmaker") or "")
                    existing_market = (
                        await session.execute(
                            select(MarketSnapshot.id).where(
                                MarketSnapshot.canonical_fixture_id == canonical_id,
                                MarketSnapshot.provider == provider,
                                MarketSnapshot.bookmaker == bookmaker,
                                MarketSnapshot.captured_at == acquired_at.replace(tzinfo=None),
                            )
                        )
                    ).scalars().first()
                    if existing_market is None:
                        session.add(MarketSnapshot(
                            canonical_fixture_id=canonical_id,
                            match_id=legacy_id,
                            provider=provider,
                            bookmaker=bookmaker,
                            market_type="1X2",
                            home_odds=float(values[0]),
                            draw_odds=float(values[1]),
                            away_odds=float(values[2]),
                            home_implied_prob_devigged=float(probs[0]),
                            draw_implied_prob_devigged=float(probs[1]),
                            away_implied_prob_devigged=float(probs[2]),
                            is_closing_line=False,
                            provider_timestamp=None,
                            captured_at=acquired_at.replace(tzinfo=None),
                            coherent=True,
                            executable=False,
                            provenance={
                                "historical": True,
                                "run_id": report.run_id,
                                "source_row_index": row.get("source_row_index"),
                                "event_timestamp": kickoff.isoformat(),
                                "acquired_at": acquired_at.isoformat(),
                            },
                        ))
                        report.market_snapshots_inserted += 1
                    else:
                        report.market_snapshots_existing += 1

                eligible = finished and kickoff <= acquired_at
                report.feature_eligible += int(eligible)
                report.non_feature_eligible += int(not eligible)
                report.competitions[competition] = report.competitions.get(competition, 0) + 1

        if not report.fixtures_seen:
            raise ManifestValidationError("manifest contains no fixture payloads")
        if commit:
            await session.commit()
        else:
            await session.rollback()
        return report
    except Exception:
        await session.rollback()
        raise
