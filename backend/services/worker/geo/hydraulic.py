import os
import numpy as np
from rasterio.features import shapes as raster_shapes
from shapely.geometry import shape, mapping
from shapely.ops import unary_union


def run_hydraulic_pooling(dem_path: str, rainfall_mm_hr: float) -> dict:
    from pysheds.grid import Grid

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
    return mapping(simplified)
