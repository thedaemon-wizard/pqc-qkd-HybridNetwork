#!/bin/sh
# =====================================================================
# Assert that every MANDATORY compose variable is present in the example
# env file operators are told to copy.
#
# Compose treats `${VAR:?message}` as fatal, and it interpolates the ENTIRE
# file before deciding which services to act on -- so a missing variable
# aborts even an `up` that names only unrelated services.
#
# This existed as a real outage: docker-compose.yml made ARNIKA_PSK mandatory
# for the alice/bob nodes, deploy/.env.example never listed it, and
# deploy/README.md told operators to copy that file. Every cloud deploy
# following the documented procedure produced an .env that could not start
# anything, and the public demo sat on a two-month-old build because of it.
#
# Run locally:   sh scripts/check_env_example.sh
# =====================================================================
set -eu

cd "$(dirname "$0")/.."

fail=0

# Each pair is: <example env file> : <space-separated compose files that must
# be satisfiable by it>. Keep in step with the compose invocations in
# deploy/deploy.sh and deploy/deploy-demo.sh.
check() {
    example="$1"
    shift

    if [ ! -f "$example" ]; then
        echo "::error::$example does not exist"
        fail=1
        return
    fi

    # `${VAR:?...}` and `${VAR?...}` are both fatal-if-unset. `${VAR:-default}`
    # is not, and must not be reported.
    required=$(grep -ohE '\$\{[A-Za-z_][A-Za-z0-9_]*:?\?' "$@" 2>/dev/null \
               | grep -oE '[A-Za-z_][A-Za-z0-9_]*' | sort -u)

    provided=$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$example" \
               | tr -d '=' | sort -u)

    # Set subtraction without process substitution: `comm <(..) <(..)` is a
    # bashism, and CI invokes this with `sh`, which on Ubuntu is dash. Running
    # it locally under bash hid that until CI failed with
    # `Syntax error: "(" unexpected`. Keep this file POSIX so it behaves the
    # same however it is invoked.
    missing=""
    for var in $required; do
        if ! printf '%s\n' "$provided" | grep -qx "$var"; then
            missing="$missing $var"
        fi
    done

    if [ -n "$missing" ]; then
        for var in $missing; do
            echo "::error::$var is mandatory in [$*] but absent from $example"
        done
        fail=1
    else
        n=$(printf '%s\n' "$required" | grep -c . || true)
        echo "ok: $example satisfies all $n mandatory variable(s) of [$*]"
    fi
}

# The cloud/demo host copies deploy/.env.example. Both overlays are layered on
# top of the base compose file, so the base file's requirements apply too.
check deploy/.env.example \
      docker-compose.yml \
      deploy/docker-compose.cloud.yml \
      deploy/docker-compose.demo.yml

# A local checkout copies the root .env.example, which additionally has to
# satisfy the strongSwan overlay used by `make up-ipsec` and the multihop
# overlay used by `make up-multihop`. The multihop file was previously checked
# by nothing, which is why `charlie` could ship without the ARNIKA_ID and
# ARNIKA_PSK its own entrypoint refuses to start without.
check .env.example \
      docker-compose.yml \
      docker-compose.strongswan.yml \
      docker-compose.multihop.yml

exit "$fail"
