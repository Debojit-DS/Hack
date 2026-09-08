import math
from geopy.distance import geodesic
from geopy.point import Point


def compute_bearing(p1: Point, p2: Point) -> float:
    lat1, lon1 = math.radians(p1.latitude), math.radians(p1.longitude)
    lat2, lon2 = math.radians(p2.latitude), math.radians(p2.longitude)
    d_lon = lon2 - lon1
    x = math.sin(d_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(d_lon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def predict_next_point(older: Point, older_time, newer: Point, newer_time, lookahead_minutes: float) -> Point:
    bearing = compute_bearing(older, newer)
    elapsed_minutes = (newer_time - older_time).total_seconds() / 60
    distance_km = geodesic(older, newer).km
    speed_km_per_min = distance_km / elapsed_minutes if elapsed_minutes > 0 else 0
    projected_distance_km = speed_km_per_min * lookahead_minutes
    destination = geodesic(kilometers=projected_distance_km).destination(newer, bearing)
    return destination
