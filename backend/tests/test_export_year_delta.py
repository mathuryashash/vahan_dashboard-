"""The year-delta export hand-encodes CSV for COPY ... WITH (FORMAT csv).

The distinction that matters, and that a row-count check cannot see: NULL is
an UNQUOTED empty field, a genuine empty string is a QUOTED one. Emitting
both unquoted silently turns '' into NULL on the target, which moves a row
between scrape passes -- and this schema's natural-key index is built on
COALESCE(maker,'') / COALESCE(fuel_type,''), so the two are not
interchangeable. Confirmed against a live COPY: '""' loads as an empty
string, a bare empty field loads as NULL.
"""
import pytest

from app.scripts.export_year_delta import _csv


@pytest.mark.parametrize("value,expected", [
    (None, ""),                  # NULL: unquoted empty
    ("", '""'),                  # empty string: quoted, NOT the same as NULL
    ("HERO MOTOCORP LTD", "HERO MOTOCORP LTD"),
    ("MARUTI, LTD", '"MARUTI, LTD"'),          # comma forces quoting
    ('SAID "HELLO"', '"SAID ""HELLO"""'),      # quotes double up
    ("LINE1\nLINE2", '"LINE1\nLINE2"'),        # newline forces quoting
    ("LINE1\r\nLINE2", '"LINE1\r\nLINE2"'),
    (True, "true"),
    (False, "false"),
    (0, "0"),                    # a zero count must not read as empty/NULL
    # Backslash is literal in CSV format (only TEXT format treats it as an
    # escape), so it must pass through untouched.
    ("A\\B", "A\\B"),
])
def test_csv_encoding(value, expected):
    assert _csv(value) == expected


def test_null_and_empty_string_are_not_interchangeable():
    # The specific regression: these two must never produce the same field.
    assert _csv(None) != _csv("")
