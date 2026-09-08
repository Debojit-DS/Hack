from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

class SensorResponse(BaseModel):
    sensor_id: int
    type: str
    lat: float
    lon: float
    ward_id: Optional[int] = None

    class Config:
        from_attributes = True

class SensorReadingResponse(BaseModel):
    reading_id: int
    value: float
    timestamp: datetime
    risk_score: Optional[float] = None

    class Config:
        from_attributes = True

class SensorReadingsListResponse(BaseModel):
    sensor_id: int
    readings: List[SensorReadingResponse]