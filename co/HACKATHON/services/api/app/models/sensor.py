from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geometry
from app.database import Base

class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    coord: Mapped[str] = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=False)
    ward_id: Mapped[int | None] = mapped_column(Integer, nullable=True)