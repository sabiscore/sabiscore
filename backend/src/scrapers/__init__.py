"""
Enhanced scraper system with Puppeteer cluster, error handling, and creative data fusion.
"""

from .understat_xg import UnderstatXGScraper
from .fbref_scouting import FBrefScoutingScraper
from .twitter_sentiment import TwitterSentimentAnalyzer
from .cluster_manager import ScraperClusterManager

__all__ = [
    "UnderstatXGScraper",
    "FBrefScoutingScraper",
    "TwitterSentimentAnalyzer",
    "ScraperClusterManager",
]
