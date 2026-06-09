#!/usr/bin/env bash
# ============================================================
# One-shot bootstrap for the FULL real-WireGuard stack on a fresh
# ConoHa (Ubuntu 22.04/24.04) KVM VPS.
#
# Idempotent: safe to re-run. Installs Docker + compose plugin, ensures
# the WireGuard kernel module + IP forwarding, sets a minimal UFW policy
# (22/80/443 only), then builds & starts the stack behind Caddy auto-TLS.
#
# Prereqs: run as root (or via sudo) on the VPS, with this repo already
# cloned (recursively) and a filled-in ./.env (see deploy/.env.example).
#
#   git clone --recurse-submodules <repo> pqc-qkd-hybrid
#   cd pqc-qkd-hybrid
#   cp deploy/.env.example .env && edit .env   # set PUBLIC_HOST, ACME_EMAIL
#   sudo bash deploy/deploy.sh
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\033[1;34m[deploy]\033[0m %s\n' "$*"; }

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
apt-get install -y --no-install-recommends wireguard-tools ca-certificates git || true
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

# ---- 4) Firewall (UFW): 22/80/443 only ---------------------
if command -v ufw >/dev/null 2>&1; then
  log "configuring UFW (allow 22/80/443, deny the rest)"
  ufw --force reset >/dev/null
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 443/udp     # HTTP/3
  ufw --force enable
fi

# ---- 5) Submodules ----------------------------------------
log "syncing git submodules"
git submodule update --init --recursive

# ---- 6) Build & start the full stack behind Caddy ----------
log "building and starting the stack (this first build is slow: liboqs/rosenpass/strongSwan)"
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build

log "done. Watch logs with:"
echo "    docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml logs -f caddy alice bob"
log "Once DNS (A record) points at this host, https://\$PUBLIC_HOST will serve the WebUI."
