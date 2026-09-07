# Developer A Build Spec — Core API, Data & Object Storage Layer
## Meghdrishti Backend — Standalone Implementation Spec

**Companion document to:** `meghdrishti-backend-prd.md` (master PRD)
**This document covers:** Service 1 (Core API), Category B & C database tables, MinIO object storage, the Verification Loop.
**Owned by:** Developer A only.
**Must be buildable and fully testable in isolation** — i.e. without Developer B's `worker`/`scheduler` containers existing yet. Every place this service needs to talk to Dev B's future code, this spec tells you to call a **named stub** so the contract is frozen now and nothing needs to change later.

> **Rule for the implementer:** Do not invent table names, column names, endpoint paths, JWT claims, or Celery task names that differ from this document. Every name here is taken verbatim from the master PRD so this service will merge into the full system without modification. If something feels ambiguous, follow this document's explicit choice rather than guessing.

---

## 1. Scope

### 1.1 In scope for this build
- FastAPI application (`api` service) — the single HTTP entry point for both the Next.js Admin dashboard and the Next.js Citizen PWA.
- JWT authentication for Admins.
- CRUD endpoints for `user_reports`.
- MinIO object storage integration for report photos.
- Database schema + Alembic migrations for: `admins`, `sensors`, `sensor_readings` (Category B), `user_reports` (Category C).
- The full Verification Loop: citizen submits `Unverified` report → admin dashboard polls the queue → admin verifies → status flips to `Verified` → a retraining hook fires.

### 1.2 Explicitly out of scope for this build (Developer B's job — do not implement)
- Anything involving Celery workers, Redis, APScheduler, Rasterio, Shapely, GeoPy, or the ML model.
- The `dem_tiles`, `wards`, `safe_havens` tables (Category A) — these belong to the master schema but are **not** built by this developer in this task; treat any endpoint that would need them (e.g. "nearest safe haven") as **not part of this deliverable**.
- Flood simulation endpoints, storm prediction endpoints, per-ward risk scores.
- Do not import `rasterio`, `shapely`, `geopy`, `celery` worker task bodies, or the ML class into this codebase. This service should have **zero Python dependency** on Dev B's code — the only shared dependency is the Postgres database itself and (optionally) the `celery` client library used purely to *enqueue* a task by name/string.

---

## 2. Tech Stack (exact versions to pin)

| Component | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Web framework | FastAPI | async, use `uvicorn` as the ASGI server |
| ORM / DB access | SQLAlchemy 2.x (async) + Alembic for migrations | Do not use a second ORM |
| Validation | Pydantic v2 | every request/response body is a Pydantic model, no raw dicts |
| Auth | `python-jose` (JWT) + `passlib[bcrypt]` (password hashing) | |
| DB driver | `asyncpg` | |
| Geometry handling | `geoalchemy2` (for reading/writing `GEOMETRY(POINT, 4326)` columns only — this is not "GIS math", just column typing) | |
| Object storage client | `minio` (official Python MinIO SDK) | |
| Task enqueue client | `celery` (client-only usage — `send_task`, never define a task body here) | |
| Testing | `pytest` + `httpx.AsyncClient` | |
| Server | `uvicorn[standard]` run inside the `api` Docker container | |

---

## 3. Project Structure

```
/services/api
  Dockerfile
  requirements.txt
  alembic.ini
  /migrations
    /versions
  /app
    main.py                 # FastAPI app instantiation, router includes, CORS, startup
    config.py                # Pydantic Settings, reads env vars
    database.py               # async SQLAlchemy engine/session
    security.py               # JWT create/verify, password hashing
    dependencies.py           # get_db, get_current_admin
    celery_client.py          # thin Celery client (send_task only)
    minio_client.py           # MinIO client wrapper, presigned URL helper
    /models                   # SQLAlchemy ORM models
      admin.py
      sensor.py
      sensor_reading.py
      user_report.py
    /schemas                  # Pydantic request/response models
      auth.py
      user_report.py
      sensor.py
    /routers
      auth.py                 # /auth/login
      reports.py               # /reports/* endpoints
      sensors.py                # /sensors/* read endpoints (metadata only)
    /services                  # business logic, kept out of routers
      report_service.py
      storage_service.py
  /tests
    test_auth.py
    test_reports.py
    test_verification.py
```

---

## 4. Environment Variables

Use exactly these names (they must match the shared `.env` in the master PRD):

```
DATABASE_URL=postgresql+asyncpg://meghdrishti_admin:changeme@postgres:5432/meghdrishti

MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=changeme
MINIO_BUCKET=meghdrishti-reports
MINIO_USE_SSL=false

JWT_SECRET=changeme
JWT_ALGORITHM=HS256
JWT_EXPIRY_HOURS=24

CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

CORS_ALLOW_ORIGINS=http://localhost:3000,http://localhost:3001
```

Load these via a Pydantic `Settings` class in `config.py` (`pydantic-settings`), never via bare `os.environ.get()` scattered through the code.

---

## 5. Database Schema — This Developer's Tables Only

These are the **exact** table definitions this developer is responsible for creating via Alembic migrations. Do not deviate from column names/types — Developer B's worker code will read/write some of these columns later.

### 5.1 `admins` (auth — needed for this build even though not explicitly in Category B/C, since login requires it)
```sql
CREATE TABLE admins (
    admin_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'admin',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```
Seed one admin row via a one-off script (`scripts/create_admin.py`) — do not build a public "register admin" endpoint; admin accounts are provisioned out-of-band for this phase.

### 5.2 Category B — Dynamic Timeseries Sensors
```sql
CREATE TABLE sensors (
    sensor_id  SERIAL PRIMARY KEY,
    type       TEXT NOT NULL,               -- 'SoilMoisture' | 'RainGauge'
    coord      GEOMETRY(POINT, 4326) NOT NULL,
    ward_id    INTEGER                       -- FK to wards(ward_id); wards table doesn't exist in this build, so DO NOT add a foreign-key constraint yet — leave as a plain nullable INTEGER column. Developer responsible for Category A will add the FK constraint in a later migration.
);
CREATE INDEX idx_sensors_coord ON sensors USING GIST (coord);

CREATE TABLE sensor_readings (
    reading_id SERIAL,
    sensor_id  INTEGER NOT NULL REFERENCES sensors(sensor_id),
    value      DOUBLE PRECISION NOT NULL,
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_score DOUBLE PRECISION             -- nullable; this column is written later by Developer B's ml.run_inference Celery task, not by this service. This service only ever reads it (for the GET /sensors/{id}/readings endpoint), never writes it.
);
SELECT create_hypertable('sensor_readings', 'timestamp');
CREATE INDEX idx_sensor_readings_sensor_time ON sensor_readings (sensor_id, timestamp DESC);
```
This developer does **not** need to write anything that inserts rows into `sensor_readings` (that's the scheduler's job) — only read endpoints against it (Section 7.4). For local testing, write a small seed script that inserts a handful of fake readings so the read endpoint is testable in isolation.

### 5.3 Category C — Crowdsourced Validation
```sql
CREATE TABLE user_reports (
    report_id   SERIAL PRIMARY KEY,
    type        TEXT NOT NULL,               -- 'FlashFlood' | 'Blockage' | 'Other'
    location    GEOMETRY(POINT, 4326) NOT NULL,
    photo_url   TEXT,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    status      TEXT NOT NULL DEFAULT 'Unverified'   -- 'Unverified' | 'Verified' | 'Rejected'
);
CREATE INDEX idx_user_reports_location ON user_reports USING GIST (location);
```

### 5.4 Table this developer must NOT create
`retraining_samples` — this table belongs to Developer B's schema ownership scope in the master PRD (it's written to by the `retrain.ingest_verified_sample` Celery task). This service only ever **triggers** that task by name (Section 8) — it never writes to that table directly.

---

## 6. Authentication Spec

### 6.1 `POST /auth/login`
**Request body:**
```json
{ "email": "admin@meghdrishti.org", "password": "plaintext-password" }
```
**Behavior:**
1. Look up `admins` by `email`.
2. Verify password with `passlib` bcrypt against `password_hash`.
3. If invalid → `401 Unauthorized`, body `{"detail": "Invalid credentials"}`.
4. If valid → issue a JWT.

**JWT claims (exact keys):**
```json
{
  "sub": "<admin_id as string>",
  "email": "<admin email>",
  "role": "admin",
  "exp": <unix timestamp, now + JWT_EXPIRY_HOURS>
}
```
**Response `200`:**
```json
{ "access_token": "<jwt>", "token_type": "bearer" }
```

### 6.2 Auth dependency
Implement `get_current_admin` in `dependencies.py`:
- Reads `Authorization: Bearer <token>` header.
- Decodes with `JWT_SECRET`/`JWT_ALGORITHM`.
- On any failure (missing header, expired, bad signature) → `401 Unauthorized`.
- On success, loads the `admins` row by `sub` and returns it; raise `401` if the admin no longer exists.
- Apply this dependency to every endpoint marked "Admin JWT" in Section 7.

### 6.3 Citizen "auth"
Citizens do **not** log in. Citizen-facing endpoints (`POST /reports`, `GET /reports/upload-url`) are public but must be rate-limited per client. Implement a simple in-memory or Redis-backed sliding-window limiter keyed on the client's IP address (or an `X-Device-Id` header if the frontend sends one) — e.g. max 10 requests/minute. Use `slowapi` (FastAPI-compatible) for this rather than hand-rolling it.

---

## 7. API Endpoint Spec (exact contracts)

All responses are JSON. All error responses use FastAPI's default `{"detail": "..."}` shape unless stated otherwise. All endpoints must appear correctly in the auto-generated `/docs` (OpenAPI) — give every route a `summary`, `response_model`, and explicit status codes.

### 7.1 `POST /reports` — Citizen submits a report
**Auth:** none (rate-limited, see 6.3)
**Request body (`application/json`):**
```json
{
  "type": "FlashFlood",
  "lat": 30.4167,
  "lon": 79.6667,
  "photo_url": "https://minio.../meghdrishti-reports/reports/uuid.jpg"
}
```
- `type` — required, must be one of `["FlashFlood", "Blockage", "Other"]`. Reject with `422` otherwise (let Pydantic's `Literal` type handle this).
- `lat`/`lon` — required floats, validate `-90 <= lat <= 90` and `-180 <= lon <= 180`.
- `photo_url` — optional string. This is the URL the client got back from `GET /reports/upload-url` (Section 8) after uploading directly to MinIO — **this endpoint does not receive the raw image bytes.**

**Behavior:**
1. Build a PostGIS point from `lat`/`lon`: `ST_SetSRID(ST_MakePoint(lon, lat), 4326)`. (Note: PostGIS point order is `(lon, lat)`.)
2. Insert into `user_reports` with `status='Unverified'`.
3. Return `201`.

**Response `201`:**
```json
{
  "report_id": 42,
  "type": "FlashFlood",
  "lat": 30.4167,
  "lon": 79.6667,
  "photo_url": "https://minio.../reports/uuid.jpg",
  "timestamp": "2026-09-07T12:00:00Z",
  "status": "Unverified"
}
```

### 7.2 `GET /reports` — Admin queue
**Auth:** Admin JWT required
**Query params:** `status` (optional, one of `Unverified|Verified|Rejected`; default returns all), `limit` (default 50, max 200), `offset` (default 0)
**Behavior:** `SELECT ... FROM user_reports WHERE (:status IS NULL OR status = :status) ORDER BY timestamp DESC LIMIT :limit OFFSET :offset`
**Response `200`:** array of the same report object shape as 7.1's response, plus a wrapping `{"total": <int>, "items": [...]}` so the Admin dashboard can paginate.

### 7.3 `GET /reports/{report_id}` — Single report detail
**Auth:** Admin JWT required
**Response `200`:** single report object. `404` if not found.

### 7.4 `PATCH /reports/{report_id}/verify` — The Verification Loop endpoint
**Auth:** Admin JWT required
**Request body:**
```json
{ "decision": "Verified" }
```
- `decision` must be `"Verified"` or `"Rejected"` (Pydantic `Literal`).

**Behavior (exact sequence — do not reorder):**
1. Fetch the report; `404` if missing.
2. `400` if the report's current `status` is not `"Unverified"` (a report can only be actioned once — prevents double-firing the retraining hook).
3. `UPDATE user_reports SET status = :decision WHERE report_id = :report_id`.
4. **Only if `decision == "Verified"`:** enqueue the retraining task (Section 8.1). If `decision == "Rejected"`, do not enqueue anything.
5. Commit the DB transaction **before** enqueuing the Celery task (so a Celery/Redis outage never blocks or rolls back the verification itself — log a warning and continue if the enqueue call throws).
6. Return `200` with the updated report object.

**Response `200`:** updated report object (same shape as 7.1).

### 7.5 `GET /reports/upload-url` — MinIO presigned upload
**Auth:** none (public — citizens need this before they've submitted anything)
**Query params:** `filename` (required, e.g. `flood1.jpg`), used only to derive a file extension; the actual object key is server-generated.
**Behavior:**
1. Generate a UUID-based object key: `reports/{uuid4()}.{ext}`, where `{ext}` is taken from `filename` (validate it's one of `jpg|jpeg|png|webp`, else `422`).
2. Ask MinIO for a presigned `PUT` URL for that key, expiring in e.g. 15 minutes.
3. Compute the **public** URL the frontend should store/reference later (`http(s)://<MINIO_ENDPOINT>/<MINIO_BUCKET>/<key>`).

**Response `200`:**
```json
{
  "upload_url": "http://minio:9000/meghdrishti-reports/reports/<uuid>.jpg?X-Amz-...",
  "public_url": "http://minio:9000/meghdrishti-reports/reports/<uuid>.jpg"
}
```
**Client flow (for the frontend team's reference, not something you build):** frontend calls this → does a raw `PUT` of the image bytes directly to `upload_url` → then calls `POST /reports` with `photo_url = public_url`. This backend service never touches raw image bytes — it only ever brokers presigned URLs. This keeps the FastAPI process from ever handling large multipart uploads directly.

### 7.6 `GET /sensors/{sensor_id}/readings` — read-only, Category B
**Auth:** Admin JWT required
**Query params:** `since` (optional ISO8601 timestamp, default = last 24h), `limit` (default 500)
**Behavior:** `SELECT reading_id, value, timestamp, risk_score FROM sensor_readings WHERE sensor_id = :id AND timestamp >= :since ORDER BY timestamp DESC LIMIT :limit`. `404` if the `sensor_id` doesn't exist in `sensors`.
**Response `200`:**
```json
{
  "sensor_id": 3,
  "readings": [
    {"reading_id": 101, "value": 42.1, "timestamp": "2026-09-07T11:59:00Z", "risk_score": 0.12},
    {"reading_id": 100, "value": 41.8, "timestamp": "2026-09-07T11:58:00Z", "risk_score": null}
  ]
}
```
Note `risk_score` will legitimately be `null` for most rows in this standalone build, since nothing populates it yet — that's expected and correct; don't treat it as a bug.

### 7.7 `GET /sensors` — list sensor metadata
**Auth:** Admin JWT required
**Response `200`:** array of `{sensor_id, type, lat, lon, ward_id}`. Straightforward CRUD-style read; no write endpoint needed for sensors in this build (sensor provisioning is out of scope — seed a handful manually for testing).

---

## 8. Integration Stub: Enqueuing Developer B's Celery Task

This service must be able to trigger the retraining pipeline **without importing any of Developer B's code**. Do this with the Celery *client* only:

```python
# app/celery_client.py
from celery import Celery
from app.config import settings

celery_app = Celery(broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)

def enqueue_retrain_ingest(report_id: int) -> None:
    celery_app.send_task(
        "retrain.ingest_verified_sample",
        kwargs={"report_id": report_id},
    )
```

### 8.1 Exact contract (must match master PRD Section 7.3 verbatim)
| Task name (string) | Kwargs | Called from |
|---|---|---|
| `retrain.ingest_verified_sample` | `{"report_id": <int>}` | `PATCH /reports/{report_id}/verify`, only when `decision == "Verified"` |

**Do not implement the body of this task.** Developer B owns it. If you run this service before Developer B's `worker` container exists, `send_task` will simply enqueue a message into Redis that sits unconsumed — this is expected and fine; it does not block or error the API request. To verify locally without Developer B's code, you may optionally register a **temporary fake consumer** in a test file only (never in `app/`) that logs the payload, purely to confirm the enqueue call fires correctly — delete it before merging.

---

## 9. MinIO Setup Details

- On service startup (`app/main.py` startup event), check if `MINIO_BUCKET` exists; if not, create it and set a bucket policy allowing public `GET` (read) on objects but not `LIST` — citizens' browsers need to read photos back but should not be able to list the whole bucket.
- Use path-style addressing (`http://minio:9000/<bucket>/<key>`), not virtual-hosted-style, since this is a self-hosted MinIO instance without wildcard DNS.
- Presigned PUT URLs: use the MinIO SDK's `presigned_put_object(bucket, object_name, expires=timedelta(minutes=15))`.

---

## 10. Validation & Error Handling Rules

- Every request body is a Pydantic model with explicit types — no accepting arbitrary JSON.
- Return `422` (FastAPI default) for schema validation failures — do not hand-write these.
- Return `401` for missing/invalid/expired JWT on protected routes.
- Return `403` if a valid JWT is presented but the `role` claim isn't `admin` (future-proofing even though only one role exists today).
- Return `404` with `{"detail": "Report not found"}` style messages for missing resources — never leak stack traces or SQL errors to the client; catch `SQLAlchemyError` at a global exception handler and return `500` with a generic message, while logging the real exception server-side.
- Wrap all multi-statement operations (e.g., verify-then-enqueue) in a single DB transaction (Section 7.4, step 5 already specifies the exact commit ordering — follow it precisely).

---

## 11. Dockerfile (reference)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

This must match the `api` service block already defined in the master PRD's `docker-compose.yaml` — do not rename the container, do not change the exposed port (`8000`), do not change the `depends_on` list (`postgres`, `redis`, `minio`).

---

## 12. Testing Requirements (must pass before calling this "done")

Using `pytest` + `httpx.AsyncClient` against a test Postgres/MinIO (docker-compose test overrides, or `testcontainers`):

1. `test_auth.py`
   - Valid login returns a JWT; wrong password returns `401`.
   - Protected route without a token returns `401`; with an expired token returns `401`.
2. `test_reports.py`
   - `POST /reports` with valid body → `201`, row exists in DB with `status='Unverified'`.
   - `POST /reports` with out-of-range lat/lon → `422`.
   - `GET /reports/upload-url` returns a `upload_url` and `public_url` that differ only by query string.
3. `test_verification.py`
   - Full loop: create report → `GET /reports?status=Unverified` shows it → `PATCH .../verify` with `"Verified"` → row status flips → a second `PATCH .../verify` call on the same report returns `400` (already actioned).
   - Assert `celery_app.send_task` was called exactly once with `("retrain.ingest_verified_sample", kwargs={"report_id": <id>})` — use `unittest.mock.patch` on `celery_app.send_task`, do not require a real Redis/Celery worker to be running for this test.
   - `PATCH .../verify` with `"Rejected"` → status flips to `Rejected`, `send_task` is **not** called.

---

## 13. Acceptance Criteria — This Deliverable Only

- [ ] `docker-compose up postgres minio api` (no worker/scheduler needed) brings up a fully functional service.
- [ ] Alembic migration creates `admins`, `sensors`, `sensor_readings`, `user_reports` with the exact schema in Section 5.
- [ ] `/docs` shows all endpoints from Section 7 with correct request/response schemas.
- [ ] A citizen can: request an upload URL → PUT a real image to MinIO → submit a report referencing that photo → the photo is fetchable via its public URL.
- [ ] An admin can: log in → see the report in the `Unverified` queue → verify it → see it disappear from the `Unverified` filter and appear under `Verified`.
- [ ] The verify action provably calls `send_task("retrain.ingest_verified_sample", ...)` (visible in Redis via `redis-cli` even with no worker consuming it, or via the mocked test in Section 12).
- [ ] No file under `app/` imports `rasterio`, `shapely`, `geopy`, or anything from a `worker`/`scheduler` package.
