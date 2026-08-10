"""
WebSocket Live Layer
Real-time goal updates and ISR revalidation endpoint

Provides WebSocket endpoint for streaming:
- Live goal events
- xG updates
- Odds movements
- Edge alerts
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import aiohttp

from ..core.redis import get_redis_client, CacheKeys
from ..core.config import settings
from ..models.edge_detector import EdgeDetector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Manage WebSocket connections"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.match_subscribers: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, match_id: str):
        """Accept new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)
        
        if match_id not in self.match_subscribers:
            self.match_subscribers[match_id] = set()
        self.match_subscribers[match_id].add(websocket)
        
        logger.info("WebSocket connected for match %s", match_id)

    def disconnect(self, websocket: WebSocket, match_id: str):
        """Remove WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        
        if match_id in self.match_subscribers:
            self.match_subscribers[match_id].discard(websocket)
            if not self.match_subscribers[match_id]:
                del self.match_subscribers[match_id]
        
        logger.info("WebSocket disconnected for match %s", match_id)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Send message to specific client"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error("Error sending personal message: %s", e)

    async def broadcast_to_match(self, message: dict, match_id: str):
        """Broadcast message to all clients subscribed to match"""
        if match_id not in self.match_subscribers:
            return
        
        disconnected = []
        for connection in self.match_subscribers[match_id]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error("Error broadcasting to match %s: %s", match_id, e)
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn, match_id)

    async def broadcast_all(self, message: dict):
        """Broadcast message to all connected clients"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error("Error broadcasting: %s", e)
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)


# Global connection manager
manager = ConnectionManager()


@router.websocket("/edge/{match_id}")
async def websocket_edge_endpoint(
    websocket: WebSocket,
    match_id: str,
):
    """WebSocket endpoint for live edge updates
    
    Streams:
    - Goal events (triggers ISR revalidation)
    - xG updates
    - Odds movements
    - Edge alerts
    
    Args:
        match_id: Match identifier
    """
    await manager.connect(websocket, match_id)
    
    try:
        # Send initial connection acknowledgment
        await manager.send_personal_message({
            "type": "connected",
            "match_id": match_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, websocket)
        
        # Start background tasks for this match
        tasks = [
            asyncio.create_task(stream_match_events(match_id)),
            asyncio.create_task(stream_xg_updates(match_id)),
            asyncio.create_task(stream_odds_updates(match_id)),
        ]
        
        # Keep connection alive and process incoming messages
        while True:
            try:
                data = await websocket.receive_json()
                await handle_client_message(data, match_id, websocket)
            except WebSocketDisconnect:
                logger.info("Client disconnected from match %s", match_id)
                break
            except Exception as e:
                logger.error("Error receiving message: %s", e)
                break
    
    finally:
        # Cancel background tasks
        for task in tasks:
            task.cancel()
        
        # Disconnect
        manager.disconnect(websocket, match_id)


async def stream_match_events(match_id: str):
    """Stream live match events (goals, cards, subs)"""
    try:
        redis_client = get_redis_client()
        await redis_client.connect()
        client = await redis_client.get_client()
        
        # Subscribe to Redis pub/sub for match events
        pubsub = client.pubsub()
        await pubsub.subscribe(f"match_events:{match_id}")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                event_data = json.loads(message["data"])
                
                # Broadcast event
                await manager.broadcast_to_match({
                    "type": "match_event",
                    "event": event_data,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, match_id)
                
                # Trigger ISR revalidation for goal events
                if event_data.get("event_type") == "goal":
                    await trigger_isr_revalidation(match_id)
    
    except asyncio.CancelledError:
        logger.info("Stream cancelled for match %s", match_id)
    except Exception as e:
        logger.error("Error streaming match events: %s", e)


async def stream_xg_updates(match_id: str):
    """Stream live xG updates"""
    try:
        redis_client = get_redis_client()
        
        # Poll for xG updates every 8 seconds
        while True:
            # Fetch latest xG from cache
            xg_data = await redis_client.get(CacheKeys.xg_chain(match_id))
            
            if xg_data:
                xg_parsed = json.loads(xg_data)
                
                # Broadcast xG update
                await manager.broadcast_to_match({
                    "type": "xg_update",
                    "xg_data": xg_parsed,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, match_id)
            
            await asyncio.sleep(8)
    
    except asyncio.CancelledError:
        logger.info("xG stream cancelled for match %s", match_id)
    except Exception as e:
        logger.error("Error streaming xG: %s", e)


async def stream_odds_updates(match_id: str):
    """Stream live odds and edge alerts"""
    try:
        redis_client = get_redis_client()
        edge_detector = EdgeDetector()
        
        # Poll for odds updates every 2 seconds
        while True:
            # Fetch latest odds
            odds_keys = await redis_client.get_client().keys(f"odds:{match_id}:*")
            
            if odds_keys:
                odds_data = {}
                for key in odds_keys:
                    bookmaker = key.split(":")[-1]
                    odds_str = await redis_client.get(key)
                    if odds_str:
                        odds_data[bookmaker] = json.loads(odds_str)
                
                # Broadcast odds update
                await manager.broadcast_to_match({
                    "type": "odds_update",
                    "odds": odds_data,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }, match_id)
                
                # Check for edge opportunities
                await check_and_broadcast_edges(match_id, odds_data, edge_detector)
            
            await asyncio.sleep(2)
    
    except asyncio.CancelledError:
        logger.info("Odds stream cancelled for match %s", match_id)
    except Exception as e:
        logger.error("Error streaming odds: %s", e)


async def check_and_broadcast_edges(
    match_id: str,
    odds_data: Dict,
    edge_detector: EdgeDetector
):
    """Check for betting edges and broadcast alerts"""
    try:
        redis_client = get_redis_client()
        
        # Fetch latest prediction
        pred_data = await redis_client.get(CacheKeys.live_prediction(match_id))
        
        if not pred_data:
            return
        
        prediction = json.loads(pred_data)
        fair_prob = prediction.get("home_win_prob", 0.5)
        
        # Extract odds from odds_data
        bookmaker_odds = {}
        for bookmaker, data in odds_data.items():
            if "home_win" in data:
                bookmaker_odds[bookmaker] = data["home_win"]
        
        if not bookmaker_odds:
            return
        
        # Detect value bet
        value_bet = edge_detector.detect_value_bet(
            fair_probability=fair_prob,
            bookmaker_odds=bookmaker_odds,
            bankroll=1000.0  # Default bankroll for demo
        )
        
        if value_bet:
            # Broadcast edge alert
            await manager.broadcast_to_match({
                "type": "edge_alert",
                "value_bet": value_bet,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, match_id)
            
            logger.info("Edge alert for match %s: %s%", match_id, value_bet['edge_percentage'])
    
    except Exception as e:
        logger.error("Error checking edges: %s", e)


async def trigger_isr_revalidation(match_id: str):
    """Trigger Next.js ISR revalidation for updated match data
    
    Makes HTTP POST to Next.js /api/revalidate endpoint to invalidate
    cached match pages and force regeneration with fresh data.
    
    Args:
        match_id: Match to revalidate
    """
    try:
        # Get Next.js revalidation settings from config
        next_url = settings.next_url
        revalidate_secret = settings.revalidate_secret
        if not revalidate_secret:
            logger.warning("ISR revalidation skipped because REVALIDATE_SECRET is not configured")
            return
        
        # Construct revalidation payload
        payload = {
            "secret": revalidate_secret,
            "path": f"/match/{match_id}"
        }
        
        # Send HTTP POST to Next.js revalidation API
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{next_url}/api/revalidate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status == 200:
                    logger.info("ISR revalidation successful for match %s", match_id)
                else:
                    logger.warning(
                        f"ISR revalidation failed for match {match_id}: "
                        f"status={response.status}"
                    )
    
    except asyncio.TimeoutError:
        logger.warning("ISR revalidation timeout for match %s", match_id)
    except Exception as exc:
        logger.error("Error triggering ISR revalidation: %s", exc)


async def handle_client_message(data: dict, match_id: str, websocket: WebSocket):
    """Handle incoming client messages
    
    Args:
        data: Message data from client
        match_id: Match ID
        websocket: Client WebSocket connection
    """
    try:
        message_type = data.get("type")
        
        if message_type == "ping":
            # Respond to ping
            await manager.send_personal_message({
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, websocket)
        
        elif message_type == "subscribe_event":
            # Subscribe to specific event type
            event_type = data.get("event_type")
            logger.info("Client subscribed to %s for match %s", event_type, match_id)
            
            await manager.send_personal_message({
                "type": "subscribed",
                "event_type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }, websocket)
        
        else:
            logger.warning("Unknown message type: %s", message_type)
    
    except Exception as e:
        logger.error("Error handling client message: %s", e)


# Export router
__all__ = ["router", "manager"]
