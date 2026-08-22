#!/bin/sh
# Check a deployed instance's security posture from OUTSIDE it.
#
# `services/webui-backend/app/main.py` has pointed readers at this file for
# some time; it did not exist. The checks below are the ones that comment
# describes, so the reference now resolves.
#
# Why external rather than a unit test: the risk is a DEPLOYMENT that forgot a
# variable, not code that computes the wrong answer. `ENABLE_CONTAINER_CONTROL`
# gates an endpoint which can start and stop containers through a mounted
# docker.sock, so on a reachable host it is a privilege-escalation path. A test
# inside the image cannot see whether the running instance was launched with
# the flag; only an HTTP request from outside can.
#
# Usage:
#   sh scripts/verify-demo-hardening.sh https://<host>
#
# Exit status is 0 only if every check passes, so it is usable as a release gate.
set -eu

BASE="${1:-${DEMO_URL:-}}"
[ -n "$BASE" ] || { echo "usage: $0 <base-url>" >&2; exit 2; }
BASE="${BASE%/}"
fail=0

say() { printf '  %-58s %s\n' "$1" "$2"; }

echo "checking $BASE"

# ---- 1) the instance answers at all --------------------------------------
health=$(curl -fsS --max-time 20 "$BASE/api/health" 2>/dev/null || echo '')
if [ -z "$health" ]; then
    echo "::error::$BASE/api/health did not respond"
    exit 1
fi
say "/api/health" "$health"

# ---- 2) container control must be OFF ------------------------------------
# Reported explicitly by /api/config so the posture can be read without
# attempting the dangerous call.
cfg=$(curl -fsS --max-time 20 "$BASE/api/config" 2>/dev/null || echo '')
say "/api/config" "$cfg"
case "$cfg" in
    *'"container_control":false'*) say "container control disabled" "ok" ;;
    *'"container_control":true'*)
        echo "::error::container_control is TRUE on $BASE -- this endpoint can"
        echo "         start/stop containers via docker.sock. Unset"
        echo "         ENABLE_CONTAINER_CONTROL and redeploy."
        fail=1 ;;
    *)
        echo "::error::could not read container_control from /api/config"
        fail=1 ;;
esac

# ---- 3) and the endpoint itself must not act -----------------------------
# Belt and braces: config could report one thing while the route does another.
# A non-existent service name is used so that a WRONGLY-enabled instance still
# does not restart anything real.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
       -X POST "$BASE/api/stack/restart" \
       -H 'Content-Type: application/json' \
       -d '{"service":"hardening-probe-does-not-exist"}' 2>/dev/null || echo 000)
say "POST /api/stack/restart" "HTTP $code"
case "$code" in
    403|404|405) : ;;                       # refused, absent, or not allowed
    200) echo "::error::container control ANSWERED on $BASE"; fail=1 ;;
    *)   echo "::error::unexpected status $code from /api/stack/restart"; fail=1 ;;
esac

# ---- 4) a missing log is a 404, not an empty file ------------------------
# Regression guard for the stub that returned HTTP 200 with
# "# log file <name>.log not found" under a Content-Disposition header, so the
# browser saved a one-line file that looked like a quiet log.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
       "$BASE/api/logs/download/hardening-probe-does-not-exist" 2>/dev/null || echo 000)
say "GET /api/logs/download/<absent>" "HTTP $code"
[ "$code" = "404" ] || {
    echo "::error::expected 404 for an absent log, got $code"
    fail=1
}

[ "$fail" -eq 0 ] && echo "ok: $BASE is hardened"
exit "$fail"
