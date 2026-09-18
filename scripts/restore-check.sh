#!/usr/bin/env bash
#
# Prove the newest backup actually restores. An untested backup is a rumour.
#
#   monthly:  0 4 1 * *  bash /opt/vahan/scripts/restore-check.sh >> /var/log/vahan-restore-check.log 2>&1
#   and by hand before any demo or migration.
#
# Invoked via `bash` for the same reason as backup.sh: a Windows-authored
# script arrives without the execute bit and cron would fail silently.
#
# Restores into a THROWAWAY container, never into the live database, then
# asserts the restored copy is actually complete. Destroys the container on
# every exit path, including failure.
#
# To prove this script can fail (do this once, or you have a check nobody has
# ever seen reject anything):
#   head -c 1000000 /var/backups/vahan/vahan-YYYY-MM-DD.dump > /tmp/truncated.dump
#   DUMP=/tmp/truncated.dump scripts/restore-check.sh   # must exit non-zero
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/vahan}"
PG_IMAGE="${PG_IMAGE:-postgres:18-alpine}"
# Defaulted, not just read: the live-count comparison below is the whole point
# of this check, and without a default the monthly cron run -- which sets no
# environment -- would silently fall back to the loose absolute floor every
# time while the docs claimed a 1% tolerance.
COMPOSE_FILE="${COMPOSE_FILE:-/opt/vahan/docker/docker-compose.yml}"
PG_USER="${POSTGRES_USER:-vahan}"
PG_DB="${POSTGRES_DB:-vahan}"
CONTAINER="${CONTAINER:-vahan-restore-check-$$}"
# Minimum rows expected in registrations. Guards against a dump taken while
# the schema existed but the data had not been loaded -- which restores
# "successfully" and is worthless.
MIN_ROWS="${MIN_ROWS:-15000000}"
MIN_YEARS="${MIN_YEARS:-20}"

DUMP="${DUMP:-$(ls -1t "${BACKUP_DIR}"/vahan-*.dump 2>/dev/null | head -1 || true)}"
if [ -z "${DUMP}" ] || [ ! -f "${DUMP}" ]; then
    echo "FAILED: no dump found in ${BACKUP_DIR}" >&2
    exit 1
fi
echo "[$(date -Is)] checking $(basename "${DUMP}") ($(du -h "${DUMP}" | cut -f1))"

cleanup() { docker rm -f "${CONTAINER}" > /dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "${CONTAINER}" -e POSTGRES_PASSWORD=throwaway "${PG_IMAGE}" > /dev/null

for _ in $(seq 1 60); do
    if docker exec "${CONTAINER}" pg_isready -U postgres > /dev/null 2>&1; then break; fi
    sleep 2
done
if ! docker exec "${CONTAINER}" pg_isready -U postgres > /dev/null 2>&1; then
    echo "FAILED: throwaway Postgres never became ready" >&2
    exit 1
fi

docker cp "${DUMP}" "${CONTAINER}:/tmp/check.dump"
docker exec "${CONTAINER}" createdb -U postgres restorecheck

# --no-owner: the role `vahan` does not exist in the throwaway container, and
# without this pg_restore errors on every GRANT/OWNER TO line.
if ! docker exec "${CONTAINER}" \
        pg_restore -U postgres -d restorecheck --no-owner -j4 /tmp/check.dump; then
    echo "FAILED: pg_restore could not restore ${DUMP}" >&2
    exit 1
fi

q() { docker exec "${CONTAINER}" psql -U postgres -d restorecheck -tAc "$1"; }

ROWS=$(q "SELECT count(*) FROM registrations")
YEARS=$(q "SELECT count(DISTINCT year) FROM registrations")
EMPTY_YEARS=$(q "SELECT count(*) FROM (SELECT year FROM registrations GROUP BY year HAVING sum(count) = 0) t")
KEYS=$(q "SELECT count(*) FROM pg_indexes WHERE indexname LIKE 'idx\\_%\\_natural\\_key'")

fail=0
check() { # name actual comparison expected
    if [ "$2" -"$3" "$4" ]; then
        echo "  ok   $1: $2"
    else
        echo "  FAIL $1: got $2, expected -$3 $4" >&2
        fail=1
    fi
}

# Compare against the LIVE database when it is reachable. The absolute floor
# below is a coarse "is this basically empty" guard -- at a live count of
# ~18.4M, MIN_ROWS=15M lets a dump quietly missing 3 million rows pass. The
# relative check is the one that catches a partial dump. Tolerance rather
# than equality because the scraper keeps writing between the dump and this
# check; it only ever ADDS rows, so the restored copy being slightly smaller
# is expected and being larger is not.
LIVE_ROWS=""
if [ -f "${COMPOSE_FILE}" ]; then
    LIVE_ROWS=$(docker compose -f "${COMPOSE_FILE}" exec -T postgres \
        psql -U "${PG_USER}" -d "${PG_DB}" -tAc \
        "SELECT count(*) FROM registrations" 2>/dev/null | tr -d '[:space:]' || true)
else
    echo "  COMPOSE_FILE not found at ${COMPOSE_FILE} -- cannot compare against live" >&2
fi

if [ -n "${LIVE_ROWS}" ] && [ "${LIVE_ROWS}" -gt 0 ] 2>/dev/null; then
    # Integer arithmetic only -- no bc/awk dependency on a minimal VPS.
    MIN_ALLOWED=$(( LIVE_ROWS - LIVE_ROWS / 100 ))
    echo "  live registrations: ${LIVE_ROWS} (restored must be >= ${MIN_ALLOWED}, within 1%)"
    check "registrations vs live" "${ROWS}" ge "${MIN_ALLOWED}"
else
    echo "  live database not reachable -- falling back to the absolute floor" >&2
    check "registrations rows" "${ROWS}" ge "${MIN_ROWS}"
fi
check "distinct years"      "${YEARS}"       ge "${MIN_YEARS}"
check "years summing zero"  "${EMPTY_YEARS}" eq 0
# The natural-key unique indexes are what stop re-scrapes re-admitting the
# duplicate rows ensure_no_duplicate_rows exists to delete. A dump that lost
# them restores "fine" and then silently corrupts on the next scrape.
check "natural-key indexes" "${KEYS}"        ge 4

for t in maker_category_totals fuel_category_totals maker_fuel_totals users; do
    n=$(q "SELECT count(*) FROM ${t}")
    check "${t} rows" "${n}" gt 0
done

if [ "${fail}" -ne 0 ]; then
    echo "[$(date -Is)] RESTORE CHECK FAILED for $(basename "${DUMP}")" >&2
    exit 1
fi

printf '[%s] RESTORE CHECK PASSED: %s registrations across %s years\n' \
    "$(date -Is)" "${ROWS}" "${YEARS}"
