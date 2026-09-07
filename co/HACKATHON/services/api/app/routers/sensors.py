from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import Admin
from app.models.sensor import Sensor
from app.models.sensor_reading import SensorReading
from app.schemas.sensor import SensorResponse, SensorReadingResponse, SensorReadingsListResponse

router = APIRouter(prefix="/sensors", tags=["Sensors"])

@router.get("", response_model=list[SensorResponse], summary="List sensors metadata")
async def list_sensors(
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    stmt = select(
        Sensor,
        func.ST_Y(Sensor.coord).label("lat"),
        func.ST_X(Sensor.coord).label("lon")
    )
    results = (await db.execute(stmt)).all()
    
    return [
        SensorResponse(
            sensor_id=s.sensor_id,
            type=s.type,
            lat=lat,
            lon=lon,
            ward_id=s.ward_id
        )
        for s, lat, lon in results
    ]

@router.get("/{sensor_id}/readings", response_model=SensorReadingsListResponse, summary="Get sensor readings")
async def get_sensor_readings(
    sensor_id: int,
    since: Optional[datetime] = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    sensor_exists = (await db.execute(select(Sensor.sensor_id).where(Sensor.sensor_id == sensor_id))).scalar_one_or_none()
    if not sensor_exists:
        raise HTTPException(status_code=404, detail="Sensor not found")

    if not since:
        since = datetime.now(timezone.utc) - timedelta(hours=24)

    stmt = select(SensorReading).where(
        SensorReading.sensor_id == sensor_id,
        SensorReading.timestamp >= since
    ).order_by(SensorReading.timestamp.desc()).limit(limit)

    readings = (await db.execute(stmt)).scalars().all()

    return SensorReadingsListResponse(
        sensor_id=sensor_id,
        readings=[SensorReadingResponse.model_validate(r) for r in readings]
    )