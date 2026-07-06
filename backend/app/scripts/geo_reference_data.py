import re

# Verified against mha.gov.in/en/page/zonal-council (Ministry of Home Affairs).
# Council membership is exact for the 5 official Zonal Councils + the North Eastern
# Council. States/UTs with no council membership (Andaman & Nicobar, Lakshadweep,
# Ladakh, Telangana post-formation) are assigned to the geographically/administratively
# closest zone for dashboard grouping purposes -- this is a practical extension, not an
# official council membership claim.
ZONE_BY_STATE_CODE = {
    # Northern Zonal Council
    "HR": "NORTH", "HP": "NORTH", "JK": "NORTH", "PB": "NORTH",
    "RJ": "NORTH", "DL": "NORTH", "CH": "NORTH",
    "LA": "NORTH",  # Ladakh -- extension, carved from J&K, no council yet
    # Central Zonal Council
    "CG": "CENTRAL", "UK": "CENTRAL", "UP": "CENTRAL", "MP": "CENTRAL",
    # Eastern Zonal Council
    "BR": "EAST", "JH": "EAST", "OD": "EAST", "WB": "EAST",
    # Western Zonal Council
    "GA": "WEST", "GJ": "WEST", "MH": "WEST", "DN": "WEST",
    # Southern Zonal Council
    "AP": "SOUTH", "KA": "SOUTH", "KL": "SOUTH", "TN": "SOUTH", "PY": "SOUTH",
    "TS": "SOUTH",  # Telangana -- extension, formed 2014 after council list above
    # North Eastern Council (separate from the 5 Zonal Councils)
    "AS": "NORTHEAST", "AR": "NORTHEAST", "MN": "NORTHEAST", "TR": "NORTHEAST",
    "MZ": "NORTHEAST", "ML": "NORTHEAST", "NL": "NORTHEAST", "SK": "NORTHEAST",
    # Island territories -- extension, not part of any council
    "AN": "SOUTH",  # Andaman & Nicobar -- grouped with South for proximity
    "LD": "WEST",   # Lakshadweep -- grouped with West for proximity
}

ZONES = [
    ("NORTH", "Northern Zone"),
    ("CENTRAL", "Central Zone"),
    ("EAST", "Eastern Zone"),
    ("WEST", "Western Zone"),
    ("SOUTH", "Southern Zone"),
    ("NORTHEAST", "North Eastern Zone"),
]

# RTO.csv (github.com/kishorek/India-Codes) uses some legacy/alternate state prefixes.
_LEGACY_STATE_CODE_MAP = {
    "OR": "OD",  # Odisha
    "UA": "UK",  # Uttarakhand (duplicate legacy prefix)
    "DD": "DN",  # Daman and Diu -> merged into existing "UT of DNH and DD"
}


def normalize_state_code(raw_prefix: str) -> str:
    return _LEGACY_STATE_CODE_MAP.get(raw_prefix, raw_prefix)


def split_district_names(place_field: str) -> list[str]:
    parts = re.split(r"[/,]", place_field)
    return [p.strip() for p in parts if p.strip()]
