from backend.src.models.ensemble import SabiScoreEnsemble

models_path = r"c:\Users\USR\Documents\SabiScore\models"
try:
    model = SabiScoreEnsemble.load_latest_model(models_path)
    print(f"Model loaded: {model is not None}")
    print(f"Is trained: {model.is_trained}")
    print(f"Meta model: {model.meta_model is not None}")
except Exception as e:
    print(f"Failed to load: {e}")
