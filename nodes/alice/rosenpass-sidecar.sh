#!/usr/bin/env bash
# ============================================================
# Rosenpass sidecar: keys wg1, the end-to-end data tunnel.
#
# rosenpass(1) v0.2.3 runs the Rosenpass handshake (Classic McEliece 460896 +
# Kyber512) with every peer in RP_PEERS. After each exchange it installs the
# output key as that peer's wg1 preshared key itself: the `wireguard` clause
# makes it run `wg set <wg1> peer <key> preshared-key /dev/stdin`
# (rosenpass/src/app_server.rs, output_key). No key is written to a file, and
# nothing reads one. arnika's PQC half is its own PQC-HPKE agreement now.
#
# The exchange runs inside wg0. rosenpass binds only the wg0 address
# (RP_LISTEN_HOST); of each pair, the end with the lower wg0 address initiates
# to the peer's wg0 address and the other end answers, so its packets are
# routed into the QKD-keyed hop tunnel either way.
#
# Fail closed, and loudly:
#   * a missing keypair, peer key or malformed peer entry is FATAL (exit 1),
#     before rosenpass starts;
#   * when a session expires, rosenpass itself installs a random key
#     (output_key with SymKey::random(), app_server.rs);
#   * if rosenpass exits, this script logs an ERROR, installs a random wg1
#     PSK for every peer it keys, and starts rosenpass again. A dead rosenpass
#     would otherwise leave its last key installed indefinitely: WireGuard has
#     no notion of a key's age, so wg1 would keep working on a key that is
#     never replaced. Restarting here rather than exiting keeps wg0 and arnika
#     running: one layer failing leaves the other intact.
#
# There is NO urandom fallback for the key itself. Only a random key that no
# peer holds is ever installed by this script, and it can only stop wg1.
#
# Required env (exported by entrypoint.sh):
#   ROSENPASS_SECRET_DIR  own keypair dir (pqc.pk / pqc.sk)
#   RP_LISTEN_HOST        this node's wg0 address
#   RP_LISTEN_PORT        UDP port to bind on that address
#   RP_PEERS              space-separated entries, one per peer. name@host:port
#                         means this end initiates, to the peer's wg0 address;
#                         a bare name means it only answers that peer (see
#                         entrypoint.sh for which end initiates, and why only
#                         one). The keys come from $SHARED_DIR/<name>.rp.pub
#                         (Rosenpass) and $SHARED_DIR/<name>.wg1.pub (wg1).
#   WG1_IFACE             the data-tunnel interface rosenpass writes into
#   SHARED_DIR            where the nodes publish their public keys
# ============================================================
set -euo pipefail

SECRET_DIR="${ROSENPASS_SECRET_DIR:?ROSENPASS_SECRET_DIR must be set}"
OWN_PK="$SECRET_DIR/pqc.pk"
OWN_SK="$SECRET_DIR/pqc.sk"
RP_LISTEN_HOST="${RP_LISTEN_HOST:?RP_LISTEN_HOST must be set to this node wg0 address}"
RP_LISTEN_PORT="${RP_LISTEN_PORT:?RP_LISTEN_PORT must be set}"
RP_PEERS="${RP_PEERS:?RP_PEERS must list at least one peer}"
WG1_IFACE="${WG1_IFACE:?WG1_IFACE must be set}"
SHARED_DIR="${SHARED_DIR:?SHARED_DIR must be set}"

# rosenpass(1) logs through env_logger (0.11 in its Cargo.lock), which prints
# only error records when RUST_LOG is unset. The per-exchange line
# "Exchanged key with peer <id>" is an info record, emitted because of
# `verbose` below, and it is the only log evidence that a wg1 key was
# produced. "could not pass psk to wg" is an error record and shows either way.
export RUST_LOG=info

# Seconds between an unexpected rosenpass exit and the restart. Rosenpass's own
# retransmission backoff tops out at 10 s (RETRANSMIT_DELAY_END in
# rosenpass/src/protocol.rs), so a crash-looping daemon retries no faster than
# a healthy one re-sends a lost handshake message.
RESTART_DELAY_S=10

if [[ ! -s "$OWN_PK" || ! -s "$OWN_SK" ]]; then
  echo "[rosenpass-sidecar] FATAL: own keypair missing ($OWN_PK / $OWN_SK)" >&2
  exit 1
fi

# One peer clause per entry. No skip-and-continue: a peer that was configured
# but whose key is absent is a broken chain, and continuing would bring wg1 up
# with a neighbour silently missing.
PEER_ARGS=()
WG1_PEER_KEYS=()
DESC=""
for entry in $RP_PEERS; do
  name="${entry%%@*}"
  if [[ "$name" == "$entry" ]]; then
    endpoint_args=()
    peer_desc="$name (answers only)"
  else
    hostport="${entry#*@}"
    if [[ -z "$name" || "$hostport" != *:* ]]; then
      echo "[rosenpass-sidecar] FATAL: RP_PEERS entry '$entry' is neither name@host:port nor name" >&2
      exit 1
    fi
    endpoint_args=(endpoint "$hostport")
    peer_desc="$name@$hostport"
  fi
  rp_pk="$SHARED_DIR/$name.rp.pub"
  wg1_pub_file="$SHARED_DIR/$name.wg1.pub"
  if [[ ! -s "$rp_pk" ]]; then
    echo "[rosenpass-sidecar] FATAL: Rosenpass public key for peer '$name' missing ($rp_pk)" >&2
    exit 1
  fi
  if [[ ! -s "$wg1_pub_file" ]]; then
    echo "[rosenpass-sidecar] FATAL: $WG1_IFACE public key for peer '$name' missing ($wg1_pub_file)" >&2
    exit 1
  fi
  wg1_pub="$(tr -d '\n' < "$wg1_pub_file")"
  # `wireguard` must close the clause: every token after
  # `wireguard <dev> <peer>` up to the next `peer` is handed to wg(8) as an
  # extra argument (rosenpass/src/config.rs, parse_args).
  PEER_ARGS+=(peer public-key "$rp_pk"
              "${endpoint_args[@]}"
              wireguard "$WG1_IFACE" "$wg1_pub")
  WG1_PEER_KEYS+=("$wg1_pub")
  DESC+="${DESC:+, }$peer_desc"
done

# Installs a random PSK, which no peer holds, on every wg1 peer this sidecar
# keys: new wg1 handshakes fail until rosenpass writes a real key again.
invalidate_wg1() {
  local key
  for key in "${WG1_PEER_KEYS[@]}"; do
    if ! wg genpsk | wg set "$WG1_IFACE" peer "$key" preshared-key /dev/stdin; then
      echo "[rosenpass-sidecar] ERROR: could not install a random PSK on $WG1_IFACE peer $key" >&2
    fi
  done
}

child=""
on_signal() {
  if [[ -n "$child" ]]; then
    kill -TERM "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
  fi
  exit 143
}
trap on_signal TERM INT

echo "[rosenpass-sidecar] starting REAL rosenpass exchange:" \
     "listen $RP_LISTEN_HOST:$RP_LISTEN_PORT peers [$DESC] -> $WG1_IFACE"

# Long-running daemon: a fresh wg1 key per peer every 130 s
# (REKEY_AFTER_TIME_INITIATOR, rosenpass/src/protocol.rs), driven by the end
# of the pair with the lower wg0 address. The answering end never rekeys on
# its own (see rp_peer_entry in entrypoint.sh).
while true; do
  rosenpass exchange \
      public-key "$OWN_PK" secret-key "$OWN_SK" \
      listen "$RP_LISTEN_HOST:$RP_LISTEN_PORT" verbose \
      "${PEER_ARGS[@]}" &
  child=$!
  status=0
  wait "$child" || status=$?
  child=""
  echo "[rosenpass-sidecar] ERROR: rosenpass exited with status $status;" \
       "installing a random $WG1_IFACE PSK for [$DESC] and restarting in ${RESTART_DELAY_S}s" >&2
  invalidate_wg1
  sleep "$RESTART_DELAY_S" &
  child=$!
  wait "$child" || true
  child=""
done
