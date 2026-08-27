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

    # Every named compose file must exist. Without this the gate is vacuous:
    # the grep below sends its errors to /dev/null, so a missing, renamed or
    # moved compose file yields an EMPTY `required` set, and the loop over an
    # empty set finds nothing missing. Measured 2026-08-27 -- run against a
    # directory holding only the two .env.example files, this script printed
    #
    #   ok: deploy/.env.example satisfies all 0 mandatory variable(s) of [...]
    #   ok: .env.example satisfies all 0 mandatory variable(s) of [...]
    #
    # and exited 0. That is the CI `env-example` gate reporting success having
    # read nothing, and this gate exists precisely because the public demo sat
    # on a two-month-old build when deploy/.env.example lacked ARNIKA_PSK.
    for f in "$@"; do
        if [ ! -f "$f" ]; then
            echo "::error::compose file $f (required by $example) does not exist."
            echo "         Renamed or moved? Update the check() call below --"
            echo "         a compose file this script cannot read is a check it"
            echo "         cannot perform, not a check that passed."
            fail=1
            return
        fi
    done

    # `${VAR:?...}` and `${VAR?...}` are both fatal-if-unset. `${VAR:-default}`
    # is not, and must not be reported.
    required=$(grep -ohE '\$\{[A-Za-z_][A-Za-z0-9_]*:?\?' "$@" 2>/dev/null \
               | grep -oE '[A-Za-z_][A-Za-z0-9_]*' | sort -u)

    # Zero mandatory variables across a real set of compose files means the
    # PATTERN stopped matching, not that the requirement went away -- compose
    # interpolates the whole file before selecting services, so these projects
    # always have some. Fail rather than print a reassuring "all 0".
    if [ -z "$required" ]; then
        echo "::error::found NO \${VAR:?} references in [$*]."
        echo "         Either compose stopped using the mandatory-variable form,"
        echo "         or this script's pattern no longer matches it. Either way"
        echo "         nothing was checked."
        fail=1
        return
    fi

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
