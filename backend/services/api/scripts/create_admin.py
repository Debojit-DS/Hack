import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import AsyncSessionLocal
from app.models.admin import Admin
from app.security import get_password_hash
from sqlalchemy import select

async def create_default_admin():
    async with AsyncSessionLocal() as db:
        email = "admin@meghdrishti.org"
        result = await db.execute(select(Admin).where(Admin.email == email))
        if result.scalar_one_or_none():
            print(f"Admin {email} already exists.")
            return

        admin = Admin(
            email=email,
            password_hash=get_password_hash("changeme123"),
            role="admin"
        )
        db.add(admin)
        await db.commit()
        print(f"Admin account created: {email} / changeme123")

if __name__ == "__main__":
    asyncio.run(create_default_admin())