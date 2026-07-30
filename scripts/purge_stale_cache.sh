#!/usr/bin/env bash
#
# Removes Redis state that outlived the rows it referred to.
#
# The companion to purge_companies.sql. Deleting a company clears its
# database rows, but Redis holds refresh tokens and web-chat sessions that
# know nothing about it — so after a purge the cache still carries
# credentials and sessions pointing at companies and users that no longer
# exist.
#
# Deliberately **selective** rather than FLUSHDB. A flush is one command
# and would also sign out every surviving user, drop live web-chat
# sessions mid-conversation, and reset rate limiters — collateral damage
# for a cleanup job. Selecting by "does the thing it references still
# exist" is the same amount of work to run and does not disturb anybody
# who is legitimately signed in.
#
# Safe to run at any time, purge or no purge: everything it deletes is
# state whose referent is already gone, which cannot produce a working
# session in any case.
#
# Usage:  scripts/purge_stale_cache.sh [--dry-run]

set -euo pipefail

cd "$(dirname "$0")/.."

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

psql() { docker compose exec -T postgres psql -U blinkengage -d blinkengage -t -A "$@" </dev/null; }

# `</dev/null` is load-bearing, not defensive. `docker compose exec -T`
# still attaches stdin, so calling it inside a `while read` loop lets it
# swallow the rest of the piped key list — the loop then exits after one
# iteration and reports success having processed almost nothing. The dry
# run caught exactly that: 1 of 28 web-chat sessions examined.
redis() { docker compose exec -T redis redis-cli "$@" 2>/dev/null </dev/null; }

echo "Reading current state from PostgreSQL..."

# Users who could actually authenticate. A soft-deleted user's refresh
# token is already refused at sign-in, so it is dead weight — but it is
# still a live-looking credential in a datastore, and those are worth
# removing rather than explaining.
mapfile -t LIVE_USERS < <(psql -c "SELECT id FROM users WHERE deleted_at IS NULL;" | tr -d '\r')
mapfile -t LIVE_COMPANIES < <(psql -c "SELECT id FROM companies WHERE deleted_at IS NULL;" | tr -d '\r')

echo "  ${#LIVE_USERS[@]} user(s) that can sign in, ${#LIVE_COMPANIES[@]} live company/companies"

is_live_user() {
  local needle="$1"
  for id in "${LIVE_USERS[@]}"; do [[ "$id" == "$needle" ]] && return 0; done
  return 1
}

is_live_company() {
  local needle="$1"
  for id in "${LIVE_COMPANIES[@]}"; do [[ "$id" == "$needle" ]] && return 0; done
  return 1
}

stale_tokens=0
kept_tokens=0

# refresh_token:<user_id>:<jti>
while read -r key; do
  [[ -z "$key" ]] && continue
  user_id="$(cut -d: -f2 <<<"$key")"
  if is_live_user "$user_id"; then
    kept_tokens=$((kept_tokens + 1))
  else
    stale_tokens=$((stale_tokens + 1))
    $DRY_RUN || redis DEL "$key" >/dev/null
  fi
done < <(redis --scan --pattern 'refresh_token:*' --count 500 | tr -d '\r')

stale_sessions=0
kept_sessions=0

# webchat_session:<token> -> JSON carrying company_id. Read rather than
# inferred: the key itself is an opaque token, and guessing which company
# a session belongs to is how a live conversation gets cut off.
while read -r key; do
  [[ -z "$key" ]] && continue
  company_id="$(redis GET "$key" | tr -d '\r' \
    | grep -oE '"company_id":"[0-9a-f-]+"' | cut -d'"' -f4 || true)"
  if [[ -n "$company_id" ]] && is_live_company "$company_id"; then
    kept_sessions=$((kept_sessions + 1))
  else
    # No company_id at all counts as stale: a session that cannot say
    # which company it belongs to cannot be routed anywhere useful.
    stale_sessions=$((stale_sessions + 1))
    $DRY_RUN || redis DEL "$key" >/dev/null
  fi
done < <(redis --scan --pattern 'webchat_session:*' --count 500 | tr -d '\r')

echo
$DRY_RUN && echo "DRY RUN — nothing deleted." || echo "Deleted:"
echo "  refresh tokens : ${stale_tokens} stale, ${kept_tokens} kept"
echo "  web-chat sessions: ${stale_sessions} stale, ${kept_sessions} kept"
echo
echo "Redis keys remaining: $(redis DBSIZE | tr -d '\r')"
