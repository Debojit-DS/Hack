import os
import time
import json
import logging
from app.celery_client import celery_app
from db.session import SessionLocal
from db.models import SensorReading, Sensor, Ward, Alert
from ml.model_loader import get_model

logger = logging.getLogger("meghdrishti_worker")
ALERT_THRESHOLD = 0.7


def json_event(task_name, event, task_id, extra):
    payload = {"event": event, "task_name": task_name, "task_id": task_id}
    payload.update(extra)
    return payload


def resolve_ward_for_sensor(db, sensor_id: int) -> int:
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise ValueError(f"Sensor {sensor_id} not found")

    if sensor.ward_id is not None:
        return sensor.ward_id

    result = db.execute(
        "SELECT ward_id FROM wards WHERE ST_Contains(ward_boundary, :coord) LIMIT 1",
        {"coord": sensor.coord},
    ).first()
    if result:
        return result.ward_id
    raise ValueError(f"No ward found for sensor {sensor_id}")


def aggregate_ward_risk(db, ward_id: int) -> float:
    result = db.execute(
        "SELECT MAX(risk_score) FROM sensor_readings WHERE sensor_id IN (SELECT sensor_id FROM sensors WHERE ward_id = :wid)",
        {"wid": ward_id},
    ).first()
    if result and result[0] is not None:
        return float(result[0])
    return 0.0


def update_ward_risk(db, ward_id: int, score: float):
    db.execute(
        "UPDATE wards SET current_risk_score = :score, risk_updated_at = now() WHERE ward_id = :wid",
        {"score": score, "wid": ward_id},
    )


def insert_alert(db, ward_id: int, score: float, message: str):
    db.execute(
        "INSERT INTO alerts (ward_id, risk_score, message) VALUES (:wid, :score, :msg)",
        {"wid": ward_id, "score": score, "msg": message},
    )


@celery_app.task(bind=True, acks_late=True, max_retries=3, default_retry_delay=15, name="ml.contextualize_risk")
def contextualize_risk(self, sensor_id: int, risk_score: float):
    start = time.time()
    task_id = self.request.id
    logger.info(json_event("ml.contextualize_risk", "task_start", task_id, {"sensor_id": sensor_id, "risk_score": risk_score}))

    db = SessionLocal()
    try:
        ward_id = resolve_ward_for_sensor(db, sensor_id)
        aggregated_score = aggregate_ward_risk(db, ward_id)
        update_ward_risk(db, ward_id, aggregated_score)

        if aggregated_score > ALERT_THRESHOLD:
            insert_alert(db, ward_id, aggregated_score, message="Elevated flood risk detected")

        db.commit()
        duration_ms = int((time.time() - start) * 1000)
        logger.info(json_event("ml.contextualize_risk", "task_success", task_id, {"ward_id": ward_id, "score": aggregated_score, "duration_ms": duration_ms}))
    except Exception as exc:
        db.rollback()
        logger.error(json_event("ml.contextualize_risk", "task_failure", task_id, {"error": str(exc), "retry_count": self.request.retries}))
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, acks_late=True, max_retries=3, default_retry_delay=15, name="ml.run_inference")
def run_inference(self, sensor_id: int):
    start = time.time()
    task_id = self.request.id
    logger.info(json_event("ml.run_inference", "task_start", task_id, {"sensor_id": sensor_id}))

    db = SessionLocal()
    try:
        sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
        if not sensor:
            raise ValueError(f"Sensor {sensor_id} not found")

        reading = (
            db.query(SensorReading)
            .filter(SensorReading.sensor_id == sensor_id)
            .order_by(SensorReading.timestamp.desc())
            .first()
        )
        if not reading:
            raise ValueError(f"No readings found for sensor {sensor_id}")

        vector = build_feature_vector(db, sensor_id)
        model = get_model()
        risk_array = model.predict(vector)
        risk_score = float(risk_array[0])

        reading.risk_score = risk_score
        db.commit()

        duration_ms = int((time.time() - start) * 1000)
        logger.info(json_event("ml.run_inference", "task_success", task_id, {"sensor_id": sensor_id, "risk_score": risk_score, "duration_ms": duration_ms}))

        contextualize_risk.delay(sensor_id=sensor_id, risk_score=risk_score)
    except Exception as exc:
        db.rollback()
        logger.error(json_event("ml.run_inference", "task_failure", task_id, {"error": str(exc), "retry_count": self.request.retries}))
        raise self.retry(exc=exc)
    finally:
        db.close()


def build_feature_vector(db, sensor_id: int):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    readings = (
        db.query(SensorReading)
        .filter(SensorReading.sensor_id == sensor_id)
        .order_by(SensorReading.timestamp.desc())
        .limit(24)
        .all()
    )
    if not readings:
        raise ValueError(f"No readings for sensor {sensor_id}")

    values = [r.value for r in reversed(readings)]
    current = values[-1] if values else 0.0

    rain_1h = 0.0
    if len(values) >= 2:
        rain_1h = values[-1] - values[-2]

    rain_24h_cumulative = current

    slope_twi = 0.0
    return [[current, rain_1h, rain_24h_cumulative, slope_twi]]
