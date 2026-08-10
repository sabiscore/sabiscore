"""
Test prediction pipeline with sample matches
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime
from src.models.orchestrator import orchestrator

def test_predictions():
    """
    Test predictions on sample matches
    """
    print("=" * 80)
    print("PREDICTION PIPELINE TEST")
    print("=" * 80)
    
    test_matches = [
        {
            'league': 'epl',
            'match_id': 'test_1',
            'home_team': 'Arsenal',
            'away_team': 'Liverpool',
            'match_date': datetime(2025, 11, 10, 15, 0),
            'odds_home': 2.10,
            'odds_draw': 3.40,
            'odds_away': 3.20,
        },
        {
            'league': 'laliga',
            'match_id': 'test_2',
            'home_team': 'Barcelona',
            'away_team': 'Real Madrid',
            'match_date': datetime(2025, 11, 10, 20, 0),
            'odds_home': 2.00,
            'odds_draw': 3.60,
            'odds_away': 3.50,
        },
        {
            'league': 'bundesliga',
            'match_id': 'test_3',
            'home_team': 'Bayern Munich',
            'away_team': 'Borussia Dortmund',
            'match_date': datetime(2025, 11, 10, 17, 30),
            'odds_home': 1.80,
            'odds_draw': 3.80,
            'odds_away': 4.20,
        },
    ]
    
    for match in test_matches:
        print(f"\n{'='*80}")
        print(f"{match['home_team']} vs {match['away_team']} ({match['league'].upper()})")
        print(f"{'='*80}")
        
        # Build odds dict
        odds = {
            'home_win': match['odds_home'],
            'draw': match['odds_draw'],
            'away_win': match['odds_away'],
        }
        
        try:
            # Get prediction
            result = orchestrator.predict(match['league'], match, odds)
            
            if 'error' in result:
                print(f"❌ Prediction failed: {result['error']}")
                continue
            
            # Display results
            predictions = result['predictions']
            print("\n📊 Predictions:")
            print(f"   Home Win: {predictions['home_win']:.2%}")
            print(f"   Draw:     {predictions['draw']:.2%}")
            print(f"   Away Win: {predictions['away_win']:.2%}")
            print(f"   Confidence: {predictions['confidence']:.2%}")
            
            # Display value bets
            if result.get('has_edge'):
                print("\n💰 Value Bets:")
                for outcome, edge in result['value_bets'].items():
                    print(f"   {outcome.upper()}")
                    print(f"      Edge: +{edge['edge_pct']:.1f}%")
                    print(f"      Kelly: {edge['kelly_stake_pct']:.1f}%")
                    print(f"      CLV: +{edge['clv_cents']:.1f}¢")
            else:
                print("\n⏸️  No value bets found")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("✅ TEST COMPLETE")
    print(f"{'='*80}")

if __name__ == "__main__":
    test_predictions()
