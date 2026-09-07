from celery import Celery
from app.config import settings

celery_app = Celery(
    "api_service",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

def enqueue_retrain_ingest(report_id: int) -> None:
    try:
        celery_app.send_task(
            "retrain.ingest_verified_sample",
            kwargs={"report_id": report_id},
        )
    except Exception as e:
        print(f"Warning: Failed to enqueue Celery task retrain.ingest_verified_sample: {e}")