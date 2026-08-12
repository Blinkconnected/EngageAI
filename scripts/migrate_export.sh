#!/usr/bin/env bash
# Export this host's entire BlinkEngage deployment for a move to new hardware.
#
# scripts/backup_all.sh already produces a restorable set, and this script
# uses it rather than reimplementing a dump. But a backup set and a server
# migration are not the same job. The set deliberately carries the four
# asset classes needed to rebuild the *product* — database, objects,
# config, secrets, source. A migration is asked to carry the *deployment*,
# which is a larger thing: the Prometheus TSDB, Grafana's own database of
# users, dashboards and annotations, Loki's log history, RabbitMQ's durable
# queues, and the TLS material under /etc/letsencrypt. None of those are in
# a backup set, and all of them are things somebody notices the loss of on
# the morning after a cutover.
#
# Two passes, because the alternative is a long outage:
#
#   --warm   runs against the live stack and moves the bulk. Nothing is
#            stopped and the export is not consistent — that is fine, it
#            exists to make the second pass small.
#   --cold   stops the writers first and re-exports. This one is
#            consistent and this one is authoritative.
#
# Run warm, transfer it, then run cold during the maintenance window and
# transfer the delta. Downtime is the cold pass plus the delta, not the
# whole 1.2 GB.
#
# What is deliberately NOT exported:
#
#   redis_data              ephemeral by design — refresh tokens, chat
#                           sessions, rate-limit counters. docs/deployment/
#                           disaster-recovery.md calls it disposable, and
#                           the AOF on this host is corrupt anyway. A fresh
#                           volume costs every user one re-login.
#   frontend_node_modules   542 MB of build artefact, rebuilt by the image
#                           build on arrival. Copying it moves a cache and
#                           risks moving a stale one.
#   docker images           rebuilt from source on the new host. Shipping
#                           layers would move whatever the old host had
#                           drifted to, which is the opposite of what a
#                           migration to a clean host is for.
#
# Usage:
#   scripts/migrate_export.sh --warm  [--out DIR]
#   scripts/migrate_export.sh --cold  [--out DIR]
#
# Env:
#   BACKUP_PASSPHRASE   passed through to backup_all.sh so the set's
#                       secrets archive is written. Optional here: this
#                       script also copies .env in the clear into the
#                       export, because the export is going straight to a
#                       host you control over ssh, not to third-party
#                       storage. Delete the export directory from both
#                       hosts when the migration is done.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

MODE=""
OUT_ROOT="/var/tmp/blinkengage-migration"

while [ $# -gt 0 ]; do
  case "$1" in
    --warm) MODE=warm ;;
    --cold) MODE=cold ;;
    --out)  OUT_ROOT="$2"; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[ -n "${MODE}" ] || { printf 'specify --warm or --cold\n' >&2; exit 2; }

EXPORT_DIR="${OUT_ROOT}/${MODE}"
STARTED_EPOCH="$(date -u +%s)"

log()   { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$1"; }
fatal() { printf '[%s] ERROR: %s\n' "$(date -u +%H:%M:%S)" "$1" >&2; exit 1; }

# The volumes whose loss would be noticed. Enumerated explicitly rather
# than globbed off `docker volume ls`, so a volume added later has to be
# considered here instead of silently riding along or silently not.
VOLUMES=(
  blinkengage_postgres_data
  blinkengage_minio_data
  blinkengage_rabbitmq_data
  blinkengage_prometheus_data
  blinkengage_grafana_data
  blinkengage_loki_data
  blinkengage_alert_sink_data
)

# Services that write to Postgres, MinIO or RabbitMQ. Stopped first for
# the cold pass so the export is a point-in-time image rather than a smear
# across one. nginx stays up deliberately — it keeps serving the
# maintenance response instead of refusing connections, which is a better
# thing for a customer to hit than a dead port.
WRITERS=(
  backend celery-worker celery-beat
  ai-autopilot-consumer audit-log-consumer autopilot-sla-consumer
  conversation-ingest-consumer csat-dispatch-consumer erp-sync-consumer
  learning-observation-consumer learning-signals-consumer
  notification-consumer reporting-consumer usage-metering-consumer
  workflow-engine-consumer
)

# Stopped later, after the backup set is taken but before their volumes
# are archived. These own the state they store, and `tar` over a live one
# copies a file the process is midway through rewriting:
#
#   grafana      grafana.db is SQLite. A copy taken during a write is a
#                torn database, and it fails at open rather than at
#                restore, which is the wrong end of the migration to
#                find out.
#   prometheus   the TSDB head block is mmap'd and compaction rewrites
#                blocks in place.
#   loki         same shape — the ingester flushes chunks asynchronously.
#   rabbitmq     the durable-queue index is written continuously.
#   minio        write-once objects, so it is the safe one — included
#                here only so the whole archive phase is quiesced
#                together rather than for correctness.
#
# Postgres is NOT in this list. It is stopped separately, after its dump,
# because backup_all.sh needs it running.
STATEFUL=( grafana prometheus loki rabbitmq minio alert-sink promtail )

# --- Preflight --------------------------------------------------------
# Checked before anything is written, because discovering the disk is full
# halfway through a cold pass means the outage is now also a cleanup.
log "preflight"

command -v docker >/dev/null || fatal "docker not found"
docker compose version >/dev/null 2>&1 || fatal "docker compose v2 not available"

avail_kb="$(df -Pk "$(dirname "${OUT_ROOT}")" | awk 'NR==2 {print $4}')"
# 1.2 GB of source volumes, compressing to roughly half, plus the backup
# set and headroom for the tar that is being written while the previous
# one still exists.
required_kb=$(( 3 * 1024 * 1024 ))
if [ "${avail_kb}" -lt "${required_kb}" ]; then
  fatal "only $(( avail_kb / 1024 )) MB free at ${OUT_ROOT} — need ~3 GB.
       Free space with 'docker builder prune -f' (3.4 GB of build cache on
       this host) or point --out at another filesystem."
fi

for v in "${VOLUMES[@]}"; do
  docker volume inspect "${v}" >/dev/null 2>&1 \
    || log "  WARNING: volume ${v} does not exist — skipping"
done

mkdir -p "${EXPORT_DIR}"
log "export ${MODE} → ${EXPORT_DIR}"

# --- Cold pass: quiesce ----------------------------------------------
STOPPED=false
restart_stack() {
  if [ "${STOPPED}" = "true" ]; then
    log "restarting the stack"
    # `up -d` rather than `start`, so services stopped in either phase come
    # back regardless of which phase the script died in.
    docker compose up -d >/dev/null 2>&1 || \
      log "WARNING: the stack did not fully restart — check 'docker compose ps'"
  fi
}
# Whatever happens after this point, the old host does not stay down. If
# the cutover is abandoned mid-export, the thing to come back to is a
# running platform.
trap restart_stack EXIT

if [ "${MODE}" = "cold" ]; then
  log "stopping writers (${#WRITERS[@]} services) — downtime starts here"
  docker compose stop "${WRITERS[@]}" >/dev/null 2>&1 || true
  STOPPED=true
  # RabbitMQ and Postgres stay up: the dump needs Postgres, and RabbitMQ
  # with no producers attached is already quiet.
  sleep 3
fi

# --- 1. The backup set ------------------------------------------------
# Database dump, objects, config, secrets and a source bundle, with the
# manifest and checksums the restore path already knows how to verify.
# --skip-remote because this set is going to the new host, not to the
# off-host archive, and pushing it to both doubles the transfer.
log "running backup_all.sh"
if ./scripts/backup_all.sh --skip-remote > "${EXPORT_DIR}/backup_all.log" 2>&1; then
  latest_set="$(find "${REPO_ROOT}/backups" -mindepth 1 -maxdepth 1 -type d -name '20*' \
    | sort | tail -n1)"
  [ -n "${latest_set}" ] || fatal "backup_all.sh reported success but produced no set"
  log "  set: $(basename "${latest_set}") ($(du -sh "${latest_set}" | cut -f1))"
  cp -a "${latest_set}" "${EXPORT_DIR}/backup_set"
else
  tail -20 "${EXPORT_DIR}/backup_all.log" >&2
  fatal "backup_all.sh failed — see ${EXPORT_DIR}/backup_all.log"
fi

# --- 2. Volumes -------------------------------------------------------
# postgres_data is included even though the set already has a logical
# dump. They are not redundant: the dump is the thing to restore from
# (portable across minor versions, and verified by the existing restore
# path), and the volume is the fallback if the dump turns out to be the
# problem. It is 182 MB; carrying both costs nothing worth optimising.
#
# postgres:17-alpine is the throwaway container image because it is
# already on this host and has tar, exactly as backup_all.sh does it. A
# migration is not the moment to pull a new image.
if [ "${MODE}" = "cold" ]; then
  # The backup set is taken, so Postgres has given up its dump and MinIO
  # has given up its objects. Everything can go quiet now, and the volume
  # archives below are consistent rather than hopeful.
  log "stopping stateful services for a consistent archive"
  docker compose stop "${STATEFUL[@]}" postgres >/dev/null 2>&1 || true
  sleep 3
fi

log "archiving volumes"
mkdir -p "${EXPORT_DIR}/volumes"
for v in "${VOLUMES[@]}"; do
  docker volume inspect "${v}" >/dev/null 2>&1 || continue
  log "  ${v}"
  docker run --rm \
    -v "${v}:/data:ro" \
    -v "${EXPORT_DIR}/volumes:/out" \
    --entrypoint sh \
    postgres:17-alpine \
    -c "tar -C /data -czf /out/${v}.tar.gz ." \
    || fatal "failed to archive ${v}"
  log "    $(du -h "${EXPORT_DIR}/volumes/${v}.tar.gz" | cut -f1)"
done

# --- 3. TLS material --------------------------------------------------
# The certificate follows the domain, not the address, so it moves with
# the platform and keeps working the moment DNS points at the new host.
# Copying the whole /etc/letsencrypt rather than just live/ because live/
# is symlinks into archive/ — copying live/ alone yields dangling links
# and an nginx that will not start.
if [ -d /etc/letsencrypt ]; then
  log "archiving /etc/letsencrypt"
  tar -C / -czf "${EXPORT_DIR}/letsencrypt.tar.gz" etc/letsencrypt
  chmod 600 "${EXPORT_DIR}/letsencrypt.tar.gz"
  log "  $(du -h "${EXPORT_DIR}/letsencrypt.tar.gz" | cut -f1)"
else
  log "WARNING: /etc/letsencrypt not present — the new host will need to issue certificates"
fi

# --- 4. Secrets, in the clear ----------------------------------------
# The set's secrets.tar.gz.gpg needs BACKUP_PASSPHRASE to open, and a
# migration that cannot start because nobody can find the passphrase is a
# failure mode worth designing out. This copy is 0600, goes host-to-host
# over ssh, and the runbook's last step deletes the export from both ends.
if [ -f .env ]; then
  cp .env "${EXPORT_DIR}/env.original"
  chmod 600 "${EXPORT_DIR}/env.original"
  log "wrote env.original ($(grep -c '=' .env) variables)"
fi

# --- 5. Deployment state the repo does not carry ---------------------
# Recorded rather than restored. The point is that the new host can be
# compared against the old one instead of assumed equivalent.
log "recording host state"
{
  echo "# BlinkEngage deployment state — $(hostname), $(date -u --iso-8601=seconds)"
  echo
  echo "## git"
  echo "commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  echo "unpushed=$(git log --oneline '@{u}..HEAD' 2>/dev/null | wc -l)"
  echo "dirty_files=$(git status --porcelain 2>/dev/null | wc -l)"
  echo
  echo "## versions"
  echo "docker=$(docker --version)"
  echo "compose=$(docker compose version --short 2>/dev/null)"
  echo "kernel=$(uname -r)"
  echo "os=$(. /etc/os-release && echo "${PRETTY_NAME}")"
  echo
  echo "## containers at export time"
  docker compose ps --format '{{.Service}}\t{{.State}}\t{{.Health}}' 2>/dev/null || true
  echo
  echo "## published ports"
  ss -tulpn 2>/dev/null | awk 'NR>1 {print $1, $5}' | sort -u
} > "${EXPORT_DIR}/HOST_STATE.txt"

# Uncommitted work is not in the source bundle, which bundles commits.
# On a host whose repository is the only copy, that difference is the
# whole risk.
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  log "WARNING: uncommitted changes present — capturing as a patch"
  git diff HEAD > "${EXPORT_DIR}/uncommitted.patch" 2>/dev/null || true
  git status --porcelain > "${EXPORT_DIR}/uncommitted.list" 2>/dev/null || true
fi

# --- 6. Manifest ------------------------------------------------------
# Checksums over the whole export, so the new host can tell "this file is
# intact" from "this file arrived" — the same reason backup_all.sh writes
# one, and the same failure (silent corruption in transit) it catches.
log "writing manifest"
{
  echo "export_mode=${MODE}"
  echo "created_utc=$(date -u --iso-8601=seconds)"
  echo "source_host=$(hostname)"
  echo "git_commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "backup_set=$(basename "${latest_set}")"
  echo "duration_seconds=$(( $(date -u +%s) - STARTED_EPOCH ))"
  echo "---"
  # In a subshell: this `cd` would otherwise outlive the block and leave
  # the rest of the script running from somewhere it did not choose.
  # Paths are relative to the export root so `sha256sum --check` works
  # after transfer, when the absolute path is a different one.
  ( cd "${EXPORT_DIR}" && find . -type f ! -name MANIFEST -printf '%P\n' \
      | sort | xargs -r sha256sum )
} > "${EXPORT_DIR}/MANIFEST"

log "export complete: $(du -sh "${EXPORT_DIR}" | cut -f1) in $(( $(date -u +%s) - STARTED_EPOCH ))s"

if [ "${MODE}" = "cold" ]; then
  log ""
  log "This host's stack is stopped and will be restarted when this script"
  log "exits. That is the safe default — an abandoned cutover comes back to"
  log "a running platform. But if you are proceeding with the cutover, stop"
  log "it again once this returns:"
  log "  docker compose stop"
  log "Two hosts serving the same domain, both accepting writes, is how a"
  log "migration turns into two divergent databases and no way to merge them."
fi

log ""
log "Next: transfer to the new host, then run scripts/migrate_import.sh there."
log "  rsync -azP --delete ${EXPORT_DIR}/ root@NEW_HOST:${EXPORT_DIR}/"
