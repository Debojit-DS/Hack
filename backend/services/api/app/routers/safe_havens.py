from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from geoalchemy2.functions import ST_Y, ST_X, ST_Distance, ST_SetSRID, ST_MakePoint

from app.database import get_db
from app.models.safe_haven import SafeHaven
from app.schemas.safe_haven import SafeHavenResponse

router = APIRouter(prefix="/safe-havens", tags=["Safe Havens"])

@router.get("/nearest", response_model=SafeHavenResponse, summary="Find nearest safe haven")
async def get_nearest_safe_haven(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
):
    point = ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    stmt = (
        select(
            SafeHaven,
            ST_Y(SafeHaven.coordinate).label("lat"),
            ST_X(SafeHaven.coordinate).label("lon"),
            ST_Distance(SafeHaven.coordinate, point).label("distance"),
        )
        .order_by(func.ST_Distance(SafeHaven.coordinate, point))
        .limit(1)
    )
    result = (await db.execute(stmt)).first()
    if not result:
        raise HTTPException(status_code=404, detail="No safe havens found")
    haven, lat_val, lon_val, _ = result
    return SafeHavenResponse(
        shelter_id=haven.shelter_id,
        name=haven.name,
        type=haven.type,
        capacity=haven.capacity,
        lat=lat_val,
        lon=lon_val,
    )
