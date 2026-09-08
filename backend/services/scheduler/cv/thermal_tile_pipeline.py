import cv2
import numpy as np
import rasterio
from rasterio.transform import xy
from scipy import ndimage


def extract_cloud_center(tile_path: str):
    with rasterio.open(tile_path) as src:
        band = src.read(1)
        transform = src.transform
        rows, cols = band.shape

    _, binary = cv2.threshold(band, 50, 255, cv2.THRESH_BINARY_INV)
    binary = binary.astype(np.uint8)

    labeled, num_features = ndimage.label(binary)
    if num_features == 0:
        return None

    sizes = ndimage.sum(binary, labeled, range(1, num_features + 1))
    largest_label = np.argmax(sizes) + 1
    center_y, center_x = ndimage.center_of_mass(binary, labeled, largest_label)

    lon, lat = xy(transform, center_y, center_x)
    return {"lat": lat, "lon": lon}
