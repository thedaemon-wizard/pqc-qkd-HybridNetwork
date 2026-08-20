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

# Arguments are parsed before the privilege check so `--help` works without
# sudo.
PULL=0
DEPLOY_BRANCH="${DEPLOY_BRANCH:-main}"
for arg in "$@"; do
  case "$arg" in
    --pull) PULL=1 ;;
    -h|--help)
      echo "usage: sudo bash deploy/deploy-demo.sh [--pull]"
      echo "  --pull   fetch and fast-forward to origin/$DEPLOY_BRANCH (default: main)"
      echo "           before building, then sync submodules"
      exit 0
      ;;
    *) echo "[deploy-demo] unknown argument: $arg" >&2; exit 1 ;;
  esac
done

if [[ "${EUID}" -ne 0 ]]; then
  echo "[deploy-demo] please run as root (sudo bash deploy/deploy-demo.sh)" >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  echo "[deploy-demo] missing ./.env — copy deploy/.env.example to .env and set PUBLIC_HOST/ACME_EMAIL" >&2
  exit 1
fi

# ---- 0) Optional: fast-forward to the published branch -------
#
# Opt-in via --pull, never implicit. This script runs as root on a live host
# where .env and any local hotfix live in the working tree; silently moving HEAD
# underneath them is the kind of thing that turns a redeploy into an outage.
#
# Fast-forward ONLY. A rebase or merge here could conflict and leave the tree
# half-updated with no one at the keyboard, and a --hard reset would discard
# exactly the local state the operator may be relying on.
if [[ "$PULL" -eq 1 ]]; then
  log "fetching origin/${DEPLOY_BRANCH}"
  git fetch --prune origin "${DEPLOY_BRANCH}"

  # Report local modifications, but do NOT refuse on their mere existence.
  #
  # An earlier version aborted on any dirty file. Tested against the real demo
  # host, that made the script unusable: the box carries a deliberate local
  # Caddyfile edit serving a second project's domain, plus a submodule pointer
  # and some stray untracked files. None of them are touched by the update. A
  # guard that blocks the correct action pushes the operator into running the
  # git commands by hand, which is strictly less safe than the script.
  #
  # `git merge --ff-only` below already refuses precisely when it matters -- it
  # will not overwrite a locally-modified file that the incoming commits change
  # -- and it is exact about which files those are, which a blanket
  # `git diff --quiet` cannot be.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    log "note: local modifications present; they are preserved unless the update touches them"
    git status --short >&2
  fi

  current="$(git rev-parse --abbrev-ref HEAD)"
  if [[ "$current" != "${DEPLOY_BRANCH}" ]]; then
    log "switching from ${current} to ${DEPLOY_BRANCH}"
    git checkout "${DEPLOY_BRANCH}"
  fi

  before="$(git rev-parse HEAD)"
  # --ff-only: fail loudly rather than create a merge commit on a deploy host,
  # and it aborts before touching anything if a locally-modified file would be
  # overwritten. That is the real safety check; see the note above.
  if ! git merge --ff-only "origin/${DEPLOY_BRANCH}"; then
    echo "[deploy-demo] fast-forward refused. Either the branch has diverged, or" >&2
    echo "[deploy-demo] the update would overwrite a locally-modified file." >&2
    echo "[deploy-demo] Nothing has been changed. Resolve, then re-run." >&2
    exit 1
  fi
  after="$(git rev-parse HEAD)"

  if [[ "$before" == "$after" ]]; then
    log "already up to date at ${after:0:8}"
  else
    log "updated ${before:0:8} -> ${after:0:8}"
    git --no-pager log --oneline "${before}..${after}" | sed 's/^/  /'
  fi
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
