#!/usr/bin/env bash
# ============================================================
# One-shot bootstrap for the FULL real-WireGuard stack on a fresh
# KVM VPS running Ubuntu 22.04/24.04.
#
# This is the HEAVY full stack: it builds liboqs + rosenpass (Rust) +
# strongSwan from source for the privileged alice/bob WireGuard nodes.
# >>> Requires a real kernel + at least 4 GB RAM (8 GB to build everything
#     on-box) and ~15 GB free disk. On a smaller box the build OOMs/fills
#     the disk and containers like bb84-kme then "fail to start". <<<
#
# For a PUBLIC DEMO you almost certainly want the much lighter
#   deploy/deploy-demo.sh   (sim-only; no privileged WG nodes)
# — the simulation pages run client-side, so the demo needs no WireGuard nodes.
#
# Idempotent: safe to re-run. Installs Docker + compose plugin, ensures
# the WireGuard kernel module + IP forwarding, adds UFW rules for ssh/80/443
# (keeping any others), adds swap if RAM is low, then builds & starts the stack
# behind Caddy auto-TLS.
#
# Prereqs: run as root (or via sudo) on the VPS, with this repo already
# cloned (recursively) and a filled-in ./.env (see deploy/.env.example).
#
#   git clone --recurse-submodules <repo> pqc-qkd-hybrid
#   cd pqc-qkd-hybrid
#   cp deploy/.env.example .env && edit .env   # set PUBLIC_HOST, ACME_EMAIL
#   sudo bash deploy/deploy.sh                 # first install
#   sudo bash deploy/deploy.sh --pull --ipsec  # redeploy, with the IPsec lane
#
# The firewall step ADDS rules (configure_firewall in deploy/lib.sh); it does
# not reset UFW. Set SKIP_UFW=1 to leave the firewall alone.
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }
# shellcheck source=deploy/lib.sh
DEPLOY_NAME=deploy
source "$REPO_ROOT/deploy/lib.sh"

# Options.
#   --pull   fetch and fast-forward to origin/$DEPLOY_BRANCH (default main)
#            before building -- the same routine as deploy-demo.sh
#   --ipsec  also build and start the strongSwan lane
#            (docker-compose.strongswan.yml, profile `ipsec`)
PULL=0
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
COMPOSE_FILES=(-f docker-compose.yml -f deploy/docker-compose.cloud.yml)
for arg in "$@"; do
  case "$arg" in
    --pull)  PULL=1 ;;
    --ipsec) COMPOSE_FILES+=(-f docker-compose.strongswan.yml --profile ipsec) ;;
    *) echo "[deploy] unknown option: $arg (known: --pull --ipsec)" >&2; exit 2 ;;
  esac
done

# Add a swapfile when RAM is low so the heavy first build (liboqs / rosenpass /
# strongSwan / scipy) doesn't get OOM-killed — the usual cause of a container
# "failing to start" on a small VPS.
ensure_swap() {
  local mem_mb swap_kb
  mem_mb=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}')
  swap_kb=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo 2>/dev/null)
  if [[ "${mem_mb:-9999}" -lt 4000 && "${swap_kb:-0}" -lt 2000000 && ! -e /swapfile ]]; then
    log "low RAM (${mem_mb} MB) + little swap — creating a 4G swapfile to avoid build OOM"
    fallocate -l 4G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

# The bb84-kme image installs all four heavy QKD backends (SimQN / SeQUeNCe /
# Strawberry Fields / TNO) from these submodules at BUILD time, and a failed
# install fails the build (services/bb84-kme/Dockerfile). An empty submodule
# therefore stops the build; no backend choice gets past it. So the fetch below
# must succeed: under `set -e` a failure ends the deploy here, with git's own
# error, instead of at a build that cannot work. `--force` re-runs the checkout
# even when the recorded commit is already current, which restores a submodule
# whose files were deleted after cloning.
#
# The backend itself is chosen by SIMULATOR_BACKEND in .env, read when a KME
# starts, so changing it means recreating bb84-kme-a and bb84-kme-b. The
# Physics page can switch it on the running KMEs only where
# ENABLE_LIVE_PARAM_OVERRIDES=true, which deploy/.env.example keeps false.
ensure_backend_submodules() {
  log "ensuring KME backend submodules are present"
  git submodule update --init --force --recursive \
      submodules/SimQN submodules/SeQUeNCe \
      submodules/strawberryfields submodules/tno-qkd-key-rate
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "[deploy] please run as root (sudo bash deploy/deploy.sh)" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "[deploy] missing ./.env — copy deploy/.env.example to .env and edit it" >&2
  exit 1
fi

# ---- 1) Docker engine + compose plugin ---------------------
if ! command -v docker >/dev/null 2>&1; then
  log "installing Docker engine + compose plugin"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || { echo "[deploy] docker compose plugin missing" >&2; exit 1; }
systemctl enable --now docker

# ---- 2) WireGuard kernel module ----------------------------
log "ensuring WireGuard kernel module"
apt-get update -y
apt-get install -y --no-install-recommends wireguard-tools ca-certificates git
modprobe wireguard || { echo "[deploy] WARNING: modprobe wireguard failed — kernel may lack WG; the WG E2E will not work" >&2; }
if ! grep -q '^wireguard$' /etc/modules-load.d/wireguard.conf 2>/dev/null; then
  echo wireguard > /etc/modules-load.d/wireguard.conf
fi

# ---- 3) IP forwarding --------------------------------------
log "enabling IPv4 forwarding"
cat > /etc/sysctl.d/99-pqcqkd.conf <<'EOF'
net.ipv4.ip_forward=1
net.ipv4.conf.all.src_valid_mark=1
EOF
sysctl --system >/dev/null

# ---- 4) Firewall: add ssh/80/443, keep existing rules ------
configure_firewall

# ---- 5) Submodules ----------------------------------------
if [[ "$PULL" == "1" ]]; then
  fast_forward_to_branch
fi
log "syncing git submodules"
git submodule update --init --recursive
ensure_backend_submodules   # force-fetch the KME backends the image build requires

# ---- 5b) Swap (avoid build OOM on small VPS) ---------------
ensure_swap

# ---- 6) Build & start the full stack behind Caddy ----------
log "building and starting the stack (this first build is slow: liboqs/rosenpass/strongSwan)"
docker compose "${COMPOSE_FILES[@]}" up -d --build

log "done. Watch logs with:"
echo "    docker compose ${COMPOSE_FILES[*]} logs -f caddy alice bob"
log "Once DNS (A record) points at this host, https://\$PUBLIC_HOST will serve the WebUI."
