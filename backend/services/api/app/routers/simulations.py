import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert
from sqlalchemy.dialects.postgresql import UUID

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import Admin
from app.models.simulation_result import SimulationResult
from app.schemas.simulation import SimulationRequest, SimulationResponse
from app.celery_client import enqueue_simulation

router = APIRouter(prefix="/simulate", tags=["Simulations"])

@router.post("/flood", response_model=SimulationResponse, status_code=status.HTTP_202_ACCEPTED, summary="Trigger flood simulation")
async def simulate_flood(
    payload: SimulationRequest,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    task_id = str(uuid.uuid4())
    stmt = (
        insert(SimulationResult)
        .values(
            task_id=task_id,
            rainfall_mm_hr=payload.rainfall_mm_hr,
            status="PENDING",
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(stmt)
    await db.commit()

    try:
        enqueue_simulation(task_id=task_id, rainfall_mm_hr=payload.rainfall_mm_hr)
    except Exception as exc:
        print(f"Warning: Failed to enqueue simulation task: {exc}")

    return SimulationResponse(task_id=task_id, status="PENDING")

@router.get("/flood/{task_id}", response_model=SimulationResponse, summary="Poll simulation result")
async def get_simulation_result(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    result = (await db.execute(select(SimulationResult).where(SimulationResult.task_id == task_id))).scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=404, detail="Simulation task not found")
    return SimulationResponse(
        task_id=str(result.task_id),
        status=result.status,
    )
