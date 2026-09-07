from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.minio_client import init_minio_bucket
from app.routers import auth, reports, sensors

limiter = Limiter(key_func=get_remote_address, default_limits=["10/minute"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_minio_bucket()
    except Exception as e:
        print(f"MinIO initialization warning: {e}")
    yield

app = FastAPI(
    title="Meghdrishti Core API",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = [origin.strip() for origin in settings.CORS_ALLOW_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(sensors.router)