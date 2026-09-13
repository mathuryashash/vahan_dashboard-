"""Admin-only company/billing-tracking CRUD. Organizations are a label on
User for seat counting -- NOT a data-isolation boundary (see Organization's
docstring in models.py). No payment gateway wired in yet; this exists so an
admin can see "how many users for company X" without a manual DB query."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_role
from app.core.database import get_db
from app.models.models import Organization, User, UserRole
from app.schemas.schemas import OrganizationOut

router = APIRouter()


class OrganizationCreate(BaseModel):
    name: str


class OrganizationUpdate(BaseModel):
    is_active: bool | None = None


@router.get("/", response_model=list[OrganizationOut])
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    result = await db.execute(
        select(Organization, func.count(User.id))
        .outerjoin(User, User.organization_id == Organization.id)
        .group_by(Organization.id)
        .order_by(Organization.name)
    )
    return [
        {"id": org.id, "name": org.name, "is_active": org.is_active, "user_count": count}
        for org, count in result.all()
    ]


@router.post("/", response_model=OrganizationOut)
async def create_organization(
    payload: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    existing = (await db.execute(select(Organization).where(Organization.name == payload.name))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=400, detail="An organization with this name already exists")

    org = Organization(name=payload.name)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return {"id": org.id, "name": org.name, "is_active": org.is_active, "user_count": 0}


@router.patch("/{organization_id}", response_model=OrganizationOut)
async def update_organization(
    organization_id: int,
    payload: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
):
    org = (await db.execute(select(Organization).where(Organization.id == organization_id))).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    if payload.is_active is not None:
        org.is_active = payload.is_active
    await db.commit()

    count = (await db.execute(
        select(func.count(User.id)).where(User.organization_id == organization_id)
    )).scalar()
    return {"id": org.id, "name": org.name, "is_active": org.is_active, "user_count": count}
