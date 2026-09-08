import os
import time
import json
import logging
from celery_app import celery_app
from db.session import SessionLocal
from db.models import SimulationResult

logger = logging.getLogger("meghdrishti_worker")


def json_event(event, task_id, extra):
    payload = {"event": event, "task_name": "simulate.hydraulic_flood", "task_id": task_id}
    payload.update(extra)
    return payload


def mark_running(task_id: str):
    db = SessionLocal()
    db.execute(
        "UPDATE simulation_results SET status = 'RUNNING' WHERE task_id = :tid",
        {"tid": task_id},
    )
    db.commit()
    db.close()


def mark_success(task_id: str, result_geojson: dict):
    db = SessionLocal()
    import json
    db.execute(
        "UPDATE simulation_results SET status = 'SUCCESS', result_geojson = :geojson, completed_at = now() WHERE task_id = :tid",
        {"geojson": json.dumps(result_geojson), "tid": task_id},
    )
    db.commit()
    db.close()


def mark_failure(task_id: str, error: str):
    db = SessionLocal()
    db.execute(
        "UPDATE simulation_results SET status = 'FAILURE', completed_at = now() WHERE task_id = :tid",
        {"tid": task_id},
    )
    db.commit()
    db.close()


@celery_app.task(bind=True, acks_late=True, max_retries=2, default_retry_delay=20, name="simulate.hydraulic_flood")
def hydraulic_flood(self, task_id: str, rainfall_mm_hr: float):
    start = time.time()
    logger.info(json_event("task_start", self.request.id, {"task_id": task_id, "rainfall_mm_hr": rainfall_mm_hr}))

    try:
        mark_running(task_id)
        dem_path = os.environ.get("DEM_TILE_STORAGE_PATH", "/data/dem_tiles/chamoli.tif")
        result_geojson = run_hydraulic_pooling(dem_path, rainfall_mm_hr)
        mark_success(task_id, result_geojson)

        duration_ms = int((time.time() - start) * 1000)
        logger.info(json_event("task_success", self.request.id, {"task_id": task_id, "duration_ms": duration_ms}))
    except Exception as exc:
        mark_failure(task_id, str(exc))
        logger.error(json_event("task_failure", self.request.id, {"error": str(exc), "retry_count": self.request.retries}))
        raise self.retry(exc=exc)


def run_hydraulic_pooling(dem_path: str, rainfall_mm_hr: float) -> dict:
    from pysheds.grid import Grid
    import numpy as np
    from rasterio.features import shapes as raster_shapes
    from shapely.geometry import shape
    from shapely.ops import unary_union

    grid = Grid.from_raster(dem_path, data_name="dem")
    dem = grid.dem

    pit_filled_dem = grid.fill_pits(dem)
    flooded_dem = pit_filled_dem + rainfall_mm_hr * 0.1
    flood_mask = flooded_dem > pit_filled_dem + 0.5

    flood_mask = grid.clip_to_grid(flood_mask)
    geometries = list(raster_shapes(flood_mask.astype(np.uint8), mask=flood_mask, transform=grid.affine))

    polygons = [shape(geom) for geom, value in geometries if value == 1]
    if not polygons:
        return {"type": "FeatureCollection", "features": []}

    merged = unary_union(polygons)
    simplified = merged.simplify(0.0001, preserve_topology=True)
    from shapely.geometry import mapping
    return mapping(simplified)
