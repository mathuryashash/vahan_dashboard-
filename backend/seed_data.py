"""Seed the database with realistic sample data for demo/testing."""

import sqlite3
import os
import random
from datetime import datetime

os.makedirs("data", exist_ok=True)
conn = sqlite3.connect("data/vahan.db")
c = conn.cursor()

c.execute("DROP TABLE IF EXISTS registrations")
c.execute("""CREATE TABLE IF NOT EXISTS states (
    state_code TEXT PRIMARY KEY, state_name TEXT NOT NULL)""")
c.execute("""CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_code TEXT, state_name TEXT, rto_code TEXT, rto_name TEXT,
    month INTEGER, year INTEGER, day INTEGER, vehicle_class TEXT, maker TEXT,
    vehicle_model TEXT, fuel_type TEXT, norms_type TEXT, count INTEGER,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

c.execute("CREATE INDEX IF NOT EXISTS idx_reg_year ON registrations(year)")
c.execute("CREATE INDEX IF NOT EXISTS idx_reg_month ON registrations(month)")
c.execute("CREATE INDEX IF NOT EXISTS idx_reg_day ON registrations(day)")
c.execute("CREATE INDEX IF NOT EXISTS idx_reg_model ON registrations(vehicle_model)")

c.execute("DELETE FROM registrations")

states = [
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
c.executemany("INSERT OR REPLACE INTO states VALUES (?,?)", states)

vehicle_classes = [
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

class_shares = {
    "Two-Wheeler": 0.45,
    "Motor Car/Jeep/Taxi": 0.30,
    "Mini Bus": 0.02,
    "Bus": 0.03,
    "Three-Wheeler": 0.05,
    "Light Motor Vehicle": 0.04,
    "Medium Bus": 0.01,
    "Medium Truck": 0.02,
    "Heavy Truck": 0.03,
    "Tractor": 0.03,
    "Construction Equipment": 0.01,
    "Other": 0.01,
}

makers_by_class = {
    "Two-Wheeler": [
        "Honda",
        "TVS",
        "Hero",
        "Bajaj",
        "Suzuki",
        "Royal Enfield",
        "YAMAHA",
        "KTM",
    ],
    "Motor Car/Jeep/Taxi": [
        "Maruti Suzuki",
        "Hyundai",
        "Tata",
        "Mahindra",
        "Kia",
        "Toyota",
        "Honda Cars",
        "Skoda",
    ],
    "Mini Bus": ["Ashok Leyland", "Tata", "Mahindra", "Eicher"],
    "Bus": ["Ashok Leyland", "Tata Motors", "Mahindra", "Eicher", "BharatBenz"],
    "Three-Wheeler": ["Piaggio", "TVS", "Mahindra", "Bajaj"],
    "Light Motor Vehicle": ["Tata", "Mahindra", "Ashok Leyland", "Eicher"],
    "Medium Bus": ["Ashok Leyland", "Tata", "Eicher"],
    "Medium Truck": ["Tata", "Ashok Leyland", "Eicher", "Mahindra"],
    "Heavy Truck": ["Tata", "Ashok Leyland", "Eicher", "BharatBenz", "M&M"],
    "Tractor": ["Mahindra", "Sonalika", "Escorts", "John Deere", "Tafe"],
    "Construction Equipment": ["JCB", "L&T", "Escorts", "Caterpillar", "Komatsu"],
    "Other": ["Various", "Unknown", "Others"],
}

models_by_maker = {
    # Two-Wheeler
    "Honda": ["Activa", "Shine", "Unicorn", "Dio"],
    "TVS": ["Jupiter", "Apache", "Raider", "Ntorq"],
    "Hero": ["Splendor Plus", "HF Deluxe", "Glamour", "Xpulse"],
    "Bajaj": ["Pulsar 150", "Platina", "Chetak (EV)", "Avenger"],
    "Suzuki": ["Access 125", "Gixxer", "Burgman", "Avenis"],
    "Royal Enfield": ["Classic 350", "Bullet 350", "Hunter 350", "Meteor 350"],
    "YAMAHA": ["R15", "MT-15", "FZ-S", "RayZR"],
    "KTM": ["Duke 200", "Duke 390", "RC 200", "Adventure 390"],
    # Motor Car/Jeep/Taxi
    "Maruti Suzuki": ["Swift", "Baleno", "WagonR", "Brezza", "Ertiga", "Dzire"],
    "Hyundai": ["Creta", "i20", "Venue", "Verna", "Alcazar", "Exter"],
    "Tata": ["Nexon", "Punch", "Tiago", "Harrier", "Altroz", "Safari"],
    "Mahindra": ["Thar", "Scorpio-N", "XUV700", "Bolero", "XUV3OO"],
    "Kia": ["Seltos", "Sonet", "Carens", "EV6"],
    "Toyota": ["Fortuner", "Innova Hycross", "Glanza", "Urban Cruiser Taisor"],
    "Honda Cars": ["City", "Amaze", "Elevate"],
    "Skoda": ["Slavia", "Kushaq", "Kodiaq"],
    # Bus & Commercial
    "Ashok Leyland": ["Oyster Bus", "Partner Truck", "BADA DOST", "Ecomet"],
    "Tata Motors": ["Starbus", "Ultra Truck", "Prima Tractor", "Signa Tipper"],
    "Eicher": ["Skyline Pro", "Pro 2049", "Pro 3015"],
    "BharatBenz": ["1917R Truck", "2823C Tipper", "3523R Heavy Truck"],
    "M&M": ["M-DURA", "M-POWER"],
    # Three-wheeler
    "Piaggio": ["Ape DX", "Ape City", "Ape E-City"],
    # Tractor
    "Sonalika": ["Sikander RX 50", "Tiger DI 60"],
    "John Deere": ["5050D", "5310 GearPro"],
    "Tafe": ["Massey Ferguson 7250", "Tafe 45 DI"],
    "Escorts": ["Farmtrac 60", "Powertrac 439"],
    # Construction
    "JCB": ["3DX Backhoe", "4DX Loader"],
    "L&T": ["9020 Wheel Loader", "9030 Vibratory Roller"],
    "Caterpillar": ["320D Excavator", "950L Wheel Loader"],
    "Komatsu": ["PC210 Excavator", "PC300 Excavator"],
}

fuel_types = ["PETROL", "DIESEL", "CNG", "ELECTRIC", "HYBRID", "LPG"]
norms = ["BS VI", "BS IV", "BS III"]

state_base = {
    "Maharashtra": 4500000,
    "Delhi": 3800000,
    "Karnataka": 3200000,
    "Tamil Nadu": 2800000,
    "Gujarat": 2500000,
    "Uttar Pradesh": 2200000,
    "West Bengal": 1800000,
    "Rajasthan": 1500000,
    "Madhya Pradesh": 1300000,
    "Haryana": 1200000,
    "Telangana": 1100000,
    "Andhra Pradesh": 1000000,
    "Kerala": 900000,
    "Punjab": 850000,
    "Odisha": 800000,
    "Chhattisgarh": 600000,
    "Jharkhand": 550000,
    "Bihar": 500000,
    "Assam": 450000,
    "Uttarakhand": 400000,
    "Himachal Pradesh": 350000,
    "Goa": 200000,
    "Jammu and Kashmir": 180000,
    "Chandigarh": 150000,
    "Manipur": 100000,
    "Meghalaya": 90000,
    "Nagaland": 80000,
    "Tripura": 75000,
    "Sikkim": 60000,
    "Mizoram": 55000,
    "Puducherry": 180000,
    "Arunachal Pradesh": 45000,
    "Andaman & Nicobar Island": 30000,
    "Lakshadweep": 15000,
    "UT of DNH and DD": 120000,
    "Ladakh": 25000,
}

records = []
now = datetime.now()

print("[Seeding] Generating registration data...")

for state_code, state_name in states:
    base = state_base.get(state_name, 300000)
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            # Seed 2026 data up to June
            if year == 2026 and month > 6:
                continue

            seasonal = 1.0 + 0.15 * ((month - 6) ** 2) / 25
            growth = 1.0 + (year - 2024) * 0.08
            monthly_total = int(base * seasonal * growth / 12)

            # Determine days in this month
            if month in [1, 3, 5, 7, 8, 10, 12]:
                days_in_month = 31
            elif month in [4, 6, 9, 11]:
                days_in_month = 30
            else:
                days_in_month = 28  # Feb

            # We seed daily data for May and June 2026, and monthly for the rest
            is_daily = (year == 2026 and month in [5, 6])

            days_to_loop = range(1, days_in_month + 1) if is_daily else [None]

            for day in days_to_loop:
                remaining = int(monthly_total / days_in_month) if is_daily else monthly_total

                # Distribute remaining count among vehicle classes
                for vc in vehicle_classes:
                    vc_share = class_shares.get(vc, 0.01)
                    vc_count = int(remaining * vc_share * random.uniform(0.9, 1.1))

                    if vc_count <= 0:
                        continue

                    # Distribute vc_count among makers of this class
                    makers = makers_by_class.get(vc, ["Unknown"])
                    maker_count_remaining = vc_count

                    for idx, maker in enumerate(makers):
                        if idx == len(makers) - 1:
                            maker_count = maker_count_remaining
                        else:
                            maker_share = random.uniform(0.5, 1.5) / len(makers)
                            maker_count = int(vc_count * maker_share)
                            maker_count_remaining -= maker_count

                        if maker_count <= 0:
                            continue

                        # Distribute maker_count among its models
                        models = models_by_maker.get(maker, [maker + " Model"])
                        model_count_remaining = maker_count

                        for m_idx, vehicle_model in enumerate(models):
                            if m_idx == len(models) - 1:
                                model_count = model_count_remaining
                            else:
                                model_share = random.uniform(0.6, 1.4) / len(models)
                                model_count = int(maker_count * model_share)
                                model_count_remaining -= model_count

                            if model_count <= 0:
                                continue

                            fuel = random.choice(fuel_types)
                            norm = random.choice(norms)

                            records.append(
                                (
                                    state_code,
                                    state_name,
                                    "",
                                    "",
                                    month,
                                    year,
                                    day,
                                    vc,
                                    maker,
                                    vehicle_model,
                                    fuel,
                                    norm,
                                    model_count,
                                    (datetime(year, month, day) if is_daily else datetime(year, month, 1)).strftime("%Y-%m-%d %H:%M:%S"),
                                )
                            )

c.executemany(
    """INSERT INTO registrations
       (state_code, state_name, rto_code, rto_name, month, year, day,
        vehicle_class, maker, vehicle_model, fuel_type, norms_type, count, recorded_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
    records,
)

conn.commit()
print(f"[OK] Seeded {len(records)} registration records across 36 states")
print(f"   States: 36 | Years: 2024-2026 | Daily Data for May & June 2026 | Multi-Model Seeding Complete!")
conn.close()
