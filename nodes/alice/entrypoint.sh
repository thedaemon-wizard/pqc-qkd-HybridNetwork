#!/usr/bin/env bash
# ============================================================
# Node entrypoint. Each node runs two WireGuard interfaces, keyed by two
# independent daemons (the layering of arXiv:2604.05599):
#
#   wg0  hop tunnel to each neighbour. arnika writes its PSK:
#        HKDF-SHA3-256(QKD key || PQC-HPKE key). arnika agrees the PQC-HPKE
#        half with its peer itself, over its own UDP channel, not over wg0.
#   wg1  end-to-end data tunnel, carried INSIDE wg0: each wg1 peer's endpoint
#        is that peer's wg0 address. Rosenpass writes the wg1 PSK through its
#        own WireGuard output, and the Rosenpass exchange also runs inside wg0:
#        Rosenpass binds this node's wg0 address, the end of each pair with the
#        lower wg0 address initiates to the peer's wg0 address, and the other
#        end answers.
#
# Steps:
#   0. Validate the configuration before touching any interface
#   1. Generate the wg0, wg1 and Rosenpass keypairs if absent
#   2. Exchange all three public keys with the peers via a shared volume
#   3. Bring up wg0 and wg1; every peer starts with a random placeholder PSK
#   4. Start the Rosenpass sidecar; wait until it has bound the wg0 address
#   5. Wait for the next wall-clock multiple of the arnika interval, then start
#      arnika, one instance per wg0 neighbour (foreground: the last one)
#
# alice, bob and charlie all use this script; behaviour differentiates via env.
# ============================================================
set -euo pipefail

# ---- 0) Configuration ---------------------------------------
NODE_NAME="${NODE_NAME:-alice}"
WG_IFACE="${WG_IFACE:-wg0}"
WG_LISTEN_PORT="${WG_LISTEN_PORT:-51820}"
WG_LOCAL_IP="${WG_LOCAL_IP:-10.0.0.1}"
WG_PEER_IP="${WG_PEER_IP:-10.0.0.2}"
WG_PEER_ENDPOINT="${WG_PEER_ENDPOINT:-bob:51821}"

# Peer identity = the hostname part of its WG endpoint (== its container/node name).
PEER_HOST="${WG_PEER_ENDPOINT%%:*}"
PEER_NAME="${PEER_NAME:-$PEER_HOST}"

# wg1, the end-to-end data tunnel. No defaults: a node that silently took
# alice's address or port would collide with alice instead of failing here.
# There is no separate endpoint variable on purpose. The endpoint is always
# WG_PEER_IP:WG1_PEER_PORT, the peer's wg0 address, which is what keeps wg1
# inside wg0.
WG1_IFACE="${WG1_IFACE:?WG1_IFACE must be set (the end-to-end data tunnel interface)}"
WG1_LISTEN_PORT="${WG1_LISTEN_PORT:?WG1_LISTEN_PORT must be set}"
WG1_LOCAL_IP="${WG1_LOCAL_IP:?WG1_LOCAL_IP must be set}"
WG1_PEER_IP="${WG1_PEER_IP:?WG1_PEER_IP must be set to the peer wg1 address}"
WG1_PEER_PORT="${WG1_PEER_PORT:?WG1_PEER_PORT must be set to the peer wg1 listen port}"

# Rosenpass (post-quantum) parameters. It binds WG_LOCAL_IP, not 0.0.0.0.
RP_LISTEN_PORT="${RP_LISTEN_PORT:-9997}"
RP_PEER_PORT="${RP_PEER_PORT:-9997}"
ROSENPASS_SECRET_DIR="${ROSENPASS_SECRET_DIR:-/etc/rosenpass-secret}"

# Shared volume used to swap public keys between the containers.
SHARED_DIR="${SHARED_DIR:-/shared}"

# One /24 per interface holds every node of the chain (10.0.0.0/24 on wg0,
# 10.0.1.0/24 on wg1). Which peer a packet goes to is decided by each peer's
# allowed-ips /32, not by the prefix.
TUNNEL_PREFIX_LEN=24

# The keepalive wg0 has always used. wg1 uses the same value so that it
# handshakes as soon as Rosenpass has keyed it, rather than on the first
# data packet.
WG_PERSISTENT_KEEPALIVE_S=25

# Bytes WireGuard adds around each inner packet when the outer transport is
# IPv4, which wg1's is (its endpoints are wg0 addresses): 20 IPv4 + 8 UDP +
# 16 data-message header (type, receiver index, counter) + 16 Poly1305 tag.
# wg1's MTU is wg0's minus this, so a full-size wg1 packet fits one wg0 packet
# instead of being IP-fragmented on its way into wg0. WireGuard pads the inner
# packet to a multiple of 16 bytes but never past the interface MTU.
WG_IPV4_ENCAP_OVERHEAD=60

# How long to wait for a neighbour's public keys. The nodes start together and
# each generates its keypairs on a first start; two minutes covers a cold start
# on a loaded host without letting a node whose neighbour never appears hang
# indefinitely. It is the value this wait has always used.
PEER_KEY_WAIT_S=120

# How long Rosenpass may take to bind its UDP socket on the wg0 address. It
# only has to load its keypair first; this bound turns a Rosenpass that cannot
# start into a container that fails at startup, as the previous sidecar check
# did, instead of a node whose wg1 silently never gets a key.
ROSENPASS_BIND_WAIT_S=30

# arnika at the pin rejects a shorter ARNIKA_PSK (config/config.go,
# minArnikaPSKLen). Checked here as well so that a bad value fails before any
# interface or key is touched, with a message that names the fix.
MIN_ARNIKA_PSK_BYTES=32
# The value .env.example and deploy/.env.example ship. It is 37 bytes, so
# arnika's own length check accepts it, and a node started with it would
# authenticate the arnika channel with a publicly known secret.
ARNIKA_PSK_PLACEHOLDER='replace-me-run-openssl-rand-base64-32'

# ARNIKA_ID and ARNIKA_PSK are both load-bearing and have no safe default here.
#
# arnika elects the per-interval master with
#     IsPrimary = ((HMAC-SHA256(ARNIKA_PSK, intervalNum)[0]) XOR ARNIKA_ID) & 1 == 0
# (config/config.go). The XOR against ARNIKA_ID is the ONLY thing that makes two
# peers reach opposite conclusions, and only bit 0 of it is used, so the two IDs
# must differ in PARITY -- one odd, one even; merely different is not enough
# (1 and 3 elect the same role every interval). The parity also picks the
# direction label of the packet HMAC (auth/auth.go, DirectionFor), so two peers
# of the same parity now fail authentication as well. Left unset, arnika
# defaults ARNIKA_ID to the port parsed from LISTEN_ADDRESS -- and both of our
# nodes listen on :9999. Fail loudly rather than ship that.
ARNIKA_ID="${ARNIKA_ID:?ARNIKA_ID must be set, and must differ in parity between the two peers}"

# The checks on the two values this node hands to arnika and must agree with
# its peer on. One function, so that tests/test_entrypoints_validate_their_input.py
# runs exactly these lines under bash with a stubbed environment.
#
# ARNIKA_PSK keys the AES-256-GCM encryption and HMAC-SHA256 signature applied
# to every arnika packet -- the key_ID exchange and the PQC-HPKE key-agreement
# frames alike (auth/auth.go) -- as well as the role election above.
#
# PQC_ENABLED switches arnika's PQC-HPKE key agreement, the PQC half of the wg0
# PSK. arnika treats every value except the exact string "true" as off
# (config/config.go), so "True" or "1" would silently mean off. Accept only the
# two exact spellings. It must be identical on both peers, like MODE.
validate_arnika_input() {
  : "${ARNIKA_PSK:?ARNIKA_PSK must be set, and must be identical on both peers}"
  # Counted in bytes, which is what arnika counts, whatever the locale.
  local psk_bytes
  psk_bytes="$(LC_ALL=C; echo "${#ARNIKA_PSK}")"
  if (( psk_bytes < MIN_ARNIKA_PSK_BYTES )); then
    echo "[entrypoint] ERROR: ARNIKA_PSK is $psk_bytes bytes, minimum $MIN_ARNIKA_PSK_BYTES." \
         "Generate one with: openssl rand -base64 32" >&2
    exit 1
  fi
  if [[ "$ARNIKA_PSK" == "$ARNIKA_PSK_PLACEHOLDER" ]]; then
    echo "[entrypoint] ERROR: ARNIKA_PSK is still the placeholder from the example env file." \
         "Generate one with: openssl rand -base64 32" >&2
    exit 1
  fi
  : "${PQC_ENABLED:?PQC_ENABLED must be set to true or false, identically on both peers}"
  case "$PQC_ENABLED" in
    true|false) ;;
    *)
      echo "[entrypoint] ERROR: PQC_ENABLED must be exactly 'true' or 'false', got '$PQC_ENABLED'" >&2
      exit 1
      ;;
  esac
}
validate_arnika_input

KMS_URL="${KMS_URL:?KMS_URL must be set}"
SERVER_ADDRESS="${SERVER_ADDRESS:?SERVER_ADDRESS must be set to the peer arnika host:port}"
MODE="${ARNIKA_MODE:-QkdAndPqcRequired}"

# ---- Start alignment (WireGuard lane only) ------------------
# Every arnika instance starts at a wall-clock multiple of its interval, so
# that the two ends of a pair start counting their intervals in step. Only this
# lane does it. The IPsec entrypoint deliberately does not, because its lane is
# the one the before/after PPK measurement compares and has to keep the start
# behaviour it had at v0.1.0 ("No start alignment in this lane" in
# nodes/strongswan/entrypoint.sh).
#
# Why: the pinned arnika counts intervals per process, from its own start: a
# ticker made when it starts and a counter from 0 that picks the role of each
# interval (submodules/arnika/main.go:327-333). A PRIMARY fetches a key from
# the KMS at its own boundary, waits for the next whole second (main.go:349)
# and builds its PSK before it sends the key_id. A BACKUP now fails closed --
# a random PSK -- at the end of any interval of its own in which no key_id
# arrived (main.go:409-418).
#
# Per tick, let d be the BACKUP's boundary minus the PRIMARY's boundary for
# that tick, and t_KMS the PRIMARY's KMS fetch time. For d below about a
# second, the chance that the PRIMARY's key_id arrives before the BACKUP's
# boundary ("early") is roughly min(1, max(0, d - t_KMS) / 1 s). That is an
# inference from the code, not a measurement, and the send also waits for the
# PSK build. An early key_id is counted in the BACKUP's previous interval. The
# BACKUP fails closed at the end of the current interval only if the next
# interval's key_id is not early too, which in practice means at its
# BACKUP-to-PRIMARY transitions.
#
# Seen locally on 2026-09-26 without this wait, in three WireGuard runs of
# about 4.5 to 7 minutes: the arnika instances that started about 0.9 to 1.9 s
# after their peer ended 13 of their 21 BACKUP intervals in total with
# `no key_id from the peer`, each followed by a window of about 0.4-0.9 s in
# which the two ends held different wg0 PSKs. Dated local observations, not
# measurements.
#
# The previous entrypoint started arnika only after the first Rosenpass key
# appeared, which happened on both nodes within milliseconds and so started
# both processes together as a side effect. arnika now starts as soon as
# Rosenpass has bound its socket, so this wait restores that synchronisation;
# without it the start offset would be whatever the containers' start offset
# is.
#
# It holds the offset only at the start. Each node resets its ticker at the
# top of its loop, after its own processing of the previous interval
# (main.go:327-333), so each node's boundary moves later by milliseconds per
# interval, d wanders, and so does the fraction of a second at which the
# PRIMARY's fetch ends. Right after an aligned start that fetch ends just
# after a whole second, so its key_id waits almost a second and is not early.
# The estimate above assumes that fraction is spread evenly, which drift
# brings about only over many intervals, so an aligned pair can be exposed
# later, and early key_ids would then come in runs rather than spread evenly.
# In one unaligned local IPsec run of about 6 minutes on 2026-09-26, the
# offset went from about 255 ms to about 217 ms over 12 intervals; bob
# received early key_ids in intervals 2-8, 10 and 11 and invalidated only at
# 8 and 11. What this means for an aligned pair is inferred from the code and
# these local runs, not measured.
#
# Residual, not fixed here (upstream #51 behaviour, to be raised there): a
# node restarted on its own, and two nodes that reach this point on either side
# of a boundary, start one or more whole intervals apart. Their counters then
# differ, and since the role election hashes the counter (config/config.go,
# IsPrimary), the two ends elect the same role in about half of the intervals;
# in the both-BACKUP ones both ends fail closed. That is inferred from the
# code, not measured. Nodes that reach this point g seconds apart straddle a
# boundary with a probability of about g / INTERVAL, also an inference.
#
# To detect it: both ends log the interval number, interval=N, on every
# `waiting for a key_id from the peer` and `serving this interval` line.
# Compare the numbers the two ends log for the same wall-clock tick; if they
# differ, recreate both nodes. As a rule, both nodes of a pair are always
# recreated together. This wait only restores the start synchronisation the
# old start order gave; it is not a fix for any key rotation race
# (docs/vici-ppk.md).
#
# Unit conversions for the interval parser and the wait below.
SECONDS_PER_MINUTE=60
SECONDS_PER_HOUR=3600
MICROSECONDS_PER_SECOND=1000000
ARNIKA_INTERVAL="${ARNIKA_INTERVAL:-30s}"

# A Go duration made of whole hours, minutes and seconds (30s, 2m, 1m30s, 1h),
# as whole seconds on stdout. Anything else fails, including forms arnika itself
# accepts (500ms, 1.5s): a boundary in whole seconds cannot honour them.
go_duration_seconds() {  # <Go duration>
  local re='^(([0-9]+)h)?(([0-9]+)m)?(([0-9]+)s)?$' total
  if [[ -z "$1" || ! "$1" =~ $re ]]; then
    echo "[entrypoint] ERROR: ARNIKA_INTERVAL is '$1'; expected whole hours," \
         "minutes and seconds such as 30s, 2m or 1m30s" >&2
    return 1
  fi
  total=$(( 10#${BASH_REMATCH[2]:-0} * SECONDS_PER_HOUR
          + 10#${BASH_REMATCH[4]:-0} * SECONDS_PER_MINUTE
          + 10#${BASH_REMATCH[6]:-0} ))
  if (( total <= 0 )); then
    echo "[entrypoint] ERROR: ARNIKA_INTERVAL is '$1', which is not a positive interval" >&2
    return 1
  fi
  echo "$total"
}

# Sleeps until the next wall-clock multiple of <seconds>.
align_arnika_start() {  # <interval in whole seconds>
  local interval_us now_us wait_us wait_s
  interval_us=$(( $1 * MICROSECONDS_PER_SECOND ))
  # EPOCHREALTIME is the wall clock with the locale's radix character between
  # the seconds and the microseconds; without it, it is microseconds.
  now_us="${EPOCHREALTIME/[^0-9]/}"
  wait_us=$(( interval_us - now_us % interval_us ))
  printf -v wait_s '%d.%06d' $(( wait_us / MICROSECONDS_PER_SECOND )) $(( wait_us % MICROSECONDS_PER_SECOND ))
  echo "[entrypoint] starting arnika at the next ${1}s wall-clock boundary, in ${wait_s}s"
  sleep "$wait_s"
}

# Parsed now, so that a bad value fails before any interface is touched.
ARNIKA_INTERVAL_S="$(go_duration_seconds "$ARNIKA_INTERVAL")"

WG_DIR=/etc/wireguard
mkdir -p "$WG_DIR" "$ROSENPASS_SECRET_DIR" "$SHARED_DIR"

# ---- 1) Keypairs --------------------------------------------
# wg0 keeps the file names it has always had in the wg-keys volume, so an
# existing node keeps its wg0 identity; wg1 has its own pair beside it.
WG0_PRIVATE="$WG_DIR/private.key"
WG0_PUBLIC="$WG_DIR/public.key"
WG1_PRIVATE="$WG_DIR/wg1.private.key"
WG1_PUBLIC="$WG_DIR/wg1.public.key"

# Private keys are created under umask 077, in a subshell so the mask does not
# leak into anything else this script creates.
ensure_wg_keypair() {  # <private key file> <public key file>
  if [[ ! -s "$1" ]]; then
    echo "[entrypoint] generating WireGuard keypair $1"
    ( umask 077; wg genkey > "$1" )
  fi
  wg pubkey < "$1" > "$2"
}
ensure_wg_keypair "$WG0_PRIVATE" "$WG0_PUBLIC"
ensure_wg_keypair "$WG1_PRIVATE" "$WG1_PUBLIC"
echo "[entrypoint] $NODE_NAME $WG_IFACE public key: $(cat "$WG0_PUBLIC")"
echo "[entrypoint] $NODE_NAME $WG1_IFACE public key: $(cat "$WG1_PUBLIC")"

RP_OWN_PK="$ROSENPASS_SECRET_DIR/pqc.pk"
RP_OWN_SK="$ROSENPASS_SECRET_DIR/pqc.sk"
if [[ ! -s "$RP_OWN_PK" || ! -s "$RP_OWN_SK" ]]; then
  echo "[entrypoint] generating Rosenpass keypair"
  rm -f "$RP_OWN_PK" "$RP_OWN_SK"
  # rosenpass writes the secret key with std::fs::write (rosenpass/src/util.rs,
  # StoreSecret), whose mode is 0666 less the umask, so without this the static
  # secret key would be world-readable.
  ( umask 077; rosenpass gen-keys --public-key "$RP_OWN_PK" --secret-key "$RP_OWN_SK" --force )
fi
# Also for a key made by an earlier version of this script, which set the mask
# only when it generated a WireGuard key in the same start. The public key is
# made readable again, as it was: the mask above applies to it too, and its
# copy in SHARED_DIR takes its mode.
chmod 600 "$RP_OWN_SK"
chmod 644 "$RP_OWN_PK"

# ---- 2) Exchange public keys via the shared volume ---------
# <name>.wg.pub is the wg0 key, <name>.wg1.pub the wg1 key and <name>.rp.pub
# the Rosenpass key. Each is published atomically (write tmp, then rename).
publish_pubkey() {  # <source file> <file name in SHARED_DIR>
  cp "$1" "$SHARED_DIR/.$2.tmp"
  mv "$SHARED_DIR/.$2.tmp" "$SHARED_DIR/$2"
}
publish_pubkey "$WG0_PUBLIC" "$NODE_NAME.wg.pub"
publish_pubkey "$WG1_PUBLIC" "$NODE_NAME.wg1.pub"
publish_pubkey "$RP_OWN_PK"  "$NODE_NAME.rp.pub"

wait_for_pubkeys() {  # <peer name> <file>...
  local name="$1" f missing
  shift
  echo "[entrypoint] waiting for $name public keys in $SHARED_DIR ..."
  for _ in $(seq 1 "$PEER_KEY_WAIT_S"); do
    missing=0
    for f in "$@"; do
      [[ -s "$f" ]] || missing=1
    done
    if (( missing == 0 )); then
      return 0
    fi
    sleep 1
  done
  echo "[entrypoint] ERROR: $name public keys not available after ${PEER_KEY_WAIT_S}s: $*" >&2
  exit 1
}

pubkey_of() {  # <file>
  tr -d '\n' < "$1"
}

wait_for_pubkeys "peer ($PEER_NAME)" \
  "$SHARED_DIR/$PEER_NAME.wg.pub" "$SHARED_DIR/$PEER_NAME.wg1.pub" "$SHARED_DIR/$PEER_NAME.rp.pub"
PEER_PUB="$(pubkey_of "$SHARED_DIR/$PEER_NAME.wg.pub")"
PEER_WG1_PUB="$(pubkey_of "$SHARED_DIR/$PEER_NAME.wg1.pub")"
echo "[entrypoint] peer $WG_IFACE public key: $PEER_PUB"
echo "[entrypoint] peer $WG1_IFACE public key: $PEER_WG1_PUB"

# ---- 3) Bring up wg0 and wg1 --------------------------------
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
# WG_QUICK_USERSPACE_IMPLEMENTATION can still name another binary, but only one
# is installed: wireguard-go. The docker-compose.boringtun.yml overlay that set
# it to `boringtun` was removed -- the image has never shipped that binary, so
# the overlay made a host without the module exit here, which is the only case
# it existed for.
create_wg_iface() {  # <iface>
  local iface="$1" userspace
  ip link del "$iface" 2>/dev/null || true
  if ! ip link add dev "$iface" type wireguard 2>/dev/null; then
    userspace="${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}"
    command -v "$userspace" >/dev/null 2>&1 || {
      echo "[entrypoint] ERROR: kernel WireGuard is unavailable and the userspace" >&2
      echo "[entrypoint]        implementation '$userspace' is not installed" >&2
      exit 1
    }
    echo "[entrypoint] kernel WireGuard unavailable; using userspace $userspace for $iface"
    "$userspace" "$iface"
  fi
}

# Every peer starts with a random PSK that only this node knows, so no
# handshake can complete on either interface until its keying daemon has
# installed the same key on both ends: arnika on wg0, Rosenpass on wg1. Both
# daemons already fail closed this way later (arnika's InvalidateTunnel and
# Rosenpass's stale-key output both install a random key); this closes the
# window before their first write. Without it, persistent-keepalive handshakes
# the moment the peer is added, with no PSK at all, and WireGuard applies a
# new PSK only at the next handshake, not to the current session. So the first
# Rosenpass exchange would travel through a wg0 session no QKD key protected,
# and wg1 would carry data before Rosenpass had keyed it.
#
# Consequence for monitoring: a `preshared key` on a peer is therefore not by
# itself evidence that arnika or Rosenpass wrote it; a completed handshake is.
add_wg_peer() {  # <iface> <peer public key> <endpoint host:port> <peer tunnel ip>
  wg genpsk | wg set "$1" peer "$2" \
      preshared-key /dev/stdin \
      endpoint "$3" \
      allowed-ips "$4/32" \
      persistent-keepalive "$WG_PERSISTENT_KEEPALIVE_S"
}

create_wg_iface "$WG_IFACE"
wg set "$WG_IFACE" listen-port "$WG_LISTEN_PORT" private-key "$WG0_PRIVATE"
ip addr add "${WG_LOCAL_IP}/${TUNNEL_PREFIX_LEN}" dev "$WG_IFACE"
ip link set up dev "$WG_IFACE"
add_wg_peer "$WG_IFACE" "$PEER_PUB" "$WG_PEER_ENDPOINT" "$WG_PEER_IP"

# wg0 address of every neighbour by name. wg1 endpoints and Rosenpass endpoints
# are derived from it, never configured separately, so neither can point
# anywhere except into wg0.
declare -A WG0_ADDR_OF=(["$PEER_NAME"]="$WG_PEER_IP")

# Additional wg0 peers, for a trusted-node chain where one node faces two
# neighbours. Space-separated `name@endpoint:port/tunnel-ip` entries; the peer's
# wg0 public key is read from $SHARED_DIR/<name>.wg.pub.
#
# Without this the node configured exactly one peer, so in the multihop profile
# alice knew bob and not charlie: charlie's wg0 showed traffic sent and none
# received, with no handshake, because the far end had never heard of it.
for entry in ${WG_EXTRA_PEERS:-}; do
  name="${entry%%@*}"
  rest="${entry#*@}"
  endpoint="${rest%%/*}"
  tunnel_ip="${rest##*/}"
  if [[ "$name" == "$entry" || -z "$endpoint" || -z "$tunnel_ip" || "$endpoint" == "$rest" ]]; then
    echo "[entrypoint] ERROR: WG_EXTRA_PEERS entry '$entry' is not name@host:port/tunnel-ip" >&2
    exit 1
  fi
  # Fatal, not skipped: a configured neighbour whose key never arrives means the
  # chain is short a hop, and bringing the tunnel up anyway hides that.
  wait_for_pubkeys "extra peer ($name)" "$SHARED_DIR/$name.wg.pub"
  extra_pub="$(pubkey_of "$SHARED_DIR/$name.wg.pub")"
  echo "[entrypoint] extra $WG_IFACE peer $name: $extra_pub via $endpoint ($tunnel_ip)"
  add_wg_peer "$WG_IFACE" "$extra_pub" "$endpoint" "$tunnel_ip"
  WG0_ADDR_OF["$name"]="$tunnel_ip"
done

wg0_mtu="$(cat "/sys/class/net/$WG_IFACE/mtu")"
wg1_mtu=$(( wg0_mtu - WG_IPV4_ENCAP_OVERHEAD ))
create_wg_iface "$WG1_IFACE"
wg set "$WG1_IFACE" listen-port "$WG1_LISTEN_PORT" private-key "$WG1_PRIVATE"
ip addr add "${WG1_LOCAL_IP}/${TUNNEL_PREFIX_LEN}" dev "$WG1_IFACE"
ip link set dev "$WG1_IFACE" mtu "$wg1_mtu" up
add_wg_peer "$WG1_IFACE" "$PEER_WG1_PUB" "${WG_PEER_IP}:${WG1_PEER_PORT}" "$WG1_PEER_IP"
echo "[entrypoint] $WG1_IFACE peer $PEER_NAME: ${WG1_PEER_IP} via ${WG_PEER_IP}:${WG1_PEER_PORT} (inside $WG_IFACE, mtu $wg1_mtu)"

# Every Rosenpass peer. The Rosenpass peer and the wg1 peer come in pairs: a
# wg1 peer nobody keys never gets a key, and a Rosenpass peer without a wg1
# peer has nowhere to write one.
#
# Exactly one end of each pair initiates: the end whose wg0 address is lower.
# Its entry is name@wg0-address:port, which becomes the rosenpass `endpoint`.
# The other end's entry is the bare name: rosenpass then only answers, to the
# address the initiator's packets come from, which is the initiator's wg0
# address and Rosenpass port. It never initiates at all, rekeys included: the
# initiation it requests at startup has no endpoint to go to, and rosenpass
# v0.2.3 requests none again until it has initiated once (the
# initiation_requested flag, rosenpass/src/protocol.rs). So the lower address
# drives every exchange of the pair, one every 130 s
# (REKEY_AFTER_TIME_INITIATOR), which is the cadence measured.
#
# Why not both ends: at a cold start both ends' first handshake messages wait
# in wg0 until arnika's first rotation keys it, and are then released
# together. Observed with both ends initiating: each end logged "Exchanged key
# with peer" twice in the same second, after which the two ends held
# different wg1 PSKs, and wg1 could not handshake until the next exchange
# 120 s later (REKEY_AFTER_TIME_RESPONDER). Inference, not traced in the
# rosenpass source: v0.2.3 completes both simultaneous handshakes and each end
# keeps the one it finished last. With one initiator, wg1 handshook within
# seconds of wg0.
#
# The cost: while the initiating end's Rosenpass is down, the other end's key
# expires after 180 s (REJECT_AFTER_TIME) and rosenpass installs a random one,
# so wg1 fails closed; after the answering end restarts, wg1 waits for the
# initiator's next exchange once wg0 is back, at most 130 s after it.
ipv4_as_int() {  # <dotted quad>
  local IFS=. a b c d
  read -r a b c d <<< "$1"
  echo $(( (a << 24) | (b << 16) | (c << 8) | d ))
}
rp_peer_entry() {  # <peer name> <peer wg0 address>
  local own peer
  own="$(ipv4_as_int "$WG_LOCAL_IP")"
  peer="$(ipv4_as_int "$2")"
  if (( own == peer )); then
    echo "[entrypoint] ERROR: $1 has this node's own wg0 address $2" >&2
    exit 1
  elif (( own < peer )); then
    echo "$1@$2:$RP_PEER_PORT"
  else
    echo "$1"
  fi
}
RP_PEERS="$(rp_peer_entry "$PEER_NAME" "$WG_PEER_IP")"

# Additional wg1 peers for the trusted-node chain. Space-separated
# `name@wg1-port/wg1-ip` entries. `name` must also be in WG_EXTRA_PEERS: the
# wg1 endpoint is that neighbour's wg0 address and the wg1 port given here.
# Each entry also becomes a Rosenpass peer, which keys it.
for entry in ${WG1_EXTRA_PEERS:-}; do
  name="${entry%%@*}"
  rest="${entry#*@}"
  port="${rest%%/*}"
  tunnel_ip="${rest##*/}"
  if [[ "$name" == "$entry" || -z "$port" || -z "$tunnel_ip" || "$port" == "$rest" ]]; then
    echo "[entrypoint] ERROR: WG1_EXTRA_PEERS entry '$entry' is not name@wg1-port/wg1-ip" >&2
    exit 1
  fi
  wg0_addr="${WG0_ADDR_OF[$name]:-}"
  if [[ -z "$wg0_addr" ]]; then
    echo "[entrypoint] ERROR: WG1_EXTRA_PEERS names '$name', which has no wg0 peer;" \
         "add it to WG_EXTRA_PEERS so its wg1 tunnel has a wg0 tunnel to run in" >&2
    exit 1
  fi
  wait_for_pubkeys "extra peer ($name)" "$SHARED_DIR/$name.wg1.pub" "$SHARED_DIR/$name.rp.pub"
  extra_wg1_pub="$(pubkey_of "$SHARED_DIR/$name.wg1.pub")"
  echo "[entrypoint] extra $WG1_IFACE peer $name: $tunnel_ip via $wg0_addr:$port (inside $WG_IFACE)"
  add_wg_peer "$WG1_IFACE" "$extra_wg1_pub" "$wg0_addr:$port" "$tunnel_ip"
  RP_PEERS+=" $(rp_peer_entry "$name" "$wg0_addr")"
done

# ---- 4) Rosenpass sidecar (REAL PQ exchange, keys wg1) ------
# It does not need ARNIKA_PSK, so it does not get it.
export ROSENPASS_SECRET_DIR SHARED_DIR WG1_IFACE RP_LISTEN_PORT RP_PEERS
export RP_LISTEN_HOST="$WG_LOCAL_IP"
env -u ARNIKA_PSK /usr/local/bin/rosenpass-sidecar.sh &
ROSENPASS_PID=$!

# Rosenpass cannot produce a key before arnika has keyed wg0 on both ends,
# because its exchange runs inside wg0, so waiting for a first key here would
# deadlock. What can be checked now is that it started: its UDP socket is
# bound on the wg0 address.
echo "[entrypoint] waiting for Rosenpass to bind $RP_LISTEN_HOST:$RP_LISTEN_PORT ..."
rosenpass_bound=0
for _ in $(seq 1 "$ROSENPASS_BIND_WAIT_S"); do
  # surface an early sidecar crash instead of waiting the full timeout
  kill -0 "$ROSENPASS_PID" 2>/dev/null || { echo "[entrypoint] ERROR: rosenpass sidecar exited" >&2; exit 1; }
  if [[ -n "$(ss -Hlun src "$RP_LISTEN_HOST:$RP_LISTEN_PORT")" ]]; then
    rosenpass_bound=1
    break
  fi
  sleep 1
done
if (( rosenpass_bound == 0 )); then
  echo "[entrypoint] ERROR: Rosenpass did not bind $RP_LISTEN_HOST:$RP_LISTEN_PORT within ${ROSENPASS_BIND_WAIT_S}s" >&2
  exit 1
fi

# ---- 5) arnika (foreground) --------------------------------
# These env vars map directly to arnika's config (see submodules/arnika/config/config.go)
export LISTEN_ADDRESS="${LISTEN_ADDRESS:-0.0.0.0:9999}"
export SERVER_ADDRESS
export INTERVAL="$ARNIKA_INTERVAL"
export MODE
export PQC_ENABLED
export KMS_URL
export ARNIKA_ID
export ARNIKA_PSK
export WIREGUARD_INTERFACE="$WG_IFACE"
export WIREGUARD_PEER_PUBLIC_KEY="$PEER_PUB"
export KMS_HTTP_TIMEOUT="${KMS_HTTP_TIMEOUT:-10s}"
export KMS_BACKOFF_MAX_RETRIES="${KMS_BACKOFF_MAX_RETRIES:-5}"
export KMS_BACKOFF_BASE_DELAY="${KMS_BACKOFF_BASE_DELAY:-200ms}"
export KMS_RETRY_INTERVAL="${KMS_RETRY_INTERVAL:-10s}"
# Fixed, not configurable. arnika logs each rotation, key_id exchange and PQC
# round at INFO, and the WebUI backend and the checklist count those lines, so
# `warn` or `error` would zero every rotation count while the tunnel kept
# rotating. `debug` adds one line per rejected datagram (logging.go).
export LOG_LEVEL=info

# Every instance this node runs starts at the same boundary; see "Start
# alignment" above. Nothing between here and the last start below waits.
align_arnika_start "$ARNIKA_INTERVAL_S"

# A second arnika per extra neighbour.
#
# arnika manages exactly ONE WIREGUARD_PEER_PUBLIC_KEY, so a node facing two
# neighbours needs one instance per leg. Without this, alice installed a
# QKD-derived PSK on the bob peer only, and no log line admitted it. Before
# every peer started with a random placeholder PSK (step 3), that left the
# charlie leg up and unprotected. With the placeholder the charlie leg fails
# closed instead: its wg0 peer never completes a handshake, so the symptom to
# look for is a latest handshake that stays at 0 for that peer, not a missing
# preshared key -- every peer has one from the moment it is added.
#
# Entries are `name@peer-host:port` in ARNIKA_EXTRA_PEERS. Each instance gets:
#   * its own UDP port, so the two do not contend for :9999
#   * its own KMS SAE path, since ETSI 014 names the PEER
#   * the neighbour's wg0 public key, read from $SHARED_DIR
#   * its own PQC-HPKE agreement with that neighbour, which arnika runs over
#     the same UDP channel as the key_ID exchange
# MODE, PQC_ENABLED and LOG_LEVEL are inherited, so the neighbour must run the
# same MODE and PQC_ENABLED.
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
      ARNIKA_ID="$ARNIKA_ID" \
      /usr/local/bin/arnika &
done

echo "[entrypoint] starting arnika (MODE=$MODE PQC_ENABLED=$PQC_ENABLED INTERVAL=$INTERVAL ID=$ARNIKA_ID KMS=$KMS_URL)"
exec /usr/local/bin/arnika
