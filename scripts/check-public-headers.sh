#!/bin/sh
# Check the response headers a deployed site sends against deploy/Caddyfile.
#
# The headers are set by the public Caddy, so only a request from outside sees
# what a visitor gets: a deploy that skipped recreating the caddy container
# (the Caddyfile is a single-file bind mount, and git replaces the file rather
# than editing it, so a running container keeps the old one) still answers 200
# on every page. This script is check 11 of scripts/verify-demo-hardening.sh.
#
# Usage:
#   sh scripts/check-public-headers.sh https://<host>
#
# Exit status 0 only if the site's root sends all of:
#   - Strict-Transport-Security exactly "max-age=31536000" (this host only,
#     no includeSubDomains, no preload);
#   - X-Content-Type-Options "nosniff";
#   - Content-Security-Policy equal to the line in deploy/Caddyfile, enforced:
#     a Content-Security-Policy-Report-Only header is a failure;
#   - no Server header;
#   - no Via header (Caddy adds "1.1 Caddy" to proxied responses unless the
#     site's header block deletes it).
# Exit status 2 if the check cannot run (no URL, no policy in the Caddyfile).
set -eu

BASE="${1:-${DEMO_URL:-}}"
[ -n "$BASE" ] || { echo "usage: $0 <base-url>" >&2; exit 2; }
BASE="${BASE%/}"
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CADDYFILE="${CADDYFILE:-$HERE/../deploy/Caddyfile}"

want_csp=$(sed -n 's/^[[:space:]]*Content-Security-Policy "\(.*\)"[[:space:]]*$/\1/p' "$CADDYFILE")
[ -n "$want_csp" ] || { echo "::error::no enforced Content-Security-Policy line in $CADDYFILE" >&2; exit 2; }

# Header names lower-cased (HTTP/1.1 answers may capitalise them), values kept.
raw=$(curl -sS -D - -o /dev/null --max-time 20 "$BASE/" 2>/dev/null) || {
    echo "::error::$BASE/ did not answer"; exit 1; }
hdrs=$(printf '%s\n' "$raw" | tr -d '\r' | awk '{ i = index($0, ": ");
    if (i > 0) print tolower(substr($0, 1, i - 1)) ": " substr($0, i + 2); else print }')
field() { printf '%s\n' "$hdrs" | sed -n "s/^$1: //p" | head -n 1; }
has() { printf '%s\n' "$hdrs" | grep -q "^$1: "; }

fail=0
say() { printf '  %-58s %s\n' "$1" "$2"; }

hsts=$(field strict-transport-security)
if [ "$hsts" = "max-age=31536000" ]; then say "Strict-Transport-Security" "ok"
else echo "::error::Strict-Transport-Security is '$hsts', expected 'max-age=31536000'"; fail=1; fi

nosniff=$(field x-content-type-options)
if [ "$nosniff" = "nosniff" ]; then say "X-Content-Type-Options" "ok"
else echo "::error::X-Content-Type-Options is '$nosniff', expected 'nosniff'"; fail=1; fi

csp=$(field content-security-policy)
if [ "$csp" = "$want_csp" ]; then say "Content-Security-Policy (as in deploy/Caddyfile)" "ok"
elif [ -z "$csp" ]; then echo "::error::no enforced Content-Security-Policy on $BASE/"; fail=1
else echo "::error::Content-Security-Policy differs from deploy/Caddyfile"
     echo "         sent:     $csp"
     echo "         expected: $want_csp"
     fail=1; fi

if has content-security-policy-report-only; then
    echo "::error::a Content-Security-Policy-Report-Only header is still sent"; fail=1
else say "no report-only policy" "ok"; fi

if has server; then echo "::error::a Server header is sent: $(field server)"; fail=1
else say "no Server header" "ok"; fi

if has via; then echo "::error::a Via header is sent: $(field via)"; fail=1
else say "no Via header" "ok"; fi

[ "$fail" -eq 0 ] && echo "ok: $BASE sends the headers in deploy/Caddyfile"
exit "$fail"
