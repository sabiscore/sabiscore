#!/usr/bin/env python3
"""
Generate training data from database matches with real features
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict
import pandas as pd
import numpy as np

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from core.database import Match, SessionLocal  # noqa: E402 - path bootstrap precedes import

def calculate_team_stats(team_id: str, match_date: datetime, session) -> Dict[str, float]:
    """Calculate team statistics up to a given date"""
    # Get all matches for this team before the given date
    matches = session.query(Match).filter(
        ((Match.home_team_id == team_id) | (Match.away_team_id == team_id)) &
        (Match.match_date < match_date) &
        (Match.status == 'finished')
    ).order_by(Match.match_date.desc()).limit(10).all()

    if not matches:
        return {
            'goals_avg': 1.5, 'conceded_avg': 1.2, 'win_rate': 0.4,
            'possession_avg': 50.0, 'shots_avg': 12.0, 'shots_on_target_avg': 4.5
        }

    goals_scored = 0
    goals_conceded = 0
    wins = 0
    total_matches = len(matches)

    for match in matches:
        if match.home_team_id == team_id:
            goals_scored += match.home_score or 0
            goals_conceded += match.away_score or 0
            if match.home_score > match.away_score:
                wins += 1
        else:
            goals_scored += match.away_score or 0
            goals_conceded += match.home_score or 0
            if match.away_score > match.home_score:
                wins += 1

    return {
        'goals_avg': goals_scored / total_matches,
        'conceded_avg': goals_conceded / total_matches,
        'win_rate': wins / total_matches,
        'possession_avg': 50.0,  # Placeholder
        'shots_avg': 12.0,       # Placeholder
        'shots_on_target_avg': 4.5  # Placeholder
    }

def generate_training_data_from_db(league_id: str, num_samples: int = None) -> pd.DataFrame:
    """Generate training data from database matches"""

    with SessionLocal() as session:
        # Get finished matches for this league
        matches = session.query(Match).filter(
            Match.league_id == league_id,
            Match.status == 'finished',
            Match.home_score.isnot(None),
            Match.away_score.isnot(None)
        ).order_by(Match.match_date).all()

        if not matches:
            print(f"No finished matches found for {league_id}")
            return pd.DataFrame()

        print(f"Found {len(matches)} finished matches for {league_id}")

        training_samples = []

        for match in matches:
            # Calculate home team stats
            home_stats = calculate_team_stats(match.home_team_id, match.match_date, session)

            # Calculate away team stats
            away_stats = calculate_team_stats(match.away_team_id, match.match_date, session)

            # Determine result
            if match.home_score > match.away_score:
                result = 'home_win'
            elif match.home_score < match.away_score:
                result = 'away_win'
            else:
                result = 'draw'

            # Create feature vector
            sample = {
                # Home team features
                'home_goals_avg': home_stats['goals_avg'],
                'home_conceded_avg': home_stats['conceded_avg'],
                'home_win_rate': home_stats['win_rate'],
                'home_possession_avg': home_stats['possession_avg'],
                'home_shots_avg': home_stats['shots_avg'],
                'home_shots_on_target_avg': home_stats['shots_on_target_avg'],

                # Away team features
                'away_goals_avg': away_stats['goals_avg'],
                'away_conceded_avg': away_stats['conceded_avg'],
                'away_win_rate': away_stats['win_rate'],
                'away_possession_avg': away_stats['possession_avg'],
                'away_shots_avg': away_stats['shots_avg'],
                'away_shots_on_target_avg': away_stats['shots_on_target_avg'],

                # Match-specific features (placeholders for now)
                'home_form_points': np.random.uniform(0.3, 2.1),
                'away_form_points': np.random.uniform(0.3, 2.1),
                'home_recent_goals': np.random.uniform(0.5, 3.5),
                'away_recent_goals': np.random.uniform(0.5, 3.5),
                'home_recent_conceded': np.random.uniform(0.3, 2.8),
                'away_recent_conceded': np.random.uniform(0.3, 2.8),
                'home_clean_sheets': np.random.uniform(0, 5),
                'away_clean_sheets': np.random.uniform(0, 5),

                # Odds and market features (simulated)
                'home_win_implied_prob': np.random.uniform(0.25, 0.65),
                'draw_implied_prob': np.random.uniform(0.15, 0.35),
                'away_win_implied_prob': np.random.uniform(0.20, 0.60),
                'home_away_odds_ratio': np.random.uniform(0.8, 2.2),
                'draw_no_draw_ratio': np.random.uniform(0.3, 0.8),
                'home_implied_edge': np.random.uniform(-0.1, 0.15),
                'away_implied_edge': np.random.uniform(-0.1, 0.15),

                # Additional features
                'home_injuries_count': np.random.randint(0, 4),
                'away_injuries_count': np.random.randint(0, 4),
                'h2h_home_wins': np.random.randint(0, 10),
                'h2h_away_wins': np.random.randint(0, 10),
                'h2h_draws': np.random.randint(0, 5),
                'home_average_age': np.random.uniform(24, 28),
                'away_average_age': np.random.uniform(24, 28),
                'home_squad_value_mean': np.random.uniform(5e6, 50e6),
                'away_squad_value_mean': np.random.uniform(5e6, 50e6),
                'home_squad_size': np.random.randint(22, 30),
                'away_squad_size': np.random.randint(22, 30),
                'home_defensive_strength': np.random.uniform(0.7, 1.3),
                'away_defensive_strength': np.random.uniform(0.7, 1.3),
                'home_attacking_strength': np.random.uniform(0.7, 1.3),
                'away_attacking_strength': np.random.uniform(0.7, 1.3),
                'home_home_advantage': np.random.uniform(0.8, 1.4),
                'away_away_disadvantage': np.random.uniform(0.6, 1.2),
                'tactical_style_matchup': np.random.uniform(1.0, 4.0),

                'result': result
            }

            training_samples.append(sample)

        df = pd.DataFrame(training_samples)

        # Limit to requested number of samples if specified
        if num_samples and len(df) > num_samples:
            df = df.sample(n=num_samples, random_state=42).reset_index(drop=True)

        print(f"Generated {len(df)} training samples for {league_id}")
        return df

def main():
    """Generate training data for all leagues"""
    leagues = ['EPL', 'La Liga', 'Bundesliga', 'Serie A', 'Ligue 1']
    processed_dir = PROJECT_ROOT / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    for league in leagues:
        print(f"Generating training data for {league}...")
        try:
            df = generate_training_data_from_db(league, num_samples=1000)

            if not df.empty:
                # Save to CSV
                filename = f"{league.lower().replace(' ', '_')}_training.csv"
                filepath = processed_dir / filename
                df.to_csv(filepath, index=False)
                print(f"Saved {len(df)} samples to {filepath}")
            else:
                print(f"No data generated for {league}")

        except Exception as e:
            print(f"Failed to generate data for {league}: {e}")

if __name__ == "__main__":
    main()
