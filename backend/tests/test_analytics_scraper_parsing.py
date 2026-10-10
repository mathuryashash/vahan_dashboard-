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

import pytest

from scraper.analytics_scraper import UnexpectedPageError, _build_form, map_site_rtos, parse_month_category_table

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


def test_a_page_with_no_results_table_raises_rather_than_reading_as_zero():
    """Used to return [] -- which the callers then persisted as a real zero,
    deleting the state's year first, or cached as "this maker sold 0"."""
    with pytest.raises(UnexpectedPageError):
        parse_month_category_table("<div>no table here</div>")


def test_an_invalid_captcha_page_is_not_mistaken_for_zero_registrations():
    html = (FIXTURES / "analytics_invalid_captcha_sample.html").read_text(encoding="utf-8")
    with pytest.raises(UnexpectedPageError):
        parse_month_category_table(html)


def test_a_genuine_all_zero_table_still_means_no_registrations():
    """The distinction the raise depends on: a state with nothing registered
    renders a table of zeros, and that must stay a valid empty result."""
    html = """
    <table>
      <tr><th>Month</th><th>TWO WHEELER</th><th>Total</th></tr>
      <tr><td>2026-01</td><td>0</td><td>0</td></tr>
      <tr><td>Total</td><td>0</td><td>0</td></tr>
    </table>
    """
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


# ---- _validate_export port: month contiguity + row/footer Total checks -------

from scraper.analytics_scraper import TableIntegrityError  # noqa: E402


def _fixture_html() -> str:
    return (FIXTURES / "analytics_monthwise_category_sample.html").read_text(encoding="utf-8")


def test_real_fixture_passes_its_own_arithmetic():
    # Bihar 2024: 12 contiguous months, every row Total and the footer agree.
    records = parse_month_category_table(_fixture_html())
    assert sum(r["count"] for r in records) == 1_395_217  # the page's own grand total


def test_a_dropped_month_row_is_rejected_by_the_footer_total():
    html = _fixture_html()
    start = html.index("2024-05")
    row_start = html.rindex("<tr", 0, start)
    row_end = html.index("</tr>", start) + len("</tr>")
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(html[:row_start] + html[row_end:])


def test_an_altered_cell_is_rejected_by_the_row_total():
    html = """
    <table>
      <tr><th>Month</th><th>Two Wheeler</th><th>Four Wheeler</th><th>Total</th></tr>
      <tr><td>2024-01</td><td>1,001</td><td>200</td><td>1,200</td></tr>
    </table>
    """
    with pytest.raises(TableIntegrityError, match="row 2024-01"):
        parse_month_category_table(html)


def test_a_duplicated_or_out_of_order_month_is_rejected():
    dup = """
    <table>
      <tr><th>Month</th><th>Two Wheeler</th><th>Total</th></tr>
      <tr><td>2024-01</td><td>5</td><td>5</td></tr>
      <tr><td>2024-01</td><td>5</td><td>5</td></tr>
    </table>
    """
    gap = dup.replace("<tr><td>2024-01</td><td>5</td><td>5</td></tr>\n    </table>",
                      "<tr><td>2024-03</td><td>5</td><td>5</td></tr>\n    </table>")
    for html in (dup, gap):
        with pytest.raises(TableIntegrityError, match="contiguous"):
            parse_month_category_table(html)


def test_footer_mismatch_names_the_column():
    html = """
    <table>
      <tr><th>Month</th><th>Two Wheeler</th><th>Four Wheeler</th><th>Total</th></tr>
      <tr><td>2024-01</td><td>1,000</td><td>200</td><td>1,200</td></tr>
      <tr><td>2024-02</td><td>0</td><td>50</td><td>50</td></tr>
      <tr><td>Total</td><td>1,000</td><td>260</td><td>1,260</td></tr>
    </table>
    """
    with pytest.raises(TableIntegrityError, match="Four Wheeler"):
        parse_month_category_table(html)


def test_integrity_error_is_an_unexpected_page_so_callers_skip_it():
    assert issubclass(TableIntegrityError, UnexpectedPageError)


# --- ragged tables the live site renders (captured 2026-10-09) -------------

from scraper.analytics_scraper import SITE_CATEGORIES, normalize_ragged_table  # noqa: E402


def _html(rows, axis=SITE_CATEGORIES):
    """`axis` = the page's own vehicleSubCategory <select> (None: absent)."""
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    sel = "" if axis is None else (
        '<select id="vehicleSubCategory">' + "".join(f'<option value="{a}">{a}</option>' for a in axis) + "</select>")
    return f"{sel}<table>{body}</table>"


def test_empty_month_two_cell_rows_are_zero_months_not_a_rejected_page():
    # AR 2026 DIESEL/HYBRID: data months are full width, empty months are [month, '0'].
    rows = [["Month", "A", "B", "Total"], ["2026-01", "0", "3", "3"], ["2026-02", "0"],
            ["2026-03", "1", "0", "1"], ["Total", "1", "3", "4"]]
    assert parse_month_category_table(_html(rows)) == [
        {"month": 1, "category": "B", "count": 3}, {"month": 3, "category": "A", "count": 1}]


def test_a_two_cell_row_with_a_nonzero_total_is_still_rejected():
    rows = [["Month", "A", "Total"], ["2026-01", "5"], ["Total", "5", "5"]]
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))


def test_collapsed_header_is_rebuilt_from_the_site_axis_when_rows_are_full_width():
    # TS 2026 PETROL(E20): Jan-Mar empty, so header and footer collapse to 2 cells
    # while Apr-Oct carry all 17 categories. This used to drop ~277k units.
    n = len(SITE_CATEGORIES)
    lmv = SITE_CATEGORIES.index("LIGHT MOTOR VEHICLE")
    two = SITE_CATEGORIES.index("TWO WHEELER(NT)")
    apr = ["0"] * n
    apr[lmv], apr[two] = "1,883", "28,195"
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-02", "0"], ["2026-03", "0"],
            ["2026-04", *apr, "30,078"], ["Total", "0"]]
    assert parse_month_category_table(_html(rows)) == [
        {"month": 4, "category": "LIGHT MOTOR VEHICLE", "count": 1883},
        {"month": 4, "category": "TWO WHEELER(NT)", "count": 28195}]


def test_collapsed_header_takes_column_order_from_the_page_not_a_fixed_list():
    # Round 5: the axis used to be ASSUMED in SITE_CATEGORIES order. A page
    # that renders the same 17 categories in another order must name the
    # columns in the page's order.
    axis = list(reversed(SITE_CATEGORIES))
    apr = ["0"] * len(axis)
    apr[0] = "7"  # first column = axis[0] = "TWO WHEELER(T)" on this page
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-02", *apr, "7"], ["Total", "0"]]
    assert parse_month_category_table(_html(rows, axis)) == [
        {"month": 2, "category": "TWO WHEELER(T)", "count": 7}]


@pytest.mark.parametrize("axis", [
    None,                                                       # no category select on the page
    [*SITE_CATEGORIES[:-1], "TWO WHEELER(TRANSPORT)"],          # a renamed category
    [*SITE_CATEGORIES, "QUADRICYCLE"],                          # an added category
])
def test_collapsed_header_with_an_unexpected_axis_is_rejected_loudly(axis):
    apr = ["0"] * len(SITE_CATEGORIES)
    apr[0] = "5"
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-04", *apr, "5"], ["Total", "0"]]
    with pytest.raises(TableIntegrityError, match="category axis"):
        parse_month_category_table(_html(rows, axis))


def test_real_collapsed_page_parses_with_its_own_axis():
    """The live TS 2026 PETROL(E20) page (round 4b probe): header collapsed,
    Jan-Mar empty, axis from its vehicleSubCategory select."""
    import pathlib
    probe = pathlib.Path("D:/hf-cache/vahan_review/round4b/probe_TS_2026.html")
    if not probe.exists():
        pytest.skip("live probe not on this machine")
    records = parse_month_category_table(probe.read_text(encoding="utf-8"))
    assert {r["month"] for r in records} >= {4, 5} and min(r["month"] for r in records) == 4
    apr = {r["category"]: r["count"] for r in records if r["month"] == 4}
    assert sum(apr.values()) == 30078


def test_collapsed_header_still_checks_each_row_total():
    n = len(SITE_CATEGORIES)
    apr = ["0"] * n
    apr[0] = "5"
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-04", *apr, "6"], ["Total", "0"]]
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))


def test_collapsed_header_with_rows_of_an_unknown_width_is_rejected():
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-04", "1", "2", "3"], ["Total", "0"]]
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))


def test_a_row_missing_one_zero_column_is_placed_by_the_footer_sums():
    # BR 2026 PETROL(E20)/HYBRID/CNG: Feb has 18 cells under a 19-cell header.
    rows = [["Month", "A", "B", "C", "Total"], ["2026-01", "0", "1", "0", "1"],
            ["2026-02", "0", "1", "1"], ["Total", "0", "2", "0", "2"]]
    header, body = normalize_ragged_table(rows[0], rows[1:])
    assert body[1] == ["2026-02", "0", "1", "0", "1"]
    assert sum(r["count"] for r in parse_month_category_table(_html(rows))) == 2


def test_a_short_row_the_footer_cannot_place_is_rejected():
    # No placement of the missing zero reproduces the footer -> refuse. (The
    # footer fixes the short row's cells exactly, so a match is always unique.)
    bad = [["Month", "A", "B", "Total"], ["2026-01", "1", "0", "1"], ["2026-02", "5", "5"],
           ["Total", "1", "1", "2"]]
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(bad))
    good = [["Month", "A", "B", "Total"], ["2026-01", "1", "0", "1"], ["2026-02", "1", "1"],
            ["Total", "1", "1", "2"]]
    assert parse_month_category_table(_html(good)) == [
        {"month": 1, "category": "A", "count": 1}, {"month": 2, "category": "B", "count": 1}]


def test_a_short_row_without_a_footer_is_rejected():
    rows = [["Month", "A", "B", "Total"], ["2026-01", "1", "0", "1"], ["2026-02", "1", "1"]]
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))


def test_a_fully_collapsed_all_zero_table_is_a_genuine_empty_result():
    # e.g. AN 2026 DIESEL/HYBRID: no month has data -> Month/Total zeros only.
    rows = [["Month", "Total"], ["2026-01", "0"], ["2026-02", "0"], ["Total", "0"]]
    assert parse_month_category_table(_html(rows)) == []


def _subset_table(full_row_cells, footer_cells=None):
    """LA 2026 PURE EV (live 2026-10-10): header/footer name 16 of the 17
    categories (THREE WHEELER (Invalid Carriage) missing, as in month 1's
    columns) while later data months carry all 17."""
    named = [c for c in SITE_CATEGORIES if c != "THREE WHEELER (Invalid Carriage)"]
    lmv, lgv = named.index("LIGHT MOTOR VEHICLE"), named.index("LIGHT GOODS VEHICLE")
    jan = ["0"] * 16
    jan[lmv] = "1"
    footer = ["0"] * 16
    footer[lmv], footer[lgv] = "2", "1"
    rows = [["Month", *named, "Total"], ["2026-01", *jan, "1"], ["2026-02", "0"], ["2026-03", "0"],
            ["2026-04", *full_row_cells, str(sum(int(c) for c in full_row_cells))],
            ["Total", *(footer_cells or footer), "3"]]
    return rows


def test_subset_header_with_full_width_months_is_mapped_by_name():
    full = ["0"] * 17
    full[SITE_CATEGORIES.index("LIGHT GOODS VEHICLE")] = "1"
    full[SITE_CATEGORIES.index("LIGHT MOTOR VEHICLE")] = "1"
    rows = _subset_table(full)
    assert parse_month_category_table(_html(rows)) == [
        {"month": 1, "category": "LIGHT MOTOR VEHICLE", "count": 1},
        {"month": 4, "category": "LIGHT GOODS VEHICLE", "count": 1},
        {"month": 4, "category": "LIGHT MOTOR VEHICLE", "count": 1},
    ]


def test_subset_header_rejects_a_full_row_with_data_in_the_unnamed_column():
    # The footer names no THREE WHEELER (Invalid Carriage) column, so its sum is
    # an implicit 0: a full row carrying a unit there contradicts the page.
    full = ["0"] * 17
    full[SITE_CATEGORIES.index("THREE WHEELER (Invalid Carriage)")] = "1"
    full[SITE_CATEGORIES.index("LIGHT GOODS VEHICLE")] = "1"
    rows = _subset_table(full)
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))


def test_subset_header_naming_an_unknown_category_is_rejected():
    full = ["0"] * 17
    full[SITE_CATEGORIES.index("LIGHT GOODS VEHICLE")] = "1"
    full[SITE_CATEGORIES.index("LIGHT MOTOR VEHICLE")] = "1"
    rows = _subset_table(full)
    rows[0][1] = "HOVERCRAFT"
    with pytest.raises(TableIntegrityError):
        parse_month_category_table(_html(rows))
