import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://meghdrishti_admin:changeme@postgres:5432/meghdrishti")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis;"))
session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis_raster;"))
session.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb;"))
session.commit()

wards = [
    ("Ward 1 - Chamoli Market", "ST_MakeEnvelope(79.55, 30.40, 79.65, 30.50, 4326)"),
    ("Ward 2 - Gopeshwar", "ST_MakeEnvelope(79.40, 30.35, 79.55, 30.45, 4326)"),
    ("Ward 3 - Nandprayag", "ST_MakeEnvelope(79.20, 30.30, 79.40, 30.42, 4326)"),
]

for name, wkt in wards:
    session.execute(
        text("INSERT INTO wards (name, ward_boundary) VALUES (:name, ST_GeomFromText(:wkt, 4326))"),
        {"name": name, "wkt": wkt},
    )

session.execute(
    text("""
    INSERT INTO safe_havens (name, type, capacity, coordinate)
    VALUES
      ('Chamoli Community Hall', 'shelter', 200, ST_SetSRID(ST_MakePoint(79.60, 30.45), 4326)),
      ('Gopeshwar Helipad', 'helipad', 10, ST_SetSRID(ST_MakePoint(79.48, 30.38), 4326)),
      ('Nandprayag Relief Center', 'shelter', 150, ST_SetSRID(ST_MakePoint(79.30, 30.36), 4326))
    ON CONFLICT DO NOTHING
    """),
)

session.execute(
    text("""
    INSERT INTO sensors (type, coord, ward_id)
    VALUES
      ('SoilMoisture', ST_SetSRID(ST_MakePoint(79.60, 30.45), 4326), 1),
      ('RainGauge', ST_SetSRID(ST_MakePoint(79.48, 30.38), 4326), 2),
      ('SoilMoisture', ST_SetSRID(ST_MakePoint(79.30, 30.36), 4326), 3)
    ON CONFLICT DO NOTHING
    """),
)

session.commit()
session.close()
print("Seed data inserted.")
