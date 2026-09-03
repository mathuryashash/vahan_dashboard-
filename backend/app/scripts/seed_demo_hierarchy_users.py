"""One-off: creates three demo accounts, one per scope tier, so the access
hierarchy can be clicked through in a browser (admin/analyst/viewer already
existed as roles -- this exercises the orthogonal scope_type dimension:
national/state/rto). Picks a real state and a real RTO within it from the
`states`/`rtos` master tables, so the state-head and RTO-head accounts are
actually scoped to data that exists.

Usage: python -m app.scripts.seed_demo_hierarchy_users
"""
import asyncio

from sqlalchemy import func, select

from app.core.auth import hash_password
from app.core.database import AsyncSessionLocal, init_db
from app.models.models import RTO, Registration, State, User, UserRole, UserScope

DEMO_PASSWORD = "Demo@12345"


async def _upsert(db, email: str, full_name: str, role: str, scope_type: str, **scope) -> User:
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        existing.full_name = full_name
        existing.role = role
        existing.scope_type = scope_type
        existing.scope_state_code = None
        existing.scope_state_name = None
        existing.scope_rto_code = None
        existing.scope_rto_name = None
        for k, v in scope.items():
            setattr(existing, k, v)
        existing.is_active = True
        return existing
    user = User(
        email=email, hashed_password=hash_password(DEMO_PASSWORD), full_name=full_name,
        role=role, scope_type=scope_type, **scope,
    )
    db.add(user)
    return user


async def main() -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        # Highest-volume state/RTO, not alphabetically-first -- picking e.g.
        # Andaman & Nicobar (real first alphabetically, near-zero volume)
        # would make the state/RTO demo accounts look broken (empty charts)
        # rather than showing off the actual drill-down.
        top_state_code = (
            await db.execute(
                select(Registration.state_code, func.sum(Registration.count).label("total"))
                .group_by(Registration.state_code).order_by(func.sum(Registration.count).desc()).limit(1)
            )
        ).first()
        state = None
        if top_state_code:
            state = (
                await db.execute(select(State).where(State.state_code == top_state_code[0]))
            ).scalar_one_or_none()
        if state is None:
            state = (await db.execute(select(State).order_by(State.state_name))).scalars().first()
        if state is None:
            print("No rows in `states` -- load seed data first (setup-native.sh / seed.sql.gz).")
            return

        top_rto_code = (
            await db.execute(
                select(Registration.rto_code, func.sum(Registration.count).label("total"))
                .where(Registration.state_code == state.state_code, Registration.rto_code.isnot(None))
                .group_by(Registration.rto_code).order_by(func.sum(Registration.count).desc()).limit(1)
            )
        ).first()
        rto = None
        if top_rto_code:
            rto = (await db.execute(select(RTO).where(RTO.rto_code == top_rto_code[0]))).scalar_one_or_none()
        if rto is None:
            rto = (
                await db.execute(select(RTO).where(RTO.state_code == state.state_code).order_by(RTO.rto_name))
            ).scalars().first()

        india_head = await _upsert(
            db, "india.head@vahan.demo", "India Head", UserRole.ADMIN, UserScope.NATIONAL,
        )
        state_head = await _upsert(
            db, "state.head@vahan.demo", f"{state.state_name} State Head", UserRole.ANALYST, UserScope.STATE,
            scope_state_code=state.state_code, scope_state_name=state.state_name,
        )
        rto_users = None
        if rto is not None:
            rto_users = await _upsert(
                db, "rto.head@vahan.demo", f"{rto.rto_name} RTO Head", UserRole.VIEWER, UserScope.RTO,
                scope_state_code=state.state_code, scope_state_name=state.state_name,
                scope_rto_code=rto.rto_code, scope_rto_name=rto.rto_name,
            )

        await db.commit()

        print(f"Password for all three: {DEMO_PASSWORD}\n")
        print(f"  india.head@vahan.demo  -- national admin, sees every state, can drill to any RTO")
        print(f"  state.head@vahan.demo  -- state analyst, locked to {state.state_name}")
        if rto_users is not None:
            print(f"  rto.head@vahan.demo    -- RTO viewer, locked to {rto.rto_name} ({state.state_name})")
        else:
            print("  rto.head@vahan.demo    -- skipped, no RTO rows found for that state")


if __name__ == "__main__":
    asyncio.run(main())
