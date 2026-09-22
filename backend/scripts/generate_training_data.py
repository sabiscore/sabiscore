#!/usr/bin/env python3
"""
Generate mock training data for model training
"""

import pandas as pd
import numpy as np
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def generate_mock_training_data(league: str, num_samples: int = 1000):
    """Generate mock training data for a league"""
    np.random.seed(42)

    # Generate features
    data = {}
    feature_names = [
        "home_goals_avg",
        "away_goals_avg",
        "home_conceded_avg",
        "away_conceded_avg",
        "home_win_rate",
        "away_win_rate",
        "home_possession_avg",
        "away_possession_avg",
        "home_form_points",
        "away_form_points",
        "home_recent_goals",
        "away_recent_goals",
        "home_recent_conceded",
        "away_recent_conceded",
        "home_clean_sheets",
        "away_clean_sheets",
        "home_win_implied_prob",
        "draw_implied_prob",
        "away_win_implied_prob",
        "home_away_odds_ratio",
        "draw_no_draw_ratio",
        "home_implied_edge",
        "away_implied_edge",
        "home_injuries_count",
        "away_injuries_count",
        "h2h_home_wins",
        "h2h_away_wins",
        "h2h_draws",
        "home_average_age",
        "away_average_age",
        "home_squad_value_mean",
        "away_squad_value_mean",
        "home_squad_size",
        "away_squad_size",
        "home_defensive_strength",
        "away_defensive_strength",
        "home_attacking_strength",
        "away_attacking_strength",
        "home_home_advantage",
        "away_away_disadvantage",
        "league_position_diff",
        "head_to_head_last_5",
        "form_trend_home",
        "form_trend_away",
        "rest_days_home",
        "rest_days_away",
        "travel_distance",
        "weather_impact",
        "motivation_home",
        "motivation_away",
        "tactical_style_matchup",
    ]

    for feature in feature_names:
        if "rate" in feature or "prob" in feature or "ratio" in feature:
            data[feature] = np.random.uniform(0, 1, num_samples)
        elif (
            "count" in feature
            or "wins" in feature
            or "draws" in feature
            or "sheets" in feature
        ):
            data[feature] = np.random.randint(0, 10, num_samples)
        elif "age" in feature:
            data[feature] = np.random.uniform(24, 30, num_samples)
        elif "value" in feature:
            data[feature] = np.random.uniform(10, 100, num_samples)
        elif "size" in feature:
            data[feature] = np.random.randint(20, 30, num_samples)
        else:
            data[feature] = np.random.uniform(0, 5, num_samples)

    # Generate target
    # Simple logic: higher home win rate -> more likely home win
    home_win_prob = data["home_win_rate"] / (
        data["home_win_rate"] + data["away_win_rate"] + 0.1
    )
    draw_prob = data["draw_implied_prob"]
    away_win_prob = data["away_win_implied_prob"]

    # Normalize
    total = home_win_prob + draw_prob + away_win_prob
    home_win_prob /= total
    draw_prob /= total
    away_win_prob /= total

    # Sample result
    results = []
    for i in range(num_samples):
        rand = np.random.random()
        if rand < home_win_prob[i]:
            results.append("home_win")
        elif rand < home_win_prob[i] + draw_prob[i]:
            results.append("draw")
        else:
            results.append("away_win")

    data["result"] = results

    df = pd.DataFrame(data)

    # Save as csv
    league_slug = league.lower().replace(" ", "_")
    output_path = PROCESSED_DIR / f"{league_slug}_training.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    print(f"Generated {num_samples} samples for {league} at {output_path}")


if __name__ == "__main__":
    leagues = ["EPL", "La Liga", "Bundesliga", "Serie A", "Ligue 1"]
    for league in leagues:
        generate_mock_training_data(league)
