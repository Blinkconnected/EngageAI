#!/bin/sh
# Reload the dockerised nginx after certbot renews a certificate.
#
# Installed as a certbot *deploy* hook, so it runs only when a certificate
# was actually renewed — not on every twice-daily renewal check.
#
# /etc/letsencrypt is bind-mounted into the container read-only, so the
# renewed files are visible inside it the moment certbot writes them. nginx
# just has to be told to re-read them: it holds the certificate in memory
# from startup and will keep serving the expired one indefinitely otherwise.
# That failure is invisible until the certificate actually expires, which is
# the worst possible moment to discover the reload never happened.
#
# A HUP signal is a graceful reload — existing connections finish on the old
# worker processes while new ones start with the new certificate, so there is
# no dropped request and no container restart.
set -eu

CONTAINER="${BLINKENGAGE_NGINX_CONTAINER:-blinkengage-nginx-1}"

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    docker kill -s HUP "$CONTAINER" >/dev/null
    echo "reload-nginx: sent HUP to $CONTAINER"
else
    # Not an error: a renewal can legitimately land while the stack is down
    # (during a migration, for instance). The next `up` reads the new
    # certificate from disk anyway.
    echo "reload-nginx: $CONTAINER not running, skipped" >&2
fi
