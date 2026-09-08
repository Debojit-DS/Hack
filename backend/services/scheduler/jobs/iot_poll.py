import os
import time
import json
import logging
from datetime import datetime
from celery_app import celery_app
from db.session import SessionLocal
from db.models import Sensor, SensorReading
from clients.iot_gateway_client import fetch_latest_reading

logger = logging.getLogger("meghdrishti_scheduler")


def log_event(event, extra):
    payload = {"event": event, "job": "iot_poll"}
    payload.update(extra)
    logger.info(json.dumps(payload))


def poll_iot_sensors():
    start = time.time()
    log_event("job_start", {"timestamp": datetime.utcnow().isoformat()})

    db = SessionLocal()
    sensors = db.query(Sensor).all()
    db.close()

    processed = 0
    skipped = 0
    for sensor in sensors:
        try:
            reading = fetch_latest_reading(sensor.sensor_id)
            db = SessionLocal()
            db.execute(
                "INSERT INTO sensor_readings (sensor_id, value, timestamp) VALUES (:sid, :val, :ts)",
                {"sid": reading["sensor_id"], "val": reading["value"], "ts": reading["timestamp"]},
            )
            db.commit()
            db.close()

            celery_app.send_task("ml.run_inference", kwargs={"sensor_id": sensor.sensor_id})
            processed += 1
        except Exception as exc:
            skipped += 1
            log_event("sensor_skip", {"sensor_id": sensor.sensor_id, "error": str(exc)})

    duration_ms = int((time.time() - start) * 1000)
    log_event("job_success", {"processed": processed, "skipped": skipped, "duration_ms": duration_ms})
