import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime

# Import the router that aggregates all endpoints
from src.api.main import app
from src.db.session import get_async_session

# Create a TestClient instance
# We need to mount the router to a FastAPI app if it's not already, 
# but here we can just use the main app which should have the router included.
# However, to be safe and isolated, we can create a new app or use the existing one.
# The existing app in src.api.main has the router included.

class CustomTestClient(TestClient):
    """
    Custom TestClient that ensures the app is properly initialized
    and handles any specific setup/teardown if needed.
    """
    pass

@pytest.fixture
def test_client():
    """Fixture to provide a TestClient instance."""
    # We use the main app which includes all routers
    return CustomTestClient(app)

@pytest.fixture
def mock_async_session():
    """Fixture to provide a mock async session."""
    session = AsyncMock()
    return session

def test_health_check(test_client: TestClient) -> None:
    """Test health check endpoint."""
    # The health endpoint might be /health or /api/v1/health depending on mounting
    # Based on src/api/__init__.py, it seems likely to be /api/v1/health if included there
    # But monitoring.py defines it as /health relative to the router.
    # Let's try /api/v1/health assuming the router is mounted there.
    
    # We need to mock the database check and cache check to ensure consistent results
    with patch('src.api.endpoints.monitoring.engine') as mock_engine, \
         patch('src.core.cache.cache.ping', return_value=True), \
         patch('src.core.cache.cache.metrics_snapshot', return_value={'hits': 10, 'misses': 1}):
        
        # Mock the connection context manager
        mock_connection = MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_connection
        
        response = test_client.get("/api/v1/health")
        
        # If /api/v1/health is not found, it might be just /health if not prefixed
        if response.status_code == 404:
            response = test_client.get("/health")
            
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert "cache" in data["components"]

def test_search_matches(test_client: TestClient, mock_async_session) -> None:
    """Test match search endpoint."""
    # Override the dependency
    app.dependency_overrides[get_async_session] = lambda: mock_async_session
    
    try:
        query_text = "manchester"
        league = "EPL"
        limit = 10
        
        # Mock cache miss to force DB query
        with patch('src.core.cache.cache_manager.get', return_value=None), \
             patch('src.core.cache.cache_manager.set'):
            
            # Mock DB execution result
            # The endpoint executes a query and expects scalars().all()
            mock_result = MagicMock()
            mock_match = MagicMock()
            mock_match.id = 1
            mock_match.home_team.name = "Manchester United"
            mock_match.away_team.name = "Liverpool"
            mock_match.league_id = "EPL"
            mock_match.match_date = datetime(2023, 10, 24, 15, 0, 0)
            mock_match.venue = "Old Trafford"
            
            mock_result.scalars.return_value.all.return_value = [mock_match]
            mock_async_session.execute.return_value = mock_result
            
            response = test_client.get(f"/api/v1/matches/search?q={query_text}&league={league}&limit={limit}")
            
            assert response.status_code == 200
            results = response.json()
            assert isinstance(results, list)
            assert len(results) == 1
            assert results[0]["home_team"] == "Manchester United"
            assert results[0]["league"] == "EPL"

    finally:
        # Clean up dependency override
        app.dependency_overrides = {}

def test_get_match_detail(test_client: TestClient, mock_async_session) -> None:
    """Test get match detail endpoint."""
    app.dependency_overrides[get_async_session] = lambda: mock_async_session
    
    try:
        match_id = "1"
        
        # Mock cache miss
        with patch('src.core.cache.cache_manager.get', return_value=None), \
             patch('src.core.cache.cache_manager.set'):
            
            # Mock DB result
            mock_result = MagicMock()
            mock_match = MagicMock()
            mock_match.id = 1
            mock_match.home_team.name = "Arsenal"
            mock_match.away_team.name = "Chelsea"
            mock_match.league.name = "EPL"
            mock_match.match_date = datetime(2023, 10, 25, 15, 0, 0)
            mock_match.venue = "Emirates"
            mock_match.status = "scheduled"
            mock_match.referee = "Mike Dean"
            mock_match.season = "2023/2024"
            
            mock_result.scalar_one_or_none.return_value = mock_match
            
            # Mock odds fetch (internal function)
            # Since _fetch_latest_odds is an async function in the same module, 
            # we might need to patch it or mock the DB query it performs.
            # It performs a separate query.
            # Let's just mock the DB execution for the odds query as well.
            # The first execute is for match, the second is for odds.
            
            mock_odds_result = MagicMock()
            mock_odds_row = MagicMock()
            mock_odds_row.match_id = "1"
            mock_odds_row.home_win = 2.5
            mock_odds_row.draw = 3.2
            mock_odds_row.away_win = 2.8
            mock_odds_result.scalars.return_value.all.return_value = [mock_odds_row]
            
            # Configure side_effect for execute to return match result then odds result
            mock_async_session.execute.side_effect = [mock_result, mock_odds_result]
            
            response = test_client.get(f"/api/v1/matches/{match_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == "1"
            assert data["home_team"] == "Arsenal"
            assert data["odds"]["home_win"] == 2.5

    finally:
        app.dependency_overrides = {}
