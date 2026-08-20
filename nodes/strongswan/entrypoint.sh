#!/usr/bin/env bash
# =====================================================================
# strongSwan IPsec node entrypoint.
#
#   1. Render swanctl.conf from the template.
#   2. Start charon and wait for its VICI socket.
#   3. Assert ML-KEM-768 is actually available (not merely configured).
#   4. Load the connection and initiate.
#   5. Exec arnika, whose strongSwan VICI key-writer rotates the RFC 8784 PPK.
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

mkdir -p /etc/swanctl/conf.d

# ---- 1) Render swanctl.conf ------------------------------------------
# Bootstrap credentials only. Both are replaced by arnika's first rotation:
# the PPK by load-shared over VICI, and thereafter every reauthentication
# consumes QKD-derived material.
BOOTSTRAP_PSK=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
BOOTSTRAP_PPK=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')

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
echo "[entrypoint] loading connections"
swanctl --load-conns
swanctl --load-creds   # bootstrap credentials, once, before arnika takes over

echo "[entrypoint] initiating child SA"
swanctl --initiate --child tunnel

# ---- 5) arnika with the strongSwan VICI key-writer ---------------------
export VICI_SOCKET
export VICI_CONNECTION="${VICI_CONNECTION:?VICI_CONNECTION must be set}"
export VICI_PPK_ID="${PPK_ID}"
export VICI_CREDENTIAL_PREFIX="${VICI_CREDENTIAL_PREFIX:?VICI_CREDENTIAL_PREFIX must be set}"
export VICI_REAUTH_TIMEOUT="${VICI_REAUTH_TIMEOUT:?VICI_REAUTH_TIMEOUT must be set}"

export INTERVAL="${ARNIKA_INTERVAL:?ARNIKA_INTERVAL must be set}"
export MODE="${ARNIKA_MODE:?ARNIKA_MODE must be set}"
export KMS_URL="${KMS_URL:?KMS_URL must be set}"
export LISTEN_ADDRESS="${LISTEN_ADDRESS:?LISTEN_ADDRESS must be set}"
export SERVER_ADDRESS="${SERVER_ADDRESS:?SERVER_ADDRESS must be set}"
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
trap 'kill "${CHARON_PID}" 2>/dev/null || true' EXIT
exec /usr/local/bin/arnika
