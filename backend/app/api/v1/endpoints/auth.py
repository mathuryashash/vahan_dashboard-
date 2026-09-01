from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import create_access_token, get_current_user, verify_password
from app.core.database import get_db
from app.models.models import User

router = APIRouter()


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """OAuth2PasswordRequestForm expects `username` + `password` fields
    (standard OAuth2 field names) -- `username` is the user's email here,
    there's no separate username concept."""
    user = (await db.execute(select(User).where(User.email == form.username))).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    # users.last_login_at is TIMESTAMP WITHOUT TIME ZONE (matches every
    # other datetime column in this schema) -- strip tzinfo rather than
    # hand asyncpg a tz-aware value it'll reject outright.
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    token = create_access_token(user.id, user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "email": user.email,
        "full_name": user.full_name,
    }


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}
