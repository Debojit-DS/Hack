from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import List, Optional
import io, os, time, math, uuid
import pandas as pd
from datetime import datetime

from app.data.villages import VILLAGES, VILLAGE_BY_ID
from app.data.historical_events import HISTORICAL_EVENTS
from app.data.sensor_simulator import sensor_network
from app.data.citizen_db import init_db, get_session, Citizen
from app.models.ml_model import build_feature_row, predict
from app.models import citizen_signal
from app.models.vision_verifier import verify_disaster_image
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
        vision = verify_disaster_image(raw, category)
        if not vision.get("is_valid", False):
            raise HTTPException(
                422,
                detail={
                    "detail": "Image rejected as unrelated or false alarm",
                    "reason": vision.get("reason", "Image did not pass AI vision verification."),
                },
            )
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


@router.get("/verified-reports")
def verified_reports():
    items = [r for r in REPORTS if r.get("status") == "verified"]
    return {
        "service": "MeghDrishti Verified Community Signals",
        "count": len(items),
        "reports": items[:20],
        "updated_at": time.time(),
    }

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


# ---------------------------------------------------------------------------
# Citizen database management
# ---------------------------------------------------------------------------
class CitizenCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    address: str
    ward_id: Optional[str] = None
    ward_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    family_members: int = 0
    notes: Optional[str] = None


class CitizenUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    ward_id: Optional[str] = None
    ward_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    family_members: Optional[int] = None
    notes: Optional[str] = None


def _citizen_to_dict(c: Citizen) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "email": c.email,
        "address": c.address,
        "ward_id": c.ward_id,
        "ward_name": c.ward_name,
        "latitude": c.latitude,
        "longitude": c.longitude,
        "family_members": c.family_members,
        "notes": c.notes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("/citizens")
def list_citizens(ward_id: Optional[str] = None, q: Optional[str] = None):
    db = get_session()
    try:
        query = db.query(Citizen)
        if ward_id:
            query = query.filter(Citizen.ward_id == ward_id)
        if q:
            like = f"%{q}%"
            query = query.filter(
                (Citizen.name.ilike(like))
                | (Citizen.phone.ilike(like))
                | (Citizen.address.ilike(like))
            )
        citizens = query.all()
        return [_citizen_to_dict(c) for c in citizens]
    finally:
        db.close()


@router.get("/citizens/{citizen_id}")
def get_citizen(citizen_id: str):
    db = get_session()
    try:
        c = db.query(Citizen).filter(Citizen.id == citizen_id).first()
        if not c:
            raise HTTPException(404, "Citizen not found")
        return _citizen_to_dict(c)
    finally:
        db.close()


@router.post("/citizens")
def create_citizen(payload: CitizenCreate):
    db = get_session()
    try:
        cid = f"CTZ-{int(time.time()*1000)}"
        c = Citizen(
            id=cid,
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            ward_id=payload.ward_id,
            ward_name=payload.ward_name,
            latitude=payload.latitude,
            longitude=payload.longitude,
            family_members=payload.family_members,
            notes=payload.notes,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return _citizen_to_dict(c)
    finally:
        db.close()


@router.put("/citizens/{citizen_id}")
def update_citizen(citizen_id: str, payload: CitizenUpdate):
    db = get_session()
    try:
        c = db.query(Citizen).filter(Citizen.id == citizen_id).first()
        if not c:
            raise HTTPException(404, "Citizen not found")
        updates = payload.dict(exclude_unset=True)
        for k, v in updates.items():
            setattr(c, k, v)
        c.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(c)
        return _citizen_to_dict(c)
    finally:
        db.close()


@router.delete("/citizens/{citizen_id}")
def delete_citizen(citizen_id: str):
    db = get_session()
    try:
        c = db.query(Citizen).filter(Citizen.id == citizen_id).first()
        if not c:
            raise HTTPException(404, "Citizen not found")
        db.delete(c)
        db.commit()
        return {"detail": "Citizen deleted", "id": citizen_id}
    finally:
        db.close()


@router.post("/citizens/upload")
async def upload_citizens_excel(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "No file uploaded")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".xlsx", ".xls"):
        raise HTTPException(400, "Unsupported file format. Please upload .xlsx or .xls")

    raw = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(raw))
    except Exception as exc:
        raise HTTPException(400, f"Unable to parse Excel file: {exc}")

    required_cols = {"name", "phone", "address"}
    missing = required_cols - set(c.lower() for c in df.columns)
    if missing:
        raise HTTPException(400, f"Missing required columns: {', '.join(sorted(missing))}")

    col_map = {c.lower(): c for c in df.columns}
    db = get_session()
    inserted = 0
    errors = []
    try:
        for idx, row in df.iterrows():
            try:
                cid = f"CTZ-{int(time.time()*1000)}-{idx}"
                c = Citizen(
                    id=cid,
                    name=str(row.get(col_map.get("name", "name"), "")).strip(),
                    phone=str(row.get(col_map.get("phone", "phone"), "")).strip(),
                    email=str(row.get(col_map.get("email", "email"), "")).strip() or None,
                    address=str(row.get(col_map.get("address", "address"), "")).strip(),
                    ward_id=str(row.get(col_map.get("ward_id", "ward_id"), "")).strip() or None,
                    ward_name=str(row.get(col_map.get("ward_name", "ward_name"), "")).strip() or None,
                    latitude=float(row[col_map.get("latitude", "latitude")]) if col_map.get("latitude") and pd.notna(row.get(col_map.get("latitude", "latitude"))) else None,
                    longitude=float(row[col_map.get("longitude", "longitude")]) if col_map.get("longitude") and pd.notna(row.get(col_map.get("longitude", "longitude"))) else None,
                    family_members=int(row[col_map.get("family_members", "family_members")]) if col_map.get("family_members") and pd.notna(row.get(col_map.get("family_members", "family_members"))) else 0,
                    notes=str(row.get(col_map.get("notes", "notes"), "")).strip() or None,
                )
                db.add(c)
                inserted += 1
            except Exception as exc:
                errors.append(f"Row {idx + 2}: {exc}")
        db.commit()
    finally:
        db.close()

    return {
        "inserted": inserted,
        "errors": errors,
        "total_rows": len(df),
    }


@router.get("/citizens/export")
def export_citizens_excel(ward_id: Optional[str] = None):
    db = get_session()
    try:
        query = db.query(Citizen)
        if ward_id:
            query = query.filter(Citizen.ward_id == ward_id)
        citizens = query.all()
        if not citizens:
            raise HTTPException(404, "No citizens found")

        rows = []
        for c in citizens:
            rows.append({
                "ID": c.id,
                "Name": c.name,
                "Phone": c.phone,
                "Email": c.email,
                "Address": c.address,
                "Ward ID": c.ward_id,
                "Ward Name": c.ward_name,
                "Latitude": c.latitude,
                "Longitude": c.longitude,
                "Family Members": c.family_members,
                "Notes": c.notes,
            })
        df = pd.DataFrame(rows)
        out = io.BytesIO()
        df.to_excel(out, index=False, engine="openpyxl")
        out.seek(0)
        return Response(
            content=out.read(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=citizens.xlsx"},
        )
    finally:
        db.close()

