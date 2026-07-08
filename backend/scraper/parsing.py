import re

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4,
    "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
    "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_STATE_OPTION_RE = re.compile(r"^(.*)\((\d+)\)$")
_RTO_OPTION_RE = re.compile(r"^(.*?)\s*-\s*([A-Z]{2}\d+[A-Z]*)\(\s*[\d-]+-[A-Z]{3}-\d{4}\s*\)$")


def parse_state_option(text: str) -> dict | None:
    """Parse a VAHAN4 state dropdown option like 'Delhi(16)' into name + RTO count.

    Returns None for the aggregate 'All Vahan4 Running States (36/36)' row —
    its parenthesized content has a slash, so it never matches the digits-only pattern.
    """
    match = _STATE_OPTION_RE.match(text.strip())
    if not match:
        return None
    return {"state_name": match.group(1).strip(), "rto_count": int(match.group(2))}


def parse_rto_option(text: str) -> dict | None:
    """Parse a VAHAN4 RTO dropdown option like
    'OLD DELHI (MALL ROAD) - DL1( 12-OCT-2015 )' into name + code.

    Returns None for the aggregate 'All Vahan4 Running Office(...)' row.
    """
    match = _RTO_OPTION_RE.match(text.strip())
    if not match:
        return None
    return {"rto_name": match.group(1).strip(), "rto_code": match.group(2).strip()}


def parse_count(text: str) -> int:
    """Parse an Indian comma-grouped count like '1,23,456' into an int. Blank/'-' -> 0."""
    cleaned = text.strip().replace(",", "")
    if not cleaned or cleaned == "-":
        return 0
    return int(cleaned)
