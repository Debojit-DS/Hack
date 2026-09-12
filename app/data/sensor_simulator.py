"""
Simulates the real-time, multi-source IoT + weather feed that in a real
deployment would come from:
  - Automatic Weather Stations / IMD rainfall gauges (rainfall mm/hr)
  - In-ground soil moisture probes (capacitive/TDR sensors, % VWC)
  - River/stream level ultrasonic sensors (m)
  - Sensor battery/connectivity telemetry

Each village keeps a rolling state that evolves via a bounded random walk,
biased by a per-village "monsoon susceptibility" derived from its static
attributes (drainage density, historical incidents). An operator can also
inject a "storm scenario" targeting specific villages to demonstrate how
lead time builds up before a flash flood / landslide event, which is the
core value proposition of the system.
"""

import random
import time
from collections import deque
from app.data.villages import VILLAGES

HISTORY_LEN = 60  # keep last 60 ticks per village (~ a few hours of sim time)


class VillageState:
    def __init__(self, village):
        self.village = village
        susceptibility = (village["drainage_density"] * 0.6 +
                           min(village["historical_flash_floods_10yr"] / 10, 1.0) * 0.4)
        self.susceptibility = susceptibility

        self.rainfall_mm_hr = round(random.uniform(0, 4), 1)
        self.rainfall_24hr_cumulative_mm = round(random.uniform(5, 25), 1)
        self.soil_moisture_pct = round(random.uniform(25, 45), 1)
        self.stream_level_m = round(random.uniform(0.8, 1.6), 2)

        self.sensor_battery_pct = round(random.uniform(70, 100), 1)
        self.sensor_online = True

        self.storm_active = False
        self.storm_ticks_remaining = 0
        self.storm_intensity = 0.0

        self.history = deque(maxlen=HISTORY_LEN)
        self._record()

    def _record(self):
        self.history.append({
            "t": time.time(),
            "rainfall_mm_hr": self.rainfall_mm_hr,
            "rainfall_24hr_cumulative_mm": self.rainfall_24hr_cumulative_mm,
            "soil_moisture_pct": self.soil_moisture_pct,
            "stream_level_m": self.stream_level_m,
        })

    def trigger_storm(self, ticks=18, intensity=1.0):
        """Kick off an intensifying storm scenario for demo purposes."""
        self.storm_active = True
        self.storm_ticks_remaining = ticks
        self.storm_intensity = intensity

    def tick(self):
        # Sensor occasionally drops out (realistic IoT flakiness)
        if random.random() < 0.01:
            self.sensor_online = not self.sensor_online
        if self.sensor_online:
            self.sensor_battery_pct = max(5.0, self.sensor_battery_pct - random.uniform(0, 0.15))

        base_rain_drift = random.uniform(-0.6, 0.6)
        storm_boost = 0.0

        if self.storm_active and self.storm_ticks_remaining > 0:
            # ramps up then the caller lets it decay naturally by not re-triggering
            progress = 1.0 - (self.storm_ticks_remaining / 18.0)
            storm_boost = self.storm_intensity * (6 + 14 * progress)
            self.storm_ticks_remaining -= 1
            if self.storm_ticks_remaining <= 0:
                self.storm_active = False

        self.rainfall_mm_hr = max(0.0, round(self.rainfall_mm_hr + base_rain_drift + storm_boost * 0.3, 1))
        # cumulative decays slowly (24hr rolling) but climbs fast under rainfall
        decay = self.rainfall_24hr_cumulative_mm * 0.03
        self.rainfall_24hr_cumulative_mm = max(0.0, round(
            self.rainfall_24hr_cumulative_mm - decay + self.rainfall_mm_hr * 0.9, 1))

        moisture_drift = (self.rainfall_mm_hr * 0.35) - 0.5 + random.uniform(-0.3, 0.3)
        self.soil_moisture_pct = max(5.0, min(100.0, round(self.soil_moisture_pct + moisture_drift, 1)))

        stream_drift = (self.rainfall_24hr_cumulative_mm / 200.0) - 0.02 + random.uniform(-0.02, 0.02)
        self.stream_level_m = max(0.1, round(self.stream_level_m + stream_drift, 2))

        self._record()

    def snapshot(self):
        return {
            "rainfall_mm_hr": self.rainfall_mm_hr,
            "rainfall_24hr_cumulative_mm": self.rainfall_24hr_cumulative_mm,
            "soil_moisture_pct": self.soil_moisture_pct,
            "stream_level_m": self.stream_level_m,
            "sensor_online": self.sensor_online,
            "sensor_battery_pct": round(self.sensor_battery_pct, 1),
            "storm_active": self.storm_active,
        }

    def history_list(self):
        return list(self.history)


class SensorNetwork:
    def __init__(self):
        self.states = {v["id"]: VillageState(v) for v in VILLAGES}
        self.tick_count = 0

    def tick_all(self):
        for state in self.states.values():
            state.tick()
        self.tick_count += 1

    def trigger_storm(self, village_ids, intensity=1.0, ticks=18):
        for vid in village_ids:
            if vid in self.states:
                self.states[vid].trigger_storm(ticks=ticks, intensity=intensity)

    def get(self, village_id):
        return self.states.get(village_id)


sensor_network = SensorNetwork()
