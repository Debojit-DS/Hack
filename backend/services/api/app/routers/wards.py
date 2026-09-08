from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from geoalchemy2.functions import ST_Y, ST_X, ST_Contains

from app.database import get_db
from app.models.ward import Ward
from app.schemas.ward import WardResponse

router = APIRouter(prefix="/wards", tags=["Wards"])

@router.get("", response_model=List[WardResponse], summary="List wards with risk scores")
async def list_wards(db: AsyncSession = Depends(get_db)):
    stmt = select(Ward).order_by(Ward.ward_id)
    results = (await db.execute(stmt)).scalars().all()
    return [
        WardResponse(
            ward_id=w.ward_id,
            name=w.name,
            current_risk_score=w.current_risk_score,
            risk_updated_at=w.risk_updated_at.isoformat() if w.risk_updated_at else None,
        )
        for w in results
    ]

@router.get("/{ward_id}", response_model=WardResponse, summary="Get ward detail")
async def get_ward(ward_id: int, db: AsyncSession = Depends(get_db)):
    result = (await db.execute(select(Ward).where(Ward.ward_id == ward_id))).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Ward not found")
    return WardResponse(
        ward_id=result.ward_id,
        name=result.name,
        current_risk_score=result.current_risk_score,
        risk_updated_at=result.risk_updated_at.isoformat() if result.risk_updated_at else None,
    )
