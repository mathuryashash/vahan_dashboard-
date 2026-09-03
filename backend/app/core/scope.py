"""Geographic data-scoping for the access hierarchy (see UserScope in
app.models.models). Each helper is a drop-in FastAPI dependency: swap an
endpoint's `state: str | None = None` for `state: str | None =
Depends(get_effective_state)`, or a path param's plain type for
`Depends(require_state_code)` / `Depends(require_rto_code)`, and the
endpoint body needs no other change -- auth + clamping happen before the
route function ever runs.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.models import RTO, User, UserScope

_FORBIDDEN = HTTPException(status.HTTP_403_FORBIDDEN, detail="Not permitted to view this state/RTO")


async def get_effective_state(state: str | None = None, user: User = Depends(get_current_user)) -> str | None:
    """`state` is a state_name, as every dashboard filter already expects.
    National users pass through unchanged. State/RTO-scoped users get their
    own state forced in regardless of what they requested (or omitted) --
    silently narrowing, not erroring, since "no state given" from a scoped
    user means "show me my own state", not "show me everything"."""
    if user.scope_type == UserScope.NATIONAL:
        return state
    # Silently override rather than 403: the state dropdown is shared UI a
    # scoped user can still click through (it lists every state, not just
    # theirs -- see geo.py), and a hard error there would read as a bug, not
    # as access control. The data returned is clamped either way.
    return user.scope_state_name


def require_state_code(state_code: str, user: User = Depends(get_current_user)) -> str:
    """For endpoints where state_code is a required path/query param (e.g.
    listing RTOs for a state) -- unlike get_effective_state there's no
    "omitted" case to default, so a mismatch is a hard 403."""
    if user.scope_type != UserScope.NATIONAL and state_code != user.scope_state_code:
        raise _FORBIDDEN
    return state_code


async def require_rto_code(
    rto_code: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> str:
    if user.scope_type == UserScope.NATIONAL:
        return rto_code
    if user.scope_type == UserScope.RTO:
        if rto_code != user.scope_rto_code:
            raise _FORBIDDEN
        return rto_code
    # STATE-scoped: the RTO must belong to their own state. One indexed
    # lookup against the small `rtos` master table, not the registrations
    # table, so this stays cheap per request.
    owner_state = (await db.execute(select(RTO.state_code).where(RTO.rto_code == rto_code))).scalar()
    if owner_state != user.scope_state_code:
        raise _FORBIDDEN
    return rto_code


def enforce_state(user: User, state: str | None) -> str | None:
    """For endpoints with a required (not defaultable) state param, e.g.
    comparison.compare_states's state_a/state_b -- raises rather than
    substitutes, since silently swapping a caller-specified state_b would
    make the comparison meaningless rather than just narrower."""
    if state and user.scope_type != UserScope.NATIONAL and state != user.scope_state_name:
        raise _FORBIDDEN
    return state
