#!/usr/bin/env python3
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import SessionLocal, Team, Match

db = SessionLocal()
print("Teams:", db.query(Team).count())
print("Matches:", db.query(Match).count())
db.close()
