#!/bin/bash
# Vahan Dashboard — Setup & Run Script

echo "============================================"
echo "VAHAN Dashboard Setup"
echo "============================================"

# Backend
echo "[1/4] Setting up Python backend..."
cd backend
pip install -r requirements.txt -q
echo "  Backend deps installed."

# Frontend
echo "[2/4] Setting up React frontend..."
cd ../frontend
npm install 2>&1 | tail -5
echo "  Frontend deps installed."

# Initialize DB
echo "[3/4] Initializing database..."
cd ../backend
python -c "
import sqlite3, os
os.makedirs('data', exist_ok=True)
conn = sqlite3.connect('data/vahan.db')
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS states (
    state_code TEXT PRIMARY KEY, state_name TEXT NOT NULL)''')
c.execute('''CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_code TEXT, state_name TEXT, rto_code TEXT, rto_name TEXT,
    month INTEGER, year INTEGER, vehicle_class TEXT, maker TEXT,
    fuel_type TEXT, norms_type TEXT, count INTEGER,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE INDEX IF NOT EXISTS idx_reg_year ON registrations(year)''')
c.execute('''CREATE INDEX IF NOT EXISTS idx_reg_state ON registrations(state_name)''')
c.execute('''CREATE INDEX IF NOT EXISTS idx_reg_class ON registrations(vehicle_class)''')

# Seed all 36 states
states = [('AN','Andaman & Nicobar Island'),('AP','Andhra Pradesh'),('AR','Arunachal Pradesh'),
    ('AS','Assam'),('BR','Bihar'),('CH','Chandigarh'),('CG','Chhattisgarh'),
    ('DN','UT of DNH and DD'),('DL','Delhi'),('GA','Goa'),('GJ','Gujarat'),
    ('HP','Himachal Pradesh'),('HR','Haryana'),('JH','Jharkhand'),('JK','Jammu and Kashmir'),
    ('KA','Karnataka'),('KL','Kerala'),('LD','Ladakh'),('LA','Lakshadweep'),
    ('MH','Maharashtra'),('ML','Meghalaya'),('MN','Manipur'),('MP','Madhya Pradesh'),
    ('MZ','Mizoram'),('NL','Nagaland'),('OD','Odisha'),('PB','Punjab'),
    ('PY','Puducherry'),('RJ','Rajasthan'),('SK','Sikkim'),('TS','Telangana'),
    ('TN','Tamil Nadu'),('TR','Tripura'),('UK','Uttarakhand'),('UP','Uttar Pradesh'),('WB','West Bengal')]
c.executemany('INSERT OR REPLACE INTO states VALUES (?,?)', states)
conn.commit()
conn.close()
print('  Database initialized at backend/data/vahan.db')
"

echo "[4/4] All done!"
echo ""
echo "============================================"
echo "To start the dashboard:"
echo ""
echo "  Backend (API server):"
echo "    cd backend && uvicorn app.main:app --reload --port 8000"
echo ""
echo "  Frontend (React UI):"
echo "    cd frontend && npm run dev"
echo ""
echo "  Docker (all-in-one):"
echo "    docker-compose -f docker/docker-compose.yml up --build"
echo "============================================"