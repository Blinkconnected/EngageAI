#!/usr/bin/env bash
# One run backs up everything needed to rebuild this platform.
#
# scripts/backup_postgres.sh already dumped the database, which is the
# hard part but not the whole part. Restoring from it alone gives a
# database with rows referring to attachments that no longer exist, on a
# host whose configuration has to be reconstructed from memory. Four
# things have to survive together:
#
#   database    the rows
#   objects     the MinIO bucket the rows point at
#   config      compose files, nginx, provisioning — how it is assembled
#   secrets     .env, without which nothing starts
#
# And they have to survive *off this host*. A backup on the same disk as
# the thing it backs up covers exactly one failure mode (somebody dropped
# a table) and none of the ones that actually destroy a platform.
#
# Secrets are encrypted; nothing else is. A .env in plaintext on a backup
# server is a credential leak with a long tail, and the whole point of
# off-host storage is that the copy lives somewhere you control less.
#
# Usage: scripts/backup_all.sh [--skip-remote]
#
# Env (set in .env or the systemd unit):
#   BACKUP_RETENTION_DAYS    local retention, default 14
#   BACKUP_REMOTE            rsync target, e.g. backup@host:/srv/blinkengage
#                            unset = local only, and the run says so loudly
#   BACKUP_REMOTE_RETENTION_DAYS  remote retention, default 30
#   BACKUP_SSH_KEY           identity for the remote, default ~/.ssh/id_ed25519
#   BACKUP_PASSPHRASE        symmetric key for the secrets archive.
#                            REQUIRED. Store it somewhere that is not this
#                            host — a backup you cannot decrypt is not a
#                            backup.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
REMOTE_RETENTION_DAYS="${BACKUP_REMOTE_RETENTION_DAYS:-30}"
BACKUP_ROOT="${REPO_ROOT}/backups"
SKIP_REMOTE=false
[ "${1:-}" = "--skip-remote" ] && SKIP_REMOTE=true

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SET_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
STARTED_EPOCH="$(date -u +%s)"

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$1"; }
fatal() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$1" >&2; exit 1; }

# Partial backup sets are worse than none: they restore, and then you
# discover what was missing. Anything that dies mid-run takes its
# directory with it.
cleanup_on_failure() {
  if [ -d "${SET_DIR}" ] && [ ! -f "${SET_DIR}/MANIFEST" ]; then
    log "run failed — removing the incomplete set ${TIMESTAMP}"
    rm -rf "${SET_DIR}"
  fi
}
trap cleanup_on_failure EXIT

compose_running() {
  docker compose ps "$1" --format '{{.State}}' 2>/dev/null | grep -q running
}

mkdir -p "${SET_DIR}"
log "backup set ${TIMESTAMP}"

# --- 1. PostgreSQL ----------------------------------------------------
compose_running postgres || fatal "the 'postgres' service is not running"

postgres_user="$(docker compose exec -T postgres printenv POSTGRES_USER | tr -d '\r')"
postgres_db="$(docker compose exec -T postgres printenv POSTGRES_DB | tr -d '\r')"

log "dumping database '${postgres_db}'"
# Same plain-format dump scripts/restore_postgres.sh already knows how to
# read, so the restore path stays one path.
docker compose exec -T postgres pg_dump \
  --username="${postgres_user}" \
  --dbname="${postgres_db}" \
  --format=plain --no-owner --no-privileges \
  | gzip > "${SET_DIR}/database.sql.gz"

[ -s "${SET_DIR}/database.sql.gz" ] || fatal "the database dump is empty"

# --- 2. MinIO objects -------------------------------------------------
minio_volume="$(docker inspect "$(docker compose ps -q minio 2>/dev/null)" \
  --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"

if [ -n "${minio_volume}" ]; then
  log "archiving MinIO volume ${minio_volume}"
  # The data volume, not `mc mirror`. The MinIO image is minimal — no
  # tar, no sed — so a mirror-and-tar inside it does not run, and adding
  # a client to the host makes the backup depend on something the host
  # would have to keep in step with the server version. A read-only mount
  # into a throwaway container needs neither, and captures bucket
  # metadata and policies along with the objects.
  #
  # Consistent enough while running: MinIO writes each object's parts
  # atomically and never mutates one in place, so a file in this archive
  # is either a whole object or an in-flight upload that the restore
  # discards. Attachments are write-once here, which is the case this
  # holds for.
  docker run --rm \
    -v "${minio_volume}:/data:ro" \
    -v "${SET_DIR}:/backup" \
    --entrypoint sh \
    postgres:17-alpine \
    -c 'tar -C /data -czf /backup/minio.tar.gz .' \
    || fatal "MinIO volume archive failed"
  log "  objects: $(du -h "${SET_DIR}/minio.tar.gz" | cut -f1)"
else
  log "WARNING: minio is not running — object storage NOT backed up"
  echo "minio not running at backup time" > "${SET_DIR}/minio.SKIPPED"
fi

# --- 3. Configuration -------------------------------------------------
log "archiving configuration"
# Everything needed to stand the stack up again, and nothing secret —
# .env is handled separately and encrypted. --ignore-failed-read so an
# optional file that does not exist on this host is not fatal.
tar --ignore-failed-read -czf "${SET_DIR}/config.tar.gz" \
  docker-compose.yml \
  docker-compose.prod.yml \
  docker/ \
  monitoring/ \
  alembic.ini \
  backend/alembic.ini \
  2>/dev/null || true

# --- 4. Secrets, encrypted -------------------------------------------
if [ -f .env ]; then
  if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
    # Not fatal: refusing to back up the database because a passphrase is
    # missing would be the wrong trade. But it is loud, and the manifest
    # records it, because a restore will need these.
    log "WARNING: BACKUP_PASSPHRASE unset — secrets NOT backed up"
    echo "BACKUP_PASSPHRASE was not set" > "${SET_DIR}/secrets.SKIPPED"
  else
    log "encrypting secrets"
    tar -czf - .env $( [ -f .env.prod ] && echo .env.prod ) 2>/dev/null \
      | gpg --batch --yes --symmetric --cipher-algo AES256 \
            --passphrase-fd 3 --output "${SET_DIR}/secrets.tar.gz.gpg" \
            3<<<"${BACKUP_PASSPHRASE}"
    chmod 600 "${SET_DIR}/secrets.tar.gz.gpg"
  fi
fi

# --- 5. Manifest ------------------------------------------------------
# Checksums, so a restore can tell "this file is intact" from "this file
# arrived". Silent corruption in transit is the failure that only shows
# up when you are already restoring.
log "writing manifest"
{
  echo "backup_set=${TIMESTAMP}"
  echo "created_utc=$(date -u --iso-8601=seconds)"
  echo "host=$(hostname)"
  echo "database=${postgres_db}"
  echo "postgres_version=$(docker compose exec -T postgres postgres --version | tr -d '\r')"
  echo "git_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "alembic_head=$(docker compose exec -T backend alembic current 2>/dev/null | tail -n1 | tr -d '\r' || echo unknown)"
  echo "duration_seconds=$(( $(date -u +%s) - STARTED_EPOCH ))"
  echo "---"
  # Everything except MANIFEST itself. The redirect below creates it
  # before this runs, so including it would checksum a half-written file
  # and record a hash that never matches — a verification step that
  # always fails teaches people to skip verification.
  cd "${SET_DIR}" && find . -maxdepth 1 -type f ! -name MANIFEST -printf '%P\n' \
    | sort | xargs -r sha256sum
} > "${SET_DIR}/MANIFEST"

log "set complete: $(du -sh "${SET_DIR}" | cut -f1)"

# --- 6. Local retention ----------------------------------------------
log "pruning local sets older than ${RETENTION_DAYS} days"
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name '20*' \
  -mtime "+${RETENTION_DAYS}" -print -exec rm -rf {} + || true

# --- 7. Off-host ------------------------------------------------------
if [ "${SKIP_REMOTE}" = "true" ]; then
  log "off-host sync skipped (--skip-remote)"
elif [ -z "${BACKUP_REMOTE:-}" ]; then
  # Deliberately prominent. A backup regime that only ever wrote locally,
  # and never said so, is how people find out during an incident.
  log "WARNING: BACKUP_REMOTE is not set — this backup exists ONLY on this host."
  log "         A disk or host loss takes the backups with it. Set BACKUP_REMOTE."
else
  ssh_key="${BACKUP_SSH_KEY:-${HOME}/.ssh/id_ed25519}"
  log "syncing to ${BACKUP_REMOTE}"
  rsync -az --partial \
    -e "ssh -i ${ssh_key} -o StrictHostKeyChecking=accept-new -o BatchMode=yes" \
    "${SET_DIR}" "${BACKUP_REMOTE}/" \
    || fatal "off-host sync FAILED — the set exists locally only"
  log "  synced"

  # Remote retention, run remotely so it does not depend on a local
  # listing of the remote.
  remote_host="${BACKUP_REMOTE%%:*}"
  remote_path="${BACKUP_REMOTE#*:}"
  ssh -i "${ssh_key}" -o BatchMode=true "${remote_host}" \
    "find '${remote_path}' -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +${REMOTE_RETENTION_DAYS} -exec rm -rf {} +" \
    || log "WARNING: remote retention prune failed (backups are safe; the remote may fill)"
  log "  remote retention applied (${REMOTE_RETENTION_DAYS} days)"
fi

log "done: ${SET_DIR}"
