#!/usr/bin/env bash
# Proves an alert actually reaches an operator.
#
# Configuring alerting and verifying alerting are different things, and
# only the second one is worth anything. Provisioning succeeds with a
# webhook URL that points nowhere; a contact point can be present, named,
# and routed, and still drop every notification. This fires a real alert
# through the real routing and then goes and looks for it at the other
# end.
#
# Four checks, cheapest first:
#   1. Grafana is up, its contact points exist, and none are placeholders.
#   2. Every alert rule is provisioned and actually evaluates.
#   3. The delivery endpoint is reachable.
#   4. A synthetic alert fires, routes, and ARRIVES.
#
# Run before go-live, and after any change to the alerting provisioning
# or to the webhook secrets. Exit code is non-zero if any check fails, so
# it can gate a deploy.
#
# Usage: scripts/verify_alerting.sh
# Env:   GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD (from .env),
#        GRAFANA_URL (default http://localhost:3000)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"

if [ -f .env ]; then
  GF_USER="${GF_SECURITY_ADMIN_USER:-$(grep -E '^GF_SECURITY_ADMIN_USER=' .env | cut -d= -f2- || true)}"
  GF_PASS="${GF_SECURITY_ADMIN_PASSWORD:-$(grep -E '^GF_SECURITY_ADMIN_PASSWORD=' .env | cut -d= -f2- || true)}"
fi
GF_USER="${GF_USER:-admin}"

if [ -z "${GF_PASS:-}" ]; then
  echo "error: GF_SECURITY_ADMIN_PASSWORD not set and not found in .env" >&2
  exit 2
fi

AUTH="${GF_USER}:${GF_PASS}"
PROBE_UID="blinkengage-delivery-probe"
failures=0

pass() { printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; failures=$((failures + 1)); }
info() { printf '        %s\n' "$1"; }

echo
echo "Alert delivery verification — ${GRAFANA_URL}"
echo "============================================================"

# --- 1. Contact points -----------------------------------------------
echo
echo "1. Contact points"
contact_points="$(curl -fsS -u "${AUTH}" "${GRAFANA_URL}/api/v1/provisioning/contact-points" 2>/dev/null)"
if [ -z "${contact_points}" ]; then
  fail "cannot reach Grafana's provisioning API (is the stack up?)"
  echo
  echo "============================================================"
  echo "VERIFICATION FAILED — ${failures} check(s) failed."
  exit 1
fi

for expected in ops-critical ops-warning; do
  if echo "${contact_points}" | grep -q "\"name\":\"${expected}\""; then
    pass "contact point '${expected}' is provisioned"
  else
    fail "contact point '${expected}' is MISSING"
  fi
done

# The thing this file was written to catch: a placeholder that survived
# into production. A contact point named after a placeholder, or pointing
# at example.com, is not a destination anybody reads.
if echo "${contact_points}" | grep -Eq 'placeholder|example\.com|changeme|TODO'; then
  fail "a contact point still contains a placeholder URL"
  info "$(echo "${contact_points}" | grep -Eo '"url":"[^"]*"' | sort -u)"
else
  pass "no placeholder URLs remain"
fi

# --- 2. Alert rules ---------------------------------------------------
echo
echo "2. Alert rules"
rules="$(curl -fsS -u "${AUTH}" "${GRAFANA_URL}/api/v1/provisioning/alert-rules" 2>/dev/null)"
rule_count="$(echo "${rules}" | grep -o '"uid":' | wc -l | tr -d ' ')"
if [ "${rule_count}" -gt 0 ]; then
  pass "${rule_count} alert rule(s) provisioned"
else
  fail "no alert rules are provisioned"
fi

# A rule whose query does not evaluate is dead coverage that still looks
# like coverage — the exact failure mode this whole exercise is about.
health="$(curl -fsS -u "${AUTH}" "${GRAFANA_URL}/api/prometheus/grafana/api/v1/rules" 2>/dev/null)"
# Parsed rather than grepped: counting '"health":"error"' over the raw
# JSON undercounts, and a check that under-reports its own failures is
# not a check.
error_detail="$(echo "${health}" | python3 -c '
import json, sys
try:
    groups = json.load(sys.stdin)["data"]["groups"]
except Exception:
    print("PARSE_ERROR"); raise SystemExit
bad = [r["name"] for g in groups for r in g["rules"] if r.get("health") == "error"]
print(len(bad))
for name in bad:
    print("  " + name)
' 2>/dev/null)"
error_rules="$(echo "${error_detail}" | head -n1)"
if [ "${error_rules}" = "0" ]; then
  pass "all ${rule_count} alert rule(s) evaluate without error"
elif [ "${error_rules}" = "PARSE_ERROR" ] || [ -z "${error_rules}" ]; then
  fail "could not read alert rule health from Grafana"
else
  fail "${error_rules} alert rule(s) are failing to evaluate"
  echo "${error_detail}" | tail -n +2 | sed 's/^/        /'
  info "a rule that cannot evaluate is dead coverage that looks like coverage"
fi

# --- 3. Sink reachable ------------------------------------------------
echo
echo "3. Delivery endpoint"
if docker compose ps alert-sink --format '{{.State}}' 2>/dev/null | grep -q running; then
  pass "alert-sink is running"
else
  info "alert-sink is not running — skipping sink checks."
  info "This is expected when alerts route to an external webhook."
fi

# --- 4. End-to-end delivery ------------------------------------------
# A real alert, through the real routing.
#
# Grafana's "test contact point" API was removed (HTTP 410 on 13.x), and
# testing a receiver directly would have skipped the notification policy
# anyway — which is half of what can be misconfigured. Instead this
# provisions a temporary rule that always fires, labelled severity=critical
# so the policy tree has to route it, and then looks for it arriving. It
# exercises exactly the path a genuine 03:00 page takes.
echo
echo "4. End-to-end delivery (firing a real alert)"

FOLDER_UID="$(curl -fsS -u "${AUTH}" "${GRAFANA_URL}/api/v1/provisioning/alert-rules" 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["folderUID"] if d else "")' 2>/dev/null)"

if [ -z "${FOLDER_UID}" ]; then
  fail "cannot determine the alerting folder — skipping delivery test"
else
  # Counted from the container's logs rather than a file: the sink writes
  # to stdout so Docker's rotation bounds it (see the note in
  # docker/alert-sink/nginx.conf).
  before="$(docker compose logs alert-sink 2>/dev/null | grep -c '"channel"')"
  before="${before:-0}"

  probe_payload="$(cat <<JSON
{
  "uid": "${PROBE_UID}",
  "orgID": 1,
  "folderUID": "${FOLDER_UID}",
  "ruleGroup": "blinkengage-alert-delivery-probe",
  "title": "Alert delivery probe",
  "condition": "C",
  "data": [
    {"refId": "A", "relativeTimeRange": {"from": 300, "to": 0},
     "datasourceUid": "prometheus",
     "model": {"expr": "vector(1)", "instant": true, "refId": "A"}},
    {"refId": "C", "relativeTimeRange": {"from": 0, "to": 0},
     "datasourceUid": "__expr__",
     "model": {"conditions": [{"evaluator": {"params": [0], "type": "gt"}}],
               "expression": "A", "refId": "C", "type": "threshold"}}
  ],
  "noDataState": "NoData",
  "execErrState": "Alerting",
  "for": "0s",
  "annotations": {"summary": "Synthetic probe from scripts/verify_alerting.sh. Safe to ignore."},
  "labels": {"severity": "critical"},
  "isPaused": false
}
JSON
)"

  # Provisioned rules are read-only via the API unless this header says
  # the change is coming from outside the provisioning files.
  create_code="$(curl -fsS -o /dev/null -w '%{http_code}' -u "${AUTH}" \
    -H 'Content-Type: application/json' -H 'X-Disable-Provenance: true' \
    -X POST "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
    -d "${probe_payload}" 2>/dev/null || true)"

  if [ "${create_code}" != "201" ] && [ "${create_code}" != "202" ]; then
    fail "could not create the probe alert rule (HTTP ${create_code:-no response})"
  else
    info "probe rule created; waiting for it to fire and route ..."
    # Evaluation interval + group_wait (10s for critical) + delivery.
    delivered=0
    for _ in $(seq 1 24); do
      sleep 5
      after="$(docker compose logs alert-sink 2>/dev/null | grep -c '"channel"')"
      after="${after:-0}"
      if [ "${after}" -gt "${before}" ]; then delivered=1; break; fi
    done

    if [ "${delivered}" -eq 1 ]; then
      pass "alert FIRED and was DELIVERED to the contact point"
      info "as received:"
      docker compose logs alert-sink 2>/dev/null | grep '"channel"' | tail -n 1 \
        | cut -c1-200 | sed 's/^/          /'
    else
      fail "the probe alert fired but nothing arrived at the sink"
      info "alerts are configured but NOT reaching operators — go-live blocker"
    fi

    # Always clean up, pass or fail. A synthetic rule left firing is a
    # rule people learn to ignore.
    curl -fsS -o /dev/null -u "${AUTH}" -H 'X-Disable-Provenance: true' \
      -X DELETE "${GRAFANA_URL}/api/v1/provisioning/alert-rules/${PROBE_UID}" 2>/dev/null || true
    info "probe rule removed"
  fi
fi

echo
echo "============================================================"
if [ "${failures}" -eq 0 ]; then
  echo "ALERTING VERIFIED — notifications reach their destination."
  exit 0
fi
echo "VERIFICATION FAILED — ${failures} check(s) failed."
exit 1
