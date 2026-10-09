"""Round 5: the round-4 DDL constraints live in models.py, so a fresh DB (CI,
Docker, a restore) gets the same schema as prod, and ensure_declared_constraints
retrofits an existing DB that lacks one. Also pins ux_reg_natural as a real
NULLS NOT DISTINCT constraint (NULL maker / fuel duplicates rejected).
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.database import Base
from app.core.migrations import ensure_declared_constraints
from app.models.models import RTO, Registration, State
from tests.conftest import TEST_DATABASE_URL

# The 21 constraints the live DB carries from the round-4 DDL (pg_constraint,
# 2026-10-09). Adding one to the live DB means adding it here AND in models.py.
EXPECTED = {
    "ck_reg_pass_shape", "ck_reg_count", "ck_reg_month", "ck_reg_year",
    "ck_mct_count", "ck_mct_year", "ck_fct_count", "ck_fct_year", "ck_mft_count", "ck_mft_year",
    "ck_mlqc_count", "ck_mlqc_month", "ck_smct_count", "ck_smct_month", "ck_smcft_count", "ck_smcft_month",
    "fk_registrations_state_code_name", "fk_maker_category_totals_state_code_name",
    "fk_fuel_category_totals_state_code_name", "fk_maker_fuel_totals_state_code_name",
    "uq_states_code_name",
}
NAMED = "SELECT conname FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND conname ~ '^(ck|fk|uq)_'"


async def test_fresh_db_has_every_live_constraint(db_session):
    # db_session = drop_all + create_all on the test DB: a fresh build.
    names = set((await db_session.execute(text(NAMED))).scalars())
    assert names == EXPECTED, f"missing {EXPECTED - names}, unexpected {names - EXPECTED}"
    not_null = set((await db_session.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'registrations' AND is_nullable = 'NO'"
    ))).scalars())
    assert {"rto_code", "count", "is_supplementary", "state_code", "state_name", "month", "year",
            "vehicle_class"} <= not_null


async def test_existing_db_missing_a_constraint_gets_it_back(db_session):
    await db_session.execute(text("ALTER TABLE registrations DROP CONSTRAINT ck_reg_pass_shape"))
    await db_session.execute(text("ALTER TABLE registrations DROP CONSTRAINT fk_registrations_state_code_name"))
    await db_session.execute(text("ALTER TABLE states DROP CONSTRAINT uq_states_code_name CASCADE"))
    await db_session.commit()
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        await ensure_declared_constraints(engine, Base.metadata)
        await ensure_declared_constraints(engine, Base.metadata)  # idempotent: no error, no duplicates
    finally:
        await engine.dispose()
    assert set((await db_session.execute(text(NAMED))).scalars()) == EXPECTED


async def _seed(db):
    await db.merge(State(state_code="DL", state_name="Delhi"))
    await db.merge(RTO(rto_code="DL1", rto_name="DL1", state_code="DL"))
    await db.commit()


def _row(**kw):
    base = dict(state_code="DL", state_name="Delhi", rto_code="DL1", year=2025, month=1, count=1)
    return Registration(**{**base, **kw})


@pytest.mark.parametrize("shape", [
    dict(is_supplementary=False, vehicle_class="All", maker="HONDA", fuel_type=None),   # fuel NULL
    dict(is_supplementary=True, vehicle_class="MOTOR CAR", maker=None, fuel_type=None),  # maker + fuel NULL
    dict(is_supplementary=True, vehicle_class="All", maker=None, fuel_type="PETROL"),    # maker NULL
])
async def test_ux_reg_natural_rejects_duplicates_with_null_maker_or_fuel(db_session, shape):
    await _seed(db_session)
    db_session.add(_row(**shape))
    await db_session.commit()
    db_session.add(_row(**shape, count=2))
    with pytest.raises(IntegrityError, match="ux_reg_natural"):
        await db_session.commit()
    await db_session.rollback()


async def test_pass_shape_and_state_name_are_enforced(db_session):
    await _seed(db_session)
    db_session.add(_row(is_supplementary=False, vehicle_class="MOTOR CAR", maker=None))  # synthetic shape
    with pytest.raises(IntegrityError, match="ck_reg_pass_shape"):
        await db_session.commit()
    await db_session.rollback()
    db_session.add(_row(state_name="Dilli", vehicle_class="All", maker="HONDA"))
    with pytest.raises(IntegrityError, match="fk_registrations_state_code_name"):
        await db_session.commit()
    await db_session.rollback()
