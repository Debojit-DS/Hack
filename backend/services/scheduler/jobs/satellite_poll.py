import os
import time
import json
import logging
from datetime import datetime
from celery_app import celery_app
from db.session import SessionLocal
from db.models import StormObservation
from clients.isro_bhuvan_client import fetch_latest_thermal_tile
from cv.thermal_tile_pipeline import extract_cloud_center

logger = logging.getLogger("meghdrishti_scheduler")


def log_event(event, extra):
    payload = {"event": event, "job": "satellite_poll"}
    payload.update(extra)
    logger.info(json.dumps(payload))


def poll_satellite_tiles():
    start = time.time()
    log_event("job_start", {"timestamp": datetime.utcnow().isoformat()})

    try:
        tile_path = fetch_latest_thermal_tile()
        cloud_center = extract_cloud_center(tile_path)
        if cloud_center is None:
            log_event("job_skip", {"reason": "no_storm_signature"})
            return

        db = SessionLocal()
        result = db.execute(
            "INSERT INTO storm_observations (center_point) VALUES (ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)) RETURNING obs_id",
            {"lon": cloud_center["lon"], "lat": cloud_center["lat"]},
        ).first()
        obs_id = result.obs_id
        db.commit()
        db.close()

        celery_app.send_task("advection.predict_storm_path", kwargs={"obs_id": obs_id})

        duration_ms = int((time.time() - start) * 1000)
        log_event("job_success", {"obs_id": obs_id, "lat": cloud_center["lat"], "lon": cloud_center["lon"], "duration_ms": duration_ms})
    except Exception as exc:
        log_event("job_failure", {"error": str(exc)})
