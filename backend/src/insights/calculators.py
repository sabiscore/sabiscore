import math
import warnings
from typing import Any, Dict, List, Optional, Tuple

# Suppress numpy warnings for division operations
warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*divide by zero.*")
warnings.filterwarnings(
    "ignore", category=RuntimeWarning, message=".*invalid value encountered.*"
)


def calculate_expected_value(
    model_prob: float, odds: float, stake: float = 1.0
) -> float:
    """Return the expected value (EV) for a wager."""

    if not 0 <= model_prob <= 1 or odds <= 1.0 or stake <= 0:
        return 0.0
    win_amount = stake * (odds - 1)
    loss_amount = stake
    return (model_prob * win_amount) - ((1 - model_prob) * loss_amount)


def calculate_kelly_stake(
    prob: float,
    odds: float,
    bankroll: float = 100.0,
    kelly_fraction: float = 1.0,
) -> float:
    """Compute Kelly staking amount with optional fractional Kelly."""

    if not 0 <= prob <= 1 or odds <= 1.0 or bankroll <= 0 or kelly_fraction <= 0:
        return 0.0
    kelly = ((prob * (odds - 1)) - (1 - prob)) / (odds - 1)
    kelly = max(0.0, min(kelly, 1.0))
    stake = bankroll * kelly * min(kelly_fraction, 1.0)
    return float(round(stake, 6))


def calculate_implied_probability(decimal_odds: float) -> Optional[float]:
    """Convert decimal odds into implied probability."""

    if decimal_odds <= 0:
        return None
    return 1.0 / decimal_odds


def calculate_value_percentage(model_prob: float, market_prob: float) -> float:
    """Return percentage edge of model probability versus market probability."""

    if not 0 <= model_prob <= 1 or not 0 < market_prob < 1:
        return 0.0
    edge = (model_prob - market_prob) / market_prob * 100.0
    return float(round(edge, 6))


def calculate_confidence_interval(
    prob: float,
    sample_size: int = 1000,
    confidence_level: float = 0.95,
) -> Tuple[float, float]:
    """Wilson score interval for a Bernoulli proportion."""

    if sample_size <= 0 or not 0 <= prob <= 1:
        return prob, prob

    z_scores = {0.95: 1.96, 0.99: 2.576, 0.90: 1.645}
    z = z_scores.get(confidence_level, 1.96)
    centre = (prob + (z**2) / (2 * sample_size)) / (1 + (z**2) / sample_size)
    margin = (
        z
        * math.sqrt((prob * (1 - prob) + (z**2) / (4 * sample_size)) / sample_size)
        / (1 + (z**2) / sample_size)
    )
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    return lower, upper


def calculate_roi(
    initial_bankroll: float, final_bankroll: float, total_stakes: float
) -> float:
    """Return on investment percentage for a betting strategy."""

    if total_stakes <= 0:
        return 0.0
    profit = final_bankroll - initial_bankroll
    return (profit / total_stakes) * 100.0


def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02) -> float:
    """Annualised Sharpe ratio based on daily returns."""

    if not returns:
        return 0.0
    # Use pure-Python math to avoid hard dependency on numpy in test environments
    n = len(returns)
    if n <= 1:
        return 0.0

    # Mean of returns
    mean_ret = sum(returns) / n
    # Sample standard deviation (ddof=1)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
    std_dev = math.sqrt(max(variance, 0.0))
    if std_dev == 0:
        return 0.0

    daily_rf = risk_free_rate / 252
    excess_mean = mean_ret - daily_rf
    sharpe = excess_mean / std_dev
    # Annualise using sqrt(252) trading days
    return float(sharpe * math.sqrt(252))


def calculate_betting_edge(
    model_probs: Dict[str, float], market_odds: Dict[str, float]
) -> Dict[str, float]:
    """Edge (model probability minus market implied probability) per outcome."""

    edges: Dict[str, float] = {}
    for outcome, model_prob in model_probs.items():
        if outcome not in market_odds:
            continue
        implied = calculate_implied_probability(market_odds[outcome])
        if implied is None:
            continue
        edges[outcome] = model_prob - implied
    return edges


def optimize_bet_size(
    kelly_stake: float, max_stake: float, min_stake: float = 0.0
) -> float:
    """Clamp Kelly bet to bankroll constraints."""

    if max_stake < min_stake:
        max_stake = min_stake
    return max(min_stake, min(kelly_stake, max_stake))


def calculate_breakeven_odds(prob: float) -> float:
    """Return decimal odds required to break even at probability prob."""

    if not 0 < prob < 1:
        return float("inf")
    return 1.0 / prob


def assess_bet_quality(
    ev: float, confidence: float, market_liquidity: float = 1.0
) -> Dict[str, Any]:
    """Heuristic assessment combining EV, confidence, and liquidity."""

    quality_score = (ev * 100.0 + confidence * 50.0 + market_liquidity * 25.0) / 1.75
    quality_score = max(0.0, min(100.0, quality_score))

    if quality_score >= 80:
        tier = "Excellent"
        recommendation = "Strong bet"
    elif quality_score >= 60:
        tier = "Good"
        recommendation = "Consider betting"
    elif quality_score >= 40:
        tier = "Fair"
        recommendation = "Optional"
    else:
        tier = "Poor"
        recommendation = "Avoid"

    return {
        "quality_score": quality_score,
        "tier": tier,
        "recommendation": recommendation,
        "ev_contribution": ev * 100.0,
        "confidence_contribution": confidence * 50.0,
        "liquidity_contribution": market_liquidity * 25.0,
    }
