#!/usr/bin/env bash
# ============================================================
# Node entrypoint:
#   1. Generate WireGuard keypair if absent
#   2. Bring up wg0 with local config (no PSK initially)
#   3. Start Rosenpass sidecar in background -> writes PQC_PSK_FILE
#   4. Start arnika -> rotates WireGuard PSK = HKDF(QKD || PQC)
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

WG_DIR=/etc/wireguard
mkdir -p "$WG_DIR"

# ---- 1) WireGuard keypair ----------------------------------
if [[ ! -f "$WG_DIR/private.key" ]]; then
  echo "[entrypoint] generating WireGuard keypair"
  umask 077
  wg genkey > "$WG_DIR/private.key"
  wg pubkey < "$WG_DIR/private.key" > "$WG_DIR/public.key"
fi

LOCAL_PUB="$(cat "$WG_DIR/public.key")"
echo "[entrypoint] $NODE_NAME public key: $LOCAL_PUB"

# Publish our public key over a tiny HTTP-less file exchange so the peer
# container can discover it. We use the shared `wan-net` via curl on the peer's
# /pubkey endpoint exposed by a coproc.
# (Simplification: bake peer pubkey via env when present; otherwise probe peer.)

PEER_HOST="${WG_PEER_ENDPOINT%%:*}"
PEER_PUB_FILE=/tmp/peer.pub
if [[ -n "${PEER_PUBLIC_KEY:-}" ]]; then
  echo "$PEER_PUBLIC_KEY" > "$PEER_PUB_FILE"
else
  # Run a tiny "publish my pubkey" HTTP server on port 9100 so the peer can grab us.
  ( while true; do
      { echo -e "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: $(wc -c < "$WG_DIR/public.key")\r\n\r\n$(cat "$WG_DIR/public.key")"; } | nc -l -p 9100 -q 1 || true
    done ) &
  echo "[entrypoint] published pubkey on :9100, waiting for peer ($PEER_HOST:9100)..."
  for i in $(seq 1 60); do
    if curl -sf "http://$PEER_HOST:9100/" -o "$PEER_PUB_FILE" 2>/dev/null; then
      [[ -s "$PEER_PUB_FILE" ]] && break
    fi
    sleep 1
  done
fi

PEER_PUB="$(tr -d '\n' < "$PEER_PUB_FILE" 2>/dev/null || true)"
if [[ -z "$PEER_PUB" ]]; then
  echo "[entrypoint] ERROR: could not obtain peer public key from $PEER_HOST" >&2
  exit 1
fi
echo "[entrypoint] peer public key: $PEER_PUB"

# ---- 2) Bring up wg0 ---------------------------------------
ip link del "$WG_IFACE" 2>/dev/null || true
ip link add dev "$WG_IFACE" type wireguard
wg set "$WG_IFACE" listen-port "$WG_LISTEN_PORT" private-key "$WG_DIR/private.key"
ip addr add "${WG_LOCAL_IP}/24" dev "$WG_IFACE"
ip link set up dev "$WG_IFACE"

wg set "$WG_IFACE" peer "$PEER_PUB" \
    endpoint "$WG_PEER_ENDPOINT" \
    allowed-ips "${WG_PEER_IP}/32" \
    persistent-keepalive 25

# ---- 3) Rosenpass sidecar ----------------------------------
PQC_PSK_FILE="${PQC_PSK_FILE:-/var/lib/rosenpass/pqc.psk}"
mkdir -p "$(dirname "$PQC_PSK_FILE")"
/usr/local/bin/rosenpass-sidecar.sh &
ROSENPASS_PID=$!

# Wait until Rosenpass has produced at least one PQC key
echo "[entrypoint] waiting for Rosenpass PQC PSK ($PQC_PSK_FILE)..."
for i in $(seq 1 30); do
  [[ -s "$PQC_PSK_FILE" ]] && break
  sleep 1
done
if [[ ! -s "$PQC_PSK_FILE" ]]; then
  echo "[entrypoint] WARNING: PQC PSK not produced yet; arnika may fall back per mode" >&2
fi

# ---- 4) arnika (foreground) --------------------------------
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
export ARNIKA_ID="$NODE_NAME"

echo "[entrypoint] starting arnika (MODE=$MODE INTERVAL=$INTERVAL KMS=$KMS_URL)"
exec /usr/local/bin/arnika
