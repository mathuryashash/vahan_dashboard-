from app.scripts.geo_reference_data import (
    split_district_names,
    normalize_state_code,
    ZONE_BY_STATE_CODE,
)


def test_split_district_names_handles_slash_delimiter():
    assert split_district_names("Adilabad / Mancherial / Nirmal") == [
        "Adilabad", "Mancherial", "Nirmal",
    ]


def test_split_district_names_handles_comma_delimiter():
    assert split_district_names("Kolkata, Howrah") == ["Kolkata", "Howrah"]


def test_split_district_names_single_name():
    assert split_district_names("Kakinada") == ["Kakinada"]


def test_normalize_state_code_maps_legacy_prefixes():
    assert normalize_state_code("OR") == "OD"
    assert normalize_state_code("UA") == "UK"
    assert normalize_state_code("DD") == "DN"


def test_normalize_state_code_passes_through_known_codes():
    assert normalize_state_code("MH") == "MH"
    assert normalize_state_code("AP") == "AP"


def test_zone_mapping_covers_all_zonal_council_states():
    # Spot-check a few real Zonal Council memberships (verified via
    # mha.gov.in/en/page/zonal-council during design).
    assert ZONE_BY_STATE_CODE["DL"] == "NORTH"
    assert ZONE_BY_STATE_CODE["MH"] == "WEST"
    assert ZONE_BY_STATE_CODE["TN"] == "SOUTH"
    assert ZONE_BY_STATE_CODE["WB"] == "EAST"
    assert ZONE_BY_STATE_CODE["UP"] == "CENTRAL"
    assert ZONE_BY_STATE_CODE["AS"] == "NORTHEAST"


def test_zone_mapping_ladakh_lakshadweep_not_swapped():
    # Regression test: LD is the real-world/RTO.csv code for Lakshadweep, LA is Ladakh
    # (confirmed against the real RTO.csv and app.scripts.seed_geo_hierarchy's
    # _NAME_CORRECTIONS). An earlier version of this mapping had the zone assignments
    # attached to the wrong code (LD labeled "Ladakh", LA labeled "Lakshadweep").
    assert ZONE_BY_STATE_CODE["LD"] == "WEST"  # Lakshadweep -- grouped with West
    assert ZONE_BY_STATE_CODE["LA"] == "NORTH"  # Ladakh -- extension from J&K
