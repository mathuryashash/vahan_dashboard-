from datetime import datetime, timezone

from app.api.v1.endpoints.summary import _period_days


def test_partial_month_counts_only_scraped_days():
    scraped = datetime(2026, 10, 9, 1, 36, tzinfo=timezone.utc)  # 07:06 IST, 9 Oct
    assert _period_days(2026, 10, 10, 10, scraped) == 9
    assert _period_days(2026, 8, 10, 10, scraped) == 31
    assert _period_days(2026, None, 10, 10, scraped) == 273 + 9  # Jan-Sep + 9 days of Oct
    assert _period_days(2025, None, 12, None, scraped) == 365
