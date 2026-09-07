import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from geoalchemy2.functions import ST_SetSRID, ST_MakePoint

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.admin import Admin
from app.models.user_report import UserReport
from app.schemas.user_report import (
    ReportCreate, ReportResponse, ReportListResponse,
    VerificationRequest, UploadUrlResponse
)
from app.minio_client import generate_presigned_upload_url
from app.celery_client import enqueue_retrain_ingest

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.get("/upload-url", response_model=UploadUrlResponse, summary="Get presigned upload URL for photo")
async def get_upload_url(filename: str = Query(...)):
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in ["jpg", "jpeg", "png", "webp"]:
        raise HTTPException(status_code=422, detail="Invalid image extension. Allowed: jpg, jpeg, png, webp")
    
    object_key = f"reports/{uuid.uuid4()}.{ext}"
    upload_url, public_url = generate_presigned_upload_url(object_key)
    return UploadUrlResponse(upload_url=upload_url, public_url=public_url)

@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED, summary="Submit citizen report")
async def create_report(payload: ReportCreate, db: AsyncSession = Depends(get_db)):
    point_geom = ST_SetSRID(ST_MakePoint(payload.lon, payload.lat), 4326)
    
    report = UserReport(
        type=payload.type,
        location=point_geom,
        photo_url=payload.photo_url,
        status="Unverified"
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    return ReportResponse(
        report_id=report.report_id,
        type=report.type,
        lat=payload.lat,
        lon=payload.lon,
        photo_url=report.photo_url,
        timestamp=report.timestamp,
        status=report.status
    )

@router.get("", response_model=ReportListResponse, summary="Get report queue (Admin)")
async def get_reports(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    stmt = select(
        UserReport,
        func.ST_Y(UserReport.location).label("lat"),
        func.ST_X(UserReport.location).label("lon")
    )
    if status_filter:
        stmt = stmt.where(UserReport.status == status_filter)
    
    count_stmt = select(func.count(UserReport.report_id))
    if status_filter:
        count_stmt = count_stmt.where(UserReport.status == status_filter)
    
    total = (await db.execute(count_stmt)).scalar() or 0
    
    stmt = stmt.order_by(UserReport.timestamp.desc()).limit(limit).offset(offset)
    results = (await db.execute(stmt)).all()
    
    items = [
        ReportResponse(
            report_id=r.report_id,
            type=r.type,
            lat=lat,
            lon=lon,
            photo_url=r.photo_url,
            timestamp=r.timestamp,
            status=r.status
        )
        for r, lat, lon in results
    ]
    return ReportListResponse(total=total, items=items)

@router.get("/{report_id}", response_model=ReportResponse, summary="Get single report details")
async def get_report_detail(
    report_id: int,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    stmt = select(
        UserReport,
        func.ST_Y(UserReport.location).label("lat"),
        func.ST_X(UserReport.location).label("lon")
    ).where(UserReport.report_id == report_id)
    
    result = (await db.execute(stmt)).first()
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    
    r, lat, lon = result
    return ReportResponse(
        report_id=r.report_id,
        type=r.type,
        lat=lat,
        lon=lon,
        photo_url=r.photo_url,
        timestamp=r.timestamp,
        status=r.status
    )

@router.patch("/{report_id}/verify", response_model=ReportResponse, summary="Verify/Reject a report")
async def verify_report(
    report_id: int,
    payload: VerificationRequest,
    db: AsyncSession = Depends(get_db),
    admin: Admin = Depends(get_current_admin)
):
    stmt = select(
        UserReport,
        func.ST_Y(UserReport.location).label("lat"),
        func.ST_X(UserReport.location).label("lon")
    ).where(UserReport.report_id == report_id)
    
    result = (await db.execute(stmt)).first()
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report, lat, lon = result
    if report.status != "Unverified":
        raise HTTPException(status_code=400, detail="Report has already been processed")
    
    report.status = payload.decision
    await db.commit()
    await db.refresh(report)

    if payload.decision == "Verified":
        enqueue_retrain_ingest(report.report_id)

    return ReportResponse(
        report_id=report.report_id,
        type=report.type,
        lat=lat,
        lon=lon,
        photo_url=report.photo_url,
        timestamp=report.timestamp,
        status=report.status
    )