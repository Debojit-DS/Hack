"""
Trains the flash-flood / landslide risk classifier on a synthetically
generated but domain-informed dataset, and saves the model + metadata
to app/models/risk_model.joblib.

Run:  python train_model.py
"""

import argparse
import json
import os
import random
import numpy as np
import joblib
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

from app.models.slope_stability import factor_of_safety, SOIL_PARAMS

CITIZEN_TRAINING_LOG = "citizen_training_log.jsonl"
# Hard cap on how much a batch of citizen feedback can densify any one
# class, so a burst of reports (real or spammed) can never dominate the
# synthetic dataset or swing the model on its own -- this only runs
# offline, on demand, reviewed by whoever runs the command.
MAX_CITIZEN_FRACTION_PER_CLASS = 0.05

RANDOM_STATE = 42
random.seed(RANDOM_STATE)
np.random.seed(RANDOM_STATE)

FEATURE_NAMES = [
    "rainfall_mm_hr",
    "rainfall_24hr_cumulative_mm",
    "soil_moisture_pct",
    "slope_angle_deg",
    "factor_of_safety",
    "historical_landslides_10yr",
    "historical_flash_floods_10yr",
    "distance_to_stream_m",
    "drainage_density",
]

RISK_LABELS = ["Low", "Watch", "Warning", "Critical"]

N_SAMPLES = 14000
SAMPLES_PER_CLASS = N_SAMPLES // 4


def sample_row(regime=None):
    # Stratified scenario generation prevents the rare Critical class from
    # becoming an almost-unseen tail class in a synthetic training set.
    regime = regime or random.choice(range(4))
    soil_type = random.choice(list(SOIL_PARAMS.keys()))
    if regime == 0:  # Low
        slope = np.clip(np.random.normal(22, 5), 5, 38); soil_moisture = np.clip(np.random.normal(30, 8), 5, 55)
        rainfall_hr = np.clip(np.random.normal(4, 2), 0, 15); hist_land=np.random.poisson(2); hist_flood=np.random.poisson(1)
        dist_stream=np.clip(np.random.normal(220,60),60,500); drainage=np.clip(np.random.normal(.45,.12),.05,.75)
    elif regime == 1:  # Watch
        slope = np.clip(np.random.normal(30, 6), 10, 45); soil_moisture = np.clip(np.random.normal(48, 10), 15, 75)
        rainfall_hr = np.clip(np.random.normal(15, 5), 2, 35); hist_land=np.random.poisson(4); hist_flood=np.random.poisson(2)
        dist_stream=np.clip(np.random.normal(140,45),25,350); drainage=np.clip(np.random.normal(.58,.12),.15,.9)
    elif regime == 2:  # Warning
        slope = np.clip(np.random.normal(39, 5), 20, 52); soil_moisture = np.clip(np.random.normal(70, 9), 35, 95)
        rainfall_hr = np.clip(np.random.normal(30, 7), 8, 60); hist_land=np.random.poisson(7); hist_flood=np.random.poisson(4)
        dist_stream=np.clip(np.random.normal(75,25),15,180); drainage=np.clip(np.random.normal(.75,.10),.35,.98)
    else:  # Critical
        slope = np.clip(np.random.normal(47, 4), 30, 55); soil_moisture = np.clip(np.random.normal(88, 7), 55, 100)
        rainfall_hr = np.clip(np.random.normal(55, 10), 25, 90); hist_land=np.random.poisson(12); hist_flood=np.random.poisson(7)
        dist_stream=np.clip(np.random.normal(35,12),10,90); drainage=np.clip(np.random.normal(.88,.07),.55,.99)
    rainfall_24h = np.clip(rainfall_hr * np.random.uniform(3, 9) + np.random.exponential(8), 0, 500)

    fs = factor_of_safety(slope, soil_type, soil_moisture)

    return {
        "rainfall_mm_hr": round(rainfall_hr, 1),
        "rainfall_24hr_cumulative_mm": round(rainfall_24h, 1),
        "soil_moisture_pct": round(soil_moisture, 1),
        "slope_angle_deg": round(slope, 1),
        "factor_of_safety": fs,
        "historical_landslides_10yr": int(hist_land),
        "historical_flash_floods_10yr": int(hist_flood),
        "distance_to_stream_m": round(dist_stream, 1),
        "drainage_density": round(drainage, 2),
    }


def label_row(row):
    """
    Domain-informed composite hazard score -> 4-class label.
    Combines hydrological load, slope instability, proximity/drainage,
    and historical priors -- mirrors how a real multi-source fusion
    scoring rubric would be structured (each term interpretable).
    """
    rain_score = (row["rainfall_mm_hr"] / 40.0) * 0.5 + (row["rainfall_24hr_cumulative_mm"] / 200.0) * 0.5
    moisture_score = row["soil_moisture_pct"] / 100.0
    slope_score = np.clip((2.2 - row["factor_of_safety"]) / 1.8, 0, 1.4)
    proximity_score = np.clip((150 - row["distance_to_stream_m"]) / 150, 0, 1) * 0.6 + row["drainage_density"] * 0.4
    history_score = np.clip((row["historical_landslides_10yr"] + row["historical_flash_floods_10yr"]) / 18.0, 0, 1)

    composite = (
        0.34 * rain_score +
        0.22 * moisture_score +
        0.22 * slope_score +
        0.12 * proximity_score +
        0.10 * history_score
    )
    composite += np.random.normal(0, 0.04)  # measurement/model noise
    composite = float(np.clip(composite, 0, 2))

    if composite < 0.32:
        return 0, composite  # Low
    elif composite < 0.55:
        return 1, composite  # Watch
    elif composite < 0.78:
        return 2, composite  # Warning
    else:
        return 3, composite  # Critical


def _load_citizen_feedback():
    """Read resolved citizen reports logged by app/data/resilience.py.
    Only VERIFIED-POSITIVE reports (human "verified" or machine
    "auto-verified", i.e. a photo that agreed with the live sensor trend
    AND was confirmed) densify their corresponding risk-class bucket, and
    only up to MAX_CITIZEN_FRACTION_PER_CLASS of that bucket's samples.
    Rejected reports contribute nothing -- we don't synthesize "what a
    false report looked like", we simply don't reinforce it.
    This is intentionally an approximation (we don't have the exact
    sensor reading the citizen saw, only which risk class the village was
    in) -- good enough to nudge class balance toward real-world-confirmed
    scenarios, not to replace the domain-informed synthetic generator.
    """
    if not os.path.exists(CITIZEN_TRAINING_LOG):
        print("No citizen_training_log.jsonl found -- skipping citizen feedback.")
        return {}
    label_to_regime = {"Low": 0, "Watch": 1, "Warning": 2, "Critical": 3}
    counts = {0: 0, 1: 0, 2: 0, 3: 0}
    with open(CITIZEN_TRAINING_LOG) as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("label") != 1:
                continue
            regime = label_to_regime.get(row.get("live_risk_label_at_submission"))
            if regime is not None:
                counts[regime] += 1
    print(f"Loaded citizen feedback (verified-positive only): {counts}")
    return counts


def main(include_citizen_feedback=False):
    rows, labels = [], []
    # Rejection-sample each target class so all four operational states are
    # represented evenly. This makes validation meaningful for Critical.
    buckets = {i: [] for i in range(4)}
    while min(len(v) for v in buckets.values()) < SAMPLES_PER_CLASS:
        for regime in range(4):
            row = sample_row(regime)
            label, _ = label_row(row)
            if len(buckets[label]) < SAMPLES_PER_CLASS:
                buckets[label].append(row)

    if include_citizen_feedback:
        feedback_counts = _load_citizen_feedback()
        for regime, n_confirmed in feedback_counts.items():
            cap = int(SAMPLES_PER_CLASS * MAX_CITIZEN_FRACTION_PER_CLASS)
            n_extra = min(n_confirmed, cap)
            for _ in range(n_extra):
                buckets[regime].append(sample_row(regime))
            if n_extra:
                print(f"  + added {n_extra} extra samples to class {RISK_LABELS[regime]} "
                      f"(capped at {cap})")

    for label, bucket in buckets.items():
        rows.extend([ [r[f] for f in FEATURE_NAMES] for r in bucket ])
        labels.extend([label] * len(bucket))

    X = np.array(rows)
    y = np.array(labels)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=y)

    model = GradientBoostingClassifier(
        n_estimators=180, max_depth=3, learning_rate=0.08, random_state=RANDOM_STATE)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    print(classification_report(y_test, y_pred, target_names=RISK_LABELS))

    joblib.dump({
        "model": model,
        "feature_names": FEATURE_NAMES,
        "risk_labels": RISK_LABELS,
    }, "app/models/risk_model.joblib")
    print("Saved app/models/risk_model.joblib")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-citizen-feedback", action="store_true",
        help="Nudge class balance using verified-positive citizen reports logged to "
             "citizen_training_log.jsonl. Offline, explicit, capped -- see _load_citizen_feedback().")
    args = parser.parse_args()
    main(include_citizen_feedback=args.include_citizen_feedback)
