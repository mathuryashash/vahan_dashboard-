#!/usr/bin/env bash
#
# Nightly Postgres backup for the Docker Compose deployment.
#
#   crontab -e:
#   30 3 * * *  bash /opt/vahan/scripts/backup.sh >> /var/log/vahan-backup.log 2>&1
#
# Invoked via `bash`, not by path alone: this repo is developed on Windows
# with core.filemode=false, so a committed script arrives on the VPS without
# the execute bit and cron would fail with EACCES -- silently, forever, while
# a manual `bash backup.sh` kept working. `chmod +x` after checkout is still
# worth doing; this just means forgetting it does not cost you the backups.
#
# Why pg_dump and not a copy of the postgres-data volume: copying that
# directory while Postgres is running gives you torn pages, not a backup. Only
# pg_dump, or a copy taken with the container stopped, is restorable.
#
# What this is NOT: app/scripts/export_seed_data.py trims registrations to the
# last few years and deliberately omits the users table -- restoring it would
# silently lose history and every account. export_year_delta.py is a one-year
# transfer tool. Neither is a recovery path. See
# docs/PRODUCTION_HARDENING_CHECKLIST.md step 3.
#
# Verify what this produces with scripts/restore-check.sh. An untested backup
# is a rumour.
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/vahan/docker/docker-compose.yml}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/vahan}"
PG_USER="${POSTGRES_USER:-vahan}"
PG_DB="${POSTGRES_DB:-vahan}"
PG_IMAGE="${PG_IMAGE:-postgres:18-alpine}"
DAILY_KEEP="${DAILY_KEEP:-7}"
WEEKLY_KEEP="${WEEKLY_KEEP:-4}"
# Optional off-host copy, e.g. OFFSITE_DEST=user@mac:/Volumes/backups/vahan
OFFSITE_DEST="${OFFSITE_DEST:-}"

STAMP="$(date +%F)"
OUT="${BACKUP_DIR}/vahan-${STAMP}.dump"

mkdir -p "${BACKUP_DIR}" "${BACKUP_DIR}/weekly"

# A failed pg_dump still leaves the file the shell created for the redirect.
# Without this, every failed night drops a stub in BACKUP_DIR that looks like
# a backup until someone tries to restore it. Cleared on success below.
INCOMPLETE="${OUT}"
cleanup() { [ -n "${INCOMPLETE}" ] && rm -f "${INCOMPLETE}"; }
trap cleanup EXIT

echo "[$(date -Is)] dumping ${PG_DB} -> ${OUT}"

# -T: without it Docker allocates a TTY and corrupts the binary stream.
# Redirecting on the HOST means the dump never occupies container disk.
# The redirect is set up before the command runs, so a failure mid-dump
# leaves a short file -- which is exactly what the size check below catches.
docker compose -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U "${PG_USER}" -d "${PG_DB}" -Fc > "${OUT}"

# A zero-byte or stub file from a failed `exec` is the classic silent backup
# failure: cron sees exit 0, the file exists, and nobody looks again until a
# restore is needed. 1 MB is far below any real dump (currently ~226 MB) and
# far above an error stub.
SIZE=$(stat -c %s "${OUT}")
if [ "${SIZE}" -lt 1000000 ]; then
    echo "FAILED: ${OUT} is only ${SIZE} bytes -- refusing to keep it" >&2
    rm -f "${OUT}"
    exit 1
fi

# Reads and decompresses EVERY data block, discarding the SQL. Deliberately
# not `pg_restore -l`: in the custom format the table of contents is written
# before the data, so `-l` succeeds on a dump truncated halfway through --
# exactly what a disk filling mid-dump produces, and exactly the case the
# size check above is too coarse to catch. This costs a minute of CPU and is
# the only thing standing between a silently truncated archive and finding
# out during a restore.
if ! docker run --rm -v "${BACKUP_DIR}:/b:ro" "${PG_IMAGE}" \
        pg_restore -f /dev/null "/b/$(basename "${OUT}")" > /dev/null 2>&1; then
    echo "FAILED: ${OUT} is truncated or corrupt -- refusing to keep it" >&2
    exit 1
fi

# Survived every check: stop the EXIT trap from deleting it.
INCOMPLETE=""
echo "[$(date -Is)] ok: $(du -h "${OUT}" | cut -f1)"

# Sunday's dump is promoted to the weekly set before the daily sweep can
# delete it, so a corruption noticed three weeks late still has a way back.
if [ "$(date +%u)" = "7" ]; then
    cp -f "${OUT}" "${BACKUP_DIR}/weekly/vahan-${STAMP}.dump"
    echo "[$(date -Is)] promoted to weekly"
fi

# Retention by COUNT, not by age. An age-only sweep runs unconditionally
# every night while promotion into weekly/ only happens on a Sunday that
# actually succeeded -- so a run of failed Sundays lets the sweep empty the
# weekly tier completely while the dailies look healthy. Keeping the newest N
# cannot reach zero no matter how many runs fail, and it sidesteps the
# question of whether -mtime +7 means 7 days or 8.
prune_keep_newest() {
    local dir="$1" keep="$2" f
    # The trailing `|| true` is load-bearing. With no matching files the glob
    # does not expand, `ls` gets the literal pattern and exits 2, and under
    # `set -o pipefail` that becomes the pipeline's status -- aborting the
    # whole script before the offsite copy. weekly/ is empty from deployment
    # until its first Sunday, so this fired every night of the first week.
    # Nothing here is fatal: failing to prune is not a backup failure.
    # shellcheck disable=SC2012  # filenames here are date-stamped, no spaces
    ls -1t "${dir}"/vahan-*.dump 2>/dev/null | tail -n "+$((keep + 1))" | while read -r f; do
        echo "[$(date -Is)] pruning $(basename "${f}")"
        rm -f "${f}"
    done || true
}

prune_keep_newest "${BACKUP_DIR}" "${DAILY_KEEP}"
prune_keep_newest "${BACKUP_DIR}/weekly" "${WEEKLY_KEEP}"

# A backup on the same disk as the database dies with the VPS. This is the
# step that makes it a backup rather than a convenience copy.
if [ -n "${OFFSITE_DEST}" ]; then
    echo "[$(date -Is)] copying offsite -> ${OFFSITE_DEST}"
    rsync -az --partial "${OUT}" "${OFFSITE_DEST}/"
    echo "[$(date -Is)] offsite copy done"
else
    echo "[$(date -Is)] WARNING: OFFSITE_DEST unset -- this copy only exists on this host" >&2
fi
