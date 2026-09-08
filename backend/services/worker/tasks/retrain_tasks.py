import os
import time
import json
import logging
from celery_app import celery_app
from db.session import SessionLocal
from db.models import RetrainingSample

logger = logging.getLogger("meghdrishti_worker")


def json_event(event, task_id, extra):
    payload = {"event": event, "task_name": "retrain.ingest_verified_sample", "task_id": task_id}
    payload.update(extra)
    return payload


@celery_app.task(bind=True, acks_late=True, max_retries=3, default_retry_delay=15, name="retrain.ingest_verified_sample")
def ingest_verified_sample(self, report_id: int):
    start = time.time()
    task_id = self.request.id
    logger.info(json_event("task_start", task_id, {"report_id": report_id}))

    db = SessionLocal()
    try:
        db.execute(
            "INSERT INTO retraining_samples (report_id) VALUES (:rid)",
            {"rid": report_id},
        )
        db.commit()

        duration_ms = int((time.time() - start) * 1000)
        logger.info(json_event("task_success", task_id, {"report_id": report_id, "duration_ms": duration_ms}))
    except Exception as exc:
        db.rollback()
        logger.error(json_event("task_failure", task_id, {"error": str(exc), "retry_count": self.request.retries}))
        raise self.retry(exc=exc)
    finally:
        db.close()
