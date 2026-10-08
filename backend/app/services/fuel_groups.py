"""The ONE place raw VAHAN fuel labels are folded into the six fuel groups the
Maker Lookup / Top Makers panels offer.

VAHAN publishes ~37 raw fuel strings ("PETROL(E20)/CNG", "STRONG HYBRID EV",
"DUAL DIESEL/LNG", ...). Offering all of them made users pick combinations
that hold nothing ("HERO MOTOCORP x DIESEL" -> an error). The panels now offer
six groups and sum the raw labels inside each one server-side.

First matching rule wins, in this order, so a multi-fuel label lands in the
group that says what is different about it:

| order | group    | a raw label containing ...              | examples                                          |
|-------|----------|-----------------------------------------|---------------------------------------------------|
| 1     | Hybrid   | HYBRID                                  | STRONG HYBRID EV, PLUG-IN HYBRID EV, PETROL/HYBRID, DIESEL/HYBRID, PETROL(E20)/HYBRID/CNG |
| 2     | Electric | ELECTRIC, PURE EV, FUEL CELL            | ELECTRIC(BOV), PURE EV, FUEL CELL HYDROGEN        |
| 3     | CNG/LPG  | CNG, LPG, LNG                           | CNG ONLY, PETROL/CNG, PETROL(E20)/CNG, LPG ONLY, PETROL/LPG, DUAL DIESEL/CNG, DUAL DIESEL/LNG, LNG, HCNG, BIO-CNG/BIO-GAS |
| 4     | Diesel   | DIESEL                                  | DIESEL, FLEX-FUEL(BIO-DIESEL)                     |
| 5     | Petrol   | PETROL                                  | PETROL, PETROL(E20), PETROL/ETHANOL, PETROL/METHANOL |
| 6     | Other    | anything else                           | ETHANOL(E100), FLEX-FUEL(ETHANOL), METHANOL, DI-METHYL ETHER, HYDROGEN(ICE), SOLAR, NOT APPLICABLE |

Hybrid before Electric: "STRONG HYBRID EV" is a hybrid, not a battery EV
(same priority as query_filters.fuel_category). CNG/LPG before Diesel/Petrol:
a bi-fuel PETROL/CNG car is sold and counted as a CNG car.
"""
from __future__ import annotations

FUEL_GROUPS: tuple[str, ...] = ("Petrol", "Diesel", "CNG/LPG", "Electric", "Hybrid", "Other")

_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hybrid", ("HYBRID",)),
    ("Electric", ("ELECTRIC", "PURE EV", "FUEL CELL")),
    ("CNG/LPG", ("CNG", "LPG", "LNG")),
    ("Diesel", ("DIESEL",)),
    ("Petrol", ("PETROL",)),
)

# Every raw label seen in the stored tables (maker_fuel_totals,
# fuel_category_totals, registrations fuel pass, state_month_category_fuel_totals)
# plus the analytics portal's static enum. Used by tests and the API's
# /fuel-groups listing; group_of() handles unseen labels by rule anyway.
KNOWN_RAW_FUELS: tuple[str, ...] = (
    "BIO-CNG/BIO-GAS", "CNG ONLY", "DI-METHYL ETHER", "DIESEL", "DIESEL/HYBRID",
    "DUAL DIESEL/BIO CNG", "DUAL DIESEL/CNG", "DUAL DIESEL/LNG", "ELECTRIC(BOV)",
    "ETHANOL(E100)", "FLEX-FUEL(BIO-DIESEL)", "FLEX-FUEL(ETHANOL)", "FUEL CELL HYDROGEN",
    "HCNG", "HYDROGEN(ICE)", "LNG", "LPG ONLY", "METHANOL", "NOT APPLICABLE", "PETROL",
    "PETROL(E20)", "PETROL(E20)/CNG", "PETROL(E20)/HYBRID", "PETROL(E20)/HYBRID/CNG",
    "PETROL(E20)/LPG", "PETROL/CNG", "PETROL/ETHANOL", "PETROL/HYBRID", "PETROL/HYBRID/CNG",
    "PETROL/LPG", "PETROL/METHANOL", "PLUG-IN HYBRID EV", "PURE EV", "SOLAR", "STRONG HYBRID EV",
)


def group_of(raw_fuel: str | None) -> str:
    """Fuel group for one raw VAHAN fuel label (case-insensitive)."""
    upper = (raw_fuel or "").upper()
    for group, needles in _RULES:
        if any(n in upper for n in needles):
            return group
    return "Other"


def normalize_group(value: str | None) -> str | None:
    """Accept a group name case-insensitively ('cng/lpg', 'ELECTRIC');
    None/'' -> None. Raises ValueError for anything else."""
    if not value:
        return None
    for g in FUEL_GROUPS:
        if g.lower() == value.strip().lower():
            return g
    raise ValueError(value)


def mapping_table() -> list[dict]:
    """[{group, raw_labels}] over KNOWN_RAW_FUELS, in FUEL_GROUPS order."""
    return [
        {"group": g, "raw_labels": sorted(f for f in KNOWN_RAW_FUELS if group_of(f) == g)}
        for g in FUEL_GROUPS
    ]
