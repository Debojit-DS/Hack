"""
Synthetic village/ward inventory for a hilly disaster-prone district cluster
(modelled loosely on Uttarakhand-type terrain: steep slopes, river valleys,
monsoon-driven flash floods & landslides). This is DEMO/SYNTHETIC data — in
a real deployment this table would be sourced from Bhuvan/ISRO DEM data,
Census ward boundaries, and the State Disaster Management Authority's
historical landslide inventory (BIS/GSI records).

Static per-village attributes act as ML features that don't change tick to
tick (elevation, slope, historical incident counts, drainage proximity),
while dynamic sensor readings (rainfall, soil moisture) are produced by
sensor_simulator.py.
"""

import random

random.seed(42)

DISTRICTS = ["Rudra Valley", "Chamundi Hills", "Tehri Ridge", "Kedar Basin"]

SOIL_TYPES = ["sandy_loam", "clay_loam", "silty_clay", "gravelly_loam"]

# name, district, lat, lon, elevation(m), slope(deg), soil_type,
# population, distance_to_stream(m), drainage_density(0-1),
# historical_landslides(count/10yr), historical_flash_floods(count/10yr)
_RAW_VILLAGES = [
    ("Kotdwar Khas", "Rudra Valley", 30.152, 78.767, 620, 22, "sandy_loam", 1840, 180, 0.62, 2, 1),
    ("Devalgarh", "Rudra Valley", 30.201, 78.812, 980, 34, "silty_clay", 960, 90, 0.71, 5, 3),
    ("Rudrapur Malla", "Rudra Valley", 30.244, 78.850, 1210, 41, "clay_loam", 640, 60, 0.78, 7, 4),
    ("Sonargaon", "Rudra Valley", 30.267, 78.901, 1450, 37, "silty_clay", 410, 45, 0.83, 9, 5),
    ("Bishnupur Talla", "Rudra Valley", 30.289, 78.933, 1580, 29, "gravelly_loam", 520, 120, 0.55, 3, 2),
    ("Chamundi Dhar", "Chamundi Hills", 30.410, 79.021, 1720, 44, "silty_clay", 380, 55, 0.88, 11, 6),
    ("Gopeshwar Gaon", "Chamundi Hills", 30.432, 79.055, 1890, 39, "clay_loam", 290, 40, 0.81, 8, 5),
    ("Nandprayag Tok", "Chamundi Hills", 30.455, 79.088, 1050, 26, "sandy_loam", 1120, 150, 0.58, 4, 3),
    ("Urgam Valley", "Chamundi Hills", 30.478, 79.112, 2100, 47, "silty_clay", 210, 30, 0.91, 14, 7),
    ("Pipalkoti Malla", "Chamundi Hills", 30.501, 79.140, 1340, 31, "gravelly_loam", 780, 100, 0.63, 5, 3),
    ("Tehri Uttari", "Tehri Ridge", 30.377, 78.480, 890, 24, "sandy_loam", 2100, 200, 0.49, 2, 1),
    ("Ghansali Khas", "Tehri Ridge", 30.401, 78.512, 1150, 33, "clay_loam", 870, 85, 0.69, 6, 4),
    ("Bhilangana Tok", "Tehri Ridge", 30.423, 78.545, 1670, 42, "silty_clay", 340, 50, 0.85, 10, 6),
    ("Ghuttu Gaon", "Tehri Ridge", 30.446, 78.578, 1980, 45, "silty_clay", 260, 35, 0.89, 13, 7),
    ("Pratapnagar Talla", "Tehri Ridge", 30.468, 78.601, 1420, 28, "gravelly_loam", 690, 110, 0.61, 4, 2),
    ("Chirbatia", "Tehri Ridge", 30.490, 78.630, 1060, 21, "sandy_loam", 1560, 170, 0.52, 3, 1),
    ("Kedarnath Marg", "Kedar Basin", 30.588, 79.033, 2340, 49, "silty_clay", 180, 25, 0.93, 16, 9),
    ("Sonprayag Khas", "Kedar Basin", 30.560, 79.005, 1870, 46, "clay_loam", 420, 40, 0.87, 12, 7),
    ("Guptkashi Tok", "Kedar Basin", 30.533, 78.977, 1290, 32, "silty_clay", 950, 70, 0.72, 7, 4),
    ("Phata Malla", "Kedar Basin", 30.505, 78.949, 1580, 36, "gravelly_loam", 560, 60, 0.76, 8, 5),
    ("Rampur Kedar", "Kedar Basin", 30.478, 78.921, 990, 27, "sandy_loam", 1340, 140, 0.57, 3, 2),
    ("Agastyamuni", "Kedar Basin", 30.451, 78.893, 1130, 30, "clay_loam", 1020, 95, 0.64, 5, 3),
    ("Ukhimath Dhar", "Kedar Basin", 30.423, 78.865, 1760, 40, "silty_clay", 380, 45, 0.84, 9, 5),
    ("Chopta Bugyal", "Kedar Basin", 30.396, 78.837, 2050, 48, "silty_clay", 150, 20, 0.90, 15, 8),
]


def build_villages():
    villages = []
    for idx, row in enumerate(_RAW_VILLAGES):
        (name, district, lat, lon, elev, slope, soil, pop, dist_stream,
         drainage, hist_land, hist_flood) = row
        villages.append({
            "id": f"WD-{idx+1:03d}",
            "name": name,
            "district": district,
            "state": "Devbhoomi Hills (demo)",
            "lat": lat,
            "lon": lon,
            "elevation_m": elev,
            "slope_angle_deg": slope,
            "soil_type": soil,
            "population": pop,
            "distance_to_stream_m": dist_stream,
            "drainage_density": drainage,
            "historical_landslides_10yr": hist_land,
            "historical_flash_floods_10yr": hist_flood,
        })
    return villages


VILLAGES = build_villages()
VILLAGE_BY_ID = {v["id"]: v for v in VILLAGES}
