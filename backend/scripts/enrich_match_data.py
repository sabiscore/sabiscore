"""
Enrich database with xG, squad values, and tactical data
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import asyncio
from datetime import datetime, timedelta
from src.core.database import SessionLocal, Match
from src.scrapers.data_pipeline import DataPipeline
import redis

async def enrich_recent_matches(days: int = 30):
    """
    Enrich matches from last N days
    """
    print(f"🔍 Enriching matches from last {days} days...")
    
    db = SessionLocal()
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_client = redis.from_url(redis_url, decode_responses=True)
    
    # Query recent matches
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    matches = db.query(Match).filter(
        Match.match_date >= cutoff_date
    ).all()
    
    print(f"Found {len(matches)} matches to enrich")
    
    async with DataPipeline(redis_client, db) as pipeline:
        for i, match in enumerate(matches, 1):
            try:
                print(f"\n[{i}/{len(matches)}] {match.home_team} vs {match.away_team}")
                
                enriched = await pipeline.enrich_match_data(
                    str(match.id),
                    match.home_team,
                    match.away_team
                )
                
                # Update match with enriched data
                if 'home_xg_l5' in enriched:
                    print("  ✅ Enriched: xG, squad values, tactics")
                else:
                    print("  ⚠️  Partial enrichment")
                
            except Exception as e:
                print(f"  ❌ Error: {e}")
    
    db.close()
    print("\n✅ Enrichment complete")

if __name__ == "__main__":
    asyncio.run(enrich_recent_matches())