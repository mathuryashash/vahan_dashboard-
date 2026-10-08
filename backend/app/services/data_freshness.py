"""What the DATA says about how fresh it is -- read-only, restart-proof.

settings.LAST_UPDATED is in-process memory: None after every restart even with
a full database (the header showed "NEVER SYNCED" on every boot), and the
scheduler's 5h timer was reset by every restart so it never fired. Both now
fall back to what is actually stored:

- last_scrape_at: newest registrations.recorded_at in the newest scraped
  (year, month), or scrape_quality_log.checked_at (written after every full
  cycle) -- whichever is later. Bounded to one (year, month) slice so it uses
  idx_reg_year_month_supp_count (~160ms cold) instead of a 6-12s scan.
- latest_scraped_month: newest (year, month) with any row.
- last_complete_month: the newest month that was fully over when it was last
  scraped. A month scraped on the 19th is partial no matter what today's date
  is -- the data froze on 2026-09-19, so September is partial in October.

Cached for a short TTL (cleared with every TTLCache after a successful scrape).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import TTLCache

_TTL_SECONDS = 600
# A TTLCache so TTLCache.clear_all() (tests, and after every successful
# scrape -- see scraper_service.run_scraper) resets it with the rest.
_cache = TTLCache(_TTL_SECONDS)


@dataclass(frozen=True)
class Freshness:
    last_scrape_at: datetime | None  # tz-aware UTC; newest write of any kind
    latest_year: int | None
    latest_month: int | None
    # Newest scrape_quality_log.checked_at -- written only after a FULL cycle
    # succeeded (scraper_service.run_scraper). A crashed run still bumps
    # recorded_at, so the scheduler measures age from this when present.
    last_success_at: datetime | None = None

    @property
    def last_updated_str(self) -> str | None:
        """Same format scraper_service writes to settings.LAST_UPDATED."""
        return self.last_scrape_at.strftime("%Y-%m-%d %H:%M UTC") if self.last_scrape_at else None

    def last_complete_month(self) -> tuple[int, int] | None:
        return last_complete_month(self.latest_year, self.latest_month, self.last_scrape_at)

    def age_seconds(self, now: datetime | None = None) -> float | None:
        """Age of the last SUCCESSFUL scrape (falls back to the newest write)."""
        ref = self.last_success_at or self.last_scrape_at
        if ref is None:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - ref).total_seconds())

    def complete_through(self, year: int, max_month: int | None) -> int | None:
        """Last COMPLETE month of `year` given that year's newest stored month.
        Years before the newest scraped year are complete through their newest
        month; the newest year is cut at last_complete_month(). 0 = none."""
        if max_month is None:
            return None
        if self.latest_year is None or year < self.latest_year:
            return max_month
        lcm = self.last_complete_month()
        if lcm is None:
            return max_month
        if lcm[0] < year:
            return 0
        return min(max_month, lcm[1])

    def partial_month(self, year: int) -> int | None:
        """The month of `year` that is stored but was still in progress when
        scraped, or None."""
        if year != self.latest_year or self.latest_month is None:
            return None
        lcm = self.last_complete_month()
        if lcm == (self.latest_year, self.latest_month):
            return None
        return self.latest_month


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    # get_freshness reads recorded_at / checked_at already cast to timestamptz
    # in SQL (see there), so DB values arrive tz-aware. A naive value only
    # reaches here from callers/tests passing literal datetimes; treat as UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def last_complete_month(year: int | None, month: int | None,
                        scraped_at: datetime | None) -> tuple[int, int] | None:
    """(year, month) of the newest month that had fully ended when scraped.

    If the newest stored month is M of year Y and it was scraped on or after
    the 1st of M+1, M is complete; otherwise M-1 is the last complete one.
    Without a scrape timestamp the newest month is assumed partial (the
    conservative choice: a YoY that cuts one month early is still a like-for-
    like comparison; one that includes a half month is not)."""
    if year is None or month is None:
        return None
    scraped_at = _as_utc(scraped_at)
    if scraped_at is not None:
        nxt_y, nxt_m = (year + 1, 1) if month == 12 else (year, month + 1)
        if (scraped_at.year, scraped_at.month) >= (nxt_y, nxt_m):
            return year, month
    return (year - 1, 12) if month == 1 else (year, month - 1)


async def get_freshness(db: AsyncSession, *, use_cache: bool = True) -> Freshness:
    # recorded_at / checked_at are `timestamp WITHOUT time zone` filled by
    # func.now(), i.e. the DB server's wall clock in its session TimeZone --
    # Asia/Calcutta on the native install, UTC in docker. Treating the naive
    # value as UTC made last_updated 5h30m too fresh (and the scheduler's
    # catch-up 5h30m late) on IST servers. `::timestamptz` makes Postgres
    # interpret the wall clock in the session TimeZone, which is the zone
    # func.now() wrote it in, so the value comes back as a correct instant.
    if use_cache:
        cached = _cache.get("freshness")
        if cached is not None:
            return cached
    # Captured before the queries: a TTLCache.clear_all() (post-scrape) that
    # lands while they run means this result predates the new data -- return
    # it, but never cache it (same pattern as stored_live_service).
    gen = TTLCache.generation
    # `::timestamptz` is Postgres-only syntax; the SQLite dev mode reads the
    # naive value as-is (it has no session zone; _as_utc treats it as UTC).
    is_pg = db.bind.dialect.name == "postgresql"
    cast = "::timestamptz" if is_pg else ""
    latest = (await db.execute(text(
        "SELECT year, (SELECT max(month) FROM registrations r2 WHERE r2.year = r.year) "
        "FROM (SELECT max(year) AS year FROM registrations) r"
    ))).first()
    year, month = (latest[0], latest[1]) if latest else (None, None)
    rec = None
    if year is not None and month is not None:
        rec = _parse_ts((await db.execute(text(
            f"SELECT max(recorded_at){cast} FROM registrations WHERE year = :y AND month = :m"
        ), {"y": year, "m": month})).scalar())
    try:
        chk = _parse_ts((await db.execute(text(f"SELECT max(checked_at){cast} FROM scrape_quality_log"))).scalar())
    except Exception:  # table missing on an old schema -- recorded_at alone is fine
        chk = None
    candidates = [d for d in (_as_utc(rec), _as_utc(chk)) if d is not None]
    value = Freshness(max(candidates) if candidates else None, year, month, _as_utc(chk))
    if gen == TTLCache.generation:
        _cache.set("freshness", value)
    return value


def _parse_ts(value) -> datetime | None:
    """SQLite returns max(timestamp) as a string; Postgres as a datetime."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
