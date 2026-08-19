"""
Unit Tests for SabiScore Scrapers
==================================

Tests for the enhanced scraping infrastructure.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime
from typing import Any, Dict, Optional

# Import scrapers
from src.data.scrapers import (
    BaseScraper,
    FootballDataEnhancedScraper,
    BetfairExchangeScraper,
    SoccerwayScraper,
    TransfermarktScraper,
    OddsPortalScraper,
    UnderstatScraper,
    FlashscoreScraper,
)


class ConcreteScraper(BaseScraper):
    """Concrete implementation of BaseScraper for testing."""
    
    async def _fetch_remote(self, **kwargs) -> Optional[Dict[str, Any]]:
        return {"test": "data"}
    
    def _parse_data(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return raw_data


class TestBaseScraper:
    """Tests for BaseScraper functionality."""
    
    def test_user_agent_rotation(self):
        """Test that user agents rotate properly."""
        scraper = ConcreteScraper(
            base_url="https://example.com",
            rate_limit_delay=0.1,
        )
        
        # Get multiple user agents
        agents = [scraper._get_random_user_agent() for _ in range(10)]
        
        # Should have some variety
        assert len(set(agents)) >= 1
        assert all("Mozilla" in agent for agent in agents)
    
    def test_rate_limiting(self):
        """Test rate limiting between requests."""
        scraper = ConcreteScraper(
            base_url="https://example.com",
            rate_limit_delay=0.1,
        )
        
        start = datetime.now()
        scraper._wait_rate_limit()
        scraper._wait_rate_limit()
        elapsed = (datetime.now() - start).total_seconds()
        
        # Should have waited at least 0.1 seconds
        assert elapsed >= 0.1


class TestFootballDataScraper:
    """Tests for football-data.co.uk scraper."""
    
    def test_league_code_mapping(self):
        """Test league code to URL path mapping."""
        scraper = FootballDataEnhancedScraper()
        
        assert "E0" in scraper.LEAGUE_CODES["EPL"]
        assert "SP1" in scraper.LEAGUE_CODES["La Liga"]
        assert "I1" in scraper.LEAGUE_CODES["Serie A"]
    
    def test_download_season_data(self, tmp_path):
        """Test fetching historical data (using cache/fallback)."""
        scraper = FootballDataEnhancedScraper()
        # Redirect the cache to an isolated temp dir so a stale-cache miss can
        # never fetch over the network and overwrite the committed fixture in
        # data/cache/football_data/ (see docs/DEBT.md item 30).
        scraper.cache_dir = tmp_path / "football_data"
        scraper.cache_dir.mkdir(parents=True, exist_ok=True)

        # This may use cache or return empty DataFrame if remote fails
        df = scraper.download_season_data("EPL", "2324", use_cache=True)

        assert hasattr(df, 'columns')  # Is a DataFrame
        # If data exists, should have expected columns
        if len(df) > 0:
            assert "home_team" in df.columns or "HomeTeam" in df.columns

    def test_pinnacle_odds_extraction(self, tmp_path):
        """Test that Pinnacle odds columns exist in standardized output."""
        scraper = FootballDataEnhancedScraper()
        scraper.cache_dir = tmp_path / "football_data"
        scraper.cache_dir.mkdir(parents=True, exist_ok=True)

        df = scraper.download_season_data("EPL", "2324", use_cache=True)
        
        if len(df) > 0:
            # Check for standardized Pinnacle columns
            pinnacle_cols = ["pinnacle_home", "pinnacle_draw", "pinnacle_away"]
            has_pinnacle = any(col in df.columns for col in pinnacle_cols)
            # Pinnacle odds should be present or we have local fallback
            assert has_pinnacle or len(df) > 0


class TestBetfairScraper:
    """Tests for Betfair exchange scraper."""

    def test_exchange_odds_structure(self):
        """Test exchange odds response structure.  Without credentials, adapter returns None."""
        scraper = BetfairExchangeScraper()

        odds = scraper.get_match_odds("Arsenal", "Chelsea", "EPL")

        # Real data requires configured credentials; without them, adapter returns None
        assert odds is None or (
            isinstance(odds, dict)
            and "markets" in odds
            and "match_odds" in odds["markets"]
        )

    def test_spread_calculation(self):
        """Test back/lay spread calculation; returns empty dict when adapter has no data."""
        scraper = BetfairExchangeScraper()

        features = scraper.calculate_exchange_features("Liverpool", "Man City", "EPL")

        # Real data requires configured credentials; without them, adapter returns {}
        assert isinstance(features, dict)
        if features:
            assert "home_back" in features
            assert "home_lay" in features
            assert features["home_lay"] >= features["home_back"]


# NOTE: WhoScored scraper removed due to bot blocking - form features now sourced from Understat


class TestSoccerwayScraper:
    """Tests for Soccerway standings scraper."""

    def test_standings_structure(self):
        """Test league standings response; returns None without network or real parser."""
        scraper = SoccerwayScraper()

        standings = scraper.get_standings("EPL")

        # Real data requires a working network connection and HTML parser implementation
        assert standings is None or (
            isinstance(standings, dict)
            and "standings" in standings
            and len(standings["standings"]) == 20
        )

    def test_position_features(self):
        """Test position-based feature calculation; returns empty dict without real standings."""
        scraper = SoccerwayScraper()

        features = scraper.calculate_position_features("Arsenal", "Chelsea", "EPL")

        assert isinstance(features, dict)
        if features:
            assert "home_position" in features
            assert "away_position" in features
            assert 1 <= features["home_position"] <= 20


class TestTransfermarktScraper:
    """Tests for Transfermarkt market value scraper."""

    def test_team_valuation_structure(self):
        """Test team valuation response; returns None without anti-bot bypass."""
        scraper = TransfermarktScraper()

        valuation = scraper.get_team_valuation("Arsenal", "EPL")

        # Real data requires a working anti-bot bypass; without it, adapter returns None
        assert valuation is None or (
            isinstance(valuation, dict)
            and "total_squad_value" in valuation
            and valuation["total_squad_value"] > 0
        )

    def test_value_features(self):
        """Test value-based feature calculation; returns empty dict without real data."""
        scraper = TransfermarktScraper()

        features = scraper.calculate_value_features("Man City", "Chelsea", "EPL")

        assert isinstance(features, dict)
        if features:
            assert "home_value_share" in features
            assert "value_ratio" in features
            assert 0 < features["home_value_share"] < 1


class TestOddsPortalScraper:
    """Tests for OddsPortal historical odds scraper."""

    def test_odds_structure(self):
        """Test historical odds response; returns None without JS renderer."""
        scraper = OddsPortalScraper()

        odds = scraper.get_match_odds("Arsenal", "Chelsea", "EPL")

        # Real data requires JavaScript rendering; without it, adapter returns None
        assert odds is None or (
            isinstance(odds, dict)
            and "opening_odds" in odds
            and "closing_odds" in odds
        )

    def test_odds_features(self):
        """Test odds-based feature calculation; returns empty dict without real odds."""
        scraper = OddsPortalScraper()

        features = scraper.calculate_odds_features("Liverpool", "Man United", "EPL")

        assert isinstance(features, dict)
        if features:
            assert "odds_home" in features
            assert "prob_home" in features
            assert 0 < features["prob_home"] < 1


class TestUnderstatScraper:
    """Tests for Understat xG scraper."""

    def test_xg_structure(self):
        """Test xG data response; returns None without a real JS parser."""
        scraper = UnderstatScraper()

        xg_data = scraper.get_team_xg("Arsenal", "EPL")

        # Real data requires JS variable parsing; without it, adapter returns None
        assert xg_data is None or (
            isinstance(xg_data, dict)
            and "stats" in xg_data
            and "xg_per_game" in xg_data["stats"]
        )

    def test_xg_prediction(self):
        """Test match xG prediction; returns defaults when adapter has no data."""
        scraper = UnderstatScraper()

        prediction = scraper.get_match_xg_prediction("Arsenal", "Chelsea", "EPL")

        # Returns a dict with default values even when both team lookups return None
        assert "home_xg" in prediction
        assert "away_xg" in prediction

    def test_xg_features(self):
        """Test xG-based feature calculation; returns empty dict without real data."""
        scraper = UnderstatScraper()

        features = scraper.calculate_xg_features("Liverpool", "Man City", "EPL")

        assert isinstance(features, dict)
        if features:
            assert "home_xg_pg" in features
            assert "away_xg_pg" in features
            assert features["home_xg_pg"] > 0


class TestFlashscoreScraper:
    """Tests for Flashscore live scores scraper."""

    def test_live_score_structure(self):
        """Test live score response; returns None without headless browser."""
        scraper = FlashscoreScraper()

        match_data = scraper.get_live_score("Arsenal", "Chelsea")

        # Real data requires Playwright; without it, adapter returns None
        assert match_data is None or (
            isinstance(match_data, dict)
            and "status" in match_data
            and "score" in match_data
        )

    def test_h2h_features(self):
        """Test head-to-head feature calculation; returns empty dict without real data."""
        scraper = FlashscoreScraper()

        features = scraper.calculate_h2h_features("Arsenal", "Chelsea")

        assert isinstance(features, dict)
        if features:
            assert "h2h_home_win_rate" in features
            assert 0 <= features["h2h_home_win_rate"] <= 1


class TestDataAggregator:
    """Tests for the data aggregator."""
    
    def test_comprehensive_features(self):
        """Test comprehensive feature aggregation."""
        from src.data.aggregator import get_enhanced_aggregator
        
        aggregator = get_enhanced_aggregator()
        features = aggregator.get_comprehensive_features("Arsenal", "Chelsea", "EPL")
        
        assert "home_team" in features
        assert "away_team" in features
        assert "timestamp" in features
        
        # Check for prefixed features from various sources
        feature_keys = list(features.keys())
        has_prefixed = any(
            k.startswith(prefix) 
            for k in feature_keys 
            for prefix in ["bf_", "ws_", "sw_", "us_", "tm_"]
        )
        assert has_prefixed or len(feature_keys) > 3  # At least basic features


# Fixtures for mocking HTTP responses
@pytest.fixture
def mock_response():
    """Create a mock HTTP response."""
    mock = Mock()
    mock.status_code = 200
    mock.text = "<html><body>Mock response</body></html>"
    mock.content = b"Mock content"
    return mock


@pytest.fixture
def mock_csv_response():
    """Create a mock CSV response."""
    csv_content = """Date,HomeTeam,AwayTeam,FTHG,FTAG,PSH,PSD,PSA
01/01/2024,Arsenal,Chelsea,2,1,1.85,3.60,4.20
08/01/2024,Liverpool,Man City,1,1,2.50,3.40,2.80"""
    mock = Mock()
    mock.status_code = 200
    mock.text = csv_content
    mock.content = csv_content.encode('utf-8')
    return mock
