"""Tests for data aggregation module with fallback scenarios."""
from unittest.mock import MagicMock, patch
import pandas as pd

from src.data.aggregator import DataAggregator


def test_aggregator_with_live_data():
    """Test successful data aggregation when scrapers return valid data."""
    with patch("src.data.aggregator.FlashscoreScraper") as MockFlashscore, \
         patch("src.data.aggregator.OddsPortalScraper") as MockOdds, \
         patch("src.data.aggregator.TransfermarktScraper") as MockTransfermarkt:
        
        # Create mock instances
        flashscore_mock = MagicMock()
        odds_mock = MagicMock()
        transfermarkt_mock = MagicMock()
        
        MockFlashscore.return_value = flashscore_mock
        MockOdds.return_value = odds_mock
        MockTransfermarkt.return_value = transfermarkt_mock
        
        # Mock successful responses
        sample_data = pd.DataFrame([{
            "home_team": "TeamA", "away_team": "TeamB",
            "home_score": 2, "away_score": 1,
            "date": "2025-10-01"
        }])
        flashscore_mock.scrape_match_results.return_value = sample_data
        odds_mock.scrape_odds.return_value = {"home_win": 2.1}
        transfermarkt_mock.scrape_injuries.return_value = pd.DataFrame()
        transfermarkt_mock.scrape_player_values.return_value = pd.DataFrame(columns=["age", "value"])
        
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()
        
        assert not data["historical_stats"].empty
        assert data["metadata"]["freshness"]["historical_stats"] is not None


def test_aggregator_fallback_to_cache():
    """Test fallback to cached data when scrapers fail."""
    # Setup cache mock
    cached_data = {
        "historical_stats": [{"home_team": "TeamA", "away_team": "TeamB"}],
        "metadata": {"cache": {"status": "cached", "cached_at": "2025-10-01"}}
    }
    with patch("src.data.aggregator.cache.get", return_value=cached_data), \
         patch("src.data.aggregator.cache.set", return_value=True):
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()

    assert data["metadata"]["cache"]["status"] == "cached"
    assert "cached_at" in data["metadata"]["cache"]
    assert isinstance(data["historical_stats"], pd.DataFrame)
    assert not data["historical_stats"].empty


def test_aggregator_graceful_scraper_failure():
    """Test empty but valid response when all scrapers fail."""
    with patch("src.data.aggregator.FlashscoreScraper") as MockFlashscore, \
         patch("src.data.aggregator.OddsPortalScraper") as MockOdds, \
         patch("src.data.aggregator.TransfermarktScraper") as MockTransfermarkt:
        
        # Create mock instances that return empty data
        flashscore_mock = MagicMock()
        odds_mock = MagicMock()
        transfermarkt_mock = MagicMock()
        
        MockFlashscore.return_value = flashscore_mock
        MockOdds.return_value = odds_mock
        MockTransfermarkt.return_value = transfermarkt_mock
        
        # Ensure scrapers return empty DataFrames
        flashscore_mock.scrape_match_results.return_value = pd.DataFrame()
        odds_mock.scrape_odds.return_value = {}
        transfermarkt_mock.scrape_injuries.return_value = pd.DataFrame()
        transfermarkt_mock.scrape_player_values.return_value = pd.DataFrame(columns=["age", "value"])
        
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()
        
        assert isinstance(data["historical_stats"], pd.DataFrame)
        assert "freshness" in data["metadata"]
        assert isinstance(data["metadata"]["freshness"], dict)


def test_aggregator_empty_scrapers():
    """Test aggregator handles empty responses from all scrapers."""
    with patch("src.data.aggregator.FlashscoreScraper") as MockFlashscore, \
         patch("src.data.aggregator.OddsPortalScraper") as MockOdds, \
         patch("src.data.aggregator.TransfermarktScraper") as MockTransfermarkt:
        
        # Setup mocks to return empty data
        flashscore_mock = MagicMock()
        flashscore_mock.scrape_match_results.return_value = pd.DataFrame()
        
        odds_mock = MagicMock()
        odds_mock.scrape_odds.return_value = {}
        
        transfermarkt_mock = MagicMock()
        transfermarkt_mock.scrape_injuries.return_value = pd.DataFrame()
        transfermarkt_mock.scrape_player_values.return_value = pd.DataFrame()
        
        MockFlashscore.return_value = flashscore_mock
        MockOdds.return_value = odds_mock
        MockTransfermarkt.return_value = transfermarkt_mock
        
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()
        
        # Should return empty but valid data structures
        assert isinstance(data["historical_stats"], pd.DataFrame)
        assert isinstance(data["odds"], dict)
        assert isinstance(data["injuries"], pd.DataFrame)


def test_aggregator_cache_usage():
    """Test aggregator properly uses cache."""
    # Setup cache mock
    cached_data = {
        "historical_stats": pd.DataFrame([{"home_team": "TeamA", "away_team": "TeamB"}]),
        "metadata": {"cache": {"status": "cached", "cached_at": "2025-10-01"}}
    }
    with patch("src.data.aggregator.cache.get", return_value=cached_data):
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()

    assert data["metadata"]["cache"]["status"] == "cached"
    assert "cached_at" in data["metadata"]["cache"]
    assert isinstance(data["historical_stats"], pd.DataFrame)
    assert not data["historical_stats"].empty


def test_aggregator_error_handling():
    """Test aggregator handles scraper errors gracefully."""
    with patch("src.data.aggregator.FlashscoreScraper") as MockFlashscore:
        MockFlashscore.return_value.scrape_match_results.side_effect = Exception("Test error")
        
        aggregator = DataAggregator("TeamA vs TeamB", "EPL")
        data = aggregator.fetch_match_data()
        
        # Should still return valid structure despite errors
        assert isinstance(data, dict)
        assert "metadata" in data
