"""Tests for the xlsx-export path that replaced AJAX pagination in
scrape_pivot_table / scrape_yaxis_by_vehicle_class_table. VAHAN's paginated
AJAX fetch_table_page occasionally re-served a stale duplicate of the
previous page under sustained load (confirmed live, corrupted/lost data in
production -- see vahan_scraper.py's SessionExpiredError and
_iter_table_pages docstrings). The table's own "Download EXCEL file" button
dumps the whole report in one response instead, with no pagination at all.
"""
import io
import zipfile

from scraper.vahan_scraper import (
    _exported_data_start,
    _exported_header_row,
    parse_exported_xlsx,
)

_XLSX_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _build_xlsx(shared_strings: list[str], rows: list[list[tuple[int, str] | None]]) -> bytes:
    """Minimal xlsx matching VAHAN's real export shape: every cell is a
    shared-string reference, blank cells are simply omitted from the row's
    <c> elements (not emitted empty) -- `rows` is [[(col_index, string_ref_index), ...], ...]
    with `None` gaps meaning "no cell at all", mirroring that."""
    sst_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<sst xmlns="{_XLSX_NS}" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{s}</t></si>" for s in shared_strings)
        + "</sst>"
    )
    sheet_rows = []
    for r_idx, cells in enumerate(rows, start=1):
        cell_xml = "".join(
            f'<c r="{chr(65 + col)}{r_idx}" t="s"><v>{ref}</v></c>' for col, ref in cells
        )
        sheet_rows.append(f'<row r="{r_idx}">{cell_xml}</row>')
    sheet_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<worksheet xmlns="{_XLSX_NS}"><sheetData>' + "".join(sheet_rows) + "</sheetData></worksheet>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/sharedStrings.xml", sst_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


def test_parse_exported_xlsx_preserves_column_position_across_blank_cells():
    # shared strings: 0="1", 1="MAKER A", 2="5", 3="0"
    strings = ["1", "MAKER A", "5", "0"]
    # Row has cells at columns 0,1,2 but skips column 3 entirely (blank,
    # omitted from the XML) -- must come back as "" at index 3, not shift
    # column 4 (if any) left.
    xlsx = _build_xlsx(strings, [[(0, 0), (1, 1), (2, 2)]])
    rows = parse_exported_xlsx(xlsx)
    assert rows == [["1", "MAKER A", "5"]]


def test_parse_exported_xlsx_handles_gap_before_a_later_column():
    strings = ["1", "MAKER A", "9"]
    # Column 0 and column 2 present, column 1 (Maker) blank/omitted.
    xlsx = _build_xlsx(strings, [[(0, 0), (2, 2)]])
    rows = parse_exported_xlsx(xlsx)
    assert rows == [["1", "", "9"]]


def test_exported_data_start_finds_first_numeric_s_no_row():
    rows = [
        ["Title row"],
        ["S No", "Maker", "TOTAL"],
        ["1", "MAKER A", "5"],
        ["2", "MAKER B", "3"],
    ]
    assert _exported_data_start(rows) == 2


def test_exported_data_start_returns_len_when_no_data_rows():
    rows = [["Title"], ["S No", "Maker", "TOTAL"]]
    assert _exported_data_start(rows) == len(rows)


def test_exported_header_row_skips_blank_spacer_rows():
    rows = [
        ["Title"],
        ["", "", "JAN", "FEB", ""],
        [],
        ["1", "MAKER A", "2", "1", "3"],
    ]
    data_start = _exported_data_start(rows)
    assert _exported_header_row(rows, data_start) == ["", "", "JAN", "FEB", ""]
