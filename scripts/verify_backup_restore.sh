#!/usr/bin/env bash
# The "restore drill": proves the most recent backup is actually
# restorable, without touching the real database. Restores it into a
# throwaway scratch database, runs a sanity query against a known table,
# then drops the scratch database. Run this on a schedule (e.g. after
# every scripts/backup_postgres.sh) — a backup nobody has ever restored
# is not a verified backup. See docs/architecture/observability.md.
#
# Usage: scripts/verify_backup_restore.sh [backup-file.sql.gz]
#        (defaults to the most recent file in backups/)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"
SCRATCH_DB="blinkengage_restore_drill"

cd "${REPO_ROOT}"

BACKUP_FILE="${1:-}"
if [ -z "${BACKUP_FILE}" ]; then
  BACKUP_FILE="$(find "${BACKUP_DIR}" -name 'blinkengage-*.sql.gz' -print0 \
    | xargs -0 ls -t 2>/dev/null | head -n1 || true)"
fi

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
  echo "error: no backup file found (looked in ${BACKUP_DIR}); pass one explicitly" >&2
  exit 1
fi

if ! docker compose ps postgres --format '{{.State}}' 2>/dev/null | grep -q running; then
  echo "error: the 'postgres' service is not running (docker compose ps postgres)" >&2
  exit 1
fi

postgres_user="$(docker compose exec -T postgres printenv POSTGRES_USER)"

cleanup() {
  docker compose exec -T postgres psql --username="${postgres_user}" --dbname=postgres \
    -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Restore drill: ${BACKUP_FILE} -> scratch database '${SCRATCH_DB}'"
cleanup # in case a previous run left it behind

docker compose exec -T postgres psql --username="${postgres_user}" --dbname=postgres \
  -c "CREATE DATABASE \"${SCRATCH_DB}\";"

gunzip -c "${BACKUP_FILE}" | docker compose exec -T postgres psql \
  --username="${postgres_user}" --dbname="${SCRATCH_DB}" --quiet

echo "Restore succeeded. Running sanity checks ..."

company_count="$(docker compose exec -T postgres psql --username="${postgres_user}" \
  --dbname="${SCRATCH_DB}" --tuples-only --no-align -c "SELECT count(*) FROM companies;")"
migration_version="$(docker compose exec -T postgres psql --username="${postgres_user}" \
  --dbname="${SCRATCH_DB}" --tuples-only --no-align -c "SELECT version_num FROM alembic_version;")"

echo "  companies table row count: ${company_count// /}"
echo "  alembic migration version: ${migration_version// /}"

if [ -z "${migration_version// /}" ]; then
  echo "error: alembic_version table is empty in the restored backup — restore is not trustworthy" >&2
  exit 1
fi

echo "Restore drill PASSED — backup ${BACKUP_FILE} is verified restorable."
