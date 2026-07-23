#!/usr/bin/env bash
# Dumps the BlinkEngage Postgres database to backups/, gzip-compressed and
# timestamped, then prunes backups older than BACKUP_RETENTION_DAYS. See
# docs/architecture/observability.md for the full backup/restore runbook.
#
# Usage: scripts/backup_postgres.sh
# Env:   BACKUP_RETENTION_DAYS (default 14), COMPOSE_PROJECT (docker compose
#        project directory, default: repo root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="${REPO_ROOT}/backups"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

cd "${REPO_ROOT}"

if ! docker compose ps postgres --format '{{.State}}' 2>/dev/null | grep -q running; then
  echo "error: the 'postgres' service is not running (docker compose ps postgres)" >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="${BACKUP_DIR}/blinkengage-${timestamp}.sql.gz"
tmp_file="${out_file}.tmp"

postgres_user="$(docker compose exec -T postgres printenv POSTGRES_USER)"
postgres_db="$(docker compose exec -T postgres printenv POSTGRES_DB)"

echo "Dumping database '${postgres_db}' to ${out_file} ..."
docker compose exec -T postgres pg_dump \
  --username="${postgres_user}" \
  --dbname="${postgres_db}" \
  --format=plain \
  --no-owner \
  --no-privileges \
  | gzip > "${tmp_file}"

mv "${tmp_file}" "${out_file}"
echo "Backup written: ${out_file} ($(du -h "${out_file}" | cut -f1))"

echo "Pruning backups older than ${RETENTION_DAYS} days ..."
find "${BACKUP_DIR}" -name 'blinkengage-*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete

echo "Done."
