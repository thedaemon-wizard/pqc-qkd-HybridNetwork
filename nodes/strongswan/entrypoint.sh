#!/usr/bin/env bash
# =====================================================================
# strongSwan IPsec node entrypoint.
#
#   1. Render swanctl.conf from the template.
#   2. Start charon and wait for its VICI socket.
#   3. Assert ML-KEM-768 is actually available (not merely configured).
#   4. Load the connection (charon initiates on demand via start_action).
#   5. Run arnika, whose strongSwan VICI key-writer rotates the RFC 8784 PPK.
#
# Every step fails loudly. The previous version backgrounded a charon binary at
# a path that does not exist and swallowed every swanctl error with `|| true`,
# so the container reported healthy while running no IKE daemon at all.
# =====================================================================
set -euo pipefail

NODE_NAME="${NODE_NAME:?NODE_NAME must be set}"
LOCAL_IP="${LOCAL_IP:?LOCAL_IP must be set}"
PEER_IP="${PEER_IP:?PEER_IP must be set}"
LOCAL_ID="${LOCAL_ID:?LOCAL_ID must be set}"
PEER_ID="${PEER_ID:?PEER_ID must be set}"

# charon is installed to $(libexecdir)/ipsec, NOT sbin. The old path
# (/usr/local/sbin/charon) silently did not exist.
CHARON_BIN=/usr/local/libexec/ipsec/charon
VICI_SOCKET="${VICI_SOCKET:-/var/run/charon.vici}"

IKE_PROPOSALS="${IKE_PROPOSALS:?IKE_PROPOSALS must be set}"
ESP_PROPOSALS="${ESP_PROPOSALS:?ESP_PROPOSALS must be set}"
PPK_ID="${VICI_PPK_ID:?VICI_PPK_ID must be set}"
REAUTH_TIME="${REAUTH_TIME:?REAUTH_TIME must be set}"

# arnika's own floor (minArnikaPSKLen in submodules/arnika/config/config.go):
# its peer authentication claim assumes 256 bits of real entropy. arnika checks
# this too, but only once it starts -- after charon is up and after the
# bootstrap credentials below have already been derived from this value.
MIN_ARNIKA_PSK_BYTES=32
# The value .env.example ships. It is 37 bytes, so it passes arnika's length
# check, and a deployment that never replaced it would authenticate its peer
# protocol and derive its bootstrap PPK from a string printed in this repository.
ARNIKA_PSK_PLACEHOLDER='replace-me-run-openssl-rand-base64-32'

# The checks on the two values this node hands to arnika and must agree with
# its peer on, before anything else runs: ARNIKA_PSK is needed before the
# config is rendered, because the bootstrap credentials are derived from it
# (see the note below). One function, so that
# tests/test_entrypoints_validate_their_input.py runs exactly these lines
# under bash with a stubbed environment.
#
# PQC_ENABLED switches the PQC half of the PPK. arnika agrees it with the peer
# itself, over HPKE on the same authenticated UDP channel as the key_ID
# (repositories/pqchpke), and it never touches disk -- there is no key file to
# mount any more. Validated here, strictly, because arnika is not strict about
# it: config.go reads `PQC_ENABLED == "true"` and treats every other value as
# off. "True", "1" or "yes" would silently disable the PQC half. Under
# MODE=QkdAndPqcRequired arnika then refuses to start, but under a mode that
# does not require PQC it would run QKD-only with nothing in the log to say
# the operator asked for otherwise. Both peers must agree (the compose file
# sets it once, in the shared anchor).
validate_arnika_input() {
    : "${ARNIKA_PSK:?ARNIKA_PSK must be set, and must be identical on both peers}"
    # Bytes, not characters: `${#ARNIKA_PSK}` counts characters in a UTF-8
    # locale, and arnika compares len([]byte). printf is a shell builtin, so
    # the value does not appear on any process command line.
    local psk_bytes
    psk_bytes=$(printf '%s' "$ARNIKA_PSK" | wc -c | tr -d ' ')
    if [ "$ARNIKA_PSK" = "$ARNIKA_PSK_PLACEHOLDER" ]; then
        echo "[entrypoint] FATAL: ARNIKA_PSK is still the .env.example placeholder." >&2
        echo "[entrypoint] Generate one with: openssl rand -base64 32" >&2
        exit 1
    fi
    if [ "$psk_bytes" -lt "$MIN_ARNIKA_PSK_BYTES" ]; then
        echo "[entrypoint] FATAL: ARNIKA_PSK is ${psk_bytes} bytes; arnika requires at least ${MIN_ARNIKA_PSK_BYTES}." >&2
        echo "[entrypoint] Generate one with: openssl rand -base64 32" >&2
        exit 1
    fi
    : "${PQC_ENABLED:?PQC_ENABLED must be set to true or false, identically on both peers}"
    case "${PQC_ENABLED}" in
        true|false) ;;
        *)
            echo "[entrypoint] FATAL: PQC_ENABLED is '${PQC_ENABLED}'; expected exactly 'true' or 'false'." >&2
            echo "[entrypoint] arnika treats anything but 'true' as disabled." >&2
            exit 1
            ;;
    esac
}
validate_arnika_input

# ---- No start alignment in this lane ------------------------------------
# Deliberate. arnika here starts as soon as the connection is loaded, as it did
# at v0.1.0, and not at a wall-clock multiple of its interval as in the
# WireGuard lane ("Start alignment" in nodes/alice/entrypoint.sh). This lane is
# the one the before/after PPK measurement compares (docs/vici-ppk.md), and at
# v0.1.0 its two nodes were never aligned: compose starts them together, about
# 30 ms apart on the public demo. Both arms run this same entrypoint start
# behaviour: no alignment, and arnika starts once the connection is loaded.
# The start offset between the two nodes is not held equal, though: arm B
# drops the depends_on on the WireGuard nodes, which changes when compose
# starts these nodes, so the offset is measured in each arm. Whatever the
# pinned arnika's fail-closed path for an interval without a key_id
# (submodules/arnika/main.go:409-418) does under that start offset is a
# finding to measure, not something to hide with a start change made in one
# arm only. The inference in that comment, about how the offset between the
# two ends wanders after the start and when a BACKUP then fails closed,
# applies here too, from whatever offset the start leaves.

# Also needed before rendering: the control-plane bypass shunt is built from
# these. They are re-exported for arnika further down.
LISTEN_ADDRESS="${LISTEN_ADDRESS:?LISTEN_ADDRESS must be set}"
SERVER_ADDRESS="${SERVER_ADDRESS:?SERVER_ADDRESS must be set}"

# Which peer owns the shared IKE_SA. The two nodes must disagree: one
# "initiator", one "responder". The same value gates both halves of SA
# ownership -- who initiates (start_action, here) and who reauthenticates after
# a key rotation (VICI_IKE_ROLE, read by the adapter) -- so they cannot drift
# apart. See the comment on swanvici.Config.DriveReauth for what two drivers
# cost.
VICI_IKE_ROLE="${VICI_IKE_ROLE:?VICI_IKE_ROLE must be set to initiator or responder, and the two peers must differ}"
# The responder is purely reactive: it never initiates and never reauthenticates.
# Leaving charon's own reauth_time active on it makes it a third initiation
# source alongside its own start_action and the initiator's arnika -- charon
# reauthenticates by establishing a NEW IKE_SA, so a responder with a reauth
# timer initiates one every period regardless of what the initiator is doing.
case "${VICI_IKE_ROLE}" in
    initiator) START_ACTION=start; CLOSE_ACTION=restart ;;
    responder) START_ACTION=none;  CLOSE_ACTION=none; REAUTH_TIME=0 ;;
    *)
        echo "[entrypoint] FATAL: VICI_IKE_ROLE is '${VICI_IKE_ROLE}';" >&2
        echo "[entrypoint] expected 'initiator' or 'responder'." >&2
        exit 1
        ;;
esac

mkdir -p /etc/swanctl/conf.d

# ---- 1) Render swanctl.conf ------------------------------------------
# Bootstrap credentials.
#
# These MUST be identical on both peers. `secrets.ike` and `secrets.ppk` are
# *shared* secrets: IKE_AUTH compares the PSK on both ends, and with
# `ppk_required = yes` the PPK must match too. An earlier version generated
# both from /dev/urandom independently on each node, so Alice's value never
# equalled Bob's and IKE_AUTH could not succeed -- and nothing repaired it,
# because the VICI adapter rotates only the PPK, never the IKEv2 PSK.
#
# Derive them from ARNIKA_PSK, which is already mandatory and already identical
# on both peers (it keys arnika's PRIMARY/BACKUP election and authenticates and
# encrypts its UDP peer channel: the key_ID frames and, since the PQC-HPKE
# reader, the HPKE key-agreement frames). Two separate `info` strings keep the
# two derived values independent, so recovering one tells you nothing about
# the other.
#
# These are BOOTSTRAP values and are NOT QKD material: they exist only so the
# first IKE_AUTH can complete. arnika replaces the PPK with
# HKDF-SHA3-256(QKD || PQC-HPKE) output on its first rotation, and every
# reauthentication after that consumes QKD-derived material.
#
# `od -v`, in both places: without it od prints a repeated 16-byte line as a
# single `*`, so a PSK that repeats a 16-byte block (16 x U+00E9 is 32 bytes
# and passes the length check) reached openssl as a hexkey with a `*` in it
# and killed the node with "odd number of digits".
ARNIKA_PSK_TMP=/run/arnika-psk.tmp
derive_bootstrap_secret() {
    # Created 0600, not chmod-ed afterwards, so it is never readable by others.
    ( umask 077; printf '%s' "$ARNIKA_PSK" > "$ARNIKA_PSK_TMP" )
    # The raw value goes through the file, so it is never an argument of od.
    # Its hex form does become one: `openssl kdf` takes a key only as a
    # -kdfopt, so the hex is on openssl's command line, readable through /proc
    # inside this container, for as long as openssl runs.
    openssl kdf -keylen 32 \
        -kdfopt digest:SHA256 \
        -kdfopt "hexkey:$(od -v -An -tx1 < "$ARNIKA_PSK_TMP" | tr -d ' \n')" \
        -kdfopt "info:$1" \
        -binary HKDF | od -v -An -tx1 | tr -d ' \n'
    rm -f "$ARNIKA_PSK_TMP"
}

BOOTSTRAP_PSK=$(derive_bootstrap_secret "pqcqkd bootstrap ike-psk")
BOOTSTRAP_PPK=$(derive_bootstrap_secret "pqcqkd bootstrap ppk")

# arnika's key_ID channel port, taken from the address arnika is actually told
# to bind, so the bypass shunt and the daemon can never disagree. See the
# "Control-plane bypass" comment in swanctl.conf.tmpl for why the shunt exists.
CONTROL_PORT="${LISTEN_ADDRESS##*:}"
case "${CONTROL_PORT}" in
    ''|*[!0-9]*)
        echo "[entrypoint] FATAL: cannot read a port from LISTEN_ADDRESS='${LISTEN_ADDRESS:-}'" >&2
        echo "[entrypoint] Expected host:port, e.g. 0.0.0.0:9998." >&2
        exit 1
        ;;
esac
# SERVER_ADDRESS is where we send; a mismatch would leave half the channel
# tunnelled and the deadlock only partly cured.
if [ "${SERVER_ADDRESS##*:}" != "${CONTROL_PORT}" ]; then
    echo "[entrypoint] FATAL: LISTEN_ADDRESS port (${CONTROL_PORT}) and" >&2
    echo "[entrypoint] SERVER_ADDRESS port (${SERVER_ADDRESS##*:}) differ." >&2
    echo "[entrypoint] The bypass shunt assumes both ends use one port." >&2
    exit 1
fi

sed -e "s|__LOCAL_IP__|${LOCAL_IP}|g" \
    -e "s|__PEER_IP__|${PEER_IP}|g" \
    -e "s|__LOCAL_ID__|${LOCAL_ID}|g" \
    -e "s|__PEER_ID__|${PEER_ID}|g" \
    -e "s|__PPK_ID__|${PPK_ID}|g" \
    -e "s|__REAUTH_TIME__|${REAUTH_TIME}|g" \
    -e "s|__IKE_PROPOSALS__|${IKE_PROPOSALS}|g" \
    -e "s|__ESP_PROPOSALS__|${ESP_PROPOSALS}|g" \
    -e "s|__BOOTSTRAP_PSK__|${BOOTSTRAP_PSK}|g" \
    -e "s|__BOOTSTRAP_PPK__|${BOOTSTRAP_PPK}|g" \
    -e "s|__CONTROL_PORT__|${CONTROL_PORT}|g" \
    -e "s|__START_ACTION__|${START_ACTION}|g" \
    -e "s|__CLOSE_ACTION__|${CLOSE_ACTION}|g" \
    /etc/swanctl/conf.d/pqcqkd.conf.tmpl \
    > /etc/swanctl/conf.d/pqcqkd.conf

# ---- 2) Start charon --------------------------------------------------
echo "[entrypoint] starting charon (${CHARON_BIN})"
"${CHARON_BIN}" &
CHARON_PID=$!

for _ in $(seq 1 30); do
    [ -S "${VICI_SOCKET}" ] && break
    # If charon died, stop waiting out the full timeout on a corpse.
    kill -0 "${CHARON_PID}" 2>/dev/null \
        || { echo "[entrypoint] FATAL: charon exited during startup" >&2; exit 1; }
    sleep 1
done
if [ ! -S "${VICI_SOCKET}" ]; then
    echo "[entrypoint] FATAL: VICI socket ${VICI_SOCKET} never appeared" >&2
    exit 1
fi

# ---- 3) Assert ML-KEM-768 is available --------------------------------
# The proposal names ke1_mlkem768. If no loaded plugin provides it, charon
# rejects the connection at load time -- previously hidden behind `|| true`.
# `swanctl --list-algs` asks the running daemon, so this proves the plugin is
# loaded, not just compiled.
#
# Read once into a variable, not piped into `grep -q`: under pipefail, grep -q
# exiting at the first match can end swanctl with SIGPIPE, and the pipeline's
# failure would then report ML-KEM missing when it is present (SC2337).
CHARON_ALGS="$(swanctl --list-algs)"
if ! grep -q 'ML_KEM_768' <<< "${CHARON_ALGS}"; then
    echo "[entrypoint] FATAL: ML_KEM_768 is not available in charon." >&2
    echo "[entrypoint] The 'ml'/'openssl' plugins must be built AND named in" >&2
    echo "[entrypoint] the charon load line (/etc/strongswan.conf)." >&2
    echo "[entrypoint] Key-exchange methods charon actually offers:" >&2
    sed -n '/^ke:/,/^[a-z-]*:/p' <<< "${CHARON_ALGS}" >&2
    exit 1
fi
echo "[entrypoint] ML_KEM_768 available: $(grep 'ML_KEM_768' <<< "${CHARON_ALGS}")"

# ---- 4) Load configuration and initiate --------------------------------
# --load-conns, NOT --load-all/--load-creds. `swanctl --load-creds` performs a
# destructive sync: it unload-shares every vici-injected credential absent from
# swanctl.conf, which would delete the rotating QKD PPK on every invocation.
# ORDER MATTERS. Credentials first, connections second.
#
# `start_action = start` makes --load-conns initiate the SA the instant the
# connection is loaded. charon resolves the PPK_ID synchronously inside
# IKE_AUTH, so if the bootstrap PPK is not already present the exchange dies
# with "PPK required but no PPK found" and the SA is destroyed -- before the
# --load-creds on the next line has had a chance to run.
echo "[entrypoint] loading bootstrap credentials"
swanctl --load-creds   # bootstrap credentials, once, before arnika takes over
echo "[entrypoint] loading connections"
swanctl --load-conns

# Deliberately NOT calling `swanctl --initiate`.
#
# The child is configured with `start_action = trap`, so charon installs a trap
# policy and initiates on the first matching packet. An explicit --initiate here
# is redundant, and under `set -euo pipefail` it is fatal: it blocks until the
# SA either establishes or fails, and a failure exits the container. With both
# peers starting simultaneously that is also a boot-order race -- whichever
# comes up first tries to initiate against a peer that is not listening yet.

# ---- 5) arnika with the strongSwan VICI key-writer ---------------------
export VICI_SOCKET
export VICI_CONNECTION="${VICI_CONNECTION:?VICI_CONNECTION must be set}"
export VICI_PPK_ID="${PPK_ID}"
export VICI_CREDENTIAL_PREFIX="${VICI_CREDENTIAL_PREFIX:?VICI_CREDENTIAL_PREFIX must be set}"
export VICI_REAUTH_TIMEOUT="${VICI_REAUTH_TIMEOUT:?VICI_REAUTH_TIMEOUT must be set}"
export VICI_IKE_ROLE   # validated above; also selects start_action
export VICI_CHILD="${VICI_CHILD:?VICI_CHILD must be set}"
export VICI_BOOTSTRAP_ID="${VICI_BOOTSTRAP_ID:?VICI_BOOTSTRAP_ID must be set}"

export INTERVAL="${ARNIKA_INTERVAL:?ARNIKA_INTERVAL must be set}"
export MODE="${ARNIKA_MODE:?ARNIKA_MODE must be set}"
export KMS_URL="${KMS_URL:?KMS_URL must be set}"
export LISTEN_ADDRESS SERVER_ADDRESS   # validated above, before rendering
# The PQC half of the PPK; validated at the top (validate_arnika_input).
export PQC_ENABLED

# INFO, and only INFO. The VICI adapter logs through the standard `log`
# package, which arnika's slog.SetDefault bridges into its handler at INFO.
# LOG_LEVEL=warn or error would therefore drop every "PPK rotated" line --
# the lines the WebUI counts for /api/vpn/ppk-rotations and the CI ipsec job
# greps -- while the tunnel kept rotating. debug logs one line per rejected
# datagram on the packet path, which arnika's rate limiter bounds in work but
# not in log volume (see LOG_LEVEL in arnika's logging.go).
case "${LOG_LEVEL:-info}" in
    info) ;;
    *)
        echo "[entrypoint] FATAL: LOG_LEVEL is '${LOG_LEVEL}'; this node requires 'info'." >&2
        echo "[entrypoint] A higher level hides the adapter's rotation log lines." >&2
        exit 1
        ;;
esac
export LOG_LEVEL=info

# See nodes/alice/entrypoint.sh for why these two cannot be defaulted: arnika
# elects PRIMARY/BACKUP from HMAC-SHA256(ARNIKA_PSK, interval) XOR ARNIKA_ID, so
# the PSK must match and the IDs must differ in their lowest bit. The parity
# also picks each direction's HMAC key (auth.DirectionFor), so same-parity
# peers now fail authentication outright rather than only mis-electing.
export ARNIKA_ID="${ARNIKA_ID:?ARNIKA_ID must be set, and must differ in parity between the two peers}"
export ARNIKA_PSK   # validated above: set, >= MIN_ARNIKA_PSK_BYTES, not the placeholder

# arnika's config parser requires these even for a non-WireGuard key writer.
# They are unused by the VICI adapter; making them conditional on the selected
# adapter is an upstream change proposed alongside the adapter itself.
export WIREGUARD_INTERFACE="${WIREGUARD_INTERFACE:-unused-by-vici-writer}"
export WIREGUARD_PEER_PUBLIC_KEY="${WIREGUARD_PEER_PUBLIC_KEY:-unused-by-vici-writer}"

echo "[entrypoint] starting arnika VICI key-writer (MODE=${MODE} INTERVAL=${INTERVAL} ID=${ARNIKA_ID})"

# Reap charon if arnika exits, so a dead key-writer cannot leave a tunnel
# running on a stale key.
#
# Note this deliberately does NOT `exec`. `exec` replaces the shell, which
# discards the trap -- so the previous version installed a handler that could
# never fire and charon was never reaped. Run arnika as a child and clean up
# after it instead.
trap 'kill "${CHARON_PID}" 2>/dev/null || true' EXIT
# INT and TERM end the script, and the EXIT trap then stops charon. When the
# INT/TERM trap only stopped charon, `wait` below returned the signal's status
# while arnika was still running, and every `docker stop` logged a false
# "arnika exited with status 143". The statuses are 128 plus the signal
# number, as a shell reports a child the signal killed.
EXIT_STATUS_ON_SIGINT=130
EXIT_STATUS_ON_SIGTERM=143
trap 'exit "${EXIT_STATUS_ON_SIGINT}"' INT
trap 'exit "${EXIT_STATUS_ON_SIGTERM}"' TERM

/usr/local/bin/arnika &
ARNIKA_PID=$!
# `|| ARNIKA_RC=$?`, because under `set -e` a bare failing `wait` exits the
# script before the line below can report the status.
ARNIKA_RC=0
wait "${ARNIKA_PID}" || ARNIKA_RC=$?
echo "[entrypoint] arnika exited with status ${ARNIKA_RC}; stopping charon" >&2
exit "${ARNIKA_RC}"
