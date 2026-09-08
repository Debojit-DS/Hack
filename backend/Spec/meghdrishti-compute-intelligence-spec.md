# Engineering Spec — Meghdrishti Compute, Simulation & Intelligence Platform
## (Services 2 & 3: Celery Worker + APScheduler Ingestion)

**Parent document:** `meghdrishti-backend-prd.md` (single source of truth — this spec is a detailed implementation drill-down of PRD Section 5.2, and must never contradict Sections 6 and 7 of that PRD. If anything here seems to conflict with the PRD, the PRD wins.)

**Scope of this document:** Everything owned by **Developer B**. This is the asynchronous compute backbone of the system — background task orchestration, spatial database physical layout for the tables this service touches, all scheduled external-data ingestion, the full 4-stage ML handoff pipeline, and the two Earth-physics compute modules (storm advection, hydraulic flood pooling).

**What you are building, in one sentence:** Two long-running Python processes — a Celery worker and an APScheduler cron process — that pull external data on a timer, run heavy geospatial/ML compute off the request path, and write results into Postgres/PostGIS/TimescaleDB tables that the API server (owned by someone else, in a separate codebase) reads and serves to the frontend.

---

## 1. Where This Fits in the Bigger System

You are building **Service 2 (`worker`)** and **Service 3 (`scheduler`)**. You do **not** build Service 1 (`api`) — that's a separate FastAPI codebase owned by a different developer ("Dev A"), and you will never import from it or it from you.

The two codebases integrate through exactly two shared surfaces, and nothing else:

1. **The Postgres database** — you read/write specific tables and columns (listed exhaustively in Section 4).
2. **Celery task names and payload shapes** — the API server enqueues tasks by string name (e.g. `celery_app.send_task("simulate.hydraulic_flood", kwargs={...})`). It never imports your code. You must implement tasks under **exactly** the names and payload shapes in Section 6 — treat this like a versioned API contract, because from the other developer's perspective, it is one.

This means: **your container must never be imported by, or import, the API server's code.** If you ever find yourself wanting to `from api import something`, stop — that's a sign the boundary is being violated.

### 1.1 The core architectural principle you are enforcing

Nothing computationally expensive is allowed to run inside an HTTP request/response cycle. A citizen or admin browser hitting an endpoint must always get a response in well under 200ms. Your entire job is to be the place where the *actual work* happens — asynchronously, on a timer or via a queued job, completely decoupled from any browser waiting on the other end.

Concretely, this means:
- ML inference never runs synchronously inside a FastAPI handler.
- The hydraulic flood simulation (which can take real wall-clock time) runs as a Celery task, not inline.
- External API polling (ISRO satellite tiles, IoT gateways) never happens because a user clicked something — it happens on a fixed schedule, always, in the background.

---

## 2. Tech Stack & Why Each Piece Is There

| Component | Library/Tool | Why |
|---|---|---|
| Distributed task queue | **Celery** | Runs heavy/slow jobs (ML inference, hydraulic sim, advection calc) off the request path, with retries and result tracking |
| Message broker + result backend | **Redis** | Celery needs a broker to receive jobs and (optionally) a backend to store results. You stand up this container. |
| Scheduled polling | **APScheduler** | Cron-like scheduling for two fixed-interval jobs: satellite tiles every 15 min, IoT sensors every 1 min |
| Spatial database | **PostGIS** (Postgres extension) | Storing/querying geometry (points, polygons) with spatial indexing |
| Time-series storage | **TimescaleDB** (Postgres extension) | `sensor_readings` will accumulate millions of rows; Timescale hypertables + native compression keep this fast and small |
| Geodesic math | **GeoPy** | Storm advection: "given a starting point, a bearing, and a distance, where do you end up on a curved Earth" |
| Raster I/O | **Rasterio** | Reading the pre-loaded Digital Elevation Model (DEM) raster tiles for the flood pooling algorithm |
| Vector geometry construction | **Shapely** | Converting the flood-fill raster/grid output into a clean GeoJSON `Polygon` |
| ML model | Delivered as a black-box Python class with `.predict()` | You integrate it, you do not build or train it |

You will need, at minimum, these Python packages in `services/worker/requirements.txt` and `services/scheduler/requirements.txt`:

```
celery[redis]
redis
apscheduler
psycopg2-binary
sqlalchemy
geopy
rasterio
shapely
numpy
opencv-python-headless   # for satellite tile CV pipeline (scheduler only)
requests                 # for polling ISRO/IoT HTTP endpoints
python-json-logger        # structured logging
```

---

## 3. Repository Layout (your slice only)

```
/repo
  /services
    /worker
      Dockerfile
      requirements.txt
      worker_app.py            # Celery app instance + config
      tasks/
        __init__.py
        ml_tasks.py             # ml.run_inference, ml.contextualize_risk
        simulation_tasks.py     # simulate.hydraulic_flood
        advection_tasks.py      # advection.predict_storm_path
        retrain_tasks.py        # retrain.ingest_verified_sample
      ml/
        model_loader.py         # loads the black-box model as a module-level singleton
      geo/
        hydraulic.py            # Rasterio + Shapely pooling algorithm
        advection.py            # GeoPy geodesic calc
      db/
        session.py              # SQLAlchemy engine/session, reads DATABASE_URL
        models.py                # SQLAlchemy models MIRRORING Dev A's schema (read/write only, never migrate from here)
    /scheduler
      Dockerfile
      requirements.txt
      scheduler_app.py          # APScheduler process entrypoint
      jobs/
        satellite_poll.py       # every 15 min
        iot_poll.py             # every 1 min
      cv/
        thermal_tile_pipeline.py  # OpenCV cloud-center extraction
      clients/
        isro_bhuvan_client.py
        iot_gateway_client.py
```

**Hard rule:** you never write or run an Alembic migration. Dev A owns `/db/migrations`. If a table or column you need doesn't exist yet, you flag it against Section 6 of the PRD and get it added there — you don't unilaterally invent columns.

---

## 4. Database Tables You Touch (read carefully — this is your contract with Dev A)

All of these tables are created by Dev A's Alembic migrations. You never `CREATE TABLE` yourself in application code — but you must understand the exact physical layout, because your Celery tasks read and write these columns directly via SQLAlchemy/raw SQL. This section restates the PRD's Section 6 schema **with an explicit read/write ownership annotation per table**, so there's zero ambiguity about who's allowed to touch what.

### 4.1 Category A — Static Topographical Geofences (read-only for you, at runtime)

These are pre-loaded once via a seed script before the demo and never change during normal operation. You **read** from these; you never write to them (except the one specific `current_risk_score` column noted below).

```sql
CREATE TABLE dem_tiles (
    tile_id       SERIAL PRIMARY KEY,
    rast_geometry RASTER NOT NULL
);
CREATE INDEX idx_dem_tiles_rast ON dem_tiles USING GIST (ST_ConvexHull(rast_geometry));
```
- **You read this** in `simulate.hydraulic_flood` via Rasterio, to get the elevation raster for the Chamoli area.
- The GIST index on `ST_ConvexHull(rast_geometry)` is what makes it fast to find which tile(s) cover a given bounding box — don't bypass it with a full table scan.

```sql
CREATE TABLE wards (
    ward_id        SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    ward_boundary  GEOMETRY(POLYGON, 4326) NOT NULL,
    current_risk_score DOUBLE PRECISION,     -- YOU WRITE THIS
    risk_updated_at    TIMESTAMPTZ           -- YOU WRITE THIS
);
CREATE INDEX idx_wards_boundary ON wards USING GIST (ward_boundary);
```
- You **read** `ward_boundary` in `ml.contextualize_risk` to run `ST_Contains`/`ST_Within` spatial joins against sensor coordinates.
- You are the **only** writer of `current_risk_score` and `risk_updated_at` — Dev A's API only ever reads these columns for the `/wards` and `/wards/{id}` endpoints. Never let the API write these; if you see API code doing so, that's a contract violation.

```sql
CREATE TABLE safe_havens (
    shelter_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    capacity    INTEGER,
    coordinate  GEOMETRY(POINT, 4326) NOT NULL
);
CREATE INDEX idx_safe_havens_coord ON safe_havens USING GIST (coordinate);
```
- You don't touch this table at all in v1. It's listed here because it's part of "Category A" and you should understand the full static geofence layer, even though nothing in your Celery tasks currently reads it.

**Why GIST indexes matter here, concretely:** without `idx_wards_boundary`, a spatial join like `ST_Contains(ward_boundary, sensor_point)` degrades to a sequential scan across every ward polygon for every single sensor reading. With hundreds of sensors reporting every minute, that's the difference between a sub-second contextualization step and one that visibly lags behind ingestion. **Never write a spatial predicate query without checking that the geometry column has a GIST index first.**

### 4.2 Category B — Dynamic Timeseries Sensors

```sql
CREATE TABLE sensors (
    sensor_id  SERIAL PRIMARY KEY,
    type       TEXT NOT NULL,          -- 'SoilMoisture' | 'RainGauge'
    coord      GEOMETRY(POINT, 4326) NOT NULL,
    ward_id    INTEGER REFERENCES wards(ward_id)
);
CREATE INDEX idx_sensors_coord ON sensors USING GIST (coord);
```
- **Read-only** for you. Sensor metadata (which sensor exists, where it is, what ward it belongs to) is CRUD'd by Dev A's API. You just look it up.

```sql
CREATE TABLE sensor_readings (
    reading_id SERIAL,
    sensor_id  INTEGER NOT NULL REFERENCES sensors(sensor_id),
    value      DOUBLE PRECISION NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_score DOUBLE PRECISION            -- YOU WRITE THIS
);
SELECT create_hypertable('sensor_readings', 'timestamp');
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, timestamp DESC);
```
- **You insert new rows** into this table from your `scheduler`'s 1-minute IoT poll job (`value`, `sensor_id`, `timestamp`).
- **You update `risk_score`** on those rows from your `ml.run_inference` Celery task, after the model produces a prediction.
- This is a **TimescaleDB hypertable** (created via `SELECT create_hypertable(...)`, which Dev A runs once as part of migrations). What this means practically for you:
  - Timescale automatically partitions the table into time-based "chunks" behind the scenes — you don't manage this, but you should know it's why time-range queries stay fast even at millions of rows.
  - You should periodically (or via a Timescale compression policy set up in migrations) expect older chunks to be compressed. This doesn't change how you write inserts (still plain `INSERT`), but be aware that `UPDATE`s (like writing `risk_score` after the fact) are cheapest when done **soon after insert**, before a chunk is compressed. In practice: run `ml.run_inference` immediately after each new reading lands, not as a batch job hours later.
  - Always query with `sensor_id` and a `timestamp` range together — the composite index `(sensor_id, timestamp DESC)` is built for exactly that access pattern (e.g., "give me the last N readings for sensor X" or "give me the latest reading for sensor X" — this is precisely what `ml.run_inference` needs to build its feature vector).

### 4.3 Category C — Crowdsourced Validation

```sql
CREATE TABLE user_reports ( ... );          -- Dev A owns this fully; you never touch it directly
CREATE TABLE retraining_samples (
    sample_id   SERIAL PRIMARY KEY,
    report_id   INTEGER REFERENCES user_reports(report_id),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
- You **write** to `retraining_samples` only, and only from the `retrain.ingest_verified_sample` task, which Dev A's API calls after an admin verifies a citizen report. You never read or write `user_reports` directly — the task payload gives you the `report_id` you need.

### 4.4 Storm Tracking & Flood Simulation (this is primarily your table space)

```sql
CREATE TABLE storm_observations (
    obs_id       SERIAL PRIMARY KEY,
    center_point GEOMETRY(POINT, 4326) NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    predicted_next_point GEOMETRY(POINT, 4326),   -- YOU WRITE THIS
    predicted_for TIMESTAMPTZ                      -- YOU WRITE THIS
);
```
- **You insert** a new row (`center_point`, `observed_at`) from the `scheduler`'s 15-minute satellite poll, after the OpenCV pipeline extracts the storm's cloud-center coordinate.
- **You write** `predicted_next_point`/`predicted_for` from the `advection.predict_storm_path` Celery task, which the satellite poll job enqueues right after inserting the new observation.
- Dev A's `/storm/latest-prediction` endpoint only reads this table — never writes it.

```sql
CREATE TABLE simulation_results (
    task_id       UUID PRIMARY KEY,             -- generated by Dev A at enqueue time
    rainfall_mm_hr DOUBLE PRECISION NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING',
    result_geojson JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);
```
- **This is a strict state-machine handoff — read this carefully, it's the single most important ownership boundary in the whole system.**
- Dev A's API is the **only** writer of the `PENDING` row (it inserts this row synchronously, in the same request that enqueues your Celery task, before returning `{task_id}` to the browser).
- **You (Celery) are the only one who transitions `status` from `PENDING` → `RUNNING` → `SUCCESS`/`FAILURE`.** You also fill in `result_geojson` and `completed_at`.
- **Never write a `PENDING` row yourself.** Your `simulate.hydraulic_flood` task receives the `task_id` as part of its payload (Dev A generates it and passes it in) — you `UPDATE ... WHERE task_id = %s`, you never `INSERT`.
- This split exists specifically so there's never a race condition or double-write on the same column from two different codebases. If you ever find your task needing to `INSERT` into this table, that's a sign something upstream is wrong — stop and check the contract.

```sql
CREATE TABLE alerts (
    alert_id    SERIAL PRIMARY KEY,
    ward_id     INTEGER REFERENCES wards(ward_id),
    risk_score  DOUBLE PRECISION NOT NULL,
    message     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
- **You insert** rows here from `ml.contextualize_risk`, once a ward's aggregated risk crosses whatever threshold logic you implement (a stub is fine for v1 — e.g. "if `current_risk_score > 0.7`, insert an alert row with a generic message"). Actual SMS/push delivery is explicitly out of scope; the row itself is the "alert was dispatched" record.

---

## 5. Service 2: Celery Worker — Configuration

### 5.1 App skeleton (`worker_app.py`)

```python
from celery import Celery
import os

celery_app = Celery(
    "meghdrishti_worker",
    broker=os.environ["CELERY_BROKER_URL"],       # redis://redis:6379/0
    backend=os.environ["CELERY_RESULT_BACKEND"],  # redis://redis:6379/1
    include=[
        "tasks.ml_tasks",
        "tasks.simulation_tasks",
        "tasks.advection_tasks",
        "tasks.retrain_tasks",
    ],
)

celery_app.conf.update(
    task_acks_late=True,          # required: only ack after successful completion
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, # don't let one worker hoard jobs; keeps heavy tasks evenly spread
    task_default_retry_delay=10,  # seconds
    task_time_limit=600,          # hard kill after 10 min (hydraulic sim is your longest task)
    task_soft_time_limit=540,
    result_expires=3600,          # don't let Redis result backend grow unbounded
    timezone="Asia/Kolkata",
)
```

**Why `task_acks_late=True` + `task_reject_on_worker_lost=True`:** if a worker process crashes or is killed mid-task (OOM during a hydraulic sim, container restart, etc.), the task must go back on the queue and be retried by another worker, not silently vanish. This is not optional — PRD Section 10 explicitly requires idempotent, retryable tasks; this config is the mechanism that makes retries actually happen when a worker dies unexpectedly.

Run command (already given in the PRD's `docker-compose.yaml`, don't change it):
```
celery -A worker_app worker --loglevel=info
```

### 5.2 Idempotency — non-negotiable, per task

Every task below must be safe to run twice with the same input and produce the same end state (no duplicate rows, no double-incremented counters, no corrupted partial writes). Specific guidance per task is in Section 6. General pattern: prefer `UPDATE`/`UPSERT` keyed on a stable identifier over blind `INSERT`, and wrap multi-statement writes in a single DB transaction so a crash mid-task can't leave the row half-written.

### 5.3 Structured logging

Every task must log, as structured JSON (use `python-json-logger` or equivalent), at minimum:
- Task start: `{"event": "task_start", "task_name": ..., "task_id": ..., "args": ...}`
- Task success: `{"event": "task_success", "task_name": ..., "task_id": ..., "duration_ms": ...}`
- Task failure: `{"event": "task_failure", "task_name": ..., "task_id": ..., "error": str(exc), "retry_count": ...}`

This is a PRD Section 10 requirement (Observability) — don't skip it, it's how you'll debug the integration checkpoint when things don't line up between your worker and Dev A's API.

---

## 6. Machine Learning Integration Pipeline — All 4 Handoff Points

This is the heart of your responsibility. The ML model itself is a black box delivered to you as an importable Python class with a `.predict()` method — **you do not train it, tune it, or touch its internals.** Your job is entirely the plumbing around it: getting clean data in, and getting a contextualized, persisted, alert-triggering result out.

### 6.0 Model loading (do this once, at process startup — not per task)

```python
# ml/model_loader.py
class ModelSingleton:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            # Replace with actual import of the delivered model artifact
            from some_delivered_package import FloodRiskModel
            cls._instance = FloodRiskModel.load(os.environ["MODEL_ARTIFACT_PATH"])
        return cls._instance
```

Load this at **module import time** in your Celery worker process (i.e., it happens once when the `worker` container boots, not on every task invocation). Reloading a model from disk on every single `ml.run_inference` call is the single most common performance mistake in this kind of pipeline — with sensors reporting every minute, that's potentially dozens of unnecessary model loads per hour for no reason.

### Handoff 1 — Structuring CRON data into tabular vectors

This happens as the **first part of the `ml.run_inference` task**, not as a separate task (see task contract in Section 7 — the payload is just `{sensor_id}`, and the task itself is responsible for building the feature vector from that).

Steps:
1. Query `sensor_readings` for the sensor's recent history: `SELECT value, timestamp FROM sensor_readings WHERE sensor_id = %s ORDER BY timestamp DESC LIMIT N` (use the `(sensor_id, timestamp DESC)` index — this is exactly the access pattern it was built for).
2. Also fetch the sensor's `type` (`SoilMoisture` vs `RainGauge`) from the `sensors` table — the model likely needs to know which kind of value it's looking at.
3. Clean the data: handle missing/null readings (e.g., forward-fill or drop, depending on what the model artifact's documentation specifies), reject obviously out-of-range sensor glitches (e.g., negative rainfall) rather than feeding them straight to the model.
4. Scale/normalize per whatever preprocessing contract the delivered model artifact specifies (check the artifact's documentation — do not invent your own scaling scheme; the black-box model was trained on a specific input distribution and mismatched scaling silently produces garbage predictions).
5. Produce a single tabular vector (e.g., a `numpy` array or `pandas` Series/DataFrame row) ready for `.predict()`.

### Handoff 2 — Black-box ML inference via Celery

```python
# tasks/ml_tasks.py
@celery_app.task(bind=True, acks_late=True, max_retries=3, default_retry_delay=15)
def run_inference(self, sensor_id: int):
    try:
        vector = build_feature_vector(sensor_id)   # Handoff 1
        model = ModelSingleton.get()
        risk_score = float(model.predict(vector))
        write_risk_score(sensor_id, risk_score)     # UPDATE latest sensor_readings row
        contextualize_risk.delay(sensor_id=sensor_id, risk_score=risk_score)  # chain to Handoff 3
    except Exception as exc:
        raise self.retry(exc=exc)
```

- This is the task literally named `ml.run_inference` in the contract (Celery task naming is covered in Section 8 — make sure the `name=` on the `@celery_app.task` decorator matches exactly, don't rely on the Python function/module path).
- Enqueued internally by your own `scheduler` process (the 1-minute IoT poll job enqueues it right after inserting a new reading) — **Dev A's API never calls this task directly.**
- Wrap the model call in a try/except with `self.retry(...)` — if the model artifact throws (e.g., transient resource issue), don't let the task die silently; let Celery's retry mechanism handle it up to `max_retries`.
- **Idempotency note:** re-running this for the same `sensor_id` should just overwrite `risk_score` on the *latest* reading row with the same recomputed value — it's naturally idempotent as long as you always target "the latest reading for this sensor" rather than blindly appending.

### Handoff 3 — PostGIS spatial join to contextualize by ward

```python
# tasks/ml_tasks.py
@celery_app.task(bind=True, acks_late=True, max_retries=3)
def contextualize_risk(self, sensor_id: int, risk_score: float):
    # 1. Look up the sensor's ward via the FK (fast path, already denormalized)
    #    OR do a live ST_Contains spatial join against wards.ward_boundary
    #    using the sensor's `coord` — use whichever the sensors.ward_id FK
    #    doesn't already cover (e.g., handle sensors with a NULL ward_id by
    #    falling back to a live spatial join).
    ward_id = resolve_ward_for_sensor(sensor_id)   # uses idx_wards_boundary GIST index

    # 2. Aggregate: for v1, a simple approach is fine — e.g., take the max
    #    (or a rolling average) of risk_score across all sensors currently
    #    reporting into that ward, then write that as the ward's score.
    aggregated_score = aggregate_ward_risk(ward_id)

    # 3. Update the ward row
    update_ward_risk(ward_id, aggregated_score)   # sets current_risk_score, risk_updated_at

    # 4. Threshold check -> alert dispatch stub
    if aggregated_score > ALERT_THRESHOLD:
        insert_alert(ward_id, aggregated_score, message="Elevated flood risk detected")
```

- Task name: `ml.contextualize_risk`. Chained internally from `ml.run_inference` — Dev A never calls this directly either.
- The spatial join query, if you go the "live join" route rather than the FK shortcut, looks like:
  ```sql
  SELECT ward_id FROM wards WHERE ST_Contains(ward_boundary, %s::geometry);
  ```
  passing in the sensor's `coord`. This is exactly why `idx_wards_boundary` (GIST) exists — confirm with `EXPLAIN ANALYZE` during development that this query is using the index, not sequential-scanning the wards table.
- Actual SMS/push notification delivery is explicitly out of scope (per PRD 5.2) — the `alerts` row **is** the deliverable here, not an actual notification being sent.

### Handoff 4 — Updating the database to trigger the alert

This is Steps 3–4 inside `contextualize_risk` above — there isn't a separate 5th task for this. "Handoff 4" in the PRD's framing refers to the fact that the *database write itself* (updating `wards.current_risk_score` + inserting into `alerts`) is what the frontend's next poll/read picks up — there's no push mechanism from worker to frontend; the frontend just re-reads `wards` and sees the new score. Your responsibility ends at "the row is correctly and durably written."

---

## 7. Earth Physics Module 1 — Advection Processing (Storm Path Prediction)

**Goal:** given the last two known positions of a storm's cloud-center, predict where it will be N minutes from now, accounting for the Earth's curvature (a naive flat-plane linear extrapolation is wrong at this kind of distance/precision — this is exactly why GeoPy's geodesic calculations, not simple lat/lon arithmetic, are required).

### 7.1 The math

1. Pull the two most recent `storm_observations` rows (ordered by `observed_at DESC`, limit 2).
2. Compute **bearing** (compass direction of travel) between the older point and the newer point.
3. Compute **distance traveled** and **elapsed time** between those two observations → derive a **speed**.
4. Project forward: using GeoPy's `geopy.distance.geodesic`, compute `.destination(start_point, bearing=bearing, distance=speed * lookahead_minutes)` to get the predicted future coordinate.

```python
# geo/advection.py
from geopy.distance import geodesic
from geopy.point import Point
import math

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
```

- **Lookahead window:** the PRD's acceptance criteria (Section 12) references "predicted_next_point" without pinning an exact minute value elsewhere in the doc — default to a **20-minute lookahead** (this matches the product framing in PRD Section 1.1: "Predicts where a storm cell is heading 20 minutes into the future"). Make this a named constant, not a magic number, so it's trivially adjustable.
- **Edge case:** if there's only one `storm_observations` row so far (first-ever satellite poll), there's no prior point to compute bearing/speed from — skip prediction for that cycle rather than guessing. `predicted_next_point` stays `NULL` until at least two observations exist, which is explicitly called out in PRD Section 12 ("after at least two satellite poll cycles").

### 7.2 Celery task

```python
# tasks/advection_tasks.py
@celery_app.task(bind=True, acks_late=True, max_retries=3)
def predict_storm_path(self, obs_id: int):
    newer = fetch_observation(obs_id)
    older = fetch_previous_observation(before=newer.observed_at)
    if older is None:
        return  # not enough history yet — no-op, this is expected on first run
    destination = predict_next_point(older.center_point, older.observed_at,
                                      newer.center_point, newer.observed_at,
                                      lookahead_minutes=20)
    update_storm_observation(obs_id, predicted_next_point=destination,
                              predicted_for=newer.observed_at + timedelta(minutes=20))
```

- Task name: `advection.predict_storm_path`. Payload: `{obs_id: int}`. Enqueued by your own `scheduler`'s satellite-poll job immediately after it inserts the new `storm_observations` row — never called by Dev A.
- **Idempotency:** this task always does a targeted `UPDATE ... WHERE obs_id = %s` against a specific, already-inserted row — re-running it with the same `obs_id` recomputes and overwrites the same prediction. Safe to retry.

---

## 8. Earth Physics Module 2 — Hydraulic Pooling (Flood Simulation)

**Goal:** given a rainfall intensity (mm/hr), simulate where water will accumulate across the Chamoli terrain and produce a flood-extent polygon the frontend can render on a map.

### 8.1 Pipeline

1. **Input:** `rainfall_mm_hr` (float), passed in by Dev A's `POST /simulate/flood` endpoint.
2. **Read the DEM raster** from `dem_tiles` via Rasterio (open the raster, read the elevation array as a numpy grid).
3. **Run flow accumulation:** for each cell, determine which direction water flows (steepest downhill neighbor — the classic D8 flow-direction algorithm), then accumulate upstream contribution per cell. This tells you which cells are "sinks" (valleys) where water pools.
4. **"Fill" based on rainfall intensity:** scale the accumulated flow by the input `rainfall_mm_hr` to determine which cells cross a flooding threshold at this rainfall rate — the higher the input, the larger/deeper the flooded area.
5. **Convert the resulting flood grid (a boolean/binary raster mask) into vector geometry** using Shapely — specifically, extract contours/polygons around contiguous flooded cells (e.g., via `rasterio.features.shapes()` to get raw geometry from the raster mask, then wrap/simplify with Shapely) and merge into a single (possibly multi-part) `Polygon`/`MultiPolygon`.
6. **Simplify** the resulting polygon (Shapely's `.simplify(tolerance, preserve_topology=True)`) before serializing — raw flood-fill output can produce polygons with thousands of vertices, which is unnecessary detail for a map render and bloats the JSONB payload.
7. **Serialize to GeoJSON** (Shapely's `shapely.geometry.mapping()` gives you a dict that's directly JSON-serializable) and write into `simulation_results.result_geojson`.

```python
# geo/hydraulic.py
import rasterio
import numpy as np
from shapely.geometry import shape, mapping
from rasterio.features import shapes as raster_shapes
from shapely.ops import unary_union

def run_hydraulic_pooling(dem_path: str, rainfall_mm_hr: float) -> dict:
    with rasterio.open(dem_path) as src:
        elevation = src.read(1)
        transform = src.transform

    flow_accum = compute_flow_accumulation(elevation)      # D8 algorithm
    flood_mask = (flow_accum * rainfall_mm_hr) > FLOOD_THRESHOLD  # boolean grid

    polygons = [
        shape(geom) for geom, value in raster_shapes(
            flood_mask.astype(np.uint8), mask=flood_mask, transform=transform
        )
    ]
    merged = unary_union(polygons)
    simplified = merged.simplify(0.0001, preserve_topology=True)  # tune tolerance for CRS units
    return mapping(simplified)  # GeoJSON-ready dict
```

### 8.2 Celery task, with the critical state-machine handling

```python
# tasks/simulation_tasks.py
@celery_app.task(bind=True, acks_late=True, max_retries=2, default_retry_delay=20)
def hydraulic_flood(self, task_id: str, rainfall_mm_hr: float):
    mark_running(task_id)  # UPDATE simulation_results SET status='RUNNING' WHERE task_id=%s
    try:
        dem_path = resolve_dem_tile_path()  # from dem_tiles table
        result_geojson = run_hydraulic_pooling(dem_path, rainfall_mm_hr)
        mark_success(task_id, result_geojson)
        # UPDATE simulation_results SET status='SUCCESS', result_geojson=%s, completed_at=now() WHERE task_id=%s
    except Exception as exc:
        mark_failure(task_id, str(exc))
        # UPDATE simulation_results SET status='FAILURE', completed_at=now() WHERE task_id=%s
        raise self.retry(exc=exc)
```

- Task name: `simulate.hydraulic_flood`. Payload: exactly `{task_id: str, rainfall_mm_hr: float}` — **the `task_id` is generated by Dev A**, not by you. Your job is purely to `UPDATE` the row Dev A already `INSERT`ed as `PENDING`.
- **Never `INSERT` into `simulation_results` from this task.** If the row with that `task_id` doesn't exist when you go to `mark_running`, that's an integration bug upstream — log it loudly and fail, don't silently create a row (see Section 4.4 for why this boundary matters).
- **Idempotency:** every step is a targeted `UPDATE ... WHERE task_id = %s`. Re-running the same `task_id` (e.g., after a retry) just recomputes and overwrites the same row — safe.
- Because this can be your longest-running task, make sure `task_time_limit`/`task_soft_time_limit` (Section 5.1) comfortably exceed your worst-case simulation runtime, or the task will be hard-killed mid-flight.

---

## 9. Service 3: APScheduler Ingestion Process

This is a **separate container** from the worker (`scheduler`), whose only job is to run two fixed-interval jobs and enqueue Celery tasks. It does not do any heavy compute itself — CV extraction and DB polling are fine to run directly in this process since they're lightweight/IO-bound, but anything genuinely heavy (ML inference, hydraulic sim, geodesic calc) must be handed off to the `worker` via Celery, not run inline here.

### 9.1 App skeleton (`scheduler_app.py`)

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from jobs.satellite_poll import poll_satellite_tiles
from jobs.iot_poll import poll_iot_sensors

scheduler = BlockingScheduler(timezone="Asia/Kolkata")
scheduler.add_job(poll_satellite_tiles, "interval", minutes=15, id="satellite_poll",
                   max_instances=1, coalesce=True, misfire_grace_time=120)
scheduler.add_job(poll_iot_sensors, "interval", minutes=1, id="iot_poll",
                   max_instances=1, coalesce=True, misfire_grace_time=30)

if __name__ == "__main__":
    scheduler.start()
```

- `max_instances=1` + `coalesce=True`: if a poll cycle runs long and overlaps the next scheduled trigger, don't stack duplicate concurrent runs — skip/merge instead. This matters especially for the 1-minute IoT job; a slow HTTP call to the gateway shouldn't cause a pile-up of overlapping polls.
- `misfire_grace_time`: if the process was briefly unavailable (e.g., container restart) and missed a trigger by a bit, still allow it to run within this grace window rather than silently skipping.

### 9.2 Job: Satellite thermal tile poll (every 15 minutes)

```python
# jobs/satellite_poll.py
def poll_satellite_tiles():
    raw_tile = isro_bhuvan_client.fetch_latest_thermal_tile()
    cloud_center = thermal_tile_pipeline.extract_cloud_center(raw_tile)  # OpenCV
    if cloud_center is None:
        log.info("no storm signature detected this cycle")
        return
    obs_id = insert_storm_observation(center_point=cloud_center)  # INSERT into storm_observations
    celery_app.send_task("advection.predict_storm_path", kwargs={"obs_id": obs_id})
```

- Uses `ISRO_BHUVAN_API_KEY` env var for auth against the external API.
- The OpenCV pipeline (`thermal_tile_pipeline.py`) should, at minimum: threshold the thermal band for cold cloud-tops (a standard proxy for storm intensity), find the largest contiguous blob, compute its centroid, and convert the pixel centroid to a lat/lon using the tile's known georeferencing metadata.
- **Failure handling:** if the external ISRO API is unreachable, log and skip the cycle — don't crash the scheduler process, and don't retry aggressively against a rate-limited external API. A missed 15-minute cycle is acceptable; a crashed scheduler that misses every future cycle is not.

### 9.3 Job: IoT sensor gateway poll (every 1 minute)

```python
# jobs/iot_poll.py
def poll_iot_sensors():
    all_sensors = fetch_sensor_list_from_db()   # read `sensors` table
    for sensor in all_sensors:
        try:
            reading = iot_gateway_client.fetch_latest_reading(sensor.sensor_id)
            insert_sensor_reading(sensor.sensor_id, reading.value, reading.timestamp)
            celery_app.send_task("ml.run_inference", kwargs={"sensor_id": sensor.sensor_id})
        except GatewayUnavailable:
            log.warning(f"sensor {sensor.sensor_id} gateway unreachable this cycle, skipping")
            continue
```

- One HTTP call per sensor to `IOT_GATEWAY_BASE_URL`, per minute. Iterate defensively — one unreachable sensor gateway must not abort the whole poll cycle for every other sensor.
- Every successful reading insert immediately enqueues `ml.run_inference` for that sensor — this is the trigger that kicks off the entire Handoff 1→4 ML pipeline described in Section 6.

---

## 10. Environment Variables You Consume

From the shared `.env` (defined once at repo root, per PRD Section 9 — **you don't invent new variable names without adding them there first**):

```
DATABASE_URL=postgresql://meghdrishti_admin:changeme@postgres:5432/meghdrishti
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
ISRO_BHUVAN_API_KEY=changeme
IOT_GATEWAY_BASE_URL=http://localhost:9100
```

You will likely also need to add (propose these to Dev A rather than hardcoding):
```
MODEL_ARTIFACT_PATH=/models/flood_risk_v1.pkl
DEM_TILE_STORAGE_PATH=/data/dem_tiles
```

---

## 11. Docker Compose Blocks (already specified in the PRD — do not deviate)

```yaml
worker:                       # YOU OWN THIS
  build: ./services/worker
  env_file: .env
  depends_on:
    - postgres
    - redis
  command: celery -A worker_app worker --loglevel=info

scheduler:                    # YOU OWN THIS
  build: ./services/scheduler
  env_file: .env
  depends_on:
    - postgres
    - redis
```

Both containers depend on `postgres` and `redis` being up — but note **you are the one who stands up the `redis` service block** in the shared `docker-compose.yaml` (per PRD Section 2.2, Redis is "shared infra — stood up by Dev B"), even though both your and Dev A's containers connect to it.

---

## 12. Explicit Boundaries — What You Must NOT Do

- **Never write JWT/auth logic, never issue tokens, never touch FastAPI route code.**
- **Never run an Alembic migration or `CREATE TABLE`.** If a needed column doesn't exist, that's a schema-contract conversation with Dev A, not something you patch around locally.
- **Never `INSERT` into `simulation_results`.** Only `UPDATE` rows Dev A already created.
- **Never import Dev A's FastAPI application code**, and conversely, Dev A's `api` container must never import `rasterio`, `shapely`, `geopy`, or your ML model class (this is explicitly checked in PRD Section 12's Definition of Done — "No FastAPI code imports rasterio, shapely, geopy, or the ML model class").
- **Never build the actual SMS/push notification delivery** for alerts — an `alerts` row is the full extent of the v1 deliverable.
- **Never train, fine-tune, or modify the ML model's internals.** Treat `.predict()` as a sealed interface.

---

## 13. Suggested Build Order

1. Bring up `redis` + a bare Celery app in the `worker` container; prove a trivial `ping` task can be enqueued (even manually, via `celery_app.send_task`) and picked up. This is your "hello world" integration check with the broker.
2. Load the ML black-box model class at worker startup as a singleton; implement `ml.run_inference` against a **mocked** sensor vector (don't wait on real IoT data existing yet) to prove the model call + DB write works end to end.
3. Implement `ml.contextualize_risk` — the PostGIS spatial join against `wards`. Verify with `EXPLAIN ANALYZE` that it's hitting the GIST index, not scanning.
4. Implement `simulate.hydraulic_flood` — start with a tiny/dummy DEM raster to validate the Rasterio → flow-accumulation → Shapely → GeoJSON pipeline before pointing it at real Chamoli tiles.
5. Implement `advection.predict_storm_path` — unit-test the geodesic bearing/distance math independently of the DB, with known lat/lon pairs and a hand-checked expected bearing.
6. Build the `scheduler` container: wire up the 15-minute satellite job and 1-minute IoT job, each enqueuing the tasks above into the same Redis broker the worker is listening on.
7. Implement `retrain.ingest_verified_sample` — the simplest task in the whole pipeline, a straight `INSERT` keyed on `report_id`.

**Integration checkpoint (with Dev A):** once you reach step 6/7, bring up the **full** `docker-compose up` stack (not just your own services) and walk through the end-to-end flow described in the PRD: citizen submits a report → admin verifies it → your `retrain.ingest_verified_sample` fires → admin triggers a flood sim via the API → you pick it up, run it, mark it `SUCCESS` → the API's poll endpoint returns the GeoJSON you wrote.

---

## 14. Your Slice of the Definition of Done

Pulled directly from PRD Section 12, filtered to what's on you:

- [ ] `POST /simulate/flood` (Dev A's endpoint) returns within <200ms because your task runs fully async; polling eventually returns `SUCCESS` with a **valid** GeoJSON polygon your pipeline produced.
- [ ] Ward `current_risk_score` values update automatically after the scheduler's 1-minute IoT poll cycle runs at least once — with **no manual trigger**, i.e. the scheduler container alone, running unattended, drives this.
- [ ] `/storm/latest-prediction` (Dev A's endpoint, reading your table) returns a non-null `predicted_next_point` after **at least two** satellite poll cycles — confirming your "skip on first observation" edge case is correct.
- [ ] No Celery task code imports FastAPI or issues JWTs.
- [ ] Every Celery task is idempotent — you should be able to manually re-trigger any task with the same payload and get the same end state, not corrupted or duplicated data.
- [ ] Every task has `acks_late=True` and a sane `max_retries`, and structured logs are emitted on start/success/failure with `task_id`.
