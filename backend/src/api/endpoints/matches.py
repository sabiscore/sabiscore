"""
Match endpoints for fetching upcoming matches and historical data
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, and_
from sqlalchemy.orm import selectinload
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import logging

from ...db.session import get_async_session
from ...db.models import Match, Odds
from ...schemas.match import (
    MatchSummary,
    MatchListResponse,
    MatchDetailResponse
)
from ...schemas.responses import MatchSearchResponse
from ...core.cache import cache_manager
from ...core.config import settings
from ...services.upcoming_match_service import UpcomingMatchService
from ...services.odds_service import OddsService, get_odds_service
from ...utils.mock_data import mock_generator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/matches", tags=["matches"])

@router.get("/upcoming", response_model=MatchListResponse)
async def get_upcoming_matches(
    league: Optional[str] = Query(None, description="Filter by league (epl, bundesliga, laliga, etc)"),
    days_ahead: int = Query(7, ge=1, le=30, description="Number of days to look ahead"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of matches to return"),
    db: AsyncSession = Depends(get_async_session),
    odds_service: OddsService = Depends(get_odds_service),
):
    """
    Get upcoming matches for predictions
    
    Returns matches scheduled within the next N days, optionally filtered by league.
    Results are cached for 5 minutes to optimize performance.
    """
    try:
        upcoming_match_service = UpcomingMatchService(odds_service=odds_service)
        # API-first upcoming fixtures with DB fallback
        service_payload = await upcoming_match_service.get_upcoming_matches(
            db=db,
            league=league,
            days_ahead=days_ahead,
            limit=limit,
        )

        if service_payload.get("matches"):
            match_responses = [
                MatchSummary(
                    id=str(m.get("match_id") or m.get("id") or ""),
                    home_team=m["home_team"],
                    away_team=m["away_team"],
                    league=m["league"],
                    match_date=datetime.fromisoformat(m["match_date"].replace("Z", "+00:00")) if isinstance(m.get("match_date"), str) and m.get("match_date") else datetime.now(timezone.utc),
                    venue=m.get("venue"),
                    status=m.get("status", "scheduled"),
                    has_odds=bool(m.get("has_odds", False)),
                )
                for m in service_payload["matches"]
            ]

            return MatchListResponse(
                matches=match_responses,
                total=service_payload.get("total", len(match_responses)),
                league_filter=league,
                date_range_days=days_ahead,
                source=service_payload.get("source"),
            )

        # Check cache first
        cache_key = f"upcoming_matches:{league}:{days_ahead}:{limit}"
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            logger.info("Cache hit for upcoming matches", extra={"league": league})
            return MatchListResponse(**cached_result) if isinstance(cached_result, dict) else cached_result
        
        # Use mock data for development
        if settings.mock_mode:
            logger.info("Using mock data generator for matches")
            mock_matches = mock_generator.generate_upcoming_matches(days=days_ahead, count=limit)
            
            # Filter by league if specified
            if league:
                mock_matches = [m for m in mock_matches if m['league'].upper() == league.upper()]
            
            # Transform to response format
            match_responses = [
                MatchSummary(
                    id=m['id'],
                    home_team=m['home_team'],
                    away_team=m['away_team'],
                    league=m['league'],
                    match_date=m['match_date'],
                    venue=m['venue'],
                    status=m['status'],
                    has_odds=True,
                )
                for m in mock_matches
            ]
            
            response = MatchListResponse(
                matches=match_responses,
                total=len(match_responses),
                league_filter=league,
                date_range_days=days_ahead,
                source="mock",
            )
            
            # Cache for 5 minutes
            cache_manager.set(cache_key, response, ttl=300)
            
            logger.info(f"Generated {len(match_responses)} mock matches (league={league})")
            return response
        
        # Calculate date range
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # ponytail: match_date is TIMESTAMP WITHOUT TIME ZONE
        end_date = now + timedelta(days=days_ahead)
        
        # Build query
        query = (
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.league),
            )
            .where(
                and_(
                    Match.match_date >= now,
                    Match.match_date <= end_date,
                    Match.status == "scheduled",
                )
            )
            .order_by(Match.match_date.asc())
            .limit(limit)
        )

        if league:
            query = query.where(func.lower(Match.league_id) == league.lower())

        # Execute query
        result = await db.execute(query)
        matches = result.scalars().unique().all()

        odds_map = await _fetch_latest_odds(db, [str(match.id) for match in matches if match.id])

        # Transform to response format
        match_responses = []
        for match in matches:
            match_responses.append(
                MatchSummary(
                    id=str(match.id),
                    home_team=match.home_team.name if match.home_team else match.home_team_id,
                    away_team=match.away_team.name if match.away_team else match.away_team_id,
                    league=match.league.name if match.league else match.league_id,
                    match_date=match.match_date,
                    venue=match.venue,
                    status=match.status or "scheduled",
                    has_odds=str(match.id) in odds_map,
                )
            )

        response = MatchListResponse(
            matches=match_responses,
            total=len(match_responses),
            league_filter=league,
            date_range_days=days_ahead,
            source="database",
        )

        # Cache for 5 minutes
        cache_manager.set(cache_key, response, ttl=300)
        
        logger.info(f"Fetched {len(match_responses)} upcoming matches (league={league})")
        return response
        
    except Exception as e:
        logger.error(f"Error fetching upcoming matches: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch upcoming matches")


@router.get("/search", response_model=List[MatchSearchResponse])
async def search_matches(
    q: str = Query(..., description="Search query for teams or matches", min_length=2),
    league: Optional[str] = Query(None, description="Filter by league"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results to return"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Search for matches with filtering and caching.
    
    Searches team names for matches containing the query string.
    """
    query_text = q.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cache_key = f"matches:search:{query_text.lower()}:{league or '*'}:{limit}"
    cached_results = cache_manager.get(cache_key)
    if cached_results is not None:
        return [MatchSearchResponse(**item) for item in cached_results]

    try:
        # Build query with async SQLAlchemy
        query = (
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
            )
        )
        
        # Can't use OR easily with relationships in async, so fetch all and filter
        result = await db.execute(query.limit(500))
        all_matches = result.scalars().all()
        
        results = []
        for match in all_matches:
            home_name = match.home_team.name if match.home_team else match.home_team_id or ""
            away_name = match.away_team.name if match.away_team else match.away_team_id or ""
            match_league = match.league_id or ""
            
            # Filter by team name
            if query_text.lower() not in home_name.lower() and query_text.lower() not in away_name.lower():
                continue
            
            # Filter by league if specified
            if league and match_league.lower() != league.lower():
                continue
                
            results.append(
                MatchSearchResponse(
                    id=str(match.id),
                    home_team=home_name,
                    away_team=away_name,
                    league=match_league,
                    match_date=match.match_date.isoformat() if match.match_date else "",
                    venue=match.venue or "",
                )
            )
            
            if len(results) >= limit:
                break

        # Cache for 5 minutes
        payload = [r.model_dump() for r in results]
        cache_manager.set(cache_key, payload, ttl=300)
        
        logger.info(f"Search '{query_text}' returned {len(results)} matches")
        return results

    except Exception:
        logger.exception("Match search failed", extra={"query": query_text, "league": league})
        # Return empty list on errors to keep UX responsive
        return []


@router.get("/{match_id}", response_model=MatchDetailResponse)
async def get_match_detail(
    match_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed information about a specific match
    
    Includes team form, head-to-head history, odds movement, and prediction metadata.
    """
    try:
        # Check cache
        cache_key = f"match_detail:{match_id}"
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            return MatchDetailResponse(**cached_result) if isinstance(cached_result, dict) else cached_result

        # Fetch match from database
        query = (
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.league),
            )
            .where(Match.id == match_id)
        )
        result = await db.execute(query)
        match = result.scalar_one_or_none()
        
        if not match:
            raise HTTPException(status_code=404, detail=f"Match {match_id} not found")
        
        # Build detailed response
        odds_map = await _fetch_latest_odds(db, [str(match.id)])
        latest_odds = odds_map.get(str(match.id))

        response = MatchDetailResponse(
            id=str(match.id),
            home_team=match.home_team.name if match.home_team else match.home_team_id,
            away_team=match.away_team.name if match.away_team else match.away_team_id,
            league=match.league.name if match.league else match.league_id,
            match_date=match.match_date,
            venue=match.venue,
            status=match.status or "scheduled",
            odds=latest_odds,
            referee=match.referee,
            season=match.season,
            round_number=None,
        )

        # Cache for 10 minutes
        cache_manager.set(cache_key, response, ttl=600)
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching match detail for {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch match details")


@router.get("/league/{league_name}", response_model=MatchListResponse)
async def get_matches_by_league(
    league_name: str,
    status: Optional[str] = Query(None, description="Filter by status (scheduled, live, finished)"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get all matches for a specific league
    
    Useful for league-specific analysis and historical performance tracking.
    """
    try:
        query = (
            select(Match)
            .options(
                selectinload(Match.home_team),
                selectinload(Match.away_team),
                selectinload(Match.league),
            )
            .where(func.lower(Match.league_id) == league_name.lower())
        )

        if status:
            query = query.where(Match.status == status.lower())

        query = query.order_by(Match.match_date.desc()).limit(limit)

        # Execute
        result = await db.execute(query)
        matches = result.scalars().unique().all()

        odds_map = await _fetch_latest_odds(db, [str(match.id) for match in matches if match.id])

        # Transform
        match_responses = [
            MatchSummary(
                id=str(match.id),
                home_team=match.home_team.name if match.home_team else match.home_team_id,
                away_team=match.away_team.name if match.away_team else match.away_team_id,
                league=match.league.name if match.league else match.league_id,
                match_date=match.match_date,
                venue=match.venue,
                status=match.status or "scheduled",
                has_odds=str(match.id) in odds_map,
            )
            for match in matches
        ]

        return MatchListResponse(
            matches=match_responses,
            total=len(match_responses),
            league_filter=league_name,
        )
        
    except Exception as e:
        logger.error(f"Error fetching matches for league {league_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch league matches")


async def _fetch_latest_odds(db: AsyncSession, match_ids: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """Fetch the most recent odds snapshot for each match id."""
    if not match_ids:
        return {}

    subquery = (
        select(
            Odds.match_id,
            func.max(Odds.timestamp).label("latest_ts"),
        )
        .where(Odds.match_id.in_(match_ids))
        .group_by(Odds.match_id)
        .subquery()
    )

    query = (
        select(Odds)
        .join(
            subquery,
            (Odds.match_id == subquery.c.match_id) & (Odds.timestamp == subquery.c.latest_ts),
        )
    )

    result = await db.execute(query)
    odds_rows = result.scalars().all()

    odds_map: Dict[str, Dict[str, Optional[float]]] = {}
    for row in odds_rows:
        odds_map[row.match_id] = {
            "home_win": row.home_win,
            "draw": row.draw,
            "away_win": row.away_win,
        }

    return odds_map
