"""Deprecated research-only endpoints backed by the provenance-blind Odds table."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import logging

from ...db.session import get_async_session
from ...db.models import Odds
from ...schemas.odds import OddsResponse, OddsCreate
from ...core.cache import cache_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/odds", tags=["odds"])


@router.get("/match/{match_id}", response_model=List[OddsResponse], deprecated=True)
async def get_match_odds(
    match_id: str,
    bookmaker: Optional[str] = Query(None, description="Filter by bookmaker"),
    limit: int = Query(10, ge=1, le=100, description="Maximum number of snapshots"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get odds history for a specific match
    
    Returns timestamped legacy references for research display only. These rows
    are not canonical market evidence and are ineligible for CLV or staking.
    """
    try:
        # Check cache
        cache_key = f"odds:match:{match_id}:{bookmaker}:{limit}"
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for odds {match_id}")
            return [OddsResponse(**item) if isinstance(item, dict) else item for item in cached_result]
        
        # Build query
        query = (
            select(Odds)
            .where(Odds.match_id == match_id)
            .order_by(desc(Odds.timestamp))
            .limit(limit)
        )
        
        if bookmaker:
            query = query.where(func.lower(Odds.bookmaker) == bookmaker.lower())
        
        # Execute
        result = await db.execute(query)
        odds_snapshots = result.scalars().all()
        
        if not odds_snapshots:
            raise HTTPException(
                status_code=404,
                detail=f"No odds found for match {match_id}"
            )
        
        # Transform to response
        responses = [
            OddsResponse(
                id=odds.id,
                match_id=odds.match_id,
                bookmaker=odds.bookmaker,
                home_win=odds.home_win,
                draw=odds.draw,
                away_win=odds.away_win,
                over_under=odds.over_under,
                created_at=odds.timestamp,
            )
            for odds in odds_snapshots
        ]
        
        # Cache for 2 minutes
        cache_manager.set(cache_key, responses, ttl=120)
        
        logger.info(f"Fetched {len(responses)} odds snapshots for match {match_id}")
        return responses
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching odds for match {match_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch odds")


@router.get("/latest/{match_id}", response_model=Dict[str, OddsResponse], deprecated=True)
async def get_latest_odds(
    match_id: str,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Get the most recent odds from all bookmakers for a match
    
    Returns a dictionary mapping bookmaker names to their latest odds snapshot.
    These references are non-executable and cannot establish value evidence.
    """
    try:
        # Check cache
        cache_key = f"odds:latest:{match_id}"
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            return cached_result
        
        # Subquery to get latest timestamp per bookmaker
        subquery = (
            select(
                Odds.bookmaker,
                func.max(Odds.timestamp).label("latest_ts")
            )
            .where(Odds.match_id == match_id)
            .group_by(Odds.bookmaker)
            .subquery()
        )
        
        # Join to get full odds records
        query = (
            select(Odds)
            .join(
                subquery,
                and_(
                    Odds.bookmaker == subquery.c.bookmaker,
                    Odds.timestamp == subquery.c.latest_ts,
                    Odds.match_id == match_id
                )
            )
        )
        
        result = await db.execute(query)
        latest_odds = result.scalars().all()
        
        if not latest_odds:
            raise HTTPException(
                status_code=404,
                detail=f"No odds found for match {match_id}"
            )
        
        # Group by bookmaker
        odds_by_bookmaker = {}
        for odds in latest_odds:
            odds_by_bookmaker[odds.bookmaker] = OddsResponse(
                id=odds.id,
                match_id=odds.match_id,
                bookmaker=odds.bookmaker,
                home_win=odds.home_win,
                draw=odds.draw,
                away_win=odds.away_win,
                over_under=odds.over_under,
                created_at=odds.timestamp,
            )
        
        # Cache for 1 minute
        cache_manager.set(cache_key, odds_by_bookmaker, ttl=60)
        
        logger.info(f"Fetched latest odds from {len(odds_by_bookmaker)} bookmakers")
        return odds_by_bookmaker
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching latest odds: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch latest odds")


@router.get("/movement/{match_id}", deprecated=True)
async def get_odds_movement(
    match_id: str,
    hours_back: int = Query(24, ge=1, le=168, description="Hours of history to analyze"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Analyze legacy odds movement for a research display.
    
    Returns market movement metrics including:
    - Opening vs current odds
    - Direction and magnitude of movement
    - Volatility indicators
    - Steam move detection
    """
    try:
        # Check cache
        cache_key = f"odds:movement:{match_id}:{hours_back}"
        cached_result = cache_manager.get(cache_key)
        if cached_result:
            return cached_result
        
        # Fetch odds within time window
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        query = (
            select(Odds)
            .where(
                and_(
                    Odds.match_id == match_id,
                    Odds.timestamp >= cutoff_time
                )
            )
            .order_by(Odds.timestamp.asc())
        )
        
        result = await db.execute(query)
        odds_history = result.scalars().all()
        
        if not odds_history:
            raise HTTPException(
                status_code=404,
                detail=f"No odds history found for match {match_id}"
            )
        
        # Calculate movement metrics
        movement_analysis = _analyze_odds_movement(odds_history)
        
        # Cache for 5 minutes
        cache_manager.set(cache_key, movement_analysis, ttl=300)
        
        return movement_analysis
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing odds movement: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to analyze odds movement")


@router.get("/best-line/{match_id}", deprecated=True)
async def get_best_line(
    match_id: str,
    outcome: str = Query(..., description="Outcome type: home_win, draw, or away_win"),
    db: AsyncSession = Depends(get_async_session),
):
    """
    Compare legacy references for a specific outcome. The result is research
    only and must not be interpreted as verified market or value evidence.
    """
    try:
        if outcome not in ["home_win", "draw", "away_win"]:
            raise HTTPException(
                status_code=400,
                detail="Outcome must be one of: home_win, draw, away_win"
            )
        
        # Get latest odds from all bookmakers
        latest_odds = await get_latest_odds(match_id, db)
        
        # Find best line
        best_odds = None
        best_bookmaker = None
        
        for bookmaker, odds in latest_odds.items():
            current_odds = getattr(odds, outcome)
            if current_odds and (best_odds is None or current_odds > best_odds):
                best_odds = current_odds
                best_bookmaker = bookmaker
        
        if best_bookmaker is None:
            raise HTTPException(
                status_code=404,
                detail=f"No odds available for outcome: {outcome}"
            )
        
        return {
            "match_id": match_id,
            "outcome": outcome,
            "best_odds": best_odds,
            "bookmaker": best_bookmaker,
            "advantage_percent": _calculate_advantage(best_odds, latest_odds, outcome),
            "full_odds": latest_odds[best_bookmaker],
            "evidence_state": "RESEARCH_ONLY",
            "executable": False,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finding best line: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to find best line")


@router.post("/", response_model=OddsResponse, deprecated=True)
async def create_odds_snapshot(
    odds_data: OddsCreate,
    db: AsyncSession = Depends(get_async_session),
):
    """
    Store a legacy research reference.

    This endpoint does not verify provider provenance. Its rows cannot enter
    canonical market features, CLV, value analysis, Kelly sizing, or staking.
    """
    try:
        # Create new odds record
        new_odds = Odds(
            match_id=odds_data.match_id,
            bookmaker=odds_data.bookmaker,
            home_win=odds_data.home_win,
            draw=odds_data.draw,
            away_win=odds_data.away_win,
            over_under=odds_data.over_under,
            timestamp=odds_data.timestamp,
        )
        
        db.add(new_odds)
        await db.commit()
        await db.refresh(new_odds)
        
        # Invalidate cache
        cache_manager.delete(f"odds:match:{odds_data.match_id}:*")
        cache_manager.delete(f"odds:latest:{odds_data.match_id}")
        
        logger.info("Created research-only legacy odds reference for match %s", odds_data.match_id)
        
        return OddsResponse(
            id=new_odds.id,
            match_id=new_odds.match_id,
            bookmaker=new_odds.bookmaker,
            home_win=new_odds.home_win,
            draw=new_odds.draw,
            away_win=new_odds.away_win,
            over_under=new_odds.over_under,
            created_at=new_odds.timestamp,
        )
        
    except Exception as e:
        logger.error(f"Error creating odds snapshot: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create odds snapshot")


def _analyze_odds_movement(odds_history: List[Odds]) -> Dict:
    """Analyze odds movement patterns and detect market signals"""
    if not odds_history:
        return {}
    
    # Group by bookmaker
    by_bookmaker = {}
    for odds in odds_history:
        if odds.bookmaker not in by_bookmaker:
            by_bookmaker[odds.bookmaker] = []
        by_bookmaker[odds.bookmaker].append(odds)
    
    # Calculate movement for each bookmaker
    movements = {}
    for bookmaker, snapshots in by_bookmaker.items():
        if len(snapshots) < 2:
            continue
        
        first = snapshots[0]
        last = snapshots[-1]
        
        movements[bookmaker] = {
            "home_win": {
                "opening": first.home_win,
                "current": last.home_win,
                "change": last.home_win - first.home_win if first.home_win and last.home_win else 0,
                "change_percent": ((last.home_win - first.home_win) / first.home_win * 100) if first.home_win and last.home_win and first.home_win > 0 else 0
            },
            "draw": {
                "opening": first.draw,
                "current": last.draw,
                "change": last.draw - first.draw if first.draw and last.draw else 0,
                "change_percent": ((last.draw - first.draw) / first.draw * 100) if first.draw and last.draw and first.draw > 0 else 0
            },
            "away_win": {
                "opening": first.away_win,
                "current": last.away_win,
                "change": last.away_win - first.away_win if first.away_win and last.away_win else 0,
                "change_percent": ((last.away_win - first.away_win) / first.away_win * 100) if first.away_win and last.away_win and first.away_win > 0 else 0
            },
            "snapshots_count": len(snapshots),
            "time_span_hours": (last.timestamp - first.timestamp).total_seconds() / 3600 if last.timestamp and first.timestamp else 0
        }
    
    # Detect steam moves (rapid uniform movement across bookmakers)
    steam_detected = _detect_steam_moves(movements)
    
    return {
        "match_id": odds_history[0].match_id,
        "bookmakers": movements,
        "steam_moves": steam_detected,
        "total_snapshots": len(odds_history),
        "time_range_hours": (odds_history[-1].timestamp - odds_history[0].timestamp).total_seconds() / 3600 if len(odds_history) > 1 else 0,
        "evidence_state": "RESEARCH_ONLY",
        "executable": False,
    }


def _detect_steam_moves(movements: Dict) -> List[Dict]:
    """Detect steam moves (coordinated rapid odds changes across bookmakers)"""
    steam_moves = []
    
    # Check each outcome
    for outcome in ["home_win", "draw", "away_win"]:
        changes = []
        for bookmaker, data in movements.items():
            change_pct = data[outcome]["change_percent"]
            if abs(change_pct) > 3:  # Significant move threshold: 3%
                changes.append({"bookmaker": bookmaker, "change": change_pct})
        
        # Steam move if 3+ bookmakers move in same direction
        if len(changes) >= 3:
            avg_change = sum(c["change"] for c in changes) / len(changes)
            if all(c["change"] * avg_change > 0 for c in changes):  # Same direction
                steam_moves.append({
                    "outcome": outcome,
                    "direction": "up" if avg_change > 0 else "down",
                    "avg_change_percent": round(avg_change, 2),
                    "bookmakers_affected": len(changes),
                    "severity": "high" if abs(avg_change) > 5 else "medium"
                })
    
    return steam_moves


def _calculate_advantage(best_odds: float, all_odds: Dict, outcome: str) -> float:
    """Calculate percentage advantage of best odds vs market average"""
    odds_values = []
    for bookmaker_odds in all_odds.values():
        odds_val = getattr(bookmaker_odds, outcome)
        if odds_val:
            odds_values.append(odds_val)
    
    if not odds_values:
        return 0.0
    
    avg_odds = sum(odds_values) / len(odds_values)
    advantage = ((best_odds - avg_odds) / avg_odds) * 100
    return round(advantage, 2)
