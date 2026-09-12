"""
Citizen photo triage layer.

DESIGN PRINCIPLE (read before touching this file):
A citizen-submitted photo is a *corroborating* signal, never a sole
trigger, and it never updates the live risk model directly. Concretely:

  1. A photo can only SPEED UP verification, and only when it agrees
     with what the live sensor-driven ML model is already seeing for
     that same village (rainfall/soil-moisture/slope trend).
  2. A photo can never, by itself, push a village to Critical or fire
     an alert -- see app/alerts/alert_engine.py, which treats the
     corroboration score purely as a lead-time/annotation modifier.
  3. Resolved reports (auto-verified / verified / rejected / auto-
     rejected) are logged to a JSONL file for later, EXPLICIT, offline
     batch retraining (see train_model.py --include-citizen-feedback).
     Nothing in this file mutates risk_model.joblib.

This keeps the "reduce false alarms" goal intact: false alarms usually
come from acting on a single unverified/noisy signal. Requiring two
independent signals to agree (photo + live sensor trend) before
auto-resolving anything is what actually suppresses false alarms --
routing every photo straight into training/prediction would do the
opposite.
"""

import hashlib
import io
import time
from collections import deque

# --- simple spam / duplicate-image guard -----------------------------------
# Rolling window of (village_id, sha256, timestamp). This is intentionally
# crude (exact-hash match, not perceptual hashing) -- good enough to catch
# the "same photo resubmitted repeatedly" spam pattern in a prototype.
_RECENT_IMAGE_HASHES = deque(maxlen=1000)
_DUPLICATE_WINDOW_SEC = 30 * 60

RISK_WEIGHT = {"Low": 0.0, "Watch": 0.35, "Warning": 0.65, "Critical": 0.85}


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_duplicate(village_id: str, raw: bytes) -> bool:
    """Flag exact repeat submissions of the same image for the same village
    within a short window -- a cheap first line of defence against spam
    before anything gets an "auto-verified" boost."""
    now = time.time()
    h = _hash(raw)
    dup = any(
        vid == village_id and hh == h and (now - ts) <= _DUPLICATE_WINDOW_SEC
        for vid, hh, ts in _RECENT_IMAGE_HASHES
    )
    _RECENT_IMAGE_HASHES.append((village_id, h, now))
    return dup


def analyze_image(raw: bytes) -> dict:
    """Very lightweight heuristic image signal (same family as the existing
    /api/cloudburst/analyze demo endpoint). This is NOT a trained
    classifier -- it's a stand-in signal for the prototype. In a real
    deployment this would be a calibrated CNN trained on labelled
    flood/landslide imagery, reviewed and versioned like any other model,
    not swapped in from raw uploads.
    """
    from PIL import Image, ImageStat

    im = Image.open(io.BytesIO(raw)).convert("RGB")
    small = im.resize((64, 64))
    stat = ImageStat.Stat(small)
    pixels = list(small.getdata())

    mean = sum(stat.mean) / 3
    contrast = sum(stat.stddev) / 3
    dark_frac = sum(1 for p in pixels if sum(p) / 3 < 90) / len(pixels)
    murky_frac = sum(1 for p in pixels if abs(p[0] - p[2]) < 18 and p[1] < 150) / len(pixels)
    texture = min(1.0, contrast / 70)

    score = max(0.0, min(100.0, 28 + dark_frac * 34 + murky_frac * 22 + texture * 16 - mean * 0.05))

    if score >= 70:
        label = "Likely flood/landslide imagery"
    elif score >= 40:
        label = "Ambiguous"
    else:
        label = "Unlikely flood/landslide imagery"

    return {
        "flood_like_score": round(score, 1),
        "label": label,
        "mean_brightness": round(mean, 1),
        "texture_index": round(texture, 3),
    }


def corroboration_score(image_analysis: dict | None, live_risk_label: str) -> float:
    """0-1 score combining (a) whether the live sensor-driven ML model
    already sees elevated risk for this village and (b) whether the photo
    looks flood/landslide-like. Deliberately weighted toward the sensor
    signal -- a dramatic-looking photo alone should not swing this much.
    """
    sensor_component = RISK_WEIGHT.get(live_risk_label, 0.0)
    image_component = (image_analysis["flood_like_score"] / 100.0) if image_analysis else 0.3
    return round(min(1.0, 0.6 * sensor_component + 0.4 * image_component), 3)


def triage(*, has_image: bool, image_analysis: dict | None, duplicate: bool, live_risk_label: str):
    """Decide what happens to a new report *before* any human looks at it.

    Returns (status, confidence, reason). Only two automatic outcomes
    exist: "auto-verified" (both signals agree) and "auto-rejected"
    (spam/duplicate). Everything else -- including a scary photo with NO
    sensor corroboration, or no photo at all -- stays "pending" for a
    human. That asymmetry is intentional: it's easy to auto-confirm when
    two signals agree, and unsafe to auto-dismiss a report just because
    the photo signal is weak.
    """
    score = corroboration_score(image_analysis, live_risk_label)

    if duplicate:
        return "auto-rejected", 0.05, "Duplicate image resubmitted within 30 minutes."

    if (
        has_image
        and image_analysis
        and image_analysis["flood_like_score"] >= 70
        and live_risk_label in ("Watch", "Warning", "Critical")
    ):
        # Capped below what a human verification grants (0.95) -- this
        # signal is corroborated but still machine-only.
        confidence = min(0.80, 0.45 + score * 0.45)
        return (
            "auto-verified",
            round(confidence, 3),
            f"Auto-confirmed: photo signal ({image_analysis['flood_like_score']}) "
            f"matches live '{live_risk_label}' sensor trend for this village.",
        )

    return "pending", round(score, 3), "Awaiting officer verification."
