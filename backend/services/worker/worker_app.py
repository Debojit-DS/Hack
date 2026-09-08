import os
import json
import time
import logging
from pythonjsonlogger import jsonlogger
from celery import Celery

os.environ.setdefault("CELERY_BROKER_URL", "redis://redis:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

celery_app = Celery(
    "meghdrishti_worker",
    broker=os.environ["CELERY_BROKER_URL"],
    backend=os.environ["CELERY_RESULT_BACKEND"],
    include=[
        "tasks.ml_tasks",
        "tasks.simulation_tasks",
        "tasks.advection_tasks",
        "tasks.retrain_tasks",
    ],
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=10,
    task_time_limit=600,
    task_soft_time_limit=540,
    result_expires=3600,
    timezone="Asia/Kolkata",
    enable_utc=True,
)

logger = logging.getLogger("meghdrishti_worker")
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)
