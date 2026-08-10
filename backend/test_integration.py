#!/usr/bin/env python3
"""
Simple integration test for SabiScore core functionality
"""
import sys
from pathlib import Path

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

def test_core_functionality():
    """Test core SabiScore functionality"""
    try:
        from schemas.responses import InsightsResponse
        from datetime import datetime
        print("[PASS] Imports successful")

        # Test response creation
        response = InsightsResponse(
            matchup='Test vs Test',
            league='EPL',
            metadata={'matchup': 'Test vs Test', 'league': 'EPL', 'home_team': 'Test', 'away_team': 'Test'},
            predictions={'home_win_prob': 0.5, 'draw_prob': 0.3, 'away_win_prob': 0.2, 'prediction': 'home_win', 'confidence': 0.7},
            xg_analysis={'home_xg': 1.5, 'away_xg': 1.2, 'total_xg': 2.7, 'xg_difference': 0.3},
            value_analysis={},
            monte_carlo={'simulations': 1000, 'distribution': {}, 'confidence_intervals': {}},
            scenarios=[],
            explanation={},
            risk_assessment={'risk_level': 'medium', 'confidence_score': 0.7, 'value_available': True, 'recommendation': 'Proceed', 'distribution': {}, 'best_bet': None},
            narrative='Test narrative',
            generated_at=datetime.utcnow(),
            confidence_level=0.7
        )
        print("[PASS] Response creation successful")

        # Test JSON serialization
        response.model_dump()
        print("[PASS] JSON dump successful")

        # Test datetime serialization
        json_str = response.model_dump_json()
        print(f"[PASS] JSON serialization successful, length: {len(json_str)}")

        print("\nSUCCESS: All core functionality tests passed!")
        return True

    except Exception as e:
        print(f"[FAIL] Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_core_functionality()
    sys.exit(0 if success else 1)
