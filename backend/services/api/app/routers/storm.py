from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from geoalchemy2.functions import ST_Y, ST_X

from app.database import get_db
from app.models.storm_observation import StormObservation
from app.schemas.storm import StormPredictionResponse

router = APIRouter(prefix="/storm", tags=["Storm"])

@router.get("/latest-prediction", response_model=StormPredictionResponse, summary="Get latest storm prediction")
async def get_latest_storm_prediction(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(
            StormObservation,
            ST_Y(StormObservation.center_point).label("lat"),
            ST_X(StormObservation.center_point).label("lon"),
            ST_Y(StormObservation.predicted_next_point).label("predicted_lat"),
            ST_X(StormObservation.predicted_next_point).label("predicted_lon"),
        )
        .where(StormObservation.predicted_next_point.is_not(None))
        .order_by(StormObservation.observed_at.desc())
        .limit(1)
    )
    result = (await db.execute(stmt)).first()
    if not result:
        raise HTTPException(status_code=404, detail="No storm prediction available yet")
    obs, lat, lon, pred_lat, pred_lon = result
    return StormPredictionResponse(
        obs_id=obs.obs_id,
        lat=lat,
        lon=lon,
        predicted_lat=pred_lat,
        predicted_lon=pred_lon,
        predicted_for=obs.predicted_for,
        observed_at=obs.observed_at,
    )
