"""ADAPTED VEHICLE must classify to Other, and must stay there.

This class is a vehicle modified for a driver with a disability. It mapped
to Four-Wheeler until 2026-09, which put ~80% of the bucket in the wrong
category -- 172,396 of 216,315 units belong to two-wheeler makers, so a
customer filtering Two-Wheeler undercounted TVS by 9,429 units in FY2026
while Four-Wheeler was inflated by the same amount.

A sub-classification DOES exist on a different source: the analytics portal
reports TWO/THREE/FOUR WHEELER (Invalid Carriage) separately and reconciles
against this class to within 0.02-0.64% for 2021-2026. Apportioning on it is
a product decision with a disclosure requirement (the ratio flips by state,
and there is no coverage before 2020), so Other is the current answer -- but
"no split exists" would be false, and these tests must not enshrine it.

These tests exist because the mapping is a judgment call that looks wrong
at a glance ("an adapted vehicle is obviously a car") and is therefore a
prime candidate for a well-meaning revert.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.migrations import ensure_reclassified
from app.core.query_filters import classify_live_category, classify_vehicle

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vahan:vahan@127.0.0.1:5432/vahan_test",
)


def _table_name() -> str:
    return f"reclass_probe_{uuid4().hex}"


async def _make_probe_table(engine, table_name: str, rows: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            f"CREATE TABLE {table_name} (id SERIAL PRIMARY KEY, vehicle_class TEXT, "
            f"vehicle_category TEXT, count INTEGER)"
        ))
        await conn.execute(text(
            f"INSERT INTO {table_name} (vehicle_class, vehicle_category, count) VALUES {rows}"
        ))


def test_adapted_vehicle_classifies_to_other():
    """The mapping itself. Not Four-Wheeler, not Two-Wheeler -- Other.

    Asserting the NEGATIVE cases too: the temptation on seeing ~80% 2W
    makers is to flip this to Two-Wheeler, which would be the same error
    in the opposite direction. Maruti Suzuki is 97.7% Four-Wheeler across
    26.5M units and its adapted vehicles are adapted cars.
    """
    category, tier = classify_vehicle("ADAPTED VEHICLE")
    assert category == "Other", (
        f"ADAPTED VEHICLE classified as {category!r}. The VAHAN4 vehicle_class "
        "axis does not sub-classify it: Hero MotoCorp is 100.0% Two-Wheeler and "
        "Maruti Suzuki 97.7% Four-Wheeler, both registering adapted vehicles "
        "under this one label. The analytics portal's Invalid Carriage split is "
        "the only source that distinguishes them, and apportioning on it is a "
        "disclosed product decision, not a mapping change."
    )
    assert category != "Four-Wheeler"
    assert category != "Two-Wheeler"
    assert tier is None


def test_live_and_stored_paths_agree_on_adapted_vehicles():
    """The two classification tables must not contradict each other.

    _VEHICLE_CATEGORY_MAP handles the stored VAHAN4 path (vehicle_class
    'ADAPTED VEHICLE'); _LIVE_CATEGORY_RULES handles the live analytics path
    ('TWO WHEELER (Invalid Carriage)' etc). They describe the SAME physical
    vehicles through two different feeds.

    Before this was pinned, the live rules substring-matched "TWO WHEELER"
    and returned Two-Wheeler while the stored path returned Other -- so a
    Two-Wheeler-scoped account saw adapted scooters in its live-query
    leaderboard but not in its KPIs, trend or crosstab. 14,154 units of
    disagreement in FY2026 alone, from one product.
    """
    stored = classify_vehicle("ADAPTED VEHICLE")[0]
    for live_label in (
        "TWO WHEELER (Invalid Carriage)",
        "THREE WHEELER (Invalid Carriage)",
        "FOUR WHEELER (Invalid Carriage)",
    ):
        assert classify_live_category(live_label) == stored, (
            f"{live_label!r} -> {classify_live_category(live_label)!r} on the live "
            f"path but {stored!r} on the stored path. These are the same vehicles; "
            "a category-scoped customer would get two different answers depending "
            "on which endpoint they hit."
        )


def test_live_category_rules_still_classify_ordinary_labels():
    """The INVALID CARRIAGE rule is first, so prove it did not shadow the rest."""
    assert classify_live_category("TWO WHEELER (NT)") == "Two-Wheeler"
    assert classify_live_category("THREE WHEELER (T)") == "Three-Wheeler"
    assert classify_live_category("FOUR WHEELER (T)") == "Four-Wheeler"
    assert classify_live_category("LIGHT MOTOR VEHICLE") == "Four-Wheeler"
    assert classify_live_category("HEAVY GOODS VEHICLE") == "Commercial Vehicle"
    assert classify_live_category("OTHER THAN MENTIONED ABOVE") == "Other"


def test_adapted_vehicle_classification_is_case_insensitive():
    """Scraped data carries 'Adapted Vehicle'; the map keys on upper case."""
    for variant in ("ADAPTED VEHICLE", "Adapted Vehicle", "adapted vehicle"):
        assert classify_vehicle(variant)[0] == "Other", f"{variant!r} misclassified"


async def test_ensure_reclassified_moves_stale_rows_and_conserves_totals():
    """The migration half: a row stored under the OLD mapping gets moved.

    ensure_vehicle_category_backfilled only fills NULLs, so editing the map
    alone leaves every already-classified row wrong forever. This is the
    pass that fixes them, and it must not change any total -- volume moves
    between categories, it is never created or destroyed.
    """
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    await _make_probe_table(engine, table_name, (
        "('Adapted Vehicle', 'Four-Wheeler', 9429), "
        "('ADAPTED VEHICLE', 'Four-Wheeler', 4143), "
        "('Motor Car',       'Four-Wheeler', 1000), "
        "('M-Cycle/Scooter', 'Two-Wheeler',  5000)"
    ))

    await ensure_reclassified(
        engine, [table_name],
        vehicle_class="ADAPTED VEHICLE", expected_category="Other",
    )

    async with engine.begin() as conn:
        totals = dict((await conn.execute(text(
            f"SELECT vehicle_category, sum(count) FROM {table_name} GROUP BY 1"
        ))).all())
        after = (await conn.execute(text(f"SELECT sum(count) FROM {table_name}"))).scalar()

        # Both adapted rows moved, regardless of stored case.
        assert totals.get("Other") == 13572, f"expected 13572 in Other, got {totals}"
        # The untouched Four-Wheeler row stayed put -- this pass is scoped to
        # one vehicle_class, not a blanket recompute.
        assert totals.get("Four-Wheeler") == 1000, f"Motor Car was moved: {totals}"
        assert totals.get("Two-Wheeler") == 5000, f"scooter row was touched: {totals}"
        # Volume is conserved: reclassification moves counts, never alters them.
        assert after == 19572

        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_reclassified_is_idempotent():
    """Runs on every startup, so repeated runs must match zero rows."""
    table_name = _table_name()
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    await _make_probe_table(engine, table_name, "('Adapted Vehicle', 'Four-Wheeler', 500)")

    for _ in range(3):
        await ensure_reclassified(
            engine, [table_name],
            vehicle_class="ADAPTED VEHICLE", expected_category="Other",
        )

    async with engine.begin() as conn:
        cat = (await conn.execute(text(f"SELECT vehicle_category FROM {table_name}"))).scalar()
        total = (await conn.execute(text(f"SELECT sum(count) FROM {table_name}"))).scalar()
        assert cat == "Other"
        assert total == 500, "repeated runs must not alter counts"
        await conn.execute(text(f"DROP TABLE {table_name}"))
    await engine.dispose()


async def test_ensure_reclassified_rejects_bad_table_name():
    """Table names are interpolated as identifiers -- validate them."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True)
    with pytest.raises(ValueError, match="Invalid table name"):
        await ensure_reclassified(
            engine, ["registrations; DROP TABLE users"],
            vehicle_class="ADAPTED VEHICLE", expected_category="Other",
        )
    await engine.dispose()
