"""Parsing tests for the Maker x Vehicle Class pivot (X-axis=Vehicle Class
instead of Month Wise). Fixtures mirror the real response shape captured
live against VAHAN this session: aria-label headers are
['S No', 'Vehicle Class ' (a static VAHAN UI label, not real data), 'TOTAL',
<class1>, <class2>, ...], and TOTAL sits right after the row label -- before
the per-class columns, unlike the month pivot where TOTAL is last.
"""
from scraper.vahan_scraper import (
    TABLE_ID,
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
