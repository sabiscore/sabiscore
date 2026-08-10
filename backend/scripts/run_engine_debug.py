import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
sys.path.append(str(project_root))

from src.insights.engine import InsightsEngine  # noqa: E402 - path bootstrap precedes import
from src.models.ensemble import SabiScoreEnsemble  # noqa: E402 - path bootstrap precedes import

if __name__ == "__main__":
    model = SabiScoreEnsemble.load_model("../models/epl_ensemble.pkl")
    engine = InsightsEngine(model)
    try:
        insights = engine.generate_match_insights("Manchester United vs Liverpool", "EPL")
        print("Success", insights.keys())
    except Exception:
        import traceback
        traceback.print_exc()
