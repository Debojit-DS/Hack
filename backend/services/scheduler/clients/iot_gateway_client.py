import os
import requests
from urllib.parse import urljoin

IOT_GATEWAY_BASE_URL = os.environ.get("IOT_GATEWAY_BASE_URL", "http://localhost:9100")


def fetch_latest_reading(sensor_id: int):
    url = urljoin(IOT_GATEWAY_BASE_URL, f"/api/sensors/{sensor_id}/latest")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = response.json()
    return {
        "sensor_id": data["sensor_id"],
        "value": float(data["value"]),
        "timestamp": data["timestamp"],
    }
