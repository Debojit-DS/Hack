"""
Converts per-village ML risk output into actionable, hyper-local alerts.

Design goals mirrored from the problem statement:
  - Alerts fire at village/ward granularity, not district-wide blanket
    warnings (this is the whole point of the "hyper-local" ask).
  - Every alert carries a recommended action and an estimated lead time,
    so the alert is actionable, not just informational.
  - We only raise a NEW alert on a risk-level transition (not every tick)
    to avoid alert fatigue, but we track a rolling "sustained" flag so a
    village stuck at Critical isn't silently dropped from the feed.
"""

import time
from collections import deque

RISK_ORDER = ["Low", "Watch", "Warning", "Critical"]

ACTIONS = {
    "Watch": "Advise ward-level pradhan; recommend residents near streams stay alert to updates.",
    "Warning": "Activate local disaster volunteers; pre-position essentials; advise vulnerable households to prepare to move.",
    "Critical": "Issue evacuation order for at-risk zones; deploy NDRF/SDRF quick reaction team; open nearest relief shelter.",
}

MAX_LOG = 200


class AlertEngine:
    def __init__(self):
        self.last_level = {}   # village_id -> risk_label
        self.log = deque(maxlen=MAX_LOG)
        self.rain_trend = {}   # village_id -> deque of recent rainfall for lead-time est.
        self.citizen_signal = {}  # village_id -> (score 0-1, expires_at)

    # --- citizen corroboration -------------------------------------------------
    # IMPORTANT: this is a modifier, not a trigger. An auto-verified citizen
    # photo can only tighten the lead-time estimate and annotate an alert
    # that the sensor-driven ML model was *already* about to raise -- it can
    # never flip is_alertable/transitioned_up on its own. That's what keeps
    # a single unverified/spoofed report from firing a false alarm.
    def register_citizen_signal(self, village_id, score, ttl_seconds=20 * 60):
        self.citizen_signal[village_id] = (score, time.time() + ttl_seconds)

    def _active_citizen_score(self, village_id):
        entry = self.citizen_signal.get(village_id)
        if not entry:
            return 0.0
        score, expires_at = entry
        if time.time() > expires_at:
            del self.citizen_signal[village_id]
            return 0.0
        return score

    def _estimate_lead_time_minutes(self, village_id, rainfall_mm_hr, risk_index):
        trend = self.rain_trend.setdefault(village_id, deque(maxlen=6))
        trend.append(rainfall_mm_hr)
        if len(trend) < 2:
            slope = 0.5
        else:
            slope = (trend[-1] - trend[0]) / max(1, len(trend) - 1)

        base = {1: 240, 2: 120, 3: 45}.get(risk_index, 360)
        if slope > 1.5:
            base *= 0.6
        elif slope < 0:
            base *= 1.3
        return max(15, int(base))

    def evaluate(self, village, risk_result, sensor_snapshot):
        vid = village["id"]
        new_level = risk_result["risk_label"]
        old_level = self.last_level.get(vid, "Low")
        self.last_level[vid] = new_level

        transitioned_up = RISK_ORDER.index(new_level) > RISK_ORDER.index(old_level)
        is_alertable = new_level in ("Watch", "Warning", "Critical")

        alert = None
        if is_alertable and (transitioned_up or new_level == "Critical"):
            lead_time = self._estimate_lead_time_minutes(
                vid, sensor_snapshot["rainfall_mm_hr"], risk_result["risk_index"])

            citizen_score = self._active_citizen_score(vid)
            if citizen_score > 0:
                # Corroborated reports tighten (never lengthen) the lead-time
                # estimate, and are surfaced in the alert -- but the alert
                # itself was already going to fire from sensor data alone.
                lead_time = max(15, int(lead_time * (1 - 0.25 * citizen_score)))

            message = (f"{new_level} level flash-flood/landslide risk detected in {village['name']} "
                       f"({village['district']}).")
            if citizen_score >= 0.5:
                message += " Corroborated by an auto-verified citizen photo report."

            alert = {
                "id": f"AL-{int(time.time()*1000)}-{vid}",
                "village_id": vid,
                "village_name": village["name"],
                "district": village["district"],
                "level": new_level,
                "timestamp": time.time(),
                "message": message,
                "recommended_action": ACTIONS.get(new_level, "Monitor situation."),
                "estimated_lead_time_min": lead_time,
                "rainfall_mm_hr": sensor_snapshot["rainfall_mm_hr"],
                "soil_moisture_pct": sensor_snapshot["soil_moisture_pct"],
                "factor_of_safety": risk_result["factor_of_safety"],
                "transition": f"{old_level} -> {new_level}",
                "citizen_corroboration_score": citizen_score,
            }
            self.log.appendleft(alert)

        return alert

    def active_alerts(self):
        """Most recent alert per village that is still at Watch/Warning/Critical."""
        seen = set()
        active = []
        for alert in self.log:
            if alert["village_id"] in seen:
                continue
            seen.add(alert["village_id"])
            if self.last_level.get(alert["village_id"]) in ("Watch", "Warning", "Critical"):
                active.append(alert)
        return active

    def recent_log(self, limit=50):
        return list(self.log)[:limit]


alert_engine = AlertEngine()
