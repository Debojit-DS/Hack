import os
import glob
import logging

MOCK_DATA_DIR = "/mock_data/satellite_frames"
FRAME_PATTERN = os.path.join(MOCK_DATA_DIR, "*.tif")

logger = logging.getLogger("meghdrishti_scheduler")


def fetch_latest_thermal_tile():
    frames = sorted(glob.glob(FRAME_PATTERN))
    if not frames:
        raise FileNotFoundError(f"No mock satellite frames found in {MOCK_DATA_DIR}")
    latest = frames[-1]
    logger.info("Selected mock satellite frame: %s", latest)
    return latest
