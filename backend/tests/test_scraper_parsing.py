from scraper.parsing import (
    parse_state_option,
    parse_rto_option,
    parse_count,
    MONTH_ABBR,
)


def test_parse_state_option_normal():
    assert parse_state_option("Delhi(16)") == {"state_name": "Delhi", "rto_count": 16}


def test_parse_state_option_with_parens_in_name():
    assert parse_state_option("UT of DNH and DD(3)") == {
        "state_name": "UT of DNH and DD",
        "rto_count": 3,
    }


def test_parse_state_option_skips_aggregate_row():
    assert parse_state_option("All Vahan4 Running States (36/36)") is None


def test_parse_rto_option_normal():
    result = parse_rto_option("OLD DELHI (MALL ROAD) - DL1( 12-OCT-2015 )")
    assert result == {"rto_name": "OLD DELHI (MALL ROAD)", "rto_code": "DL1"}


def test_parse_rto_option_fitness_center():
    result = parse_rto_option("JHULJHULI FITNESS CENTER - DL207( 19-JUN-2017 )")
    assert result == {"rto_name": "JHULJHULI FITNESS CENTER", "rto_code": "DL207"}


def test_parse_rto_option_skips_aggregate_row():
    assert parse_rto_option("All Vahan4 Running Office(16/16)") is None


def test_parse_count_indian_grouping():
    assert parse_count("1,23,456") == 123456


def test_parse_count_plain_number():
    assert parse_count("244") == 244


def test_parse_count_blank_or_dash():
    assert parse_count("") == 0
    assert parse_count("-") == 0
    assert parse_count("  ") == 0


def test_month_abbr_covers_all_twelve():
    assert MONTH_ABBR["JAN"] == 1
    assert MONTH_ABBR["DEC"] == 12
    assert len(MONTH_ABBR) == 12
