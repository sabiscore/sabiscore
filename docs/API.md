# SabiScore API Documentation

## Overview

The SabiScore API provides RESTful endpoints for football match analysis and betting insights. Built with FastAPI, it offers automatic OpenAPI documentation and comprehensive error handling.

**Base URL**: `http://localhost:8000/api/v1`

## Authentication

Currently, the API is open for development. In production, implement JWT-based authentication.

## Endpoints

### Provider Gateway

Provider routes expose redacted health, capability, and quota state for the backend-only provider gateway.

```text
GET /providers
GET /providers/health
GET /providers/capabilities
GET /providers/quota
```

Optional query parameter:

- `provider`: provider id such as `espn`, `football_data_org`, `api_football`, `sportmonks`, or `the_odds_api`.

Providers return standard envelopes with `status`, `trust_tier`, `warnings`, `quota`, and acquired timestamps. ESPN is keyless and supplementary only.

### Fixture Intelligence

```text
GET  /fixtures/upcoming
GET  /fixtures/{fixture_id}
GET  /fixtures/{fixture_id}/evidence
POST /fixtures/{fixture_id}/refresh
GET  /fixtures/{fixture_id}/odds-snapshots
POST /fixtures/{fixture_id}/odds-snapshot
POST /fixtures/{fixture_id}/analyze
```

`/odds-snapshots` returns coherent one-bookmaker 1X2 candidates. Cross-bookmaker comparisons are display evidence only; analysis uses one complete bookmaker snapshot or a user-confirmed manual snapshot.

### Upcoming Discovery

**GET** `/upcoming/matches`

The response includes `next_season_start` and the additive nullable boolean
`next_season_start_estimated`. When the flag is `true`, clients must describe the
date as an estimate and must not present an exact countdown. Fail-closed proxy
responses carry `next_season_start_estimated: null`. The field does not change
fixture identity, probability, verdict, or staking semantics.

### Health Check

**GET** `/health`

Basic health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "database": true,
  "models": true,
  "cache": true
}
```

### Match Search

**GET** `/matches/search`

Search for matches and teams.

**Query Parameters:**
- `q` (string, required): Search query
- `league` (string, optional): League filter

**Response:**
```json
[
  {
    "id": "1",
    "home_team": "Manchester City",
    "away_team": "Liverpool",
    "league": "EPL",
    "match_date": "2024-10-26T15:00:00Z",
    "venue": "Etihad Stadium"
  }
]
```

### Generate Insights

**POST** `/insights`

Generate comprehensive betting insights for a match.

**Request Body:**
```json
{
  "matchup": "Manchester City vs Liverpool",
  "league": "EPL"
}
```

**Response:**
```json
{
  "matchup": "Manchester City vs Liverpool",
  "league": "EPL",
  "predictions": {
    "home_win_prob": 0.65,
    "draw_prob": 0.20,
    "away_win_prob": 0.15,
    "prediction": "home_win",
    "confidence": 78.5
  },
  "xg_analysis": {
    "home_xg": 2.1,
    "away_xg": 1.3,
    "total_xg": 3.4,
    "xg_difference": 0.8
  },
  "value_analysis": [
    {
      "bet_type": "home_win",
      "market_odds": 2.10,
      "expected_odds": 1.54,
      "expected_value": 0.12,
      "confidence": 78.5,
      "recommendation": "Consider"
    }
  ],
  "monte_carlo": {
    "simulations_run": 10000,
    "home_win_prob": 0.652,
    "draw_prob": 0.198,
    "away_win_prob": 0.150
  },
  "scenarios": [
    {
      "name": "Most Likely",
      "probability": 0.65,
      "home_score": 2,
      "away_score": 1,
      "result": "home_win"
    }
  ],
  "explanation": {
    "feature_importance": {
      "home_attack_strength": 0.15,
      "away_defense_strength": 0.12,
      "home_win_rate": 0.10
    }
  },
  "risk_assessment": {
    "risk_level": "low",
    "confidence_score": 78.5,
    "value_available": true,
    "recommendation": "Proceed"
  },
  "narrative": "Our model predicts Home Win with 79% confidence...",
  "generated_at": "2024-10-25T20:00:00.000Z"
}
```

### Core Engine Analyze

**POST** `/core-engine/analyze`

Runs the deterministic SabiScore Core Engine v2.1 betting-decision layer over one or more verified pre-match input envelopes. This endpoint does not fetch live data, infer missing odds, inject league averages, or reuse legacy value-bet fallbacks. Inputs are evaluated independently, then actionable outputs are ranked into `top_opportunities`.

Use this endpoint when the caller already has:

- calibrated 1X2 model probabilities;
- one unified 1X2 market price matrix from a single bookmaker;
- freshness timestamps and source-status flags;
- team-strength and availability signals.

**Request Body (abridged):**
```json
{
  "matches": [
    {
      "match_id": "epl-2026-001",
      "home_team": "Arsenal",
      "away_team": "Chelsea",
      "competition": "EPL",
      "kickoff_utc": "2026-08-15T15:00:00Z",
      "model": {
        "home_probability": 0.55,
        "draw_probability": 0.25,
        "away_probability": 0.20,
        "model_version": "core-v1",
        "calibration_method": "isotonic",
        "calibration_validated": true,
        "epistemic_uncertainty": 0.05,
        "aleatoric_uncertainty": 0.12,
        "confidence_tier": "OK"
      },
      "market": {
        "bookmaker": "ExampleBook",
        "market_type": "1X2",
        "home_odds": 2.1,
        "draw_odds": 3.4,
        "away_odds": 4.5,
        "captured_at": "2026-08-15T13:45:00Z"
      },
      "signals": {
        "lineup_status": "CONFIRMED",
        "sharp_market_signal": "CONFIRMING",
        "confirmed_absences": []
      },
      "freshness": {
        "model_features_seconds": 300,
        "market_seconds": 120,
        "injury_news_seconds": 400,
        "lineup_seconds": 180
      },
      "source_status": {
        "model": "VERIFIED",
        "market": "VERIFIED",
        "team_metrics": "VERIFIED",
        "availability": "VERIFIED"
      }
    }
  ]
}
```

**Response (abridged):**
```json
{
  "engine_version": "2.1.0-prod",
  "generated_at": "2026-06-25T18:00:00Z",
  "top_opportunities": ["epl-2026-001"],
  "matches": [
    {
      "match_id": "epl-2026-001",
      "match_identifier": "Arsenal vs Chelsea",
      "verdict": "ACTIONABLE",
      "best_market": "HOME_ML",
      "market_odds": 2.1,
      "fair_market_probability": 0.43,
      "edge": 0.12,
      "expected_value": 0.155,
      "stake": "1u",
      "stake_fraction": 0.019375,
      "data_gaps": [],
      "calculation_audit": {
        "bookmaker": "ExampleBook",
        "market_overround": 1.06,
        "calibration_method": "isotonic",
        "model_version": "core-v1",
        "kelly_fraction": 0.125,
        "kelly_cap": 0.025
      }
    }
  ]
}
```

**Verdicts:**

- `PARTIAL`: critical data is missing, stale, conflicting, or mathematically invalid. Value fields are `null` and stake is `pass`.
- `NO_BET`: data is valid but the best market has non-positive edge or EV.
- `HOLD`: positive value exists but gating restrictions force inaction.
- `SPECULATIVE`: positive EV exists below the actionable edge threshold with confirming signals; it is watchlist-only, is excluded from `top_opportunities`, and always exposes zero public stake.
- `ACTIONABLE`: EV is positive, edge clears 4.2 percentage points, and model/market gates pass.
- `HIGH_CONVICTION`: action criteria plus very low epistemic uncertainty and confirmed lineup; UCL fixtures are excluded.

Full contract and implementation notes: [`docs/CORE_ENGINE.md`](./CORE_ENGINE.md).

### Model Status

**GET** `/models/status`

Get information about trained models and their performance.

**Response:**
```json
{
  "models_loaded": true,
  "last_trained": "2024-10-25T10:00:00Z",
  "accuracy": 0.732,
  "leagues_supported": ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "UCL"]
}
```

## Error Handling

All endpoints return consistent error responses:

```json
{
  "detail": "Error description",
  "error_code": "VALIDATION_ERROR"
}
```

### Common Error Codes

- `VALIDATION_ERROR`: Invalid request data
- `NOT_FOUND`: Resource not found
- `SERVICE_UNAVAILABLE`: Backend service error
- `RATE_LIMITED`: Too many requests

## Rate Limiting

- **60 requests per minute** per IP address
- Applied to all endpoints
- Returns HTTP 429 when exceeded

## Data Models

### Matchup
String format: `"Home Team vs Away Team"`

### League Codes
- `EPL`: Premier League
- `LA_LIGA`: La Liga
- `BUNDESLIGA`: Bundesliga
- `SERIE_A`: Serie A
- `LIGUE_1`: Ligue 1
- `EREDIVISIE`: Eredivisie
- `UCL`: UEFA Champions League

### Bet Types
- `home_win`: Home team to win
- `draw`: Match to end in draw
- `away_win`: Away team to win
- `over_under`: Over/under goals line
- `btts`: Both teams to score

## WebSocket Support

Real-time updates are planned for future implementation using WebSockets for live match data.

## SDKs and Libraries

### JavaScript Client

```javascript
import APIClient from './api-client.js';

const api = new APIClient();
const insights = await api.generateInsights("Man City vs Liverpool", "EPL");
```

### Python Client

```python
import requests

response = requests.post("http://localhost:8000/api/v1/insights",
    json={"matchup": "Man City vs Liverpool", "league": "EPL"}
)
insights = response.json()
```

## Versioning

API versioning follows semantic versioning:
- `/api/v1/` - Current stable version
- Breaking changes will increment the major version

## Monitoring

### Health Checks
- `/health`: Basic service health
- `/metrics`: Prometheus metrics (planned)

### Logging
All requests are logged with timing and error information.

## Security

### Headers
All responses include security headers:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Strict-Transport-Security: max-age=31536000`

### CORS
Configured for frontend domain access with credentials support.
