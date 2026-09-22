"""
Betfair Exchange Odds Scraper
==============================

Scrapes exchange odds from Betfair for sharp line comparison.

Features:
- Back/lay odds for home/draw/away
- Matched liquidity information
- Exchange vs bookmaker edge calculation
- Historical odds movement tracking

Exchange odds are typically sharper than bookmaker odds and provide
additional signal for value bet detection.
"""

import logging
from typing import Any, Dict, Optional, Tuple


from .base_scraper import BaseScraper, CACHE_DIR, PROCESSED_DIR

logger = logging.getLogger(__name__)


class BetfairExchangeScraper(BaseScraper):
    """
    Scraper for Betfair Exchange odds.

    Note: Full Betfair API requires authentication. This scraper
    provides a fallback using public data sources and simulation
    for development purposes.

    In production, integrate with official Betfair Exchange API:
    https://developer.betfair.com/exchange-api/
    """

    BASE_URL = "https://www.betfair.com"

    def __init__(
        self, api_key: Optional[str] = None, session_token: Optional[str] = None
    ):
        super().__init__(
            base_url=self.BASE_URL,
            rate_limit_delay=3.0,  # More conservative for exchange
            max_retries=3,
            timeout=30,
        )

        self.api_key = api_key
        self.session_token = session_token

        # Cache paths
        self.cache_dir = CACHE_DIR / "betfair"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_processed_path = PROCESSED_DIR / "betfair_odds.json"

    def _fetch_remote(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Fetch exchange odds for a match.

        In development mode, returns simulated odds based on
        typical exchange spreads and liquidity patterns.
        """
        # If API credentials available, use official API
        if self.api_key and self.session_token:
            return self._fetch_via_api(home_team, away_team, league)

        # No credentials and no public endpoint available; fail closed.
        logger.info(
            f"No Betfair credentials for {home_team} vs {away_team}; returning None"
        )
        return None

    def _fetch_via_api(
        self, home_team: str, away_team: str, league: str
    ) -> Optional[Dict]:
        """
        Fetch odds via official Betfair API.

        Requires valid API key and session token.
        """
        # API endpoint for exchange odds

        # Actual API integration not yet implemented; fail closed.
        logger.warning("Betfair API integration not fully implemented")
        return None

    def _parse_data(self, page_content: Dict) -> Dict:
        """Parse exchange odds data."""
        return page_content

    def get_match_odds(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Optional[Dict]:
        """
        Get exchange odds for a match.

        Args:
            home_team: Home team name
            away_team: Away team name
            league: League identifier

        Returns:
            Dict with back/lay odds and liquidity
        """
        return self.fetch_data(home_team, away_team, league)

    def calculate_exchange_edge(
        self, model_prob: float, back_odds: float, lay_odds: float
    ) -> Dict[str, float]:
        """
        Calculate edge against exchange prices.

        Args:
            model_prob: Our model's probability
            back_odds: Best available back price
            lay_odds: Best available lay price

        Returns:
            Dict with edge calculations
        """
        # Back edge: profit if we're right
        back_implied = 1 / back_odds
        back_edge = model_prob - back_implied

        # Lay edge: profit if outcome doesn't happen
        lay_implied = 1 / lay_odds
        lay_edge = (1 - model_prob) - (1 - lay_implied)

        # Expected value
        back_ev = (model_prob * (back_odds - 1)) - (1 - model_prob)
        lay_ev = ((1 - model_prob) * 1) - (model_prob * (lay_odds - 1))

        return {
            "back_edge": round(back_edge * 100, 2),  # Percentage
            "lay_edge": round(lay_edge * 100, 2),
            "back_ev": round(back_ev * 100, 2),
            "lay_ev": round(lay_ev * 100, 2),
            "recommended": "back"
            if back_edge > lay_edge
            else "lay"
            if lay_edge > 0.02
            else "pass",
        }

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def calculate_exchange_features(
        self, home_team: str, away_team: str, league: str = "EPL"
    ) -> Dict[str, float]:
        """Return structured exchange odds metrics for feature engineering."""

        odds_payload = self.get_match_odds(home_team, away_team, league)
        if not odds_payload:
            return {}

        match_odds = odds_payload.get("markets", {}).get("match_odds", {})

        def _extract(
            side: str,
        ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
            entry = match_odds.get(side, {})
            return (
                self._safe_float(entry.get("back")),
                self._safe_float(entry.get("lay")),
                self._safe_float(entry.get("liquidity_gbp")),
            )

        home_back, home_lay, home_liquidity = _extract("home")
        draw_back, draw_lay, draw_liquidity = _extract("draw")
        away_back, away_lay, away_liquidity = _extract("away")

        features: Dict[str, float] = {}
        if home_back is not None:
            features["home_back"] = home_back
        if home_lay is not None:
            features["home_lay"] = home_lay
        if draw_back is not None:
            features["draw_back"] = draw_back
        if draw_lay is not None:
            features["draw_lay"] = draw_lay
        if away_back is not None:
            features["away_back"] = away_back
        if away_lay is not None:
            features["away_lay"] = away_lay

        if home_back is not None and home_lay is not None:
            features["home_spread"] = round(home_lay - home_back, 4)
        if draw_back is not None and draw_lay is not None:
            features["draw_spread"] = round(draw_lay - draw_back, 4)
        if away_back is not None and away_lay is not None:
            features["away_spread"] = round(away_lay - away_back, 4)

        if home_liquidity is not None:
            features["home_liquidity_gbp"] = home_liquidity
        if draw_liquidity is not None:
            features["draw_liquidity_gbp"] = draw_liquidity
        if away_liquidity is not None:
            features["away_liquidity_gbp"] = away_liquidity

        total_liquidity = self._safe_float(odds_payload.get("total_liquidity_gbp"))
        if total_liquidity is not None:
            features["total_liquidity_gbp"] = total_liquidity

        margin_pct = self._safe_float(odds_payload.get("margin"))
        if margin_pct is not None:
            features["market_margin_pct"] = margin_pct

        return features


# Convenience function
def get_betfair_odds(
    home_team: str, away_team: str, league: str = "EPL"
) -> Optional[Dict]:
    """Get Betfair exchange odds for a match."""
    return BetfairExchangeScraper().get_match_odds(home_team, away_team, league)
