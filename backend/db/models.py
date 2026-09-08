from sqlalchemy import Column, Integer, Float, String, Text, TIMESTAMP, ForeignKey, UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import declarative_base
from geoalchemy2 import Geometry

Base = declarative_base()


class Admin(Base):
    __tablename__ = "admins"
    admin_id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="admin")
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())


class DemTile(Base):
    __tablename__ = "dem_tiles"
    tile_id = Column(Integer, primary_key=True, autoincrement=True)
    rast_geometry = Column(Geometry("RASTER", srid=4326), nullable=False)


class Ward(Base):
    __tablename__ = "wards"
    ward_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    ward_boundary = Column(Geometry("POLYGON", srid=4326), nullable=False)
    current_risk_score = Column(Float)
    risk_updated_at = Column(TIMESTAMP)


class SafeHaven(Base):
    __tablename__ = "safe_havens"
    shelter_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    capacity = Column(Integer)
    coordinate = Column(Geometry("POINT", srid=4326), nullable=False)


class Sensor(Base):
    __tablename__ = "sensors"
    sensor_id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    coord = Column(Geometry("POINT", srid=4326), nullable=False)
    ward_id = Column(Integer, ForeignKey("wards.ward_id"))


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    reading_id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(Integer, ForeignKey("sensors.sensor_id"), nullable=False)
    value = Column(Float, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())
    risk_score = Column(Float)


class UserReport(Base):
    __tablename__ = "user_reports"
    report_id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String, nullable=False)
    location = Column(Geometry("POINT", srid=4326), nullable=False)
    photo_url = Column(String)
    timestamp = Column(TIMESTAMP, nullable=False, server_default=func.now())
    status = Column(String, nullable=False, default="Unverified")


class StormObservation(Base):
    __tablename__ = "storm_observations"
    obs_id = Column(Integer, primary_key=True, autoincrement=True)
    center_point = Column(Geometry("POINT", srid=4326), nullable=False)
    observed_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    predicted_next_point = Column(Geometry("POINT", srid=4326))
    predicted_for = Column(TIMESTAMP)


class SimulationResult(Base):
    __tablename__ = "simulation_results"
    task_id = Column(UUID, primary_key=True)
    rainfall_mm_hr = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    result_geojson = Column(JSONB)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
    completed_at = Column(TIMESTAMP)


class Alert(Base):
    __tablename__ = "alerts"
    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    ward_id = Column(Integer, ForeignKey("wards.ward_id"))
    risk_score = Column(Float, nullable=False)
    message = Column(Text)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())


class RetrainingSample(Base):
    __tablename__ = "retraining_samples"
    sample_id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("user_reports.report_id"))
    ingested_at = Column(TIMESTAMP, nullable=False, server_default=func.now())
