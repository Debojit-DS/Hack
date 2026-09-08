from pydantic import BaseModel

class WardResponse(BaseModel):
    ward_id: int
    name: str
    current_risk_score: float | None = None
    risk_updated_at: str | None = None

    class Config:
        from_attributes = True
