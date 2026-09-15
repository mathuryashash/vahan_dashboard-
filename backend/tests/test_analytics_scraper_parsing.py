"""Parsing tests for the NEW analytics.parivahan.gov.in site (month-wise x
vehicle-category). Unlike the old VAHAN4 site's PrimeFaces markup, this
table is a plain server-rendered <table> -- no label-cell/aria-label
gymnastics needed, but real responses ship a dynamic-heading-builder
<script> block that must be stripped before any text search runs against
the page (see parse_month_category_table's docstring). fixtures/
analytics_monthwise_category_sample.html is a real captured response
(Bihar, 2024, no maker/fuel filter); analytics_invalid_captcha_sample.html
is a real captured "Invalid CAPTCHA" response with no result table.
"""
from pathlib import Path

from scraper.analytics_scraper import _build_form, map_site_rtos, parse_month_category_table

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_month_category_table_extracts_records_in_order():
    html = """
    <table>
      <tr><th>Month</th><th>Two Wheeler</th><th>Four Wheeler</th><th>Total</th></tr>
      <tr><td>2024-01</td><td>1,000</td><td>200</td><td>1,200</td></tr>
      <tr><td>2024-02</td><td>0</td><td>50</td><td>50</td></tr>
      <tr><td>Total</td><td>1,000</td><td>250</td><td>1,250</td></tr>
    </table>
    """
    records = parse_month_category_table(html)
    assert records == [
        {"month": 1, "category": "Two Wheeler", "count": 1000},
        {"month": 1, "category": "Four Wheeler", "count": 200},
        {"month": 2, "category": "Four Wheeler", "count": 50},
    ]


def test_parse_month_category_table_strips_script_pollution():
    # A dynamic-heading-builder <script> block ships on every real response;
    # confirmed live this session it can contain text that looks like table
    # content if not stripped first.
    html = """
    <script>document.write("<td>2024-99</td><td>99,999</td>");</script>
    <table>
      <tr><th>Month</th><th>Two Wheeler</th><th>Total</th></tr>
      <tr><td>2024-03</td><td>500</td><td>500</td></tr>
    </table>
    """
    records = parse_month_category_table(html)
    assert records == [{"month": 3, "category": "Two Wheeler", "count": 500}]


def test_parse_month_category_table_empty_without_a_table():
    assert parse_month_category_table("<div>no table here</div>") == []


def test_parse_month_category_table_empty_for_invalid_captcha_response():
    html = (FIXTURES / "analytics_invalid_captcha_sample.html").read_text(encoding="utf-8")
    assert parse_month_category_table(html) == []


def test_parse_month_category_table_real_fixture():
    html = (FIXTURES / "analytics_monthwise_category_sample.html").read_text(encoding="utf-8")
    records = parse_month_category_table(html)

    assert len(records) == 155
    assert {r["month"] for r in records} == set(range(1, 13))
    assert "TWO WHEELER(NT)" in {r["category"] for r in records}
    assert {"month": 12, "category": "TWO WHEELER(NT)", "count": 60158} in records


def test_build_form_returns_a_dict_httpx_can_form_encode():
    # Regression guard: httpx 0.28's `data=` only form-encodes a Mapping --
    # a list of (key, value) tuples is silently reinterpreted as raw
    # `content=` instead, which broke every POST in this module until fixed.
    form = _build_form(csrf_token="tok", state_code="BR", year=2024, captcha="ABC123", maker=None, fuel=None)
    assert isinstance(form, dict)
    assert form["archivedFlags"] == ["ACTIVE_COMPLIANT", "ACTIVE_NON_COMPLIANT", "PERMANENT_ARCHIVE", "TEMPORARY_ARCHIVE"]
    assert form["stateMultiple"] == "BR"
    assert form["captcha"] == "ABC123"
    assert "vehicleMakers" not in form


def test_build_form_translates_state_codes_the_new_site_renamed():
    # Odisha/Telangana/the DNH&DD UT use different 2-letter codes on the new
    # site than in this codebase's own states table (inherited from the old
    # VAHAN4 site) -- confirmed live by diffing the site's dropdown. Every
    # other code passes through unchanged.
    assert _build_form(csrf_token="t", state_code="OD", year=2024, captcha="X", maker=None, fuel=None)["stateMultiple"] == "OR"
    assert _build_form(csrf_token="t", state_code="TS", year=2024, captcha="X", maker=None, fuel=None)["stateMultiple"] == "TG"
    assert _build_form(csrf_token="t", state_code="DN", year=2024, captcha="X", maker=None, fuel=None)["stateMultiple"] == "DD"
    assert _build_form(csrf_token="t", state_code="BR", year=2024, captcha="X", maker=None, fuel=None)["stateMultiple"] == "BR"


def test_build_form_adds_maker_and_fuel_when_given():
    form = _build_form(
        csrf_token="tok", state_code="BR", year=2024, captcha="ABC123",
        maker="HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD", fuel="PETROL",
    )
    assert form["vehicleMakers"] == "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD"
    assert form["selectedMakersCsv"] == "HONDA MOTORCYCLE AND SCOOTER INDIA (P) LTD"
    assert form["vehicleFuels"] == "PETROL"


def test_build_form_sets_rto_code_multiple_only_when_given():
    # rtoCodeMultiple is the one date/scope field on this form that REALLY
    # filters (confirmed live against a control: DL/2024 = 711,071
    # unfiltered vs. 85,366 with rtoCodeMultiple=9). The _rtoCodeMultiple
    # field-present marker is always sent regardless -- that's Spring's
    # convention, not the filter itself.
    unfiltered = _build_form(csrf_token="t", state_code="DL", year=2024, captcha="X", maker=None, fuel=None)
    assert "rtoCodeMultiple" not in unfiltered
    assert unfiltered["_rtoCodeMultiple"] == "1"

    scoped = _build_form(csrf_token="t", state_code="DL", year=2024, captcha="X", maker=None, fuel=None, rto_code="9")
    assert scoped["rtoCodeMultiple"] == "9"


# A real json_rtos response shape for stateCode=DL (trimmed): the site's
# `id` is NOT what the form wants (id=980 returns nothing; rtoCode=9 is the
# value that filters), and its rtoName carries our own rto_code as a suffix.
_DELHI_SITE_RTOS = [
    {"id": 980, "rtoCode": 9, "rtoName": "DWARKA - DL9", "stateCode": "DL"},
    {"id": 972, "rtoCode": 1, "rtoName": "MALL ROAD - DL1", "stateCode": "DL"},
    {"id": 985, "rtoCode": 13, "rtoName": "SOUTH-WEST - DL13", "stateCode": "DL"},
]


def test_map_site_rtos_keys_by_our_rto_code_from_the_name_suffix():
    # Matched by rtoName's suffix, never by parsing an integer out of our
    # own rto_code -- the two vocabularies don't line up (see map_site_rtos).
    assert map_site_rtos(_DELHI_SITE_RTOS) == {"DL9": "9", "DL1": "1", "DL13": "13"}


def test_map_site_rtos_splits_on_the_LAST_hyphen_only():
    # "SOUTH-WEST - DL13" has a hyphen inside the office name too: a plain
    # split-on-first-hyphen would key this as "WEST - DL13" and the RTO
    # would silently have no live option.
    assert map_site_rtos(_DELHI_SITE_RTOS)["DL13"] == "13"


def test_map_site_rtos_omits_rtos_the_site_doesnt_list():
    # Confirmed live for Delhi: we hold 27 RTOs, the site lists 23, 16 map.
    # DL14 is one of the real gaps, and "DL1L" isn't even numeric -- both
    # must simply be absent (no live option), not guessed at.
    mapping = map_site_rtos(_DELHI_SITE_RTOS)
    assert "DL14" not in mapping
    assert "DL1L" not in mapping


def test_map_site_rtos_skips_entries_with_no_suffix_separator():
    # Without the guard, a name with no " - " lands in the map under its
    # whole name, which can never match a real rto_code anyway.
    assert map_site_rtos([{"id": 1, "rtoCode": 4, "rtoName": "AGRA", "stateCode": "UP"}]) == {}
