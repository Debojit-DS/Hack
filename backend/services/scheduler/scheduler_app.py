import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from jobs.satellite_poll import poll_satellite_tiles
from jobs.iot_poll import poll_iot_sensors

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meghdrishti_scheduler")

scheduler = BlockingScheduler(timezone="Asia/Kolkata")
scheduler.add_job(poll_satellite_tiles, "interval", minutes=15, id="satellite_poll", max_instances=1, coalesce=True, misfire_grace_time=120)
scheduler.add_job(poll_iot_sensors, "interval", minutes=1, id="iot_poll", max_instances=1, coalesce=True, misfire_grace_time=30)

if __name__ == "__main__":
    logger.info("Starting Meghdrishti scheduler")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
