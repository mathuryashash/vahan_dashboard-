"""fuel_category groups VAHAN's ~37 raw fuel_type strings (exact
powertrain/fuel-system combinations) into the handful of categories people
actually compare. Priority-ordered substring rules, so the tricky cases are
multi-fuel values where more than one rule could match -- this locks in
which one wins.
"""
import pytest

from app.core.query_filters import fuel_category


@pytest.mark.parametrize("raw,expected", [
    ("PETROL", "Petrol"),
    ("PETROL(E20)", "Petrol"),
    ("DIESEL", "Diesel"),
    ("ELECTRIC(BOV)", "EV"),
    ("PURE EV", "EV"),
    ("FUEL CELL HYDROGEN", "EV"),
    ("CNG ONLY", "CNG"),
    ("HCNG", "CNG"),
    ("PETROL/HYBRID", "Hybrid"),
    ("STRONG HYBRID EV", "Hybrid"),
    ("PLUG-IN HYBRID EV", "Hybrid"),
    # Multi-fuel: HYBRID and CNG both present -- HYBRID is the more specific
    # descriptor (what makes it different from a plain CNG vehicle), so it
    # wins over the CNG rule despite CNG also matching.
    ("PETROL(E20)/HYBRID/CNG", "Hybrid"),
    # Diesel+CNG dual-fuel: CNG is checked before DIESEL, so this lands in
    # CNG, not Diesel.
    ("DUAL DIESEL/CNG", "CNG"),
    # LPG isn't one of the five requested buckets -- explicitly Other, not
    # folded into Petrol just because "PETROL" also appears in the string.
    ("PETROL/LPG", "Other"),
    ("LPG ONLY", "Other"),
    # Hydrogen internal combustion is combustion, not electric, and matches
    # none of the five buckets.
    ("HYDROGEN(ICE)", "Other"),
    ("NOT APPLICABLE", "Other"),
    ("ETHANOL(E100)", "Other"),
    ("SOLAR", "Other"),
])
def test_fuel_category_maps_raw_vahan_values(raw, expected):
    assert fuel_category(raw) == expected


def test_fuel_category_is_case_insensitive():
    assert fuel_category("petrol") == "Petrol"
    assert fuel_category("Diesel") == "Diesel"
