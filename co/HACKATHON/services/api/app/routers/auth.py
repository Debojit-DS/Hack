from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.admin import Admin
from app.schemas.auth import LoginRequest, TokenResponse
from app.security import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse, summary="Admin Login")
async def login(credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Admin).where(Admin.email == credentials.email))
    admin = result.scalar_one_or_none()
    
    if not admin or not verify_password(credentials.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
        
    access_token = create_access_token(data={"sub": str(admin.admin_id), "email": admin.email, "role": admin.role})
    return TokenResponse(access_token=access_token)