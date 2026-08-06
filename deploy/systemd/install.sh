#!/usr/bin/env bash
# Installs the backup and restore-drill timers.
#
# Run once per host, as root, from the deployed checkout. Idempotent —
# re-run it after changing a unit file.
#
# The units carry a __REPO_ROOT__ placeholder that this substitutes with
# wherever the checkout actually is, so the same units work on a host
# that deployed to /opt/blinkengage and one that did not. A hardcoded
# path silently installs a timer that fails every night.
#
# Usage: sudo deploy/systemd/install.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR=/etc/systemd/system
ENV_FILE=/etc/blinkengage/backup.env

[ "$(id -u)" -eq 0 ] || { echo "error: run as root" >&2; exit 1; }

# The secrets file has to exist before the units start, and it must not
# be world-readable — it holds the passphrase that decrypts every backed
# up credential.
if [ ! -f "${ENV_FILE}" ]; then
  echo "Creating ${ENV_FILE} — EDIT IT before the first run."
  install -d -m 0700 /etc/blinkengage
  cat > "${ENV_FILE}" <<'EOF'
# Passphrase for the encrypted secrets archive.
# Store a copy somewhere that is NOT this host. Without it, the .env in
# every backup set is unrecoverable.
BACKUP_PASSPHRASE=

# Off-host destination, e.g. backup@backups.internal:/srv/blinkengage
# Leave empty and backups exist only on this host — which does not
# survive the failure they are for.
BACKUP_REMOTE=
BACKUP_SSH_KEY=/root/.ssh/id_ed25519

BACKUP_RETENTION_DAYS=14
BACKUP_REMOTE_RETENTION_DAYS=30
EOF
  chmod 0600 "${ENV_FILE}"
else
  echo "${ENV_FILE} already exists — leaving it alone."
fi

REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
echo "Installing units for checkout at ${REPO_ROOT}"

for script in scripts/backup_all.sh scripts/verify_backup_restore.sh; do
  [ -x "${REPO_ROOT}/${script}" ] || { echo "error: ${REPO_ROOT}/${script} missing or not executable" >&2; exit 1; }
done

for unit in blinkengage-backup blinkengage-restore-drill; do
  sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "${SCRIPT_DIR}/${unit}.service" \
    > "${UNIT_DIR}/${unit}.service"
  chmod 0644 "${UNIT_DIR}/${unit}.service"
  install -m 0644 "${SCRIPT_DIR}/${unit}.timer" "${UNIT_DIR}/${unit}.timer"
done

systemctl daemon-reload
systemctl enable --now blinkengage-backup.timer
systemctl enable --now blinkengage-restore-drill.timer

echo
echo "Installed. Next runs:"
systemctl list-timers 'blinkengage-*' --no-pager

echo
if ! grep -q '^BACKUP_PASSPHRASE=.\+' "${ENV_FILE}"; then
  echo "WARNING: BACKUP_PASSPHRASE is empty in ${ENV_FILE}."
  echo "         Secrets will NOT be backed up until it is set."
fi
if ! grep -q '^BACKUP_REMOTE=.\+' "${ENV_FILE}"; then
  echo "WARNING: BACKUP_REMOTE is empty in ${ENV_FILE}."
  echo "         Backups will stay on this host only."
fi
echo
echo "Test it now with:  systemctl start blinkengage-backup.service"
echo "Then check:        journalctl -u blinkengage-backup.service -n 40"
