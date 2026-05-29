#!/usr/bin/env bash
# ===================================================================
# Generate self-signed mTLS certificates for ETSI-014 KME endpoints.
# Idempotent: skips if certs already exist.
# Output:
#   pki/ca.{key,pem}
#   pki/server-{alice,bob}.{key,pem}
#   pki/client-{alice,bob}.{key,pem}
# ===================================================================
set -euo pipefail

PKI_DIR="$(cd "$(dirname "$0")" && pwd)"
DAYS=825   # < 27 months to comply with TLS policy norms

mkdir -p "$PKI_DIR"
cd "$PKI_DIR"

if [[ -f ca.pem ]]; then
  echo "[pki] CA already exists; skipping. Delete pki/*.pem to regenerate."
  exit 0
fi

echo "[pki] Generating CA..."
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -nodes -key ca.key -sha256 -days $DAYS \
  -subj "/CN=PQCQKD-PoC-CA" \
  -out ca.pem

issue_cert() {
  local name="$1" san="$2" purpose="$3"
  echo "[pki] Issuing cert: ${name} (${purpose}, SAN=${san})"
  openssl genrsa -out "${name}.key" 2048 2>/dev/null

  local ext_usage
  if [[ "$purpose" == "server" ]]; then
    ext_usage="serverAuth"
  else
    ext_usage="clientAuth"
  fi

  cat > "${name}.cnf" <<EOF
[req]
distinguished_name = dn
req_extensions = v3_req
prompt = no
[dn]
CN = ${name}
[v3_req]
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = ${ext_usage}
subjectAltName = ${san}
EOF

  openssl req -new -key "${name}.key" -out "${name}.csr" -config "${name}.cnf"
  openssl x509 -req -in "${name}.csr" -CA ca.pem -CAkey ca.key -CAcreateserial \
    -out "${name}.pem" -days $DAYS -sha256 \
    -extfile "${name}.cnf" -extensions v3_req

  rm -f "${name}.csr" "${name}.cnf"
  chmod 600 "${name}.key"
}

issue_cert server-alice "DNS:bb84-kme-a,DNS:localhost,IP:127.0.0.1" server
issue_cert server-bob   "DNS:bb84-kme-b,DNS:localhost,IP:127.0.0.1" server
issue_cert client-alice "DNS:alice"     client
issue_cert client-bob   "DNS:bob"       client

chmod 600 ca.key
echo "[pki] Done. Certificates in: $PKI_DIR"
