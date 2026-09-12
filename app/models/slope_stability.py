"""
Simplified infinite-slope stability model.

Factor of Safety (FS) is a classic geotechnical slope-stability indicator:

    FS = [c' + (gamma_sat - m * gamma_w) * z * cos^2(beta) * tan(phi')]
         / [gamma_sat * z * sin(beta) * cos(beta)]

Where:
    c'      = effective soil cohesion (kPa)
    phi'    = effective friction angle (deg)
    gamma_sat / gamma_w = unit weight of saturated soil / water (kN/m^3)
    beta    = slope angle (deg)
    z       = failure plane depth (m) — assumed constant per soil type
    m       = fraction of slope height that is saturated, driven by
              real-time soil moisture (this is the link between live
              sensor data and the physical stability calculation)

FS < 1.0  -> theoretically unstable
FS 1.0-1.5 -> marginally stable, sensitive to saturation
FS > 1.5  -> stable

This is a teaching-grade simplification (single infinite-slope plane,
fixed depth) — good enough to act as a genuine physics-informed FEATURE
for the ML model, not a substitute for a full geotechnical survey.
"""

SOIL_PARAMS = {
    # cohesion (kPa), friction angle (deg), sat. unit weight (kN/m3), failure depth (m)
    "sandy_loam":    {"c": 4.0,  "phi": 32, "gamma_sat": 18.5, "z": 1.5},
    "clay_loam":     {"c": 12.0, "phi": 24, "gamma_sat": 19.5, "z": 2.0},
    "silty_clay":    {"c": 9.0,  "phi": 21, "gamma_sat": 19.0, "z": 2.2},
    "gravelly_loam": {"c": 2.0,  "phi": 36, "gamma_sat": 20.0, "z": 1.2},
}

GAMMA_W = 9.81  # kN/m3


def factor_of_safety(slope_angle_deg: float, soil_type: str, soil_moisture_pct: float) -> float:
    import math

    p = SOIL_PARAMS.get(soil_type, SOIL_PARAMS["clay_loam"])
    beta = math.radians(slope_angle_deg)
    phi = math.radians(p["phi"])

    # soil_moisture_pct (0-100) -> saturation fraction m (0-1), clipped
    m = max(0.0, min(1.0, soil_moisture_pct / 100.0))

    numerator = p["c"] + (p["gamma_sat"] - m * GAMMA_W) * p["z"] * (math.cos(beta) ** 2) * math.tan(phi)
    denominator = p["gamma_sat"] * p["z"] * math.sin(beta) * math.cos(beta)

    if denominator <= 0:
        return 5.0  # flat ground, treat as very stable

    fs = numerator / denominator
    return round(max(0.1, min(5.0, fs)), 3)
