from datetime import datetime
from typing import Literal, List, Optional
from pydantic import BaseModel, Field

class ReportCreate(BaseModel):
    type: Literal["FlashFlood", "Blockage", "Other"]
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    photo_url: Optional[str] = None

class ReportResponse(BaseModel):
    report_id: int
    type: str
    lat: float
    lon: float
    photo_url: Optional[str] = None
    timestamp: datetime
    status: str

    class Config:
        from_attributes = True

class ReportListResponse(BaseModel):
    total: int
    items: List[ReportResponse]

class VerificationRequest(BaseModel):
    decision: Literal["Verified", "Rejected"]

class UploadUrlResponse(BaseModel):
    upload_url: str
    public_url: str