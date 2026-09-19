"""Notes for maker names VAHAN still records long after the company changed.

VAHAN keeps the maker name as it was at registration, so a renamed or exited
brand goes on appearing under its old name. Hero Honda registrations continue
into 2026, fifteen years after it became Hero MotoCorp -- re-registrations and
inter-state transfers of vehicles sold before the rename. General Motors and
Ford do the same. So "no data in recent years" cannot identify a defunct
brand, and this is a short curated list instead, keyed on VAHAN's own
spelling (measured against maker_category_totals and registrations).

A category's brand list drops these from recent years by its volume floor --
Hero Honda has 8 registrations in 2026 -- but "All Brands" lists every
company, and in historical years Hero Honda was the market leader. Either way
the note is what tells a reader what became of it.
"""
import re


def normalize(name: str) -> str:
    """VAHAN spells some names with stray double spaces ("HERO HONDA MOTORS  LTD");
    compare on a collapsed, upper-cased form so a note cannot silently miss."""
    return re.sub(r"\s+", " ", name).strip().upper()


_NOTES = {
    normalize(name): note
    for name, note in {
        "HERO HONDA MOTORS  LTD": "Renamed Hero MotoCorp in 2011",
        "KINETIC HONDA MOTOR LIMITED": "Former Kinetic-Honda joint venture; now Kinetic Motor",
        "GENERAL MOTORS INDIA PVT LTD": "Exited the Indian market in 2017",
        "M/S GENERAL MOTORS LLC": "Exited the Indian market in 2017",
        "CHEVROLET SALES INDIA PVT LTD": "General Motors brand; exited India in 2017",
        "FORD INDIA PVT LTD": "Ended Indian production in 2022",
        "LML LIMITED": "Ceased production",
        # One company under two spellings, so its numbers are split between them.
        "HERO ELECTRIC VEHICLE PVT LTD": "Also recorded as HERO ELECTRIC VEHICLES PVT. LTD",
        "HERO ELECTRIC VEHICLES PVT. LTD": "Also recorded as HERO ELECTRIC VEHICLE PVT LTD",
    }.items()
}


def note_for(maker: str) -> str | None:
    return _NOTES.get(normalize(maker))
