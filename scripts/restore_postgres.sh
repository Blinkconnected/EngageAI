#!/usr/bin/env bash
# Restores a backup produced by scripts/backup_postgres.sh into the
# running Postgres container. DESTRUCTIVE — drops and recreates the
# target database before restoring. See
# docs/architecture/observability.md for the full runbook, and
# scripts/verify_backup_restore.sh for a non-destructive drill against a
# scratch database instead.
#
# Usage: scripts/restore_postgres.sh <backup-file.sql.gz> [--force]
#        [--target-db NAME]  (default: the real POSTGRES_DB — use
#         --target-db for restoring into a scratch database instead)

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <backup-file.sql.gz> [--force] [--target-db NAME]" >&2
  exit 1
fi

BACKUP_FILE="$1"
shift

FORCE=false
TARGET_DB=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=true; shift ;;
    --target-db) TARGET_DB="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "error: backup file not found: ${BACKUP_FILE}" >&2
  exit 1
fi

if ! docker compose ps postgres --format '{{.State}}' 2>/dev/null | grep -q running; then
  echo "error: the 'postgres' service is not running (docker compose ps postgres)" >&2
  exit 1
fi

postgres_user="$(docker compose exec -T postgres printenv POSTGRES_USER)"
target_db="${TARGET_DB:-$(docker compose exec -T postgres printenv POSTGRES_DB)}"

if [ "${FORCE}" != "true" ]; then
  echo "About to DROP and recreate database '${target_db}' and restore ${BACKUP_FILE} into it."
  read -r -p "Type the database name to confirm: " confirmation
  if [ "${confirmation}" != "${target_db}" ]; then
    echo "Confirmation did not match — aborting." >&2
    exit 1
  fi
fi

echo "Dropping and recreating '${target_db}' ..."
docker compose exec -T postgres psql --username="${postgres_user}" --dbname=postgres \
  -c "DROP DATABASE IF EXISTS \"${target_db}\";" \
  -c "CREATE DATABASE \"${target_db}\";"

echo "Restoring ${BACKUP_FILE} into '${target_db}' ..."
gunzip -c "${BACKUP_FILE}" | docker compose exec -T postgres psql \
  --username="${postgres_user}" --dbname="${target_db}" --quiet

echo "Restore complete."
