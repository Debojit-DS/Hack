from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.config import settings
from app.database import get_db
from app.models.admin import Admin

security_scheme = HTTPBearer()

async def get_current_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db)
) -> Admin:
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        admin_id_str: str = payload.get("sub")
        role: str = payload.get("role")
        if admin_id_str is None or role != "admin":
            raise credentials_exception
        admin_uuid = uuid.UUID(admin_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    result = await db.execute(select(Admin).where(Admin.admin_id == admin_uuid))
    admin = result.scalar_one_or_none()
    if admin is None:
        raise credentials_exception
    return admin