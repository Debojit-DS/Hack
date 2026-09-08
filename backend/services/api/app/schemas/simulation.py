from pydantic import BaseModel

class SimulationRequest(BaseModel):
    rainfall_mm_hr: float

class SimulationResponse(BaseModel):
    task_id: str
    status: str = "PENDING"
