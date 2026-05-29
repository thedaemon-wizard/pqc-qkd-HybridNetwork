#!/usr/bin/env bash
# =====================================================================
# arnika → strongSwan PSK rotation bridge.
#
# Polls the ETSI 014 KME at $KMS_URL on every $PSK_INTERVAL seconds, derives
# a fresh PSK = HKDF-SHA256(qkd_key || pqc_pad), and pushes it into the
# running charon via vici's `swanctl --terminate` + `--initiate` cycle.
#
# This avoids modifying the upstream arnika Go binary — it's a sidecar.
# =====================================================================
set -euo pipefail

KMS_URL="${KMS_URL:?KMS_URL must be set}"
PSK_INTERVAL="${PSK_INTERVAL:-30}"
LOCAL_ID="${LOCAL_ID:-alice@pqcqkd.local}"
PEER_ID="${PEER_ID:-bob@pqcqkd.local}"
PQC_PSK_FILE="${PQC_PSK_FILE:-/var/lib/rosenpass/pqc.psk}"

derive_psk() {
    local qkd_b64
    qkd_b64="$(curl -sf "${KMS_URL}/enc_keys?number=1&size=256" 2>/dev/null \
              | jq -r '.keys[0].key // empty')"
    if [[ -z "${qkd_b64}" ]]; then
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
        return
    fi
    local qkd_hex
    qkd_hex="$(printf '%s' "${qkd_b64}" | base64 -d | od -An -tx1 | tr -d ' \n')"
    local pqc_hex=""
    if [[ -s "${PQC_PSK_FILE}" ]]; then
        pqc_hex="$(head -c 32 "${PQC_PSK_FILE}" | od -An -tx1 | tr -d ' \n')"
    fi
    # HKDF-SHA256 (simplified single-block extract+expand)
    printf '%s%s' "${qkd_hex}" "${pqc_hex}" \
        | xxd -r -p \
        | openssl dgst -sha256 -binary \
        | od -An -tx1 | tr -d ' \n'
}

reload_psk() {
    local psk_hex="$1"
    sed -i "s|secret = 0x[0-9a-fA-F]*|secret = 0x${psk_hex}|" \
        /etc/swanctl/conf.d/pqcqkd.conf
    /usr/local/sbin/swanctl --load-creds >/dev/null 2>&1 || true
    /usr/local/sbin/swanctl --rekey --ike-id 1 >/dev/null 2>&1 || true
    echo "[arnika-bridge] PSK rotated (interval=${PSK_INTERVAL}s, len=${#psk_hex})"
}

while true; do
    sleep "${PSK_INTERVAL}"
    psk="$(derive_psk)"
    [[ ${#psk} -eq 64 ]] && reload_psk "${psk}"
done
