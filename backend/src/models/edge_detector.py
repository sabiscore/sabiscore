"""
Edge Detector v2
Advanced value bet identification with Smart Kelly bankroll management

Features:
- Fair probability calculation with Platt calibration
- Implied odds comparison across multiple bookmakers
- Smart Kelly criterion (fractional Kelly for risk management)
- Dynamic bankroll sync
- CLV tracking
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class EdgeDetector:
    """Detect +EV betting opportunities and calculate optimal stakes"""

    def __init__(
        self,
        min_edge_threshold: float = 0.042,  # 4.2% minimum edge
        kelly_fraction: float = 0.25,  # Quarter-Kelly
        max_stake_pct: float = 0.05,  # Max 5% of bankroll per bet
        min_odds: float = 1.50,  # Minimum odds to consider
        max_odds: float = 10.0,  # Maximum odds to consider
    ):
        """Initialize edge detector

        Args:
            min_edge_threshold: Minimum edge to trigger alert (0.042 = 4.2%)
            kelly_fraction: Fraction of Kelly criterion to use (0.25 = Quarter-Kelly)
            max_stake_pct: Maximum stake as % of bankroll
            min_odds: Minimum decimal odds to consider
            max_odds: Maximum decimal odds to consider
        """
        self.min_edge_threshold = min_edge_threshold
        self.kelly_fraction = kelly_fraction
        self.max_stake_pct = max_stake_pct
        self.min_odds = min_odds
        self.max_odds = max_odds

    def calculate_edge(
        self,
        fair_probability: float,
        decimal_odds: float,
        volume_weight: float = 1.0,
    ) -> float:
        """Calculate betting edge

        Formula:
            implied_prob = 1 / decimal_odds
            value = fair_prob - implied_prob
            edge = value * (decimal_odds - 1) * volume_weight

        Args:
            fair_probability: True probability from calibrated model
            decimal_odds: Bookmaker decimal odds
            volume_weight: Market volume weight (0.0-1.0)

        Returns:
            Edge value (positive = +EV, negative = -EV)
        """
        try:
            # Validate inputs
            if fair_probability <= 0 or fair_probability >= 1:
                raise ValueError(f"Invalid fair_probability: {fair_probability}")

            if decimal_odds < 1.0:
                raise ValueError(f"Invalid decimal_odds: {decimal_odds}")

            # Calculate implied probability (with vig removed)
            implied_prob = 1.0 / decimal_odds

            # Calculate value
            value = fair_probability - implied_prob

            # Calculate edge
            edge = value * (decimal_odds - 1.0) * volume_weight

            return round(edge, 4)

        except Exception as e:
            logger.error(f"Error calculating edge: {e}")
            return 0.0

    def calculate_kelly_stake(
        self,
        fair_probability: float,
        decimal_odds: float,
        bankroll: float,
    ) -> Dict[str, float]:
        """Calculate Smart Kelly stake

        Uses fractional Kelly to reduce variance while maintaining growth:
        - Raw Kelly signal: f = (bp - q) / b
        - Fractional Kelly: stake = f * kelly_fraction

        Args:
            fair_probability: True probability
            decimal_odds: Decimal odds
            bankroll: Current bankroll

        Returns:
            Dictionary with stake calculations
        """
        try:
            # Kelly formula components
            b = decimal_odds - 1.0  # Net odds
            p = fair_probability  # Win probability
            q = 1.0 - p  # Lose probability

            # Raw Kelly fraction before public stake caps.
            kelly_f = (b * p - q) / b

            # Apply fractional Kelly
            fractional_f = kelly_f * self.kelly_fraction

            # Calculate stake amount
            stake_amount = fractional_f * bankroll

            # Apply maximum stake constraint
            max_stake = self.max_stake_pct * bankroll
            if stake_amount > max_stake:
                stake_amount = max_stake
                actual_fraction = stake_amount / bankroll
            else:
                actual_fraction = fractional_f

            # Ensure positive stake
            if stake_amount < 0:
                stake_amount = 0
                actual_fraction = 0

            return {
                "raw_kelly_fraction": round(kelly_f, 4),
                "fractional_kelly": round(fractional_f, 4),
                "actual_fraction": round(actual_fraction, 4),
                "stake_amount": round(stake_amount, 2),
                "max_stake": round(max_stake, 2),
                "expected_profit": round(stake_amount * b * p, 2),
            }

        except Exception as e:
            logger.error(f"Error calculating Kelly stake: {e}")
            return {
                "raw_kelly_fraction": 0.0,
                "fractional_kelly": 0.0,
                "actual_fraction": 0.0,
                "stake_amount": 0.0,
                "max_stake": 0.0,
                "expected_profit": 0.0,
            }

    def detect_value_bet(
        self,
        fair_probability: float,
        bookmaker_odds: Dict[str, float],
        bankroll: float,
        volume_weights: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict]:
        """Detect value betting opportunity

        Args:
            fair_probability: Calibrated probability from model
            bookmaker_odds: Dict of {bookmaker_name: decimal_odds}
            bankroll: Current bankroll
            volume_weights: Optional volume weights per bookmaker

        Returns:
            Value bet details if opportunity detected, None otherwise
        """
        if volume_weights is None:
            volume_weights = {bookie: 1.0 for bookie in bookmaker_odds}

        best_edge = -float("inf")
        best_bet = None

        for bookmaker, odds in bookmaker_odds.items():
            # Filter odds range
            if odds < self.min_odds or odds > self.max_odds:
                continue

            # Calculate edge
            weight = volume_weights.get(bookmaker, 1.0)
            edge = self.calculate_edge(fair_probability, odds, weight)

            # Check if edge exceeds threshold
            if edge > self.min_edge_threshold and edge > best_edge:
                best_edge = edge

                # Calculate Kelly stake
                kelly_calc = self.calculate_kelly_stake(
                    fair_probability, odds, bankroll
                )

                best_bet = {
                    "bookmaker": bookmaker,
                    "decimal_odds": odds,
                    "fair_probability": round(fair_probability, 4),
                    "implied_probability": round(1.0 / odds, 4),
                    "edge": round(edge, 4),
                    "edge_percentage": round(edge * 100, 2),
                    "kelly_stake": kelly_calc,
                    "detected_at": datetime.now(timezone.utc).isoformat(),
                }

        if best_bet:
            logger.info(
                f"Value bet detected: {best_bet['bookmaker']} @ {best_bet['decimal_odds']} "
                f"(edge: {best_bet['edge_percentage']:+.2f}%)"
            )

        return best_bet

    def calculate_clv(
        self,
        bet_odds: float,
        closing_odds: float,
    ) -> Dict[str, float]:
        """Calculate Closing Line Value

        Args:
            bet_odds: Odds when bet was placed
            closing_odds: Closing line odds (e.g., from Pinnacle)

        Returns:
            CLV metrics in cents and percentages
        """
        try:
            bet_prob = 1.0 / bet_odds
            closing_prob = 1.0 / closing_odds

            # CLV in cents
            clv_cents = (bet_prob - closing_prob) * 100

            # CLV as percentage
            clv_pct = ((closing_odds - bet_odds) / bet_odds) * 100

            return {
                "clv_cents": round(clv_cents, 2),
                "clv_percentage": round(clv_pct, 2),
                "bet_odds": bet_odds,
                "closing_odds": closing_odds,
                "bet_implied_prob": round(bet_prob, 4),
                "closing_implied_prob": round(closing_prob, 4),
            }

        except Exception as e:
            logger.error(f"Error calculating CLV: {e}")
            return {
                "clv_cents": 0.0,
                "clv_percentage": 0.0,
                "bet_odds": bet_odds,
                "closing_odds": closing_odds,
                "bet_implied_prob": 0.0,
                "closing_implied_prob": 0.0,
            }

    def assess_bet_quality(
        self,
        fair_probability: float,
        decimal_odds: float,
        confidence: float,
    ) -> str:
        """Assess overall bet quality

        Args:
            fair_probability: Model probability
            decimal_odds: Bookmaker odds
            confidence: Model confidence (0.0-1.0)

        Returns:
            Quality tier: "PREMIUM", "VALUE", "MARGINAL", "AVOID"
        """
        edge = self.calculate_edge(fair_probability, decimal_odds)

        # Premium: High edge + high confidence
        if edge > 0.08 and confidence > 0.75:
            return "PREMIUM"

        # Value: Decent edge + good confidence
        if edge > 0.05 and confidence > 0.65:
            return "VALUE"

        # Marginal: Small edge or lower confidence
        if edge > 0.02 and confidence > 0.55:
            return "MARGINAL"

        # Avoid: Negative or tiny edge
        return "AVOID"

    def compare_bookmakers(
        self,
        fair_probability: float,
        bookmaker_odds: Dict[str, float],
    ) -> List[Dict]:
        """Compare value across multiple bookmakers

        Args:
            fair_probability: Model probability
            bookmaker_odds: Dict of bookmaker odds

        Returns:
            Sorted list of bookmaker comparisons (best first)
        """
        comparisons = []

        for bookmaker, odds in bookmaker_odds.items():
            edge = self.calculate_edge(fair_probability, odds)

            comparisons.append(
                {
                    "bookmaker": bookmaker,
                    "odds": odds,
                    "edge": round(edge, 4),
                    "edge_pct": round(edge * 100, 2),
                    "implied_prob": round(1.0 / odds, 4),
                }
            )

        # Sort by edge (descending)
        comparisons.sort(key=lambda x: x["edge"], reverse=True)

        return comparisons


def example_usage():
    """Example usage of EdgeDetector"""
    detector = EdgeDetector(
        min_edge_threshold=0.042,
        kelly_fraction=0.25,
        max_stake_pct=0.05,
    )

    # Model prediction
    fair_prob = 0.52  # 52% win probability
    bankroll = 1000.0

    # Bookmaker odds
    odds = {
        "Bet365": 2.10,
        "Pinnacle": 1.96,
        "Betfair": 2.08,
    }

    # Detect value bet
    value_bet = detector.detect_value_bet(fair_prob, odds, bankroll)

    if value_bet:
        print("🎯 VALUE BET DETECTED")
        print(f"Bookmaker: {value_bet['bookmaker']}")
        print(f"Odds: {value_bet['decimal_odds']}")
        print(f"Edge: {value_bet['edge_percentage']:+.2f}%")
        print(f"Stake: ${value_bet['kelly_stake']['stake_amount']:.2f}")
        print(f"Expected Profit: ${value_bet['kelly_stake']['expected_profit']:.2f}")
    else:
        print("❌ No value bet detected")

    # Compare bookmakers
    print("\n📊 BOOKMAKER COMPARISON")
    comparisons = detector.compare_bookmakers(fair_prob, odds)
    for comp in comparisons:
        print(f"{comp['bookmaker']}: {comp['odds']} (edge: {comp['edge_pct']:+.2f}%)")


if __name__ == "__main__":
    example_usage()
