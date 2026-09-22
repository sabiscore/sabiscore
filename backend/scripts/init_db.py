#!/usr/bin/env python3
"""
Initialize database with schema and seed data
"""

import sys
import os
import subprocess

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import SessionLocal
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_database():
    """Run migrations and seed reference data."""
    try:
        logger.info("Running Alembic migrations...")

        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        subprocess.run(["alembic", "upgrade", "head"], check=True, cwd=backend_dir)

        logger.info("Database migrations completed successfully")

        # Seed with initial data
        seed_database()

        logger.info("Database initialization completed")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


def seed_database():
    """Seed database with initial data"""
    try:
        db = SessionLocal()

        # Check if data already exists
        from src.core.database import League

        existing_leagues = db.query(League).count()

        if existing_leagues > 0:
            logger.info("Database already seeded, skipping...")
            db.close()
            return

        logger.info("Seeding database with initial data...")

        # Seed leagues
        leagues_data = [
            {"id": "EPL", "name": "Premier League", "country": "England", "tier": 1},
            {"id": "La Liga", "name": "La Liga", "country": "Spain", "tier": 1},
            {"id": "Bundesliga", "name": "Bundesliga", "country": "Germany", "tier": 1},
            {"id": "Serie A", "name": "Serie A", "country": "Italy", "tier": 1},
            {"id": "Ligue 1", "name": "Ligue 1", "country": "France", "tier": 1},
            {
                "id": "UCL",
                "name": "UEFA Champions League",
                "country": "Europe",
                "tier": 0,
            },
        ]

        for league_data in leagues_data:
            league = League(**league_data)
            db.add(league)

        db.commit()
        logger.info(f"Seeded {len(leagues_data)} leagues")

        db.close()

    except Exception as e:
        logger.error(f"Database seeding failed: {e}")
        raise


if __name__ == "__main__":
    init_database()
