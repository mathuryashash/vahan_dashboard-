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

from scraper.analytics_scraper import _build_form, parse_month_category_table

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
