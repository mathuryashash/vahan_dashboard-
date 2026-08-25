"""fuel_category groups VAHAN's ~37 raw fuel_type strings (exact
powertrain/fuel-system combinations) into the handful of categories people
actually compare. Priority-ordered substring rules, so the tricky cases are
multi-fuel values where more than one rule could match -- this locks in
which one wins.
"""
import pytest

from app.core.query_filters import classify_vehicle, fuel_category, fuel_group


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


@pytest.mark.parametrize("raw,expected_category,expected_tier", [
    ("M-CYCLE/SCOOTER", "Two-Wheeler", None),
    ("MOPED", "Two-Wheeler", None),
    ("MOTORISED CYCLE (CC > 25CC)", "Two-Wheeler", None),
    ("Two-Wheeler", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-USED FOR HIRE", "Two-Wheeler", None),
    ("M-CYCLE/SCOOTER-WITH SIDE CAR", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-SIDECAR(T)", "Two-Wheeler", None),
    ("MOTOR CYCLE/SCOOTER-WITH TRAILER", "Two-Wheeler", None),
    ("THREE WHEELER (PASSENGER)", "Three-Wheeler", None),
    ("THREE WHEELER (GOODS)", "Three-Wheeler", None),
    ("THREE WHEELER (PERSONAL)", "Three-Wheeler", None),
    ("E-RICKSHAW(P)", "Three-Wheeler", None),
    ("E-RICKSHAW WITH CART (G)", "Three-Wheeler", None),
    ("Three-Wheeler", "Three-Wheeler", None),
    ("QUADRICYCLE (COMMERCIAL)", "Three-Wheeler", None),
    ("QUADRICYCLE (PRIVATE)", "Three-Wheeler", None),
    ("MOTOR CAR", "Four-Wheeler", None),
    ("Motor Car/Jeep/Taxi", "Four-Wheeler", None),
    ("MOTOR CAB", "Four-Wheeler", None),
    ("MAXI CAB", "Four-Wheeler", None),
    ("LUXURY CAB", "Four-Wheeler", None),
    ("Light Motor Vehicle", "Four-Wheeler", None),
    ("ADAPTED VEHICLE", "Four-Wheeler", None),
    ("PRIVATE SERVICE VEHICLE", "Four-Wheeler", None),
    ("PRIVATE SERVICE VEHICLE (INDIVIDUAL USE)", "Four-Wheeler", None),
    ("GOODS CARRIER", "Commercial Vehicle", "Unspecified"),
    ("TRACTOR (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("TRACTOR-TROLLEY(COMMERCIAL)", "Commercial Vehicle", "Unspecified"),
    ("Mini Bus", "Commercial Vehicle", "LCV"),
    ("Bus", "Commercial Vehicle", "HCV"),
    ("BUS", "Commercial Vehicle", "HCV"),
    ("Medium Bus", "Commercial Vehicle", "MCV"),
    ("OMNI BUS", "Commercial Vehicle", "Unspecified"),
    ("OMNI BUS (PRIVATE USE)", "Commercial Vehicle", "Unspecified"),
    ("EDUCATIONAL INSTITUTION BUS", "Commercial Vehicle", "Unspecified"),
    ("SCHOOL BUS", "Commercial Vehicle", "Unspecified"),
    ("Medium Truck", "Commercial Vehicle", "MCV"),
    ("Heavy Truck", "Commercial Vehicle", "HCV"),
    ("TRAILER (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("ARTICULATED VEHICLE", "Commercial Vehicle", "HCV"),
    ("SEMI-TRAILER (COMMERCIAL)", "Commercial Vehicle", "HCV"),
    ("AUXILIARY TRAILER", "Commercial Vehicle", "Unspecified"),
    ("DUMPER", "Commercial Vehicle", "HCV"),
    ("MODULAR HYDRAULIC TRAILER", "Commercial Vehicle", "Unspecified"),
    ("AGRICULTURAL TRACTOR", "Other", None),
    ("TRAILER (AGRICULTURAL)", "Other", None),
    ("Tractor", "Other", None),
    ("HARVESTER", "Other", None),
    ("POWER TILLER", "Other", None),
    ("POWER TILLER (COMMERCIAL)", "Other", None),
    ("PULLER TRACTOR", "Other", None),
    ("CONSTRUCTION EQUIPMENT VEHICLE", "Other", None),
    ("CONSTRUCTION EQUIPMENT VEHICLE (COMMERCIAL)", "Other", None),
    ("Construction Equipment", "Other", None),
    ("EARTH MOVING EQUIPMENT", "Other", None),
    ("EXCAVATOR (NT)", "Other", None),
    ("EXCAVATOR (COMMERCIAL)", "Other", None),
    ("CRANE MOUNTED VEHICLE", "Other", None),
    ("FORK LIFT", "Other", None),
    ("ROAD ROLLER", "Other", None),
    ("BULLDOZER", "Other", None),
    ("VEHICLE FITTED WITH RIG", "Other", None),
    ("VEHICLE FITTED WITH COMPRESSOR", "Other", None),
    ("VEHICLE FITTED WITH GENERATOR", "Other", None),
    ("TOW TRUCK", "Other", None),
    ("RECOVERY VEHICLE", "Other", None),
    ("BREAKDOWN VAN", "Other", None),
    ("AMBULANCE", "Other", None),
    ("ANIMAL AMBULANCE", "Other", None),
    ("FIRE FIGHTING VEHICLE", "Other", None),
    ("FIRE TENDERS", "Other", None),
    ("HEARSES", "Other", None),
    ("ARMOURED/SPECIALISED VEHICLE", "Other", None),
    ("SNORKED LADDERS", "Other", None),
    ("TREE TRIMMING VEHICLE", "Other", None),
    ("MOBILE CANTEEN", "Other", None),
    ("CASH VAN", "Other", None),
    ("MOBILE CLINIC", "Other", None),
    ("MOBILE WORKSHOP", "Other", None),
    ("LIBRARY VAN", "Other", None),
    ("X-RAY VAN", "Other", None),
    ("TOWER WAGON", "Other", None),
    ("CAMPER VAN / TRAILER", "Other", None),
    ("CAMPER VAN / TRAILER (PRIVATE USE)", "Other", None),
    ("TRAILER FOR PERSONAL USE", "Other", None),
    ("MOTOR CARAVAN", "Other", None),
    ("VINTAGE MOTOR VEHICLE", "Other", None),
    ("Other", "Other", None),
    ("All", "Other", None),
    ("SOME FUTURE VAHAN CATEGORY NOBODY HAS SEEN YET", "Other", None),
])
def test_classify_vehicle_maps_raw_vahan_values(raw, expected_category, expected_tier):
    assert classify_vehicle(raw) == (expected_category, expected_tier)


def test_classify_vehicle_is_case_insensitive():
    assert classify_vehicle("motor car") == ("Four-Wheeler", None)


@pytest.mark.parametrize("raw,expected", [
    ("PETROL", "ICE"),
    ("DIESEL", "ICE"),
    ("CNG ONLY", "ICE"),
    ("PETROL/LPG", "ICE"),
    ("ELECTRIC(BOV)", "EV"),
    ("PURE EV", "EV"),
    ("PETROL/HYBRID", "Hybrid"),
    ("STRONG HYBRID EV", "Hybrid"),
])
def test_fuel_group_maps_fuel_category_buckets(raw, expected):
    assert fuel_group(raw) == expected
