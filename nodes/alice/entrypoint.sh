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

# Kernel WireGuard first; userspace only when the module is absent.
#
# This was an unconditional `ip link add ... type wireguard` under
# `set -euo pipefail`, so on a host without the module the container died right
# here -- while README.md and docs/BUILD.md both promised "the stack still
# works and you need to do nothing", and `wireguard-go` sat installed in the
# image (nodes/alice/Dockerfile) and was never invoked once. Nothing in the
# tree calls `wg-quick`, which is what those documents assumed would arrange
# the fallback, so WG_QUICK_USERSPACE_IMPLEMENTATION was read by nothing --
# and tests/test_compose_env_is_read_by_something.py exempted it on the
# strength of that same assumption.
#
# Selecting the implementation by variable keeps docker-compose.boringtun.yml
# working, which sets it to `boringtun`.
if ! ip link add dev "$WG_IFACE" type wireguard 2>/dev/null; then
    userspace="${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}"
    command -v "$userspace" >/dev/null 2>&1 || {
        echo "[entrypoint] ERROR: kernel WireGuard is unavailable and the userspace" >&2
        echo "[entrypoint]        implementation '$userspace' is not installed" >&2
        exit 1
    }
    echo "[entrypoint] kernel WireGuard unavailable; using userspace $userspace"
    "$userspace" "$WG_IFACE"
fi
wg set "$WG_IFACE" listen-port "$WG_LISTEN_PORT" private-key "$WG_DIR/private.key"
ip addr add "${WG_LOCAL_IP}/24" dev "$WG_IFACE"
ip link set up dev "$WG_IFACE"

wg set "$WG_IFACE" peer "$PEER_PUB" \
    endpoint "$WG_PEER_ENDPOINT" \
    allowed-ips "${WG_PEER_IP}/32" \
    persistent-keepalive 25

# Additional WireGuard peers, for a trusted-node chain where one node faces two
# neighbours. Space-separated `name@endpoint:port/tunnel-ip` entries; the peer's
# WireGuard public key is read from $SHARED_DIR/<name>.wg.pub.
#
# Without this the node configured exactly one peer, so in the multihop profile
# alice knew bob and not charlie: charlie's wg0 showed traffic sent and none
# received, with no handshake, because the far end had never heard of it. The
# Rosenpass layer already supported multiple peers; this is the layer below it.
for entry in ${WG_EXTRA_PEERS:-}; do
  name="${entry%%@*}"
  rest="${entry#*@}"
  endpoint="${rest%%/*}"
  tunnel_ip="${rest##*/}"
  if [[ "$name" == "$entry" || -z "$endpoint" || -z "$tunnel_ip" || "$endpoint" == "$rest" ]]; then
    echo "[entrypoint] ERROR: WG_EXTRA_PEERS entry '$entry' is not name@host:port/tunnel-ip" >&2
    exit 1
  fi

  pub_file="$SHARED_DIR/$name.wg.pub"
  echo "[entrypoint] waiting for extra peer ($name) WireGuard key ..."
  for _ in $(seq 1 120); do
    [[ -s "$pub_file" ]] && break
    sleep 1
  done
  # Fatal, not skipped: a configured neighbour whose key never arrives means the
  # chain is short a hop, and bringing the tunnel up anyway hides that.
  if [[ ! -s "$pub_file" ]]; then
    echo "[entrypoint] ERROR: extra peer '$name' public key not available ($pub_file)" >&2
    exit 1
  fi

  extra_pub="$(tr -d '\n' < "$pub_file")"
  echo "[entrypoint] extra peer $name: $extra_pub via $endpoint ($tunnel_ip)"
  wg set "$WG_IFACE" peer "$extra_pub" \
      endpoint "$endpoint" \
      allowed-ips "${tunnel_ip}/32" \
      persistent-keepalive 25
done

# ---- 5) Rosenpass sidecar (REAL PQ exchange) ---------------
export ROSENPASS_SECRET_DIR
export ROSENPASS_PEER_PK="$PEER_RP_PUB_FILE"
export RP_LISTEN_PORT RP_PEER_PORT
export RP_PEER_HOST="$PEER_HOST"
# Extra neighbours for a trusted-node chain, e.g. RP_EXTRA_PEERS="charlie@charlie:9997".
# rosenpass takes any number of peers; the sidecar builds one clause per entry.
export RP_EXTRA_PEERS="${RP_EXTRA_PEERS:-}"
export SHARED_DIR
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
# These env vars map directly to arnika's config (see submodules/arnika/config/config.go)
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

# ARNIKA_ID and ARNIKA_PSK are both load-bearing and have no safe default here.
#
# arnika elects the per-interval master with
#     IsPrimary = ((HMAC-SHA256(ARNIKA_PSK, intervalNum)[0]) XOR ARNIKA_ID) & 1 == 0
# (config/config.go). The XOR against ARNIKA_ID is the ONLY thing that makes two
# peers reach opposite conclusions, so the two IDs must differ. Left unset,
# arnika defaults ARNIKA_ID to the port parsed from LISTEN_ADDRESS -- and both
# of our nodes listen on :9999, which would give both peers the same role every
# interval and deadlock the key exchange. Fail loudly rather than ship that.
export ARNIKA_ID="${ARNIKA_ID:?ARNIKA_ID must be set, and must differ between the two peers}"

# ARNIKA_PSK keys the AES-256-GCM encryption and HMAC-SHA256 signature applied
# to the UDP key_ID packets (auth/auth.go), as well as the role election above.
# An empty value leaves that channel unauthenticated, so require it explicitly.
export ARNIKA_PSK="${ARNIKA_PSK:?ARNIKA_PSK must be set, and must be identical on both peers}"

# A second arnika per extra neighbour.
#
# arnika manages exactly ONE WIREGUARD_PEER_PUBLIC_KEY, so a node facing two
# neighbours needs one instance per leg. Without this, alice installed a
# QKD-derived PSK on the bob peer and left the charlie peer with none -- the
# tunnel was up and unprotected, which `wg show` reports as
# `1 of 2 peers have a preshared key` and no log line admits.
#
# Entries are `name@peer-host:port` in ARNIKA_EXTRA_PEERS. Each instance gets:
#   * its own UDP port, so the two do not contend for :9999
#   * its own KMS SAE path, since ETSI 014 names the PEER
#   * the neighbour's WireGuard public key, read from $SHARED_DIR
#   * its own PQC PSK file, written by the matching rosenpass peer clause
for entry in ${ARNIKA_EXTRA_PEERS:-}; do
  name="${entry%%@*}"
  hostport="${entry#*@}"
  if [[ "$name" == "$entry" || -z "$hostport" ]]; then
    echo "[entrypoint] ERROR: ARNIKA_EXTRA_PEERS entry '$entry' is not name@host:port" >&2
    exit 1
  fi
  port="${hostport##*:}"
  pub_file="$SHARED_DIR/$name.wg.pub"
  if [[ ! -s "$pub_file" ]]; then
    echo "[entrypoint] ERROR: arnika extra peer '$name' has no WireGuard key ($pub_file)" >&2
    exit 1
  fi

  upper_name="$(echo "$name" | tr '[:lower:]' '[:upper:]')"
  echo "[entrypoint] starting arnika for $name (listen :$port peer $hostport SAE=$upper_name)"
  env LISTEN_ADDRESS="0.0.0.0:$port" \
      SERVER_ADDRESS="$hostport" \
      KMS_URL="${KMS_URL%/*}/$upper_name" \
      WIREGUARD_PEER_PUBLIC_KEY="$(tr -d '\n' < "$pub_file")" \
      PQC_PSK_FILE="${PQC_PSK_FILE%.psk}.$name.psk" \
      ARNIKA_ID="$ARNIKA_ID" \
      /usr/local/bin/arnika &
done

echo "[entrypoint] starting arnika (MODE=$MODE INTERVAL=$INTERVAL ID=$ARNIKA_ID KMS=$KMS_URL)"
exec /usr/local/bin/arnika
