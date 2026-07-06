import os
import sqlite3
from datetime import datetime

DB_PATH = "./data/vahan.db"
DATA_DIR = "./data"


def run_scraper():
    print(f"[Scraper] Starting scrape at {datetime.utcnow()}")
    os.makedirs(DATA_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS states (
            state_code TEXT PRIMARY KEY,
            state_name TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rtos (
            rto_code TEXT PRIMARY KEY,
            rto_name TEXT NOT NULL,
            state_code TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state_code TEXT,
            state_name TEXT,
            rto_code TEXT,
            rto_name TEXT,
            month INTEGER,
            year INTEGER,
            day INTEGER,
            vehicle_class TEXT,
            maker TEXT,
            vehicle_model TEXT,
            fuel_type TEXT,
            norms_type TEXT,
            count INTEGER,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reg_year ON registrations(year)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reg_month ON registrations(month)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reg_day ON registrations(day)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_reg_model ON registrations(vehicle_model)
    """)

    states_data = [
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
    cursor.executemany(
        "INSERT OR REPLACE INTO states (state_code, state_name) VALUES (?, ?)",
        states_data,
    )
    conn.commit()

    print(
        "[Scraper] Database initialized. Note: Full Playwright scraping from VAHAN requires running on a server with network access to analytics.parivahan.gov.in"
    )
    print(
        "[Scraper] For production scraping, deploy the scraper separately with proper network access and authentication handling."
    )

    conn.close()
    print(f"[Scraper] Done. Total records in DB: checking...")
    conn2 = sqlite3.connect(DB_PATH)
    c = conn2.execute("SELECT COUNT(*) FROM registrations").fetchone()
    print(f"[Scraper] Current registration records: {c[0]}")
    conn2.close()
