#!/usr/bin/env python3
"""
Simple test server to verify API functionality
"""

import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = PROJECT_ROOT.parent
SRC_PATH = BACKEND_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))
sys.path.insert(0, str(BACKEND_ROOT))

app = FastAPI(title="SabiScore Test API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
async def health_check():
    """Simple health check endpoint"""
    return {
        "status": "healthy",
        "message": "SabiScore API is running",
        "database": "test",
        "models": "test",
        "cache": "test",
    }


@app.post("/api/v1/insights")
async def generate_insights(matchup: str = "Test Match", league: str = "Test League"):
    """Mock insights generation"""
    from datetime import datetime

    return {
        "matchup": matchup,
        "league": league,
        "predictions": {
            "home_win_prob": 0.5,
            "draw_prob": 0.3,
            "away_win_prob": 0.2,
            "prediction": "home_win",
            "confidence": 0.7,
        },
        "xg_analysis": {
            "home_xg": 1.8,
            "away_xg": 1.2,
            "total_xg": 3.0,
            "xg_difference": 0.6,
        },
        "value_analysis": {},
        "monte_carlo": {
            "simulations": 1000,
            "distribution": {},
            "confidence_intervals": {},
        },
        "scenarios": [],
        "explanation": {},
        "risk_assessment": {
            "risk_level": "medium",
            "confidence_score": 0.7,
            "value_available": True,
            "recommendation": "Proceed",
            "distribution": {},
            "best_bet": None,
        },
        "narrative": f"Analysis generated for {matchup} in {league}",
        "generated_at": datetime.utcnow().isoformat(),
        "confidence_level": 0.7,
    }


@app.get("/")
async def root():
    return {"message": "SabiScore Test API", "health": "/api/v1/health"}


if __name__ == "__main__":
    import uvicorn

    print("Starting SabiScore Test API on http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
