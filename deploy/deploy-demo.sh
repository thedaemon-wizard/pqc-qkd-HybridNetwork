#!/usr/bin/env bash
# ============================================================
# One-shot bootstrap for the LIGHT public-demo profile on a fresh
# Ubuntu (22.04/24.04) VPS.
#
# Unlike deploy/deploy.sh (the heavy FULL real-WireGuard stack), this brings up
# only the sim-only demo: the E2E / Paper / Physics / BB84 pages run ENTIRELY
# CLIENT-SIDE, so there are NO privileged WireGuard nodes and NO rosenpass /
# strongSwan builds. The only backend services are webui-backend (DEMO_MODE=1),
# bb84-kme-a/b and pqc-validator (for the /verify cross-check) behind Caddy TLS.
#
# This needs much less than the full stack, but pqc-validator + bb84-kme still
# build liboqs / Python wheels — give the box ~2 GB RAM (swap is auto-added) and
# ~8 GB free disk.
#
# Even lighter: the four simulation pages need NO backend at all — you can serve
# services/webui-frontend's built `dist/` statically (GitHub/Cloudflare/Netlify
# Pages) for a near-$0 demo; only /verify is then unavailable.
#
#   git clone --recurse-submodules <repo> pqc-qkd-hybrid
#   cd pqc-qkd-hybrid
#   cp deploy/.env.example .env && edit .env   # set PUBLIC_HOST, ACME_EMAIL
#   sudo bash deploy/deploy-demo.sh
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

log() { printf '\033[1;35m[deploy-demo]\033[0m %s\n' "$*"; }

ensure_swap() {
  local mem_mb swap_kb
  mem_mb=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}')
  swap_kb=$(awk '/^SwapTotal:/{print $2}' /proc/meminfo 2>/dev/null)
  if [[ "${mem_mb:-9999}" -lt 3000 && "${swap_kb:-0}" -lt 2000000 && ! -e /swapfile ]]; then
    log "low RAM (${mem_mb} MB) + little swap — creating a 2G swapfile to avoid build OOM"
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

if [[ "${EUID}" -ne 0 ]]; then
  echo "[deploy-demo] please run as root (sudo bash deploy/deploy-demo.sh)" >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "[deploy-demo] missing ./.env — copy deploy/.env.example to .env and set PUBLIC_HOST/ACME_EMAIL" >&2
  exit 1
fi

# ---- 1) Docker engine + compose plugin ---------------------
if ! command -v docker >/dev/null 2>&1; then
  log "installing Docker engine + compose plugin"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || { echo "[deploy-demo] docker compose plugin missing" >&2; exit 1; }
systemctl enable --now docker

# ---- 2) Firewall (UFW): 22/80/443 only — no WG module needed ----
apt-get update -y && apt-get install -y --no-install-recommends ca-certificates git || true
if command -v ufw >/dev/null 2>&1; then
  log "configuring UFW (allow 22/80/443)"
  ufw --force reset >/dev/null
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp; ufw allow 80/tcp; ufw allow 443/tcp; ufw allow 443/udp
  ufw --force enable
fi

# ---- 3) Submodules (bb84-kme + pqc-validator builds need them) ----
log "syncing git submodules"
git submodule update --init --recursive
# The bb84-kme image installs its QKD backends from these submodules at build
# time. The default backend is `simqn`; if SimQN isn't checked out the KME
# crashes on boot. Make it deterministic: force-fetch the backends and, if
# SimQN is still absent, deploy on the always-present built-in `qutip` backend
# (no submodule needed). For a public demo this is ideal — the simulation pages
# run client-side, so the server backend choice is cosmetic.
git submodule update --init --force --recursive \
    submodules/SimQN submodules/SeQUeNCe \
    submodules/strawberryfields submodules/tno-qkd-key-rate || true
if [[ ! -e submodules/SimQN/setup.py ]]; then
  log "SimQN submodule absent — deploying on the built-in 'qutip' backend (SIMULATOR_BACKEND=qutip)."
  export SIMULATOR_BACKEND=qutip
fi

ensure_swap

# ---- 4) Build & start ONLY the demo services behind Caddy ----
# Overlay order: base + cloud (adds Caddy + restart) + demo (DEMO_MODE, drops
# docker.sock, bounds the export store). Start the sim-only services — NOT the
# privileged alice/bob WireGuard nodes.
log "building and starting the demo profile (pqc-validator builds liboqs — be patient)"
docker compose \
  -f docker-compose.yml \
  -f deploy/docker-compose.cloud.yml \
  -f deploy/docker-compose.demo.yml \
  up -d --build caddy webui-frontend webui-backend bb84-kme-a bb84-kme-b pqc-validator

log "done. The four simulation pages run client-side; backend is DEMO_MODE (container"
log "control disabled, rate-limited). Watch logs with:"
echo "    docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml -f deploy/docker-compose.demo.yml logs -f caddy webui-backend pqc-validator"
log "Once DNS (A record) points here, https://\$PUBLIC_HOST serves the demo."
