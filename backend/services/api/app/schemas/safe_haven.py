from pydantic import BaseModel

class SafeHavenResponse(BaseModel):
    shelter_id: int
    name: str
    type: str
    capacity: int | None = None
    lat: float
    lon: float

    class Config:
        from_attributes = True
