"""Demo data services for citizen safety, terrain, messaging and verification."""
from collections import Counter, deque
import json, math, os, time
from app.data.villages import VILLAGES

REPORTS = deque(maxlen=250)
MESSAGES = deque(maxlen=100)
VERIFICATIONS = deque(maxlen=250)

# Where citizen-uploaded photos are saved (served via the existing /static
# mount). This is a demo filesystem store; a real deployment would use
# object storage (S3/GCS) with lifecycle policies and access controls.
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Append-only log of RESOLVED citizen reports (auto-verified / verified /
# rejected / auto-rejected only -- never "pending"), for later OFFLINE,
# EXPLICIT, human-reviewed batch retraining. Nothing reads this file
# automatically; see train_model.py --include-citizen-feedback. Photos
# themselves are never fed into the live model -- only the resolved
# label + lightweight image signal are logged here.
CITIZEN_TRAINING_LOG = os.path.join(os.path.dirname(__file__), "..", "..", "citizen_training_log.jsonl")


def _log_for_offline_retraining(report):
    if report["status"] not in ("auto-verified", "verified", "rejected", "auto-rejected"):
        return
    label = 1 if report["status"] in ("auto-verified", "verified") else 0
    row = {
        "report_id": report["id"],
        "village_id": report["village_id"],
        "category": report["category"],
        "status": report["status"],
        "label": label,
        "image_flood_like_score": (report.get("image_analysis") or {}).get("flood_like_score"),
        "live_risk_label_at_submission": report.get("live_risk_label_at_submission"),
        "timestamp": report["timestamp"],
    }
    try:
        with open(CITIZEN_TRAINING_LOG, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass  # best-effort demo logging; never block the request on this

# Deterministic, demo-safe locations derived from village coordinates.
SAFE_SPOTS = []
HELIPADS = []
for i, v in enumerate(VILLAGES):
    SAFE_SPOTS.append({
        "id": f"SAFE-{i+1:03d}", "village_id": v["id"],
        "name": f"{v['name']} High-Ground Shelter", "lat": v["lat"] + 0.006,
        "lon": v["lon"] + 0.004, "capacity": max(80, int(v["population"] * 0.28)),
        "elevation_m": v["elevation_m"] + 38, "distance_km": round(0.7 + (i % 4) * 0.35, 1),
        "type": "Shelter / High Ground"
    })
    if i % 2 == 0:
        HELIPADS.append({
            "id": f"HELI-{i+1:03d}", "village_id": v["id"],
            "name": f"{v['name']} Emergency Helipad", "lat": v["lat"] - 0.004,
            "lon": v["lon"] - 0.005, "elevation_m": v["elevation_m"] + 12,
            "capacity": 2, "surface": "Prepared emergency landing zone"
        })


def _sample_histogram(hours):
    # Synthetic but smooth rainfall hazard series for PPT/demo exports.
    points = max(12, int(hours * 12))
    out = []
    for i in range(points):
        x = i / max(1, points - 1)
        rain = 5 + 18 * x + 9 * math.sin(x * math.pi * 1.4) + 2 * math.sin(x * math.pi * 7)
        risk = max(0, min(100, 18 + rain * 2.7 + 14 * x * x))
        out.append({"label": round(hours * x, 2), "rainfall": round(rain, 1), "risk": round(risk, 1)})
    return out


def histogram(hours):
    return {"hours": hours, "series": _sample_histogram(hours), "generated_at": time.time()}


def add_report(report, *, status="pending", confidence=0.0, triage_reason=None,
               image_url=None, image_analysis=None, live_risk_label_at_submission=None):
    """`status`/`confidence`/`triage_reason` are set by the citizen_signal
    triage step in routes.py *before* this is called for reports with a
    photo. Reports without a photo, or where the photo signal doesn't
    corroborate the live sensor trend, always land as "pending" here --
    i.e. this function never grants a report more trust than the triage
    step decided; it only records the outcome.
    """
    item = {
        "id": f"REP-{int(time.time()*1000)}", "timestamp": time.time(),
        "status": status, "confidence": confidence, "triage_reason": triage_reason,
        "image_url": image_url, "image_analysis": image_analysis,
        "live_risk_label_at_submission": live_risk_label_at_submission,
        **report,
    }
    REPORTS.appendleft(item)
    if status in ("auto-verified", "auto-rejected"):
        _log_for_offline_retraining(item)
    return item


def verify_report(report_id, verified, verifier="Duty Officer"):
    for r in REPORTS:
        if r["id"] == report_id:
            r["status"] = "verified" if verified else "rejected"
            r["confidence"] = 0.95 if verified else 0.08
            item = {"report_id": report_id, "verified": verified, "verifier": verifier, "timestamp": time.time()}
            VERIFICATIONS.appendleft(item)
            _log_for_offline_retraining(r)
            return r
    return None


def send_message(message, recipients, channels):
    delivered = max(0, int(recipients * (0.96 if "SMS" in channels else 0.90)))
    item = {"id": f"MSG-{int(time.time()*1000)}", "timestamp": time.time(),
            "message": message, "recipients": recipients, "delivered": delivered,
            "channels": channels, "status": "simulated-delivery"}
    MESSAGES.appendleft(item)
    return item
