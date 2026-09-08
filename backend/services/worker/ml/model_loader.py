import os
import joblib

_model_instance = None


def get_model():
    global _model_instance
    if _model_instance is None:
        model_path = os.environ.get("MODEL_ARTIFACT_PATH", "/models/flood_risk_v1.pkl")
        _model_instance = joblib.load(model_path)
    return _model_instance
