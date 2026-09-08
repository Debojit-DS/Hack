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

def enqueue_simulation(task_id: str, rainfall_mm_hr: float) -> None:
    try:
        celery_app.send_task(
            "simulate.hydraulic_flood",
            kwargs={"task_id": task_id, "rainfall_mm_hr": rainfall_mm_hr},
        )
    except Exception as e:
        print(f"Warning: Failed to enqueue Celery task simulate.hydraulic_flood: {e}")