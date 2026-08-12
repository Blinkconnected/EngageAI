#!/usr/bin/env bash
# Rebuild a BlinkEngage deployment on this host from a migrate_export.sh
# export. Runs on the NEW host.
#
# The order below is not arbitrary. Source has to exist before images can
# be built from it; .env has to exist before compose can interpolate it;
# volumes have to be restored before the services that own them start, or
# each service initialises an empty one and the restore then has to fight
# a running process for the directory. Every step here fails loudly rather
# than continuing into a stack that comes up looking healthy and serving
# nothing.
#
# The database is restored from the backup set's logical dump, not from
# the postgres_data volume archive. Both are in the export and they are
# not equivalent: the dump is a `pg_dump` taken through a live connection
# and is portable and internally consistent, while the volume archive is a
# file-level copy that the export takes as a fallback. Prefer the dump.
# --from-volume switches to the fallback if the dump turns out to be the
# problem.
#
# Usage:
#   scripts/migrate_import.sh --export DIR [--from-volume] [--no-start]
#
# Expects on this host: docker, docker compose v2, git, and a clone of the
# repository at the commit the export was taken from (this script will
# check, and tell you the commit if it does not match).

set -euo pipefail

EXPORT_DIR=""
FROM_VOLUME=false
NO_START=false

while [ $# -gt 0 ]; do
  case "$1" in
    --export)      EXPORT_DIR="$2"; shift ;;
    --from-volume) FROM_VOLUME=true ;;
    --no-start)    NO_START=true ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[ -n "${EXPORT_DIR}" ] || { printf 'specify --export DIR\n' >&2; exit 2; }
[ -d "${EXPORT_DIR}" ] || { printf 'no such directory: %s\n' "${EXPORT_DIR}" >&2; exit 2; }
EXPORT_DIR="$(cd "${EXPORT_DIR}" && pwd)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

log()   { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$1"; }
fatal() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$1" >&2; exit 1; }

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)

# --- 1. Verify the export before trusting it -------------------------
# A checksum failure here costs a re-transfer. The same failure discovered
# after the DNS cutover costs the outage twice.
log "verifying export integrity"
[ -f "${EXPORT_DIR}/MANIFEST" ] || fatal "no MANIFEST in ${EXPORT_DIR} — is this an export directory?"

( cd "${EXPORT_DIR}" && sed -n '/^---$/,$p' MANIFEST | tail -n +2 | sha256sum --check --quiet ) \
  || fatal "checksum mismatch — the export is corrupt or incomplete. Re-transfer it."
log "  every artefact matches its recorded checksum"

export_mode="$(grep '^export_mode=' "${EXPORT_DIR}/MANIFEST" | cut -d= -f2)"
export_commit="$(grep '^git_commit=' "${EXPORT_DIR}/MANIFEST" | cut -d= -f2)"
log "  mode=${export_mode} commit=${export_commit:0:8}"

if [ "${export_mode}" != "cold" ]; then
  log ""
  log "  WARNING: this is a WARM export. It was taken against a running"
  log "  stack, so the database dump is consistent but the volume archives"
  log "  are not. Fine for staging a transfer and rehearsing this script;"
  log "  do not cut production over to it. Re-run --cold for the real move."
  log ""
fi

# --- 2. Preflight ------------------------------------------------------
log "preflight"
command -v docker >/dev/null || fatal "docker not found — install it before running this"
"${COMPOSE[@]}" version >/dev/null 2>&1 || fatal "docker compose v2 not available"

current_commit="$(git rev-parse HEAD 2>/dev/null || echo none)"
if [ "${current_commit}" != "${export_commit}" ] && [ "${export_commit}" != "unknown" ]; then
  fatal "this checkout is at ${current_commit:0:8}, the export was taken at ${export_commit:0:8}.
       Application code newer than the dump's schema fails on its first
       write. Check out the matching commit first:
         git checkout ${export_commit}"
fi

# Ports 80 and 443 have to be free. Anything already holding them (a
# distro nginx or apache installed by the image) means the edge silently
# fails to start later.
for port in 80 443; do
  if ss -tulpn 2>/dev/null | grep -q ":${port} "; then
    fatal "port ${port} is already in use on this host — stop whatever holds it
       (often a distro nginx/apache: 'systemctl disable --now nginx apache2')"
  fi
done

avail_kb="$(df -Pk "${REPO_ROOT}" | awk 'NR==2 {print $4}')"
if [ "${avail_kb}" -lt $(( 20 * 1024 * 1024 )) ]; then
  log "  WARNING: only $(( avail_kb / 1024 / 1024 )) GB free. The old host filled"
  log "  38 GB to 85% with images, build cache and volumes. Plan for more."
fi

# --- 3. Secrets --------------------------------------------------------
# Before anything else that compose touches: every service's environment
# interpolates from this file, and a missing one produces a stack that
# starts with empty passwords rather than an error.
log "restoring .env"
if [ -f "${REPO_ROOT}/.env" ]; then
  cp "${REPO_ROOT}/.env" "${REPO_ROOT}/.env.pre-migration.$(date -u +%s)"
  log "  existing .env preserved as .env.pre-migration.*"
fi

if [ -f "${EXPORT_DIR}/env.original" ]; then
  cp "${EXPORT_DIR}/env.original" "${REPO_ROOT}/.env"
elif [ -f "${EXPORT_DIR}/backup_set/secrets.tar.gz.gpg" ]; then
  log "  no env.original — decrypting secrets.tar.gz.gpg (needs BACKUP_PASSPHRASE)"
  [ -n "${BACKUP_PASSPHRASE:-}" ] || fatal "BACKUP_PASSPHRASE not set and no env.original in the export"
  gpg --batch --quiet --decrypt --passphrase-fd 3 \
      "${EXPORT_DIR}/backup_set/secrets.tar.gz.gpg" 3<<<"${BACKUP_PASSPHRASE}" \
    | tar -xz -C "${REPO_ROOT}"
else
  fatal "the export contains no secrets — nothing can start without .env"
fi
chmod 600 "${REPO_ROOT}/.env"
log "  .env restored ($(grep -c '=' "${REPO_ROOT}/.env") variables)"

# --- 4. Production settings -------------------------------------------
# The old host ran with ENVIRONMENT=development and DEBUG=true while
# serving the production domain. DEBUG=true returns tracebacks to
# unauthenticated callers on error, which discloses paths, versions and
# occasionally query fragments. Carrying that across to a fresh host would
# be choosing to keep it.
log "applying production settings to .env"
set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "${REPO_ROOT}/.env"; then
    local current
    current="$(grep -E "^${key}=" "${REPO_ROOT}/.env" | head -n1 | cut -d= -f2-)"
    if [ "${current}" != "${value}" ]; then
      sed -i "s|^${key}=.*|${key}=${value}|" "${REPO_ROOT}/.env"
      log "  ${key}: ${current} → ${value}"
    fi
  else
    printf '%s=%s\n' "${key}" "${value}" >> "${REPO_ROOT}/.env"
    log "  ${key}=${value} (added)"
  fi
}
set_env ENVIRONMENT production
set_env DEBUG false

# CORS still lists localhost origins from development. They are not a
# vulnerability on their own — an attacker cannot make a victim's browser
# originate from http://localhost — but they are not needed in production
# and they widen the allowed set for no reason.
if grep -q 'localhost' "${REPO_ROOT}/.env" 2>/dev/null; then
  log "  NOTE: CORS_ALLOW_ORIGINS still contains localhost origins."
  log "        Review before go-live; left alone here because trimming it"
  log "        blindly can break an internal tool nobody remembered."
fi

# --- 5. TLS ------------------------------------------------------------
# Restored before nginx starts. docker-compose.prod.yml bind-mounts
# /etc/letsencrypt read-only into the edge, and an nginx whose certificate
# path does not resolve does not start — which on a cutover looks like the
# whole platform being down.
if [ -f "${EXPORT_DIR}/letsencrypt.tar.gz" ]; then
  log "restoring /etc/letsencrypt"
  if [ -d /etc/letsencrypt ]; then
    mv /etc/letsencrypt "/etc/letsencrypt.pre-migration.$(date -u +%s)"
  fi
  tar -C / -xzf "${EXPORT_DIR}/letsencrypt.tar.gz"
  cert="/etc/letsencrypt/live/engage.blinkconnected.com/fullchain.pem"
  if [ -f "${cert}" ]; then
    log "  certificate expires $(openssl x509 -enddate -noout -in "${cert}" | cut -d= -f2)"
  else
    log "  WARNING: expected certificate not found at ${cert}"
  fi
else
  log "WARNING: no TLS material in the export — issue certificates before cutover"
fi

# --- 6. Volumes --------------------------------------------------------
# Restored while nothing is running. Docker creates a named volume on
# first use, so starting the stack first would mean extracting over a
# directory a live process already opened.
log "restoring volumes"
"${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true

for archive in "${EXPORT_DIR}"/volumes/*.tar.gz; do
  [ -f "${archive}" ] || continue
  vol="$(basename "${archive}" .tar.gz)"

  # postgres_data only if explicitly asked for — the dump is the primary
  # path and restoring both means the dump replays over a volume that
  # already has the data, which works but wastes the outage.
  if [ "${vol}" = "blinkengage_postgres_data" ] && [ "${FROM_VOLUME}" = "false" ]; then
    log "  ${vol}: skipped (restoring from the dump instead; --from-volume to override)"
    continue
  fi

  log "  ${vol}"
  docker volume rm "${vol}" >/dev/null 2>&1 || true
  docker volume create "${vol}" >/dev/null

  # Same throwaway-container pattern the export and backup_all.sh use.
  docker run --rm \
    -v "${vol}:/data" \
    -v "${EXPORT_DIR}/volumes:/in:ro" \
    --entrypoint sh \
    postgres:17-alpine \
    -c "rm -rf /data/* /data/..?* 2>/dev/null; tar -C /data -xzf /in/${vol}.tar.gz" \
    || fatal "failed to restore ${vol}"
done

# redis_data is deliberately absent from the export. A fresh volume is the
# intended outcome: every user re-logs-in once, and the corrupt AOF on the
# old host does not travel.
log "  blinkengage_redis_data: intentionally fresh (see disaster-recovery.md)"

if [ "${NO_START}" = "true" ]; then
  log "stopping here (--no-start). Volumes and configuration are in place."
  exit 0
fi

# --- 7. Build and start ------------------------------------------------
log "building images (this is the slow step — several minutes)"
"${COMPOSE[@]}" build || fatal "image build failed"

log "starting postgres"
"${COMPOSE[@]}" up -d postgres
for i in $(seq 1 60); do
  if "${COMPOSE[@]}" ps postgres --format '{{.Health}}' 2>/dev/null | grep -q healthy; then
    break
  fi
  [ "${i}" = "60" ] && fatal "postgres did not become healthy within 60s"
  sleep 1
done
log "  healthy"

# --- 8. Database -------------------------------------------------------
if [ "${FROM_VOLUME}" = "true" ]; then
  log "database restored from the volume archive (--from-volume)"
else
  dump="${EXPORT_DIR}/backup_set/database.sql.gz"
  [ -f "${dump}" ] || fatal "no database.sql.gz in the export's backup set"
  log "restoring database from dump ($(du -h "${dump}" | cut -f1))"
  # restore_postgres.sh is the path the DR rehearsal exercises quarterly,
  # so this is a rehearsed code path rather than a bespoke one.
  ./scripts/restore_postgres.sh "${dump}" --force \
    || fatal "database restore failed — the stack is not started; fix and re-run"
  log "  restored"
fi

# --- 9. The rest of the stack -----------------------------------------
log "starting the full stack"
"${COMPOSE[@]}" up -d || fatal "stack failed to start"

log "waiting for the backend to report ready"
# /api/v1/health/ready, not /health/ready — the health router is mounted
# under settings.api_v1_prefix like every other router. It returns 503
# until Postgres, Redis and RabbitMQ are all reachable, which is exactly
# the condition worth waiting on here.
READY_URL="http://127.0.0.1:8000/api/v1/health/ready"
ready=false
for i in $(seq 1 90); do
  if curl -fsS "${READY_URL}" >/dev/null 2>&1; then
    ready=true; break
  fi
  sleep 2
done
if [ "${ready}" = "true" ]; then
  log "  ready"
else
  log "  WARNING: ${READY_URL} did not return 200 within 180s"
  log "  It reports which dependency is unreachable — read the body first:"
  log "    curl -s ${READY_URL}"
  log "    ${COMPOSE[*]} logs backend --tail 50"
fi

# --- 10. Report --------------------------------------------------------
log ""
log "=== import complete ==="
"${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.State}}\t{{.Health}}' 2>/dev/null || true
log ""
log "Verify BEFORE touching DNS — this host is still invisible to users:"
log "  curl --resolve engage.blinkconnected.com:443:127.0.0.1 \\"
log "       https://engage.blinkconnected.com/api/v1/health/ready"
log "  ./scripts/verify_backup_restore.sh"
log "  ./scripts/verify_alerting.sh"
log ""
log "Then harden the edge (Docker bypasses ufw — see the runbook), and only"
log "then repoint the A record for engage.blinkconnected.com at this host."
