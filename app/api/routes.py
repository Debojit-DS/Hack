from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import List
import io, os, time, math, uuid

from app.data.villages import VILLAGES, VILLAGE_BY_ID
from app.data.historical_events import HISTORICAL_EVENTS
from app.data.sensor_simulator import sensor_network
from app.models.ml_model import build_feature_row, predict
from app.models import citizen_signal
from app.alerts.alert_engine import alert_engine
from app.data.resilience import (SAFE_SPOTS, HELIPADS, REPORTS, MESSAGES, UPLOAD_DIR,
                                  histogram, add_report, verify_report, send_message)

router = APIRouter()


def _village_current_view(village):
    state = sensor_network.get(village["id"])
    snapshot = state.snapshot()
    features = build_feature_row(village, snapshot)
    risk = predict(features)
    return village, snapshot, risk


@router.get("/villages")
def list_villages():
    out = []
    for v in VILLAGES:
        village, snapshot, risk = _village_current_view(v)
        out.append({"id": village["id"], "name": village["name"], "district": village["district"],
                    "lat": village["lat"], "lon": village["lon"], "population": village["population"],
                    "risk_label": risk["risk_label"], "composite_score": risk["composite_score"],
                    "rainfall_mm_hr": snapshot["rainfall_mm_hr"], "soil_moisture_pct": snapshot["soil_moisture_pct"],
                    "sensor_online": snapshot["sensor_online"], "stream_level_m": snapshot["stream_level_m"]})
    return out


@router.get("/villages/{village_id}")
def village_detail(village_id: str):
    village = VILLAGE_BY_ID.get(village_id)
    if not village: raise HTTPException(404, "Village not found")
    state = sensor_network.get(village_id); snapshot = state.snapshot()
    features = build_feature_row(village, snapshot); risk = predict(features)
    events = [e for e in HISTORICAL_EVENTS if e["village_id"] == village_id][:10]
    return {"village": village, "sensor": snapshot, "risk": risk, "features": features,
            "history": state.history_list(), "historical_events": events,
            "safe_spots": [s for s in SAFE_SPOTS if s["village_id"] == village_id],
            "helipads": [h for h in HELIPADS if h["village_id"] == village_id]}


@router.get("/alerts")
def get_alerts(): return {"active": alert_engine.active_alerts(), "log": alert_engine.recent_log(50)}


@router.get("/public-alerts")
def public_alerts():
    return {
        "service": "MeghDrishti Public Disaster Alerts",
        "updated_at": time.time(),
        "alerts": alert_engine.active_alerts(),
        "notice": "Prototype early-warning feed. Follow official district/state disaster-management instructions during an emergency."
    }


@router.get("/public-summary")
def public_summary():
    active = alert_engine.active_alerts()
    highest = next((x for x in ("Critical", "Warning", "Watch") if any(a["level"] == x for a in active)), "Low")
    return {
        "service": "MeghDrishti",
        "active_alerts": len(active),
        "highest_level": highest,
        "alerts": active[:20],
        "updated_at": time.time()
    }

@router.get("/historical-events")
def get_historical_events(village_id: str = None):
    return [e for e in HISTORICAL_EVENTS if not village_id or e["village_id"] == village_id]

@router.get("/status")
def system_status():
    total = len(VILLAGES); online = sum(1 for v in VILLAGES if sensor_network.get(v["id"]).snapshot()["sensor_online"])
    level_counts = {"Low":0,"Watch":0,"Warning":0,"Critical":0}
    for v in VILLAGES: level_counts[_village_current_view(v)[2]["risk_label"]] += 1
    return {"total_villages": total, "sensors_online": online, "sensors_total": total,
            "active_alerts": len(alert_engine.active_alerts()), "level_counts": level_counts,
            "tick_count": sensor_network.tick_count, "reports_pending": sum(r["status"] == "pending" for r in REPORTS)}

class StormRequest(BaseModel):
    village_ids: List[str]; intensity: float = Field(1.0, ge=0.2, le=3.0)

@router.post("/simulate/storm")
def simulate_storm(req: StormRequest):
    valid_ids = [vid for vid in req.village_ids if vid in VILLAGE_BY_ID]
    if not valid_ids: raise HTTPException(400, "No valid village_ids provided")
    sensor_network.trigger_storm(valid_ids, intensity=req.intensity)
    return {"triggered": valid_ids, "intensity": req.intensity}

@router.get("/villages-list-simple")
def villages_simple(): return [{"id":v["id"],"name":v["name"],"district":v["district"]} for v in VILLAGES]

@router.get("/safe-spots")
def safe_spots(village_id: str = None): return [s for s in SAFE_SPOTS if not village_id or s["village_id"] == village_id]

@router.get("/helipads")
def helipads(village_id: str = None): return [h for h in HELIPADS if not village_id or h["village_id"] == village_id]

@router.get("/terrain/{village_id}")
def terrain(village_id: str):
    v = VILLAGE_BY_ID.get(village_id)
    if not v: raise HTTPException(404, "Village not found")
    sensor = sensor_network.get(village_id).snapshot()
    grid=[]
    for y in range(13):
        row=[]
        for x in range(13):
            dx=x-6; dy=y-6
            elev=v["elevation_m"] + 85*math.exp(-(dx*dx+dy*dy)/22) + 12*math.sin(x*0.9)*math.cos(y*0.7)
            row.append(round(elev,1))
        grid.append(row)
    water_base=max(0, sensor["stream_level_m"]*18)
    return {"x": list(range(13)), "y": list(range(13)), "z": grid, "water_level_m": round(water_base,2), "elevation_m":v["elevation_m"]}

@router.get("/histogram")
def get_histogram(hours: int = 5):
    if hours not in (5,3,2,1): raise HTTPException(400, "hours must be 1, 2, 3 or 5")
    return histogram(hours)

class MessageRequest(BaseModel):
    message: str = Field(min_length=5, max_length=320)
    recipients: int = Field(ge=1, le=10000000)
    channels: List[str] = ["SMS"]

@router.post("/mass-message")
def mass_message(req: MessageRequest): return send_message(req.message, req.recipients, req.channels)

@router.get("/mass-message")
def message_log(): return list(MESSAGES)[:30]

MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6MB, generous for a phone photo, small enough to stay a demo


@router.post("/reports")
async def create_report(
    village_id: str = Form(...),
    category: str = Form(...),
    description: str = Form(..., min_length=3, max_length=500),
    severity: str = Form("Warning"),
    lat: float | None = Form(None),
    lon: float | None = Form(None),
    image: UploadFile | None = File(None),
):
    """Citizens can optionally attach a photo. The photo is used ONLY as a
    triage signal (see app/models/citizen_signal.py): it can speed up
    verification when it corroborates what the live sensor-driven ML model
    already sees for this village, and it never updates the live model or
    bypasses review on its own. Every resolved report (auto or human) is
    logged for later, explicit, offline batch retraining -- see
    train_model.py --include-citizen-feedback.
    """
    if village_id not in VILLAGE_BY_ID:
        raise HTTPException(400, "Unknown village")

    village = VILLAGE_BY_ID[village_id]
    snapshot = sensor_network.get(village_id).snapshot()
    live_risk = predict(build_feature_row(village, snapshot))
    live_risk_label = live_risk["risk_label"]

    image_url, image_analysis, duplicate = None, None, False
    if image is not None and image.filename:
        raw = await image.read()
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(400, "Image too large (max 6MB).")
        duplicate = citizen_signal.is_duplicate(village_id, raw)
        try:
            image_analysis = citizen_signal.analyze_image(raw)
        except Exception:
            raise HTTPException(400, "Unable to process image — please attach a valid photo.")
        ext = os.path.splitext(image.filename)[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            ext = ".jpg"
        fname = f"{uuid.uuid4().hex}{ext}"
        with open(os.path.join(UPLOAD_DIR, fname), "wb") as f:
            f.write(raw)
        image_url = f"/static/uploads/{fname}"

    status, confidence, reason = citizen_signal.triage(
        has_image=image is not None and bool(image.filename),
        image_analysis=image_analysis,
        duplicate=duplicate,
        live_risk_label=live_risk_label,
    )

    report = add_report(
        {"village_id": village_id, "category": category, "description": description,
         "severity": severity, "lat": lat, "lon": lon},
        status=status, confidence=confidence, triage_reason=reason,
        image_url=image_url, image_analysis=image_analysis,
        live_risk_label_at_submission=live_risk_label,
    )

    if status == "auto-verified":
        # Register the corroboration with the alert engine as a modifier
        # only -- it cannot fire an alert by itself (see alert_engine.py).
        score = citizen_signal.corroboration_score(image_analysis, live_risk_label)
        alert_engine.register_citizen_signal(village_id, score)

    return report

@router.get("/reports")
def reports(): return list(REPORTS)[:100]

class VerifyRequest(BaseModel): verified: bool; verifier: str = "Duty Officer"

@router.post("/reports/{report_id}/verify")
def verify(report_id: str, req: VerifyRequest):
    result=verify_report(report_id, req.verified, req.verifier)
    if not result: raise HTTPException(404, "Report not found")
    return result

@router.post("/cloudburst/analyze")
async def cloudburst_analyze(image: UploadFile = File(...)):
    """Lightweight image-analysis demo. Production should use a trained satellite/radar model."""
    raw = await image.read()
    try:
        from PIL import Image, ImageStat
        im=Image.open(io.BytesIO(raw)).convert("RGB")
        small=im.resize((64,64)); stat=ImageStat.Stat(small)
        mean=sum(stat.mean)/3; contrast=sum(stat.stddev)/3
        dark=sum(1 for p in small.getdata() if sum(p)/3 < 90)/(64*64)
        texture=min(1, contrast/70)
        score=max(0,min(100, 35 + dark*42 + texture*20 - mean*0.08))
        verdict="High" if score>=72 else "Moderate" if score>=48 else "Low"
        return {"filename":image.filename,"width":im.width,"height":im.height,"cloudburst_probability":round(score,1),
                "verdict":verdict,"signals":{"dark_cloud_fraction":round(dark,3),"texture_index":round(texture,3),"mean_brightness":round(mean,1)},
                "note":"Prototype image-processing signal; calibrate with labelled satellite/radar imagery before operational use."}
    except Exception as exc:
        raise HTTPException(400, f"Unable to process image: {exc}")
