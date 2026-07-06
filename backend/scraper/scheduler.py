import asyncio
import subprocess
import sys
from datetime import datetime, time
import time as time_module

SCRAPE_INTERVAL_HOURS = 24
SCRAPE_HOUR = 1  # 1:30 AM IST
SCRAPE_MINUTE = 30


def run_scraper():
    print(f"[{datetime.now()}] Running VAHAN scraper...")
    try:
        result = subprocess.run(
            [sys.executable, "vahan_scraper.py"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"Scraper failed: {result.stderr}")
    except Exception as e:
        print(f"Scraper error: {e}")


def next_run():
    now = datetime.now()
    next_time = datetime.combine(now.date(), time(SCRAPE_HOUR, SCRAPE_MINUTE))
    if next_time <= now:
        next_time = next_time.replace(day=now.day + 1)
    return next_time


async def main():
    print(
        f"[Scheduler] VAHAN scraper scheduler started. Running daily at {SCRAPE_HOUR}:{SCRAPE_MINUTE:02d} IST"
    )
    while True:
        next_scrape = next_run()
        seconds = (next_scrape - datetime.now()).total_seconds()
        if seconds > 0:
            print(
                f"[Scheduler] Next scrape scheduled at {next_scrape.strftime('%Y-%m-%d %H:%M IST')} (in {seconds / 3600:.1f}h)"
            )
        await asyncio.sleep(max(seconds, 60))
        run_scraper()


if __name__ == "__main__":
    asyncio.run(main())
