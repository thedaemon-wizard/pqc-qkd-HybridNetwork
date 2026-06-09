#!/usr/bin/env bash
# ============================================================
# Node entrypoint:
#   1. Generate WireGuard keypair if absent
#   2. Generate Rosenpass (PQ) keypair if absent
#   3. Exchange BOTH public keys with the peer via a shared volume
#   4. Bring up wg0 with local config (PSK injected later by arnika)
#   5. Start Rosenpass sidecar -> REAL PQ exchange -> writes PQC_PSK_FILE
#   6. Start arnika -> rotates WireGuard PSK = HKDF(QKD || PQC)
#
# Both alice and bob use this script; behaviour differentiates via env.
# ============================================================
set -euo pipefail

NODE_NAME="${NODE_NAME:-alice}"
WG_IFACE="${WG_IFACE:-wg0}"
WG_LISTEN_PORT="${WG_LISTEN_PORT:-51820}"
WG_LOCAL_IP="${WG_LOCAL_IP:-10.0.0.1}"
WG_PEER_IP="${WG_PEER_IP:-10.0.0.2}"
WG_PEER_ENDPOINT="${WG_PEER_ENDPOINT:-bob:51821}"

# Peer identity = the hostname part of its WG endpoint (== its container/node name).
PEER_HOST="${WG_PEER_ENDPOINT%%:*}"
PEER_NAME="${PEER_NAME:-$PEER_HOST}"

# Rosenpass (post-quantum) parameters
RP_LISTEN_PORT="${RP_LISTEN_PORT:-9997}"
RP_PEER_PORT="${RP_PEER_PORT:-9997}"
ROSENPASS_SECRET_DIR="${ROSENPASS_SECRET_DIR:-/etc/rosenpass-secret}"
PQC_PSK_FILE="${PQC_PSK_FILE:-/var/lib/rosenpass/pqc.psk}"

# Shared volume used to swap public keys between the two containers.
SHARED_DIR="${SHARED_DIR:-/shared}"
mkdir -p "$SHARED_DIR"

WG_DIR=/etc/wireguard
mkdir -p "$WG_DIR" "$ROSENPASS_SECRET_DIR" "$(dirname "$PQC_PSK_FILE")"

# ---- 1) WireGuard keypair ----------------------------------
if [[ ! -f "$WG_DIR/private.key" ]]; then
  echo "[entrypoint] generating WireGuard keypair"
  umask 077
  wg genkey > "$WG_DIR/private.key"
  wg pubkey < "$WG_DIR/private.key" > "$WG_DIR/public.key"
fi
LOCAL_PUB="$(cat "$WG_DIR/public.key")"
echo "[entrypoint] $NODE_NAME WireGuard public key: $LOCAL_PUB"

# ---- 2) Rosenpass (PQ) keypair -----------------------------
RP_OWN_PK="$ROSENPASS_SECRET_DIR/pqc.pk"
RP_OWN_SK="$ROSENPASS_SECRET_DIR/pqc.sk"
if [[ ! -s "$RP_OWN_PK" || ! -s "$RP_OWN_SK" ]]; then
  echo "[entrypoint] generating Rosenpass keypair"
  rm -f "$RP_OWN_PK" "$RP_OWN_SK"
  rosenpass gen-keys --public-key "$RP_OWN_PK" --secret-key "$RP_OWN_SK" --force
fi

# ---- 3) Exchange public keys via the shared volume ---------
# Publish ours (atomic: write tmp then rename) ...
cp "$WG_DIR/public.key"            "$SHARED_DIR/.$NODE_NAME.wg.pub.tmp"
mv "$SHARED_DIR/.$NODE_NAME.wg.pub.tmp" "$SHARED_DIR/$NODE_NAME.wg.pub"
cp "$RP_OWN_PK"                    "$SHARED_DIR/.$NODE_NAME.rp.pub.tmp"
mv "$SHARED_DIR/.$NODE_NAME.rp.pub.tmp" "$SHARED_DIR/$NODE_NAME.rp.pub"

# ... then wait for the peer to publish theirs.
PEER_WG_PUB_FILE="$SHARED_DIR/$PEER_NAME.wg.pub"
PEER_RP_PUB_FILE="$SHARED_DIR/$PEER_NAME.rp.pub"
echo "[entrypoint] waiting for peer ($PEER_NAME) public keys in $SHARED_DIR ..."
for _ in $(seq 1 120); do
  [[ -s "$PEER_WG_PUB_FILE" && -s "$PEER_RP_PUB_FILE" ]] && break
  sleep 1
done
if [[ ! -s "$PEER_WG_PUB_FILE" || ! -s "$PEER_RP_PUB_FILE" ]]; then
  echo "[entrypoint] ERROR: peer public keys not available ($PEER_WG_PUB_FILE / $PEER_RP_PUB_FILE)" >&2
  exit 1
fi
PEER_PUB="$(tr -d '\n' < "$PEER_WG_PUB_FILE")"
echo "[entrypoint] peer WireGuard public key: $PEER_PUB"

# ---- 4) Bring up wg0 ---------------------------------------
ip link del "$WG_IFACE" 2>/dev/null || true
ip link add dev "$WG_IFACE" type wireguard
wg set "$WG_IFACE" listen-port "$WG_LISTEN_PORT" private-key "$WG_DIR/private.key"
ip addr add "${WG_LOCAL_IP}/24" dev "$WG_IFACE"
ip link set up dev "$WG_IFACE"

wg set "$WG_IFACE" peer "$PEER_PUB" \
    endpoint "$WG_PEER_ENDPOINT" \
    allowed-ips "${WG_PEER_IP}/32" \
    persistent-keepalive 25

# ---- 5) Rosenpass sidecar (REAL PQ exchange) ---------------
export ROSENPASS_SECRET_DIR
export ROSENPASS_PEER_PK="$PEER_RP_PUB_FILE"
export RP_LISTEN_PORT RP_PEER_PORT
export RP_PEER_HOST="$PEER_HOST"
export PQC_PSK_FILE

/usr/local/bin/rosenpass-sidecar.sh &
ROSENPASS_PID=$!

echo "[entrypoint] waiting for Rosenpass PQC OSK ($PQC_PSK_FILE)..."
for _ in $(seq 1 90); do
  [[ -s "$PQC_PSK_FILE" ]] && break
  # surface an early sidecar crash instead of waiting the full timeout
  kill -0 "$ROSENPASS_PID" 2>/dev/null || { echo "[entrypoint] ERROR: rosenpass sidecar exited" >&2; exit 1; }
  sleep 1
done
if [[ ! -s "$PQC_PSK_FILE" ]]; then
  echo "[entrypoint] WARNING: PQC OSK not produced within timeout; arnika will retry per mode" >&2
fi

# ---- 6) arnika (foreground) --------------------------------
# These env vars map directly to arnika's config (see submodules/arnika-vq/config/config.go)
export LISTEN_ADDRESS="${LISTEN_ADDRESS:-0.0.0.0:9999}"
export SERVER_ADDRESS="${SERVER_ADDRESS:-peer:9999}"
export INTERVAL="${ARNIKA_INTERVAL:-30s}"
export MODE="${ARNIKA_MODE:-QkdAndPqcRequired}"
export KMS_URL="${KMS_URL:?KMS_URL must be set}"
export WIREGUARD_INTERFACE="$WG_IFACE"
export WIREGUARD_PEER_PUBLIC_KEY="$PEER_PUB"
export PQC_PSK_FILE
export KMS_HTTP_TIMEOUT="${KMS_HTTP_TIMEOUT:-10s}"
export KMS_BACKOFF_MAX_RETRIES="${KMS_BACKOFF_MAX_RETRIES:-5}"
export KMS_BACKOFF_BASE_DELAY="${KMS_BACKOFF_BASE_DELAY:-200ms}"
export KMS_RETRY_INTERVAL="${KMS_RETRY_INTERVAL:-10s}"
# ARNIKA_ID is an optional numeric identifier; omitting it lets arnika default
# to the port from LISTEN_ADDRESS (NODE_NAME is not numeric, so don't set it).

echo "[entrypoint] starting arnika (MODE=$MODE INTERVAL=$INTERVAL KMS=$KMS_URL)"
exec /usr/local/bin/arnika
