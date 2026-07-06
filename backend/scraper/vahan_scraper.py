import asyncio
from playwright.async_api import async_playwright
import csv
import os
import sys

ANALYTICS_URL = (
    "https://analytics.parivahan.gov.in/analytics/publicdashboard/vahan?lang=en"
)
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./data")

MONTHS = [
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
]
VEHICLE_CLASSES = [
    "Two-Wheeler",
    "Motor Car/Jeep/Taxi",
    "Mini Bus",
    "Bus",
    "Three-Wheeler",
    "Light Motor Vehicle",
    "Medium Bus",
    "Medium Truck",
    "Heavy Truck",
    "Tractor",
    "Construction Equipment",
    "Other",
]
STATES = [
    ("AN", "Andaman & Nicobar Island"),
    ("AP", "Andhra Pradesh"),
    ("AR", "Arunachal Pradesh"),
    ("AS", "Assam"),
    ("BR", "Bihar"),
    ("CH", "Chandigarh"),
    ("CG", "Chhattisgarh"),
    ("DN", "UT of DNH and DD"),
    ("DL", "Delhi"),
    ("GA", "Goa"),
    ("GJ", "Gujarat"),
    ("HP", "Himachal Pradesh"),
    ("HR", "Haryana"),
    ("JH", "Jharkhand"),
    ("JK", "Jammu and Kashmir"),
    ("KA", "Karnataka"),
    ("KL", "Kerala"),
    ("LD", "Ladakh"),
    ("LA", "Lakshadweep"),
    ("MH", "Maharashtra"),
    ("ML", "Meghalaya"),
    ("MN", "Manipur"),
    ("MP", "Madhya Pradesh"),
    ("MZ", "Mizoram"),
    ("NL", "Nagaland"),
    ("OD", "Odisha"),
    ("PB", "Punjab"),
    ("PY", "Puducherry"),
    ("RJ", "Rajasthan"),
    ("SK", "Sikkim"),
    ("TS", "Telangana"),
    ("TN", "Tamil Nadu"),
    ("TR", "Tripura"),
    ("UK", "Uttarakhand"),
    ("UP", "Uttar Pradesh"),
    ("WB", "West Bengal"),
]

XAXIS_OPTIONS = ["Month Wise", "Fuel", "Norms"]
YAXIS_OPTIONS = ["Vehicle Class", "Maker", "Fuel"]


async def scrape_vahan():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print(f"[Scraper] Starting VAHAN data extraction...")
    print(f"[Scraper] Target URL: {ANALYTICS_URL}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        records = 0
        for xaxis in XAXIS_OPTIONS:
            for yaxis in YAXIS_OPTIONS:
                for state_code, state_name in STATES:
                    try:
                        await page.goto(
                            ANALYTICS_URL, wait_until="networkidle", timeout=30000
                        )
                        await page.wait_for_timeout(2000)

                        await page.select_option('select[name*="state"]', state_code)
                        await asyncio.sleep(1)

                        try:
                            rows = await page.query_selector_all("table tbody tr")
                            for row in rows:
                                cells = await row.query_selector_all("td")
                                if len(cells) >= 3:
                                    label = await cells[0].inner_text()
                                    count_text = await cells[1].inner_text()
                                    try:
                                        count = int(count_text.strip().replace(",", ""))
                                        records += 1
                                    except ValueError:
                                        pass
                        except Exception:
                            pass

                        await asyncio.sleep(3)

                    except Exception as e:
                        print(f"  [WARN] {state_name}: {e}")
                        continue

        await browser.close()

    print(f"[Scraper] Extraction complete. {records} data points collected.")
    return records


if __name__ == "__main__":
    asyncio.run(scrape_vahan())
