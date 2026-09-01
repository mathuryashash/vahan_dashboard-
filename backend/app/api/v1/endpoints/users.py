"""Admin-only user management -- there's no self-registration. An admin
creates every account (via this API or app/scripts/create_admin.py for the
very first one) and assigns its role."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_password, require_role
from app.core.database import get_db
from app.models.models import User, UserRole

router = APIRouter()


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str | None = None
    role: str = UserRole.VIEWER


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None


def _serialize(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at,
    }


@router.get("/")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(select(User).order_by(User.email))
    return [_serialize(u) for u in result.scalars().all()]


@router.post("/")
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    if payload.role not in UserRole.ALL:
        raise HTTPException(status_code=400, detail=f"role must be one of {UserRole.ALL}")
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _serialize(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.role is not None:
        if payload.role not in UserRole.ALL:
            raise HTTPException(status_code=400, detail=f"role must be one of {UserRole.ALL}")
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await db.commit()
    return _serialize(user)
