#!/usr/bin/env bash
# Install the TLS renewal plumbing on a host. Run once per host, as root,
# from the deployed checkout.
#
# This exists because certificate renewal had two pieces living only on the
# server that issued them, and neither was in version control:
#
#   1. The deploy hook that reloads nginx after a renewal. Without it nginx
#      keeps serving the certificate it read at startup, and the renewal
#      succeeds while the site continues presenting the old one until it
#      expires.
#
#   2. The webroot path recorded in the renewal configuration. certbot
#      stores it as an *absolute* path at issuance time. Deploy the
#      repository anywhere other than the host it was issued on and renewal
#      writes its challenge to a directory nginx does not serve — which
#      fails silently for up to 90 days and then takes the site down.
#
# Both are derived from wherever this checkout actually is, so the same
# script works on a host that deployed to /root/BlinkEngage and one that
# did not.
#
# Idempotent — safe to re-run after changing the hook.
#
# Usage:
#   sudo deploy/letsencrypt/install.sh [--domain engage.blinkconnected.com]
#
# This script does NOT issue or renew certificates. It prints the exact
# command to do that and stops, because issuance depends on DNS already
# pointing at this host — see docs/deployment/server-migration-runbook.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
WEBROOT="${REPO_ROOT}/docker/nginx/acme"
HOOK_DIR=/etc/letsencrypt/renewal-hooks/deploy
DOMAIN=engage.blinkconnected.com

while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || { echo "error: run as root" >&2; exit 1; }
command -v certbot >/dev/null || { echo "error: certbot is not installed" >&2; exit 1; }

echo "repository : ${REPO_ROOT}"
echo "webroot    : ${WEBROOT}"
echo "domain     : ${DOMAIN}"
echo

# --- 1. The webroot -----------------------------------------------------
# Must exist and be readable by the nginx container before any challenge is
# written into it.
mkdir -p "${WEBROOT}"
echo "webroot ready"

# --- 2. The deploy hook -------------------------------------------------
mkdir -p "${HOOK_DIR}"
install -m 0755 "${SCRIPT_DIR}/reload-nginx.sh" "${HOOK_DIR}/reload-blinkengage-nginx.sh"
echo "deploy hook installed → ${HOOK_DIR}/reload-blinkengage-nginx.sh"

# --- 3. Reconcile an existing renewal configuration ---------------------
# When a certificate was migrated from another host, its renewal config
# carries that host's absolute webroot. Correct it rather than leaving a
# renewal that will fail quietly.
RENEWAL_CONF="/etc/letsencrypt/renewal/${DOMAIN}.conf"
if [ -f "${RENEWAL_CONF}" ]; then
  current="$(grep -E '^webroot_path' "${RENEWAL_CONF}" | head -n1 | cut -d= -f2- | tr -d ' ,' || true)"
  if [ "${current}" != "${WEBROOT}" ]; then
    cp -a "${RENEWAL_CONF}" "${RENEWAL_CONF}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    sed -i "s|^webroot_path = .*|webroot_path = ${WEBROOT},|" "${RENEWAL_CONF}"
    sed -i "s|^${DOMAIN} = .*|${DOMAIN} = ${WEBROOT}|" "${RENEWAL_CONF}"
    echo "renewal config webroot corrected:"
    echo "  was: ${current:-<unset>}"
    echo "  now: ${WEBROOT}"
    echo "  (previous file kept as ${RENEWAL_CONF}.bak.*)"
  else
    echo "renewal config webroot already correct"
  fi
else
  echo "no renewal config yet for ${DOMAIN} — the certificate has not been issued on this host"
fi

# --- 4. What to run next, and when -------------------------------------
cat <<EOF

Next steps — NOT performed by this script:

  1. Only once DNS for ${DOMAIN} points at THIS host, and the stack is up so
     nginx is serving :80, issue or verify the certificate:

       # if this host has no certificate yet
       certbot certonly --webroot -w ${WEBROOT} -d ${DOMAIN}

       # if the certificate was migrated from another host
       certbot renew --dry-run

  2. Confirm the hook fires on a real renewal. A dry run does not execute
     deploy hooks, so the first proof that nginx reloads is the first real
     renewal — or force it:

       certbot renew --force-renewal --cert-name ${DOMAIN}

     Only do that deliberately: Let's Encrypt rate-limits issuance.

EOF
