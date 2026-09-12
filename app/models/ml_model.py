"""
Runtime wrapper around the trained GradientBoostingClassifier.
Loads the persisted model bundle and exposes a simple predict() API
plus a lightweight, per-prediction "factor contribution" breakdown
(feature_importance x normalized feature value) used to power the
dashboard's explainability panel -- this is what lets the system say
*why* a village is flagged, not just that it is.
"""

import os
import joblib
import numpy as np

from app.models.slope_stability import factor_of_safety

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "risk_model.joblib")

_bundle = None


def _load():
    global _bundle
    if _bundle is None:
        if not os.path.exists(_MODEL_PATH):
            raise RuntimeError(
                "Model not found. Run `python train_model.py` first to train and save it.")
        _bundle = joblib.load(_MODEL_PATH)
    return _bundle


# Normalization ranges used only to make the explainability panel
# human-readable (0-1 scaled contribution), not used by the model itself.
_FEATURE_NORM_RANGES = {
    "rainfall_mm_hr": (0, 60),
    "rainfall_24hr_cumulative_mm": (0, 250),
    "soil_moisture_pct": (0, 100),
    "slope_angle_deg": (5, 55),
    "factor_of_safety": (0.1, 3.0),   # inverted below (lower FS = higher hazard)
    "historical_landslides_10yr": (0, 18),
    "historical_flash_floods_10yr": (0, 10),
    "distance_to_stream_m": (500, 10),  # inverted (closer = higher hazard)
    "drainage_density": (0, 1),
}

# Group raw features into the 4 "multi-source" categories used in the
# problem statement, for the dashboard's fusion panel.
FACTOR_GROUPS = {
    "Rainfall": ["rainfall_mm_hr", "rainfall_24hr_cumulative_mm"],
    "Soil Moisture": ["soil_moisture_pct"],
    "Slope Stability": ["slope_angle_deg", "factor_of_safety"],
    "Historical + Terrain": ["historical_landslides_10yr", "historical_flash_floods_10yr",
                              "distance_to_stream_m", "drainage_density"],
}


def build_feature_row(village, sensor_snapshot):
    fs = factor_of_safety(
        village["slope_angle_deg"], village["soil_type"], sensor_snapshot["soil_moisture_pct"])
    return {
        "rainfall_mm_hr": sensor_snapshot["rainfall_mm_hr"],
        "rainfall_24hr_cumulative_mm": sensor_snapshot["rainfall_24hr_cumulative_mm"],
        "soil_moisture_pct": sensor_snapshot["soil_moisture_pct"],
        "slope_angle_deg": village["slope_angle_deg"],
        "factor_of_safety": fs,
        "historical_landslides_10yr": village["historical_landslides_10yr"],
        "historical_flash_floods_10yr": village["historical_flash_floods_10yr"],
        "distance_to_stream_m": village["distance_to_stream_m"],
        "drainage_density": village["drainage_density"],
    }


def _normalize(feature_name, value):
    lo, hi = _FEATURE_NORM_RANGES[feature_name]
    if hi == lo:
        return 0.0
    return float(np.clip((value - lo) / (hi - lo), 0, 1))


def predict(features: dict):
    bundle = _load()
    model = bundle["model"]
    feature_names = bundle["feature_names"]
    risk_labels = bundle["risk_labels"]

    x = np.array([[features[f] for f in feature_names]])
    proba = model.predict_proba(x)[0]
    pred_idx = int(np.argmax(proba))

    importances = getattr(model, "feature_importances_", np.ones(len(feature_names)) / len(feature_names))

    contributions = {}
    for fname, imp in zip(feature_names, importances):
        norm_val = _normalize(fname, features[fname])
        contributions[fname] = float(imp) * norm_val

    group_scores = {}
    for group, feats in FACTOR_GROUPS.items():
        total = sum(contributions[f] for f in feats)
        group_scores[group] = total
    total_all = sum(group_scores.values()) or 1e-9
    group_scores_pct = {g: round(100 * v / total_all, 1) for g, v in group_scores.items()}

    return {
        "risk_label": risk_labels[pred_idx],
        "risk_index": pred_idx,
        "probabilities": {lbl: round(float(p), 3) for lbl, p in zip(risk_labels, proba)},
        "composite_score": round(float(sum(p * i for p, i in zip(proba, range(len(proba))))) / (len(proba) - 1), 3),
        "factor_contributions_pct": group_scores_pct,
        "factor_of_safety": features["factor_of_safety"],
    }


def risk_labels():
    return _load()["risk_labels"]
