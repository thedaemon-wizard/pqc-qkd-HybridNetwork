#!/usr/bin/env bash
# ============================================================
# Rosenpass sidecar — runs a REAL post-quantum key exchange.
#
# rosenpass(1) v0.2.3 performs the Rosenpass PQ handshake with the peer
# over UDP and periodically (~every 2 min) derives a fresh Output Shared
# Key (OSK), writing it base64-encoded to $PQC_PSK_FILE. arnika then
# HKDF-combines that PQC half with the QKD key (MODE=QkdAndPqcRequired):
#       WireGuard PSK = base64(HKDF-SHA3-256(QKD_key ‖ PQC_OSK))[:32]
#
# There is NO urandom fallback: if the keypair or peer public key is
# missing, or the exchange cannot start, this script exits non-zero so
# the failure is visible rather than masked by fake randomness.
#
# Required env (exported by entrypoint.sh):
#   ROSENPASS_SECRET_DIR  own keypair dir (pqc.pk / pqc.sk)
#   ROSENPASS_PEER_PK     path to the peer's rosenpass public key
#   RP_LISTEN_PORT        local UDP port to listen on (container-internal)
#   RP_PEER_HOST          peer hostname/IP
#   RP_PEER_PORT          peer rosenpass UDP port
#   PQC_PSK_FILE          output OSK file (base64) consumed by arnika
# ============================================================
set -euo pipefail

PQC_PSK_FILE="${PQC_PSK_FILE:-/var/lib/rosenpass/pqc.psk}"
SECRET_DIR="${ROSENPASS_SECRET_DIR:-/etc/rosenpass-secret}"
OWN_PK="$SECRET_DIR/pqc.pk"
OWN_SK="$SECRET_DIR/pqc.sk"
PEER_PK="${ROSENPASS_PEER_PK:-/tmp/peer-rosenpass.pk}"
RP_LISTEN_PORT="${RP_LISTEN_PORT:-9997}"
RP_PEER_HOST="${RP_PEER_HOST:?RP_PEER_HOST must be set}"
RP_PEER_PORT="${RP_PEER_PORT:-9997}"

# Additional peers, for a trusted-node chain where one node faces two
# neighbours. Space-separated `name@host:port` entries; the public key for
# `name` is read from $SHARED_DIR/<name>.rp.pub.
#
# rosenpass has always supported this -- `rosenpass exchange <OWN> [PEERS]...`
# is variadic and its help says "the `peer` token always separates multiple
# peers". This script was the limitation, not the library: it accepted exactly
# one RP_PEER_HOST, which is why alice could peer with bob but not also with
# charlie, and why the multi-hop profile could not relay. No new dependency was
# needed to fix it.
RP_EXTRA_PEERS="${RP_EXTRA_PEERS:-}"
SHARED_DIR="${SHARED_DIR:-/shared}"

mkdir -p "$(dirname "$PQC_PSK_FILE")"

if [[ ! -s "$OWN_PK" || ! -s "$OWN_SK" ]]; then
  echo "[rosenpass-sidecar] FATAL: own keypair missing ($OWN_PK / $OWN_SK)" >&2
  exit 1
fi
if [[ ! -s "$PEER_PK" ]]; then
  echo "[rosenpass-sidecar] FATAL: peer public key missing ($PEER_PK)" >&2
  exit 1
fi

# Build the peer clauses. The primary peer keeps writing the OSK that arnika
# reads, so its outfile is unchanged; each extra peer gets its own outfile so a
# second neighbour cannot overwrite the first one's key.
PEER_ARGS=(peer public-key "$PEER_PK"
           endpoint "$RP_PEER_HOST:$RP_PEER_PORT"
           outfile "$PQC_PSK_FILE")
DESC="$RP_PEER_HOST:$RP_PEER_PORT"

for entry in $RP_EXTRA_PEERS; do
  name="${entry%%@*}"
  hostport="${entry#*@}"
  [[ "$name" == "$entry" || -z "$hostport" ]] && {
    echo "[rosenpass-sidecar] FATAL: RP_EXTRA_PEERS entry '$entry' is not name@host:port" >&2
    exit 1
  }
  pk="$SHARED_DIR/$name.rp.pub"
  # No skip-and-continue here: a peer that was configured but whose key is
  # absent is a broken chain, and continuing would bring the tunnel up with a
  # neighbour silently missing.
  if [[ ! -s "$pk" ]]; then
    echo "[rosenpass-sidecar] FATAL: public key for extra peer '$name' missing ($pk)" >&2
    exit 1
  fi
  PEER_ARGS+=(peer public-key "$pk"
              endpoint "$hostport"
              outfile "${PQC_PSK_FILE%.psk}.$name.psk")
  DESC="$DESC, $name@$hostport"
done

echo "[rosenpass-sidecar] starting REAL rosenpass exchange:" \
     "listen 0.0.0.0:$RP_LISTEN_PORT peers [$DESC] -> $PQC_PSK_FILE"

# Long-running daemon: refreshes the OSK in $PQC_PSK_FILE ~every 2 minutes.
exec rosenpass exchange \
    public-key "$OWN_PK" secret-key "$OWN_SK" \
    listen "0.0.0.0:$RP_LISTEN_PORT" verbose \
    "${PEER_ARGS[@]}"
