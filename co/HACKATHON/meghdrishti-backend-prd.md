# Product Requirements Document (PRD)
## Meghdrishti — Chamoli Flood Intelligence & Early-Warning Backend

**Document type:** Backend Engineering PRD
**Audience:** AI-assisted / "vibe coding" developers implementing this system from scratch
**Status:** Draft v1.0
**Owners:** 2 backend developers (Dev A — Core API & Data Platform, Dev B — Compute, Simulation & Intelligence Platform)
**Integration mechanism:** Single `docker-compose.yaml` at repo root

---

## 0. How to Use This Document

This PRD is written so that two developers can build **independently, in parallel, in separate folders**, and still guarantee their code merges into one working system on the first `docker-compose up`. Every section that is a **shared contract** (database schema, API request/response shapes, message formats, environment variables) is called out explicitly and **must not be changed unilaterally** by either developer — if a contract needs to change, both developers must agree and update this document first.

If you are an AI coding agent implementing a section of this PRD: **do not invent your own schema, endpoint names, or payload shapes.** Use exactly what is specified in Sections 6 and 7. This is what allows the two halves of the system to integrate without a manual "glue" phase.

---

## 1. Project Overview

### 1.1 What we are building
A disaster-response backend for a flood early-warning system in **Chamoli, Uttarakhand**. The system:
- Ingests live IoT sensor telemetry (soil moisture, rain gauges) and satellite thermal tiles on a schedule.
- Runs an ML risk model (treated as a black box) against that telemetry to produce per-sensor risk scores.
- Spatially joins those risk scores against administrative ward boundaries so risk can be shown "per village."
- Lets an Admin simulate a flood ("what if it rains at 150mm/hr") and see a rendered flood polygon.
- Lets citizen volunteers submit geotagged reports with photos via a PWA, which admins verify.
- Predicts where a storm cell is heading 20 minutes into the future using geodesic vector math.
- Serves all of the above to a Next.js Admin dashboard and a Next.js Citizen PWA.

### 1.2 What this backend is explicitly NOT responsible for
- The ML model's internals (training, feature engineering, model architecture). The ML model is delivered to the backend as an importable Python class/artifact with a `.predict()` method. **Backend developers integrate it; they do not build it.**
- The frontend (Next.js Admin / Citizen PWA) — out of scope for this PRD, only the API contract they consume is in scope.
- Any hardware/firmware for the IoT sensors themselves — the backend only consumes their HTTP/telemetry output.

### 1.3 Guiding architectural principle
**Separate synchronous, user-facing work from heavy asynchronous compute.** No request from a browser should ever block on a hydraulic simulation, a satellite CV pipeline, or an ML inference call. This single principle is *why* the system is split into an API service and a worker service, and it is also *why* the two developers' responsibilities are split the way they are in Section 5.

---

## 2. System Architecture

### 2.1 High-level diagram (textual)

```
                         ┌─────────────────────────┐
                         │   Next.js Admin (PWA)    │
                         │   Next.js Citizen (PWA)  │
                         └────────────┬─────────────┘
                                      │ HTTPS / REST / JWT
                                      ▼
                         ┌─────────────────────────┐
   DEV A OWNS ─────────► │   Service 1: Core API    │
                         │   (FastAPI, sync-facing) │
                         └────┬───────────┬─────────┘
                              │           │
                 enqueue job  │           │  read/write
                              ▼           ▼
                  ┌───────────────┐  ┌─────────────────────────┐
                  │  Redis (broker)│  │ PostgreSQL + PostGIS +   │
                  │                │  │ TimescaleDB              │
                  └───────┬────────┘  └─────────────┬────────────┘
                          │                          ▲
                          ▼                          │
             ┌─────────────────────────┐             │
DEV B OWNS ─►│ Service 2: Celery Worker │─────────────┘
             │ (ML inference, hydraulic │
             │ sim, GeoPy advection)    │
             └─────────────────────────┘
                          ▲
                          │ schedules jobs into Redis
             ┌─────────────────────────┐
DEV B OWNS ─►│ Service 3: CRON /        │
             │ APScheduler Ingestion    │
             └─────────────────────────┘

             ┌─────────────────────────┐
DEV A OWNS ─►│ MinIO (S3-compatible      │◄── photo uploads (via API), read by both
             │ object storage)           │
             └─────────────────────────┘
```

### 2.2 Services and who builds them

| # | Service | Container name | Owner | Purpose |
|---|---|---|---|---|
| 1 | Core API Server | `api` | **Dev A** | Auth, CRUD, request validation, serves frontends, enqueues jobs |
| 2 | Background Worker | `worker` | **Dev B** | Celery worker: ML inference, hydraulic sim, PostGIS spatial join, advection calc |
| 3 | Scheduled Ingestion | `scheduler` | **Dev B** | APScheduler process: pulls satellite tiles + IoT readings on a timer, pushes jobs to Celery |
| 4 | Postgres/PostGIS/TimescaleDB | `postgres` | **Shared infra** — Dev A defines schema/migrations, Dev B only queries it | Single source of truth |
| 5 | Redis | `redis` | **Shared infra** — stood up by Dev B (it's the Celery broker) but both connect | Celery broker + optional cache |
| 6 | MinIO | `minio` | **Dev A** stands it up; both may read/write via presigned URLs | Object storage for photos/tiles |

All six run as services inside **one `docker-compose.yaml`**, defined in Section 8, which both developers contribute to (each owns their own service blocks; nobody edits the other's blocks without discussion).

---

## 3. Goals

1. Sub-200ms p95 response time on all synchronous `api` endpoints (nothing heavy ever runs inline in a request handler).
2. Flood simulation and ML inference run fully asynchronously; the frontend polls or receives a webhook/status update, never blocks.
3. All spatial queries (nearest shelter, ward containment, risk aggregation) use PostGIS **GIST indexes** — must return in well under 1 second even under "crisis load" (many concurrent citizen report submissions).
4. System must survive the "offline sandbox" hackathon demo mode: all static geofence data (`dem_tiles`, `wards`, `safe_havens`) is pre-loaded once and never depends on external network calls during a demo.
5. Every long-running task is idempotent and retryable (Celery task failures must not corrupt state).
6. Clean two-developer separation: Dev A never has to touch Rasterio/Shapely/GeoPy code; Dev B never has to touch JWT/auth/CRUD code. The only shared surface is the **database schema** and the **Celery task signatures** (Section 7.3).

## 4. Non-Goals
- No Kubernetes / cloud deployment automation in this phase — Docker Compose only.
- No horizontal auto-scaling logic — services are single-instance for the hackathon/demo phase (architecture should *allow* scaling later, but building it is out of scope now).
- No production-grade secrets manager — `.env` file is acceptable for this phase (see Section 9).

---

## 5. Developer Split of Responsibilities

This is the authoritative division of labor. If a task isn't listed here, default to: "does it involve a browser-facing HTTP request/response, auth, or plain CRUD?" → Dev A. "Does it involve raster/vector geometry math, ML inference, or scheduled external polling?" → Dev B.

### 5.1 Developer A — "Core API & Data Platform"
**Owns Service 1 (`api`), the Postgres schema/migrations, and MinIO.**

Responsibilities:
- FastAPI application scaffold, routing, dependency injection, middleware (CORS, logging, error handling).
- JWT-based authentication (Admin login, citizen anonymous/lightweight auth — see Section 6.1).
- All CRUD endpoints for `user_reports`, `wards`, `safe_havens`, `sensors` (metadata only, not readings).
- Request/response validation via Pydantic models that exactly mirror Section 7 schemas.
- MinIO integration: presigned upload URLs, storing the returned object URL into `user_reports.photo_url`.
- Database schema definition and migrations (using Alembic) for **all** tables in Section 6, including the ones Dev B's worker will write to (`sensor_readings`, risk score columns, simulation results) — Dev A owns the schema file even though Dev B's code writes rows into some of those tables.
- The "Verify Report" admin action (`PATCH /reports/{id}/verify`) including firing the retraining-feedback hook (a Celery task call — Dev A only needs to *call* `celery_app.send_task("retrain.ingest_verified_sample", ...)`, not implement it).
- API endpoints that *trigger* async work by enqueuing Celery tasks (e.g., `POST /simulate/flood`), and endpoints that *poll* for the result (e.g., `GET /simulate/flood/{task_id}`).
- OpenAPI docs (FastAPI gives this for free — make sure every endpoint has a docstring and Pydantic schema so `/docs` is fully usable by the frontend team without reading backend code).

Explicitly NOT Dev A's job: writing any Rasterio/Shapely/GeoPy code, writing the ML `.predict()` call, writing the APScheduler polling logic, or touching Celery task *internals* (Dev A only calls `.delay()` / `.send_task()`).

### 5.2 Developer B — "Compute, Simulation & Intelligence Platform"
**Owns Service 2 (`worker`), Service 3 (`scheduler`), and Redis.**

Responsibilities:
- Celery app configuration, Redis broker/result-backend wiring.
- APScheduler process (`scheduler` container) with two jobs:
  - Every 15 min: fetch ISRO Bhuvan satellite thermal tile → run OpenCV pipeline → extract cloud-center coordinate → write to a `storm_observations` table (Section 6.2) → enqueue advection Celery task.
  - Every 1 min: poll local IoT sensor gateways → write rows into `sensor_readings` (TimescaleDB hypertable) → enqueue ML inference Celery task.
- Loading the ML model as a black-box Python class at worker startup (module-level singleton, loaded once, not per-task, to avoid reload overhead).
- Celery task: `ml.run_inference` — structures the latest sensor vector (cleaning, scaling, missing-value handling), calls `model.predict(vector)`, gets a risk score.
- Celery task: `ml.contextualize_risk` — takes the risk score + sensor GPS coordinate, runs a PostGIS spatial join (`ST_Contains` / `ST_Within`) against `wards`, writes the aggregated per-ward risk score, and triggers alert dispatch (can be a stub — e.g., write an `alerts` row — actual SMS/push integration out of scope).
- Celery task: `simulate.hydraulic_flood` — takes rainfall intensity (mm/hr) as input, reads `dem_tiles` raster via Rasterio, runs the flow-accumulation / pooling algorithm, converts result to a GeoJSON polygon via Shapely, writes result + status to a `simulation_results` table that Dev A's polling endpoint reads.
- Celery task: `advection.predict_storm_path` — uses GeoPy `geodesic().destination()` on the last two `storm_observations` points to compute bearing + future distance, writes predicted coordinate.
- Celery task: `retrain.ingest_verified_sample` (called by Dev A's verify endpoint) — appends the verified report to a retraining dataset/table (implementation can be a simple append-only table or file write to a mounted volume; full retraining pipeline is out of scope, just the ingestion hook).

Explicitly NOT Dev B's job: JWT/auth, MinIO presigned URLs, defining the DB schema/migrations (Dev B queries/writes existing tables, does not run `alembic revision`), any FastAPI route.

### 5.3 The only two things that require both developers to agree
1. **The database schema** (Section 6) — Dev A writes the migration files, but every column Dev B's tasks read or write must be listed here first.
2. **Celery task names and payload shapes** (Section 7.3) — Dev A enqueues tasks by name/string with a specific payload; Dev B implements the task with that exact name/signature. Treat this like an API contract between the two services.

---

## 6. Database Schema (Shared Contract — Dev A implements, Dev B consumes)

**Engine:** PostgreSQL 15+ with `postgis`, `postgis_raster`, and `timescaledb` extensions enabled.

### 6.1 Auth
```sql
CREATE TABLE admins (
    admin_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
Citizen users are not required to register for v1 — citizen report submissions are unauthenticated but rate-limited by IP/device-id at the API layer (Dev A's call on implementation, e.g. a lightweight device UUID header).

### 6.2 Category A — Static Topographical Geofences (pre-loaded once, read-only at runtime)
```sql
CREATE TABLE dem_tiles (
    tile_id       SERIAL PRIMARY KEY,
    rast_geometry RASTER NOT NULL
);
CREATE INDEX idx_dem_tiles_rast ON dem_tiles USING GIST (ST_ConvexHull(rast_geometry));

CREATE TABLE wards (
    ward_id        SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    ward_boundary  GEOMETRY(POLYGON, 4326) NOT NULL,
    current_risk_score DOUBLE PRECISION,          -- written by Dev B's contextualize_risk task
    risk_updated_at    TIMESTAMPTZ
);
CREATE INDEX idx_wards_boundary ON wards USING GIST (ward_boundary);

CREATE TABLE safe_havens (
    shelter_id  SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,        -- 'shelter' | 'helipad'
    capacity    INTEGER,
    coordinate  GEOMETRY(POINT, 4326) NOT NULL
);
CREATE INDEX idx_safe_havens_coord ON safe_havens USING GIST (coordinate);
```

### 6.3 Category B — Dynamic Timeseries Sensors
```sql
CREATE TABLE sensors (
    sensor_id  SERIAL PRIMARY KEY,
    type       TEXT NOT NULL,          -- 'SoilMoisture' | 'RainGauge'
    coord      GEOMETRY(POINT, 4326) NOT NULL,
    ward_id    INTEGER REFERENCES wards(ward_id)
);
CREATE INDEX idx_sensors_coord ON sensors USING GIST (coord);

CREATE TABLE sensor_readings (
    reading_id SERIAL,
    sensor_id  INTEGER NOT NULL REFERENCES sensors(sensor_id),
    value      DOUBLE PRECISION NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_score DOUBLE PRECISION            -- written by Dev B's ml.run_inference task
);
SELECT create_hypertable('sensor_readings', 'timestamp');
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, timestamp DESC);
```

### 6.4 Category C — Crowdsourced Validation
```sql
CREATE TABLE user_reports (
    report_id   SERIAL PRIMARY KEY,
    type        TEXT NOT NULL,          -- 'FlashFlood' | 'Blockage' | ...
    location    GEOMETRY(POINT, 4326) NOT NULL,
    photo_url   TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status      TEXT NOT NULL DEFAULT 'Unverified'   -- 'Unverified' | 'Verified' | 'Rejected'
);
CREATE INDEX idx_user_reports_location ON user_reports USING GIST (location);
```

### 6.5 Storm tracking & flood simulation (used by Dev B's tasks, read via Dev A's polling endpoints)
```sql
CREATE TABLE storm_observations (
    obs_id       SERIAL PRIMARY KEY,
    center_point GEOMETRY(POINT, 4326) NOT NULL,
    observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    predicted_next_point GEOMETRY(POINT, 4326),   -- filled by advection.predict_storm_path
    predicted_for TIMESTAMPTZ
);

CREATE TABLE simulation_results (
    task_id       UUID PRIMARY KEY,             -- Celery task id, generated by Dev A at enqueue time
    rainfall_mm_hr DOUBLE PRECISION NOT NULL,
    status        TEXT NOT NULL DEFAULT 'PENDING',  -- 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILURE'
    result_geojson JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ
);

CREATE TABLE alerts (
    alert_id    SERIAL PRIMARY KEY,
    ward_id     INTEGER REFERENCES wards(ward_id),
    risk_score  DOUBLE PRECISION NOT NULL,
    message     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE retraining_samples (
    sample_id   SERIAL PRIMARY KEY,
    report_id   INTEGER REFERENCES user_reports(report_id),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 7. API & Task Contracts

### 7.1 Auth
| Method | Path | Owner | Notes |
|---|---|---|---|
| POST | `/auth/login` | Dev A | body `{email, password}` → `{access_token, token_type}` (JWT, expiry 24h) |

### 7.2 Core API endpoints (Dev A implements all of these)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/wards` | Public | List wards with `current_risk_score` |
| GET | `/wards/{id}` | Public | Ward detail incl. boundary GeoJSON |
| GET | `/safe-havens/nearest?lat=&lon=` | Public | PostGIS `ORDER BY coordinate <-> ST_MakePoint(...)` nearest-neighbor query |
| POST | `/reports` | Public (rate-limited) | Citizen submits report; body includes `type, lat, lon, photo (multipart or presigned-url flow)` |
| GET | `/reports?status=Unverified` | Admin JWT | Admin queue |
| PATCH | `/reports/{id}/verify` | Admin JWT | Sets status, fires `retrain.ingest_verified_sample` Celery task |
| GET | `/reports/upload-url` | Public | Returns MinIO presigned PUT URL + the final `photo_url` to store |
| POST | `/simulate/flood` | Admin JWT | body `{rainfall_mm_hr}` → enqueues `simulate.hydraulic_flood`, returns `{task_id}`, inserts a `PENDING` row in `simulation_results` |
| GET | `/simulate/flood/{task_id}` | Admin JWT | Polls `simulation_results` table; returns `{status, result_geojson?}` |
| GET | `/storm/latest-prediction` | Public | Returns latest `storm_observations` row with `predicted_next_point` |
| GET | `/sensors/{id}/readings?since=` | Admin JWT | Timeseries read from `sensor_readings` |

### 7.3 Celery task contract (Dev A enqueues by exact name; Dev B implements with this exact signature)

| Task name | Enqueued by | Payload | Result / side-effect |
|---|---|---|---|
| `simulate.hydraulic_flood` | Dev A, `POST /simulate/flood` | `{task_id: str, rainfall_mm_hr: float}` | Writes GeoJSON + status into `simulation_results` row matching `task_id` |
| `ml.run_inference` | Dev B's scheduler (internal, Dev A never calls this) | `{sensor_id: int}` | Writes `risk_score` into latest `sensor_readings` row |
| `ml.contextualize_risk` | Dev B's `ml.run_inference` on completion (chained) | `{sensor_id: int, risk_score: float}` | Updates `wards.current_risk_score`, inserts `alerts` row |
| `advection.predict_storm_path` | Dev B's scheduler (internal) | `{obs_id: int}` | Updates `storm_observations.predicted_next_point` |
| `retrain.ingest_verified_sample` | Dev A, `PATCH /reports/{id}/verify` | `{report_id: int}` | Inserts row into `retraining_samples` |

**Rule:** Dev A must be able to call every task in this table with `celery_app.send_task("task.name", kwargs={...})` **without importing any of Dev B's code**. This is what keeps the two codebases decoupled — Dev A's container never imports Rasterio, Shapely, GeoPy, or the ML model class.

---

## 8. Docker Compose Orchestration

Single file at repo root: `docker-compose.yaml`. Each developer contributes their own service blocks. Suggested repo layout:

```
/repo
  docker-compose.yaml
  .env
  /services
    /api          <- Dev A
    /worker       <- Dev B
    /scheduler    <- Dev B
  /db
    /migrations   <- Dev A (Alembic)
  /minio
```

```yaml
version: "3.9"

services:
  postgres:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data

  api:                          # DEV A
    build: ./services/api
    env_file: .env
    depends_on:
      - postgres
      - redis
      - minio
    ports:
      - "8000:8000"

  worker:                       # DEV B
    build: ./services/worker
    env_file: .env
    depends_on:
      - postgres
      - redis
    command: celery -A worker_app worker --loglevel=info

  scheduler:                    # DEV B
    build: ./services/scheduler
    env_file: .env
    depends_on:
      - postgres
      - redis

volumes:
  pgdata:
  minio_data:
```

Both developers run `docker-compose up postgres redis minio` locally to develop against shared infra, and only their own service (`api` or `worker`+`scheduler`) while iterating, then `docker-compose up` (full stack) before merging to confirm integration.

---

## 9. Environment Variables (`.env`, shared, checked into `.env.example` only)

```
POSTGRES_DB=meghdrishti
POSTGRES_USER=meghdrishti_admin
POSTGRES_PASSWORD=changeme
DATABASE_URL=postgresql://meghdrishti_admin:changeme@postgres:5432/meghdrishti

REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=changeme
MINIO_ENDPOINT=minio:9000
MINIO_BUCKET=meghdrishti-reports

JWT_SECRET=changeme
JWT_EXPIRY_HOURS=24

ISRO_BHUVAN_API_KEY=changeme
IOT_GATEWAY_BASE_URL=http://localhost:9100
```

---

## 10. Non-Functional Requirements
- **Fault tolerance:** every Celery task must be written idempotently (safe to retry). Use `acks_late=True` and a sane `max_retries`.
- **Spatial performance:** all geometry columns must have GIST indexes (already specified in Section 6) — do not skip these, PostGIS queries without them will not meet the sub-1s requirement under load.
- **Data integrity:** the API server (Dev A) is the only writer of `simulation_results.status = PENDING` rows; only Celery (Dev B) transitions them to `RUNNING`/`SUCCESS`/`FAILURE`. Never let both sides write the same column.
- **Offline resilience:** Category A tables must be fully loaded via a seed script before the demo; nothing in the "static geofence" read path may depend on network access at runtime.
- **Observability:** structured JSON logging on both `api` and `worker`; Celery task start/end/failure must be logged with `task_id`.

---

## 11. Suggested Build Order (for each developer)

**Dev A**
1. Postgres + PostGIS + TimescaleDB extensions up in Compose; write Alembic migrations for all tables in Section 6.
2. Seed script for Category A static data (dummy Chamoli geofences for dev).
3. FastAPI skeleton, JWT auth, `/auth/login`.
4. Ward + safe-haven read endpoints (prove PostGIS queries work).
5. `user_reports` CRUD + MinIO presigned upload flow.
6. `/simulate/flood` enqueue + poll endpoints (task_id can be a stub UUID until Dev B's worker exists — insert `PENDING` row and just poll it).
7. Verify-report endpoint + retraining task call.

**Dev B**
1. Redis + Celery app skeleton in `worker` container; confirm it can pick up a trivial `ping` task from `api`.
2. Load ML black-box model class at worker startup; implement `ml.run_inference` against a mocked sensor vector.
3. Implement `ml.contextualize_risk` (PostGIS spatial join against `wards`).
4. Implement `simulate.hydraulic_flood` (Rasterio + Shapely pipeline against `dem_tiles`).
5. Implement `advection.predict_storm_path` (GeoPy geodesic calc).
6. Build `scheduler` container (APScheduler): 15-min satellite poll, 1-min IoT poll, each enqueuing the tasks above.
7. Implement `retrain.ingest_verified_sample`.

**Integration checkpoint:** once both reach step 6/7, run full `docker-compose up` and walk through: citizen submits report → admin verifies → retraining task fires → admin triggers flood sim → polls until `SUCCESS` → sees GeoJSON.

---

## 12. Acceptance Criteria (Definition of Done)
- [ ] `docker-compose up` brings up all 6 services with no manual steps beyond `.env` setup and one seed script.
- [ ] Admin can log in and receive a JWT.
- [ ] Citizen can submit a geotagged report with a photo that lands in MinIO and is queryable via `/reports`.
- [ ] Admin can verify a report and see a corresponding row appear in `retraining_samples`.
- [ ] `POST /simulate/flood` returns a `task_id` within <200ms; polling `GET /simulate/flood/{task_id}` eventually returns `SUCCESS` with a valid GeoJSON polygon.
- [ ] `/wards` risk scores update automatically after the scheduler's 1-minute IoT poll cycle runs at least once, without any manual trigger.
- [ ] `/storm/latest-prediction` returns a non-null `predicted_next_point` after at least two satellite poll cycles.
- [ ] No FastAPI code imports `rasterio`, `shapely`, `geopy`, or the ML model class. No Celery task code imports FastAPI or issues JWTs.
