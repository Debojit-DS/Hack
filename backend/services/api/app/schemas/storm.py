from pydantic import BaseModel
from datetime import datetime

class StormPredictionResponse(BaseModel):
    obs_id: int
    lat: float | None = None
    lon: float | None = None
    predicted_lat: float | None = None
    predicted_lon: float | None = None
    predicted_for: datetime | None = None
    observed_at: datetime
