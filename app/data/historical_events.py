"""
Synthetic historical landslide / flash-flood inventory, generated
consistently with each village's historical_* counts in villages.py.
Represents what would, in production, be sourced from GSI's National
Landslide Susceptibility Mapping (NLSM) records and SDMA incident logs.
"""

import random
from datetime import datetime, timedelta
from app.data.villages import VILLAGES

random.seed(7)

_EVENT_TYPES_LAND = ["Debris flow", "Slope failure", "Rockfall", "Mudslide"]
_EVENT_TYPES_FLOOD = ["Flash flood", "Stream overflow", "Cloudburst flooding"]
_SEVERITIES = ["Minor", "Moderate", "Severe", "Catastrophic"]
_SEVERITY_WEIGHTS = [0.45, 0.30, 0.18, 0.07]

_MONSOON_MONTHS = [6, 7, 8, 9]


def _random_monsoon_date(years_back):
    year = datetime.now().year - random.randint(1, years_back)
    month = random.choice(_MONSOON_MONTHS)
    day = random.randint(1, 28)
    return datetime(year, month, day)


def build_events():
    events = []
    eid = 1
    for v in VILLAGES:
        for _ in range(v["historical_landslides_10yr"]):
            d = _random_monsoon_date(10)
            events.append({
                "id": f"EV-{eid:04d}",
                "village_id": v["id"],
                "village_name": v["name"],
                "type": random.choice(_EVENT_TYPES_LAND),
                "severity": random.choices(_SEVERITIES, weights=_SEVERITY_WEIGHTS)[0],
                "date": d.strftime("%Y-%m-%d"),
            })
            eid += 1
        for _ in range(v["historical_flash_floods_10yr"]):
            d = _random_monsoon_date(10)
            events.append({
                "id": f"EV-{eid:04d}",
                "village_id": v["id"],
                "village_name": v["name"],
                "type": random.choice(_EVENT_TYPES_FLOOD),
                "severity": random.choices(_SEVERITIES, weights=_SEVERITY_WEIGHTS)[0],
                "date": d.strftime("%Y-%m-%d"),
            })
            eid += 1
    events.sort(key=lambda e: e["date"], reverse=True)
    return events


HISTORICAL_EVENTS = build_events()
