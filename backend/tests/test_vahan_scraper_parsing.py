"""Parsing tests for the Maker x Vehicle Class pivot (X-axis=Vehicle Class
instead of Month Wise). VAHAN renders one of two header shapes for the same
report depending on how many vehicle classes have data (confirmed live
against the same RTO/year on separate requests): a flat single <tr> with
TOTAL third (right after the row label, before the classes), or a grouped
two-<tr> header (a colspan group over the leaf class columns) with TOTAL
last. See _parse_header_layout in vahan_scraper.py.
"""
from scraper.vahan_scraper import (
    TABLE_ID,
    _parse_header_layout,
    _parse_maker_category_table_rows,
    _parse_vehicle_class_columns,
)


def _label_cell(index: int, text: str) -> str:
    return f'<label id="{TABLE_ID}:{index}:j_idt1">{text}</label>'


def test_parse_vehicle_class_columns_extracts_classes_in_order():
    html_fragment = (
        'aria-label="S No"'
        'aria-label="Vehicle Class "'
        'aria-label="\xa0\xa0\xa0\xa0\xa0TOTAL\xa0\xa0\xa0\xa0\xa0"'
        'aria-label="\xa0\xa0\xa0\xa0\xa0 M-Cycle/Scooter \xa0\xa0\xa0\xa0\xa0"'
        'aria-label="\xa0\xa0\xa0\xa0\xa0 Moped \xa0\xa0\xa0\xa0\xa0"'
        'aria-label="\xa0\xa0\xa0\xa0\xa0 Motor Car \xa0\xa0\xa0\xa0\xa0"'
    )
    assert _parse_vehicle_class_columns(html_fragment) == ["M-Cycle/Scooter", "Moped", "Motor Car"]


def test_parse_vehicle_class_columns_empty_when_no_headers_present():
    assert _parse_vehicle_class_columns("<div>no headers here</div>") == []


def test_parse_vehicle_class_columns_ignores_paginator_footer_labels():
    # Real responses include a ui-paginator footer *after* the thead, with
    # its own aria-labels (Pagination/First Page/Previous Page/Next Page/
    # Last Page) that aren't real vehicle classes -- confirmed live against
    # VAHAN, this was inflating the parsed class count and desyncing every
    # row's cell alignment (see _parse_vehicle_class_columns).
    html_fragment = (
        "<thead>"
        'aria-label="S No"'
        'aria-label="Vehicle Class "'
        'aria-label="\xa0\xa0\xa0\xa0\xa0TOTAL\xa0\xa0\xa0\xa0\xa0"'
        'aria-label="\xa0\xa0\xa0\xa0\xa0 M-Cycle/Scooter \xa0\xa0\xa0\xa0\xa0"'
        'aria-label="\xa0\xa0\xa0\xa0\xa0 Motor Car \xa0\xa0\xa0\xa0\xa0"'
        "</thead>"
        '<div class="ui-paginator" aria-label="Pagination">'
        '<a aria-label="First Page"></a><a aria-label="Previous Page"></a>'
        '<a aria-label="Next Page"></a><a aria-label="Last Page"></a>'
        "</div>"
    )
    assert _parse_vehicle_class_columns(html_fragment) == ["M-Cycle/Scooter", "Motor Car"]


def test_parse_header_layout_handles_grouped_two_row_header_with_total_last():
    # Wide class sets make VAHAN switch to a grouped header: row 1 has S No/
    # Maker/TOTAL as rowspan=2, plus a colspan="3" "Vehicle Class" group
    # caption; row 2 has the 3 real leaf class headers, which slot into that
    # group's position. Body rows follow the same order, so TOTAL ends up
    # last -- not third. Confirmed live against VAHAN, 2026-08-26.
    html_fragment = (
        "<thead>"
        '<tr role="row">'
        '<th aria-label="S No" rowspan="2"></th>'
        '<th aria-label="Maker" rowspan="2"></th>'
        '<th aria-label="Vehicle Class " colspan="3"></th>'
        '<th aria-label="\xa0\xa0\xa0\xa0\xa0TOTAL\xa0\xa0\xa0\xa0\xa0" rowspan="2"></th>'
        "</tr>"
        '<tr role="row">'
        '<th aria-label="\xa0\xa0\xa0\xa0\xa0 M-Cycle/Scooter \xa0\xa0\xa0\xa0\xa0"></th>'
        '<th aria-label="\xa0\xa0\xa0\xa0\xa0 Moped \xa0\xa0\xa0\xa0\xa0"></th>'
        '<th aria-label="\xa0\xa0\xa0\xa0\xa0 Motor Car \xa0\xa0\xa0\xa0\xa0"></th>'
        "</tr>"
        "</thead>"
    )
    class_names, total_before_classes = _parse_header_layout(html_fragment)
    assert class_names == ["M-Cycle/Scooter", "Moped", "Motor Car"]
    assert total_before_classes is False


def test_parse_maker_category_table_rows_reorders_when_total_is_last():
    # Same two rows/three classes as the flat-header test above, but laid
    # out as [S No, Maker, class1, class2, class3, Total] -- the grouped-
    # header body order -- and must come back normalized the same way.
    cells = [
        _label_cell(0, "1"),
        _label_cell(1, "ACTION CONSTRUCTION EQUIPMENT LTD."),
        _label_cell(2, "0"),
        _label_cell(3, "0"),
        _label_cell(4, "5"),
        _label_cell(5, "5"),
        _label_cell(6, "2"),
        _label_cell(7, "HONDA MOTORCYCLE"),
        _label_cell(8, "1,00,000"),
        _label_cell(9, "20,000"),
        _label_cell(10, "0"),
        _label_cell(11, "1,20,000"),
    ]
    html_fragment = "".join(cells)
    rows = _parse_maker_category_table_rows(html_fragment, num_class_cols=3, total_before_classes=False)
    assert rows == [
        ["1", "ACTION CONSTRUCTION EQUIPMENT LTD.", "5", "0", "0", "5"],
        ["2", "HONDA MOTORCYCLE", "1,20,000", "1,00,000", "20,000", "0"],
    ]


def test_parse_maker_category_table_rows_extracts_maker_and_class_counts():
    # Two rows, three class columns: [S No, Maker, Total, class1, class2, class3]
    cells = [
        _label_cell(0, "1"),
        _label_cell(1, "ACTION CONSTRUCTION EQUIPMENT LTD."),
        _label_cell(2, "5"),
        _label_cell(3, "0"),
        _label_cell(4, "0"),
        _label_cell(5, "5"),
        _label_cell(6, "2"),
        _label_cell(7, "HONDA MOTORCYCLE"),
        _label_cell(8, "1,20,000"),
        _label_cell(9, "1,00,000"),
        _label_cell(10, "20,000"),
        _label_cell(11, "0"),
    ]
    html_fragment = "".join(cells)
    rows = _parse_maker_category_table_rows(html_fragment, num_class_cols=3)
    assert rows == [
        ["1", "ACTION CONSTRUCTION EQUIPMENT LTD.", "5", "0", "0", "5"],
        ["2", "HONDA MOTORCYCLE", "1,20,000", "1,00,000", "20,000", "0"],
    ]
