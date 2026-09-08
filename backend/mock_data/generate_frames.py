import rasterio
from rasterio.transform import from_bounds
import numpy as np
import os

OUTPUT_DIR = "/mock_data/satellite_frames"
os.makedirs(OUTPUT_DIR, exist_ok=True)

width, height = 100, 100
bounds = (79.40, 30.35, 79.65, 30.50)
transform = from_bounds(*bounds, width, height)

for i in range(3):
    data = np.random.randint(0, 256, (height, width), dtype=np.uint8)
    data[40:60, 40:60] = 30
    data[45:55, 45:55] = 20

    output_path = os.path.join(OUTPUT_DIR, f"frame_{i+1:03d}.tif")
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=data.dtype,
        crs="EPSG:4326",
        transform=transform,
    ) as dst:
        dst.write(data, 1)
    print(f"Created {output_path}")
