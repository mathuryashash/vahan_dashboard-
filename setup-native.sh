#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# No-Docker setup: installs backend/frontend dependencies, creates the
# Postgres role/database if missing, loads the committed seed data, and
# starts both servers. Unlike setup.sh's Docker path, this can't provision
# Python/Node/PostgreSQL itself -- install those first:
#   Python 3.12+, Node 18+, PostgreSQL (running, reachable on PGHOST:PGPORT)
#
# Override any of these via environment variables if your Postgres install
# uses different credentials, e.g.:
#   PGSUPERUSER=postgres PGSUPERPASSWORD=mysecret ./setup-native.sh
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
APP_DB="${APP_DB:-vahan}"
APP_USER="${APP_USER:-vahan}"
APP_PASSWORD="${APP_PASSWORD:-vahan}"
SUPERUSER="${PGSUPERUSER:-postgres}"
SUPERPASSWORD="${PGSUPERPASSWORD:-postgres}"

command -v python >/dev/null 2>&1 || { echo "Python not found on PATH. Install Python 3.12+ first."; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node not found on PATH. Install Node 18+ first."; exit 1; }
command -v psql >/dev/null 2>&1 || { echo "psql not found on PATH. Install PostgreSQL first."; exit 1; }

echo "[1/5] Checking PostgreSQL role/database..."
# SUPERPASSWORD's default ("postgres") is just a common guess -- most real
# installs (especially the Windows installer, which prompts you to choose
# one) use something else. Rather than dying on a wrong guess, retry once
# interactively: this is the setup path every future install/buyer machine
# goes through, and "password authentication failed" with no recovery path
# is a bad first impression on a machine that's otherwise fine.
if ! PGPASSWORD="$SUPERPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
  if [ -t 0 ]; then
    echo "  Default superuser password didn't work for '$SUPERUSER'."
    read -r -s -p "  Enter the PostgreSQL superuser password for '$SUPERUSER': " SUPERPASSWORD
    echo ""
  fi
fi
role_exists=$(PGPASSWORD="$SUPERPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d postgres -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" 2>/dev/null || echo "")
if [ "$role_exists" != "1" ]; then
  echo "  Creating role '$APP_USER'..."
  PGPASSWORD="$SUPERPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE ROLE $APP_USER LOGIN PASSWORD '$APP_PASSWORD'" || {
    echo "  Could not connect as superuser '$SUPERUSER'. Create the role/database yourself, then re-run:"
    echo "    createuser -h $PGHOST -p $PGPORT -U <your-superuser> -P $APP_USER"
    echo "    createdb   -h $PGHOST -p $PGPORT -U <your-superuser> -O $APP_USER $APP_DB"
    echo "  Or re-run with the right password: PGSUPERPASSWORD=<password> ./setup-native.sh"
    exit 1
  }
fi
db_exists=$(PGPASSWORD="$SUPERPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='$APP_DB'" 2>/dev/null || echo "")
if [ "$db_exists" != "1" ]; then
  echo "  Creating database '$APP_DB'..."
  PGPASSWORD="$SUPERPASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$SUPERUSER" -d postgres -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE $APP_DB OWNER $APP_USER"
fi

echo "[2/5] Loading seed data..."
row_count=$(PGPASSWORD="$APP_PASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -tAc \
  "SELECT count(*) FROM registrations" 2>/dev/null || echo 0)
if [ "${row_count:-0}" = "0" ]; then
  gunzip -c docker/seed/seed.sql.gz | PGPASSWORD="$APP_PASSWORD" psql -h "$PGHOST" -p "$PGPORT" -U "$APP_USER" -d "$APP_DB" -v ON_ERROR_STOP=1 >/dev/null
  echo "  Loaded."
else
  echo "  Already has $row_count rows, skipping."
fi

echo "[3/5] Installing backend dependencies..."
cd backend
[ -d .venv ] || python -m venv .venv
if [ -f .venv/Scripts/activate ]; then source .venv/Scripts/activate; else source .venv/bin/activate; fi
# `pip install --upgrade pip` (not `python -m pip ...`) fails on Windows:
# pip.exe can't replace its own running executable file.
python -m pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
cat > .env <<ENV
DATABASE_URL=postgresql+asyncpg://$APP_USER:$APP_PASSWORD@$PGHOST:$PGPORT/$APP_DB
ENV
cd ..

echo "[4/5] Installing frontend dependencies..."
cd frontend
npm install --silent
cd ..

echo "[5/5] Starting servers..."
# Checked explicitly rather than just launching -- Vite silently falls back
# to the next free port (3001, 3002, ...) instead of erroring when 3000 is
# taken, and a second uvicorn on an already-bound port fails immediately in
# the background with nothing watching it. Left unchecked, re-running this
# script while servers from a previous run are still up looks like it
# succeeded but actually leaves the dashboard on the wrong port with a dead
# second backend (confirmed by hand).
port_in_use() {
  if command -v netstat >/dev/null 2>&1 && netstat -ano 2>/dev/null | grep -qE "[:.]$1[[:space:]].*LISTENING"; then
    return 0
  elif command -v lsof >/dev/null 2>&1 && lsof -i tcp:"$1" -sTCP:LISTEN >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

if port_in_use 8020 || port_in_use 3000; then
  echo "  Already running (something's listening on 8020 or 3000) -- skipping."
  echo "  Run ./stop-native.sh first if you want to restart clean."
else
  # Not tracking these via `$!` -- on Windows, `nohup <cmd> & ; echo $!`
  # through an activated venv captures an intermediate wrapper's pid, not
  # the real server process (confirmed by hand: netstat showed a different
  # pid actually bound to the port). stop-native.sh kills by port instead,
  # which is authoritative regardless of how the process was spawned.
  cd backend
  if [ -f .venv/Scripts/activate ]; then source .venv/Scripts/activate; else source .venv/bin/activate; fi
  nohup uvicorn app.main:app --host 0.0.0.0 --port 8020 > ../backend.log 2>&1 &
  cd ../frontend
  nohup npm run dev > ../frontend.log 2>&1 &
  cd ..
fi

echo ""
echo "Dashboard: http://localhost:3000"
echo "API health: http://localhost:8020/health"
echo "Logs: backend.log, frontend.log"
echo "Stop with: ./stop-native.sh"
