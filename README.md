# MeghDrishti
### Hyper-Local Flash Flood & Landslide Early Warning System
**SIH 2026 · Problem Statement 26192 · Ministry of Home Affairs / NDRF, DM Division**

A working prototype that fuses **rainfall, soil moisture, slope stability, and
historical disaster data** with simulated real-time IoT inputs to generate
**village/ward-level risk forecasts** and actionable early warnings with
estimated evacuation lead time.

---

## 1. What this prototype actually does

| Problem statement requirement | How it's implemented here |
|---|---|
| Integrate rainfall + soil moisture + slope stability + historical data | `app/models/ml_model.py` fuses all 4 sources into one feature vector per village |
| Slope stability modelling | `app/models/slope_stability.py` — real infinite-slope Factor-of-Safety geotechnical formula, driven live by simulated soil-moisture saturation |
| Real-time IoT inputs | `app/data/sensor_simulator.py` — per-village rainfall/soil-moisture/stream-level feed with realistic drift, sensor dropout, and battery telemetry, ticking every 4s |
| Historical landslide inventory | `app/data/historical_events.py` — synthetic 10-year event log per village (type, severity, date), structured the way GSI/SDMA records are |
| Hyper-local (village/ward) forecasts | Every prediction, alert, and map marker is per-village, not district-wide |
| Actionable lead time for evacuation | `app/alerts/alert_engine.py` estimates minutes-to-impact from rainfall trend + risk severity, and pairs every alert with a concrete recommended action (Watch → Warning → Critical/evacuate) |

**Data reality check:** all inputs are synthetically generated but domain-informed
(realistic ranges for rainfall, soil saturation, terrain, and geotechnical
parameters). This is standard and expected for a hackathon prototype — the
architecture is what's being demonstrated, not a claim of live government
data integration. Section 6 below lists exactly what would need to be swapped
in for a real deployment.

---

## 2. Architecture

```
                     ┌─────────────────────────────┐
                     │   Data Sources (simulated)   │
                     │  rainfall · soil moisture ·   │
                     │  stream level · IoT battery   │
                     └───────────────┬───────────────┘
                                     │  every 4s tick
                                     ▼
   ┌───────────────────┐   ┌──────────────────────┐   ┌─────────────────────┐
   │ Static village DB  │──▶│  Feature Fusion Layer │──▶│  ML Risk Classifier │
   │ elevation, slope,  │   │ + Slope Stability(FS) │   │ GradientBoosting,   │
   │ soil type, history │   │  (geotechnical model)  │   │ 4-class risk output │
   └───────────────────┘   └──────────────────────┘   └──────────┬──────────┘
                                                                    │
                                                                    ▼
                                                        ┌───────────────────────┐
                                                        │     Alert Engine       │
                                                        │ level transitions,     │
                                                        │ lead-time estimate,    │
                                                        │ recommended action     │
                                                        └───────────┬───────────┘
                                                                    │
                                                                    ▼
                                                 ┌────────────────────────────────┐
                                                 │  FastAPI REST API (/api/*)      │
                                                 └───────────────┬────────────────┘
                                                                 ▼
                                                 ┌────────────────────────────────┐
                                                 │  Command-center Web Dashboard   │
                                                 │  live map · alert ticker ·      │
                                                 │  per-village risk fusion panel  │
                                                 └────────────────────────────────┘
```

**Tech stack:** Python, FastAPI, scikit-learn (GradientBoostingClassifier),
vanilla JS + Leaflet.js (map) + Chart.js (trends) for the frontend — no
build step required.

---

## 3. Setup & run

Requires Python 3.10+.

```bash
cd flashflood-system
pip install -r requirements.txt

# Train the risk model (only needed once, ~10s)
python train_model.py

# Run the server
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser. The dashboard loads directly.

### Environment variables

Create a `.env` file in the project root if you want to enable AI vision
verification for citizen photo reports:

```
GROQ_API_KEY=your_groq_api_key_here
```

If `GROQ_API_KEY` is not set, the system falls back to a strict local
image heuristic. The Groq vision model used is `llama-3.2-90b-vision-preview`.

### Troubleshooting Groq vision

If photo verification returns `is_valid: false` with reason
`"Heuristic demo signal — configure GROQ_API_KEY for AI Vision."`,
your Groq API key is either missing or invalid. Common causes:

- The key in `.env` is expired or was revoked.
- The Groq account has no access to vision models.
- Network egress to `api.groq.com` is blocked.

The app will continue working with the local heuristic fallback; live
sensor predictions, maps, alerts, and offline mode do not depend on Groq.

---

## 4. Demoing it (for judges)

The dashboard starts with all 24 villages in a calm/baseline state. To show
the system actually predicting an unfolding flash flood:

1. Click any village on the map or in the left list to open its detail panel.
2. Click **"⚡ Simulate storm event on this ward"**.
3. Watch, over the next ~30–60 seconds (the sim runs faster than real time):
   - Rainfall & soil-moisture readouts climb
   - The Factor of Safety (slope stability) drops
   - The risk badge transitions **Watch → Warning → Critical**
   - A new entry appears in the bottom alert ticker with an estimated lead
     time and recommended action (evacuate / activate volunteers / etc.)
   - The map marker grows and turns red

This demonstrates the full multi-source fusion → prediction → hyper-local
alert → actionable lead time pipeline end-to-end, live.

Good villages to pick for a dramatic demo: **Kedarnath Marg**, **Chopta
Bugyal**, or **Urgam Valley** — they have the steepest slopes and highest
historical incident counts, so they escalate fastest.

---

## 5. Project structure

```
flashflood-system/
├── app/
│   ├── main.py                    # FastAPI app + background simulation loop
│   ├── api/routes.py              # REST endpoints
│   ├── models/
│   │   ├── slope_stability.py     # Geotechnical Factor-of-Safety model
│   │   ├── ml_model.py            # Runtime prediction + explainability
│   │   └── risk_model.joblib      # Trained model (generated by train_model.py)
│   ├── data/
│   │   ├── villages.py            # 24-village synthetic inventory
│   │   ├── sensor_simulator.py    # Live multi-source data feed
│   │   └── historical_events.py   # Synthetic 10-yr disaster inventory
│   ├── alerts/alert_engine.py     # Transition detection, lead-time, actions
│   ├── templates/index.html
│   └── static/{css,js}/           # Command-center dashboard UI
├── train_model.py                 # Trains the classifier on synthetic data
└── requirements.txt
```

---

## 6. What a real deployment would need (be upfront about this with judges)

This prototype proves the architecture and the prediction/alerting logic.
To go from prototype to a real NDRF-deployed system:

- **Rainfall**: replace the simulator with IMD's real-time gridded rainfall
  API / AWS network feeds.
- **Soil moisture**: integrate actual in-ground capacitive/TDR sensor
  networks (LoRaWAN or NB-IoT telemetry) — hardware deployment + calibration.
- **Slope stability**: replace the simplified single-plane FS model with a
  calibrated geotechnical model per slope, ideally validated against GSI's
  Landslide Susceptibility Zonation maps and site-specific soil surveys.
- **Historical inventory**: ingest the GSI National Landslide Susceptibility
  database and State Disaster Management Authority incident logs.
- **Model training**: retrain on real historical rainfall-triggered
  event data (this prototype's model is trained on a domain-informed
  synthetic dataset, not real incident records).
- **Alert delivery**: integrate SMS gateway (e.g. via NDMA's Common Alerting
  Protocol / Cell Broadcast) and IVR for last-mile delivery to
  low-connectivity villages, alongside the dashboard.
- **Offline resilience**: edge caching / store-and-forward for sensor nodes
  in low-connectivity hill terrain.

Being explicit about this boundary is a strength in the SIH evaluation —
it shows the team understands the difference between a demonstrated
architecture and a production system.

---

## 7. Possible extensions if you have more build time

- Swap the GradientBoostingClassifier for an LSTM/temporal model that
  ingests the full rainfall time series rather than a single reading (this
  is a natural "if we had more time" answer to a judge's question).
- Add SHAP-based explainability instead of the current feature-importance
  approximation.
- Add a village-officer login + SMS/WhatsApp broadcast simulation.
- Add a satellite/DEM-derived slope layer (Bhuvan API) instead of static
  per-village slope angles.
