import os
import time
import json
import logging
from datetime import timedelta
from geopy.point import Point
from celery_app import celery_app
from db.session import SessionLocal
from db.models import StormObservation
from geo.advection import compute_bearing, predict_next_point

LOOKAHEAD_MINUTES = 20

logger = logging.getLogger("meghdrishti_worker")


def json_event(event, task_id, extra):
    payload = {"event": event, "task_name": "advection.predict_storm_path", "task_id": task_id}
    payload.update(extra)
    return payload


@celery_app.task(bind=True, acks_late=True, max_retries=3, default_retry_delay=15, name="advection.predict_storm_path")
def predict_storm_path(self, obs_id: int):
    start = time.time()
    task_id = self.request.id
    logger.info(json_event("task_start", task_id, {"obs_id": obs_id}))

    db = SessionLocal()
    try:
        newer = db.query(StormObservation).filter(StormObservation.obs_id == obs_id).first()
        if not newer:
            logger.info(json_event("task_skip", task_id, {"reason": "obs_not_found", "obs_id": obs_id}))
            return

        older = (
            db.query(StormObservation)
            .filter(StormObservation.obs_id != obs_id)
            .order_by(StormObservation.observed_at.desc())
            .first()
        )
        if older is None:
            logger.info(json_event("task_skip", task_id, {"reason": "insufficient_history", "obs_id": obs_id}))
            return

        newer_point = Point(newer.center_point.y, newer.center_point.x)
        older_point = Point(older.center_point.y, older.center_point.x)

        destination = predict_next_point(
            older_point,
            older.observed_at,
            newer_point,
            newer.observed_at,
            LOOKAHEAD_MINUTES,
        )

        newer.predicted_next_point = f"SRID=4326;POINT({destination.longitude} {destination.latitude})"
        newer.predicted_for = newer.observed_at + timedelta(minutes=LOOKAHEAD_MINUTES)
        db.commit()

        duration_ms = int((time.time() - start) * 1000)
        logger.info(json_event("task_success", task_id, {"obs_id": obs_id, "duration_ms": duration_ms}))
    except Exception as exc:
        db.rollback()
        logger.error(json_event("task_failure", task_id, {"error": str(exc), "retry_count": self.request.retries}))
        raise self.retry(exc=exc)
    finally:
        db.close()
