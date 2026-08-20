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

# Needed before the config is rendered, because the bootstrap credentials are
# derived from it. See the note below.
ARNIKA_PSK="${ARNIKA_PSK:?ARNIKA_PSK must be set, and must be identical on both peers}"

# Also needed before rendering: the control-plane bypass shunt is built from
# these. They are re-exported for arnika further down.
LISTEN_ADDRESS="${LISTEN_ADDRESS:?LISTEN_ADDRESS must be set}"
SERVER_ADDRESS="${SERVER_ADDRESS:?SERVER_ADDRESS must be set}"

# Which peer owns the shared IKE_SA. The two nodes must disagree: one
# "initiator", one "responder". The same value gates both halves of SA
# ownership -- who initiates (start_action, here) and who reauthenticates after
# a key rotation (VICI_IKE_ROLE, read by the adapter) -- so they cannot drift
# apart. See the comment on ViciConfig.DriveReauth for what two drivers cost.
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
# on both peers (it keys arnika's master election and its UDP key_ID channel).
# Two separate `info` strings keep the two derived values independent, so
# recovering one tells you nothing about the other.
#
# These are BOOTSTRAP values and are NOT QKD material: they exist only so the
# first IKE_AUTH can complete. arnika replaces the PPK with HKDF(QKD || PQC)
# output on its first rotation, and every reauthentication after that consumes
# QKD-derived material.
derive_bootstrap_secret() {
    printf '%s' "$ARNIKA_PSK" > /run/arnika-psk.tmp
    chmod 600 /run/arnika-psk.tmp
    # hexkey via a file keeps ARNIKA_PSK off the process command line, which is
    # world-readable through /proc.
    openssl kdf -keylen 32 \
        -kdfopt digest:SHA256 \
        -kdfopt "hexkey:$(od -An -tx1 < /run/arnika-psk.tmp | tr -d ' \n')" \
        -kdfopt "info:$1" \
        -binary HKDF | od -An -tx1 | tr -d ' \n'
    rm -f /run/arnika-psk.tmp
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
if ! swanctl --list-algs | grep -q 'ML_KEM_768'; then
    echo "[entrypoint] FATAL: ML_KEM_768 is not available in charon." >&2
    echo "[entrypoint] The 'ml'/'openssl' plugins must be built AND named in" >&2
    echo "[entrypoint] the charon load line (/etc/strongswan.conf)." >&2
    echo "[entrypoint] Key-exchange methods charon actually offers:" >&2
    swanctl --list-algs | sed -n '/^ke:/,/^[a-z-]*:/p' >&2
    exit 1
fi
echo "[entrypoint] ML_KEM_768 available: $(swanctl --list-algs | grep 'ML_KEM_768')"

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

export INTERVAL="${ARNIKA_INTERVAL:?ARNIKA_INTERVAL must be set}"
export MODE="${ARNIKA_MODE:?ARNIKA_MODE must be set}"
export KMS_URL="${KMS_URL:?KMS_URL must be set}"
export LISTEN_ADDRESS SERVER_ADDRESS   # validated above, before rendering
export PQC_PSK_FILE="${PQC_PSK_FILE:?PQC_PSK_FILE must be set}"

# See nodes/alice/entrypoint.sh for why these two cannot be defaulted: arnika's
# master election is HMAC(ARNIKA_PSK, interval) XOR ARNIKA_ID, so the IDs must
# differ between peers and the PSK must match.
export ARNIKA_ID="${ARNIKA_ID:?ARNIKA_ID must be set, and must differ between the two peers}"
export ARNIKA_PSK="${ARNIKA_PSK:?ARNIKA_PSK must be set, and must be identical on both peers}"

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
trap 'kill "${CHARON_PID}" 2>/dev/null || true' EXIT INT TERM

/usr/local/bin/arnika &
ARNIKA_PID=$!
wait "${ARNIKA_PID}"
ARNIKA_RC=$?
echo "[entrypoint] arnika exited with status ${ARNIKA_RC}; stopping charon" >&2
exit "${ARNIKA_RC}"
