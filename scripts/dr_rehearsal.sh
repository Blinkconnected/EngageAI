#!/usr/bin/env bash
# A full disaster-recovery rehearsal, timed.
#
# scripts/verify_backup_restore.sh proves the *database* dump restores.
# That is the narrowest useful drill and it leaves the interesting
# question unanswered: how long does it take to get the whole platform
# back, and how much would have been lost? This restores all four asset
# classes, times every phase, and prints measured RTO and RPO.
#
# Non-destructive. Everything lands in scratch resources that are torn
# down at the end:
#   - database  -> blinkengage_dr_rehearsal (a separate database)
#   - objects   -> a throwaway Docker volume
#   - config    -> a temp directory
#   - secrets   -> decrypted in a temp directory, never written to .env
# Production is read from, never written to.
#
# Usage: scripts/dr_rehearsal.sh [backup-set-dir] [--keep]
#        default: the most recent set in backups/
#        --keep:  leave the scratch resources for inspection
#
# Env: BACKUP_PASSPHRASE (to exercise the secrets restore)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# shellcheck disable=SC1091
[ -f .env ] && set -a && . ./.env && set +a

BACKUP_ROOT="${REPO_ROOT}/backups"
SCRATCH_DB="blinkengage_dr_rehearsal"
SCRATCH_VOLUME="blinkengage_dr_rehearsal_minio"
SCRATCH_MINIO="blinkengage-dr-rehearsal-minio"
KEEP=false

SET_DIR=""
for arg in "$@"; do
  case "${arg}" in
    --keep) KEEP=true ;;
    *) SET_DIR="${arg}" ;;
  esac
done

if [ -z "${SET_DIR}" ]; then
  SET_DIR="$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | tail -n1)"
fi
[ -n "${SET_DIR}" ] && [ -d "${SET_DIR}" ] || {
  echo "error: no backup set found. Run scripts/backup_all.sh first." >&2; exit 1; }

failures=0
phase_log=""

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; failures=$((failures + 1)); }
info() { printf '        %s\n' "$1"; }

# Nanoseconds, divided down. `date +%s%3N` looks like it truncates to
# milliseconds and does not on coreutils here — it emits the full
# nanosecond field and silently ignores the width, which turns every
# measurement into a number a thousand times too large. The whole point
# of this script is the numbers, so they are computed explicitly.
now_ms() { echo $(( $(date -u +%s%N) / 1000000 )); }
record()  { phase_log="${phase_log}$(printf '%-34s %6.1fs' "$1" "$(echo "scale=1; $2/1000" | bc)")\n"; }

teardown() {
  [ "${KEEP}" = "true" ] && { echo; info "--keep: scratch resources left in place"; return; }
  docker rm -f "${SCRATCH_MINIO}" >/dev/null 2>&1 || true
  docker volume rm "${SCRATCH_VOLUME}" >/dev/null 2>&1 || true
  docker compose exec -T postgres psql --username="${PG_USER:-blinkengage}" --dbname=postgres \
    -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";" >/dev/null 2>&1 || true
  rm -rf "${TMP_DIR:-/nonexistent}" 2>/dev/null || true
}
trap teardown EXIT

TMP_DIR="$(mktemp -d)"

echo
echo "Disaster recovery rehearsal"
echo "============================================================"
echo "Backup set : $(basename "${SET_DIR}")"
echo "Started    : $(date -u --iso-8601=seconds)"
echo

REHEARSAL_START="$(now_ms)"

# --- Phase 0: integrity ----------------------------------------------
echo "Phase 0 — backup integrity"
t0="$(now_ms)"

if [ ! -f "${SET_DIR}/MANIFEST" ]; then
  fail "no MANIFEST — the set is incomplete and must not be trusted"
else
  pass "MANIFEST present"
  # Checksums first. Restoring a corrupt archive wastes the outage.
  if (cd "${SET_DIR}" && sed -n '/^---$/,$p' MANIFEST | tail -n +2 | sha256sum --check --quiet) 2>/dev/null; then
    pass "every artefact matches its recorded checksum"
  else
    fail "CHECKSUM MISMATCH — the backup set is corrupt"
  fi
fi

BACKUP_EPOCH="$(stat -c %Y "${SET_DIR}/MANIFEST" 2>/dev/null || echo 0)"
record "0. Integrity check" "$(( $(now_ms) - t0 ))"

# --- Phase 1: database ------------------------------------------------
echo
echo "Phase 1 — database"
t0="$(now_ms)"

PG_USER="$(docker compose exec -T postgres printenv POSTGRES_USER | tr -d '\r')"

docker compose exec -T postgres psql --username="${PG_USER}" --dbname=postgres \
  -c "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\";" \
  -c "CREATE DATABASE \"${SCRATCH_DB}\";" >/dev/null 2>&1

if gunzip -c "${SET_DIR}/database.sql.gz" \
    | docker compose exec -T postgres psql --username="${PG_USER}" \
        --dbname="${SCRATCH_DB}" --quiet -v ON_ERROR_STOP=0 >/dev/null 2>&1; then
  pass "database restored into ${SCRATCH_DB}"
else
  fail "database restore reported errors"
fi

table_count="$(docker compose exec -T postgres psql --username="${PG_USER}" --dbname="${SCRATCH_DB}" \
  -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | tr -d '\r ')"
if [ "${table_count:-0}" -gt 20 ]; then
  pass "${table_count} tables present"
else
  fail "only ${table_count:-0} tables restored — expected the full schema"
fi

# The schema version matters as much as the rows: restoring data that a
# different migration head expects is how a restore appears to work and
# then fails at the first write.
alembic_version="$(docker compose exec -T postgres psql --username="${PG_USER}" --dbname="${SCRATCH_DB}" \
  -tAc "SELECT version_num FROM alembic_version;" 2>/dev/null | tr -d '\r ')"
if [ -n "${alembic_version}" ]; then
  pass "schema at migration ${alembic_version}"
else
  fail "no alembic_version row — schema provenance unknown"
fi

# A row count from a table that matters, to prove data and not just DDL.
company_count="$(docker compose exec -T postgres psql --username="${PG_USER}" --dbname="${SCRATCH_DB}" \
  -tAc "SELECT count(*) FROM companies;" 2>/dev/null | tr -d '\r ')"
if [ -n "${company_count}" ]; then
  pass "business data present (${company_count} companies)"
else
  fail "could not read companies — data may not have restored"
fi

record "1. Database restore" "$(( $(now_ms) - t0 ))"

# --- Phase 2: object storage -----------------------------------------
echo
echo "Phase 2 — object storage"
t0="$(now_ms)"

if [ -f "${SET_DIR}/minio.tar.gz" ]; then
  docker volume rm "${SCRATCH_VOLUME}" >/dev/null 2>&1 || true
  docker volume create "${SCRATCH_VOLUME}" >/dev/null

  if docker run --rm \
      -v "${SCRATCH_VOLUME}:/data" \
      -v "${SET_DIR}:/backup:ro" \
      --entrypoint sh postgres:17-alpine \
      -c 'tar -C /data -xzf /backup/minio.tar.gz' >/dev/null 2>&1; then
    pass "object archive extracted into ${SCRATCH_VOLUME}"
  else
    fail "object archive failed to extract"
  fi

  # Extracting is not the same as MinIO being able to serve it. Starting
  # a real server against the restored volume is the only thing that
  # proves the bucket metadata survived too.
  docker rm -f "${SCRATCH_MINIO}" >/dev/null 2>&1 || true
  if docker run -d --name "${SCRATCH_MINIO}" \
      -v "${SCRATCH_VOLUME}:/data" \
      -e "MINIO_ROOT_USER=${MINIO_ROOT_USER:-blinkengage}" \
      -e "MINIO_ROOT_PASSWORD=${MINIO_ROOT_PASSWORD}" \
      minio/minio:latest server /data >/dev/null 2>&1; then

    ready=false
    for _ in $(seq 1 20); do
      sleep 1
      docker exec "${SCRATCH_MINIO}" curl -sf http://127.0.0.1:9000/minio/health/live >/dev/null 2>&1 \
        && { ready=true; break; }
    done

    if [ "${ready}" = "true" ]; then
      pass "MinIO started against the restored volume"
      listing="$(docker exec "${SCRATCH_MINIO}" sh -c '
        mc alias set dr http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
        mc ls --recursive dr 2>/dev/null | wc -l' 2>/dev/null | tr -d '\r ')"
      if [ "${listing:-0}" -gt 0 ]; then
        pass "${listing} object(s) readable through the S3 API"
      else
        info "0 objects listed — the bucket is empty in this backup set"
      fi
    else
      fail "MinIO did not become healthy against the restored volume"
    fi
  else
    fail "could not start MinIO against the restored volume"
  fi
else
  fail "no object archive in this set — attachments would be lost"
fi

record "2. Object storage restore" "$(( $(now_ms) - t0 ))"

# --- Phase 3: configuration ------------------------------------------
echo
echo "Phase 3 — configuration"
t0="$(now_ms)"

if [ -f "${SET_DIR}/config.tar.gz" ]; then
  mkdir -p "${TMP_DIR}/config"
  if tar -xzf "${SET_DIR}/config.tar.gz" -C "${TMP_DIR}/config" 2>/dev/null; then
    pass "configuration archive extracted"
    missing=""
    for required in docker-compose.yml docker-compose.prod.yml docker/nginx/nginx.prod.conf; do
      [ -f "${TMP_DIR}/config/${required}" ] || missing="${missing} ${required}"
    done
    if [ -z "${missing}" ]; then
      pass "every file needed to rebuild the stack is present"
    else
      fail "configuration archive is missing:${missing}"
    fi
  else
    fail "configuration archive failed to extract"
  fi
else
  fail "no configuration archive in this set"
fi

record "3. Configuration restore" "$(( $(now_ms) - t0 ))"

# --- Phase 4: secrets -------------------------------------------------
echo
echo "Phase 4 — secrets"
t0="$(now_ms)"

if [ -f "${SET_DIR}/secrets.tar.gz.gpg" ]; then
  if [ -z "${BACKUP_PASSPHRASE:-}" ]; then
    fail "BACKUP_PASSPHRASE not set — cannot prove the secrets are recoverable"
    info "this is not a partial pass: an unverifiable secrets archive is a"
    info "restore that stops at 'the stack will not start'"
  else
    mkdir -p "${TMP_DIR}/secrets"
    if gpg --batch --quiet --decrypt --passphrase-fd 3 \
         "${SET_DIR}/secrets.tar.gz.gpg" 3<<<"${BACKUP_PASSPHRASE}" 2>/dev/null \
         | tar -xz -C "${TMP_DIR}/secrets" 2>/dev/null; then
      pass "secrets archive decrypted"
      if [ -s "${TMP_DIR}/secrets/.env" ]; then
        var_count="$(grep -cE '^[A-Z_]+=' "${TMP_DIR}/secrets/.env" || echo 0)"
        pass ".env recovered with ${var_count} variables"
      else
        fail ".env missing from the decrypted archive"
      fi
    else
      fail "secrets archive did NOT decrypt — wrong passphrase or corrupt"
    fi
  fi
else
  fail "no secrets archive in this set"
fi

record "4. Secrets restore" "$(( $(now_ms) - t0 ))"

# --- Results ----------------------------------------------------------
TOTAL_MS="$(( $(now_ms) - REHEARSAL_START ))"
NOW_EPOCH="$(date -u +%s)"
RPO_SECONDS="$(( NOW_EPOCH - BACKUP_EPOCH ))"

echo
echo "============================================================"
echo "Phase timings"
echo "------------------------------------------------------------"
printf "%b" "${phase_log}"
echo "------------------------------------------------------------"
printf '%-34s %6.1fs\n' "TOTAL (measured RTO)" "$(echo "scale=1; ${TOTAL_MS}/1000" | bc)"
echo

echo "Recovery objectives"
echo "------------------------------------------------------------"
printf 'RTO  measured   : %s\n' "$(printf '%dm %ds' $((TOTAL_MS/60000)) $(((TOTAL_MS/1000)%60)))"
printf 'RTO  note       : restore only; excludes decision time, DNS, and\n'
printf '                  bringing application containers up.\n'
printf 'RPO  this set   : %s old at rehearsal time\n' \
  "$(printf '%dh %dm' $((RPO_SECONDS/3600)) $(((RPO_SECONDS/60)%60)))"
printf 'RPO  worst case : 24h — the gap between nightly backups. Anything\n'
printf '                  written after the last backup is lost.\n'
echo

echo "============================================================"
if [ "${failures}" -eq 0 ]; then
  echo "REHEARSAL PASSED — all four asset classes restored and verified."
  exit 0
fi
echo "REHEARSAL FAILED — ${failures} check(s) failed."
exit 1
