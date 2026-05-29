#!/usr/bin/env bash
# =====================================================================
# strongSwan IPsec node entrypoint.
#
# 1. Generate the initial PSK from /dev/urandom (replaced by arnika via
#    the vici bridge once QKD/PQC handshakes start).
# 2. Render swanctl config from template.
# 3. Start charon (IKE daemon) and load the connection.
# 4. Launch the arnika-vici PSK rotation loop in the background.
# =====================================================================
set -euo pipefail

NODE_NAME="${NODE_NAME:-alice-ipsec}"
LOCAL_IP="${LOCAL_IP:-10.30.0.20}"
PEER_IP="${PEER_IP:-10.30.0.21}"
LOCAL_ID="${LOCAL_ID:-alice@pqcqkd.local}"
PEER_ID="${PEER_ID:-bob@pqcqkd.local}"
KMS_URL="${KMS_URL:-http://bb84-kme-a:8080/api/v1/keys/ALICE}"
PSK_INTERVAL="${PSK_INTERVAL:-30}"

mkdir -p /etc/swanctl/conf.d

# 1) Initial PSK — 32 bytes of urandom, hex-encoded
PSK_HEX=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')

# 2) Render swanctl conf
sed -e "s|__LOCAL_IP__|${LOCAL_IP}|g" \
    -e "s|__PEER_IP__|${PEER_IP}|g" \
    -e "s|__LOCAL_ID__|${LOCAL_ID}|g" \
    -e "s|__PEER_ID__|${PEER_ID}|g" \
    -e "s|__PSK_HEX__|${PSK_HEX}|g" \
    /etc/swanctl/conf.d/pqcqkd.conf.tmpl \
    > /etc/swanctl/conf.d/pqcqkd.conf

echo "[entrypoint] starting charon (IKE daemon)..."
/usr/local/sbin/charon &
CHARON_PID=$!

# Wait for the vici socket to come up
for i in $(seq 1 30); do
    [ -S /var/run/charon.vici ] && break
    sleep 1
done

echo "[entrypoint] loading swanctl config..."
/usr/local/sbin/swanctl --load-all || true
/usr/local/sbin/swanctl --initiate --child tunnel || true

echo "[entrypoint] starting arnika-vici PSK rotation bridge (interval=${PSK_INTERVAL}s)..."
KMS_URL="${KMS_URL}" PSK_INTERVAL="${PSK_INTERVAL}" \
  LOCAL_ID="${LOCAL_ID}" PEER_ID="${PEER_ID}" \
  /usr/local/bin/arnika-vici-bridge.sh &

wait "${CHARON_PID}"
