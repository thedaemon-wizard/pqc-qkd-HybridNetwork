# Cloud deployment (`deploy/`)

Artifacts to run the **full real-WireGuard stack** (all 7 services, including
the privileged `alice`/`bob` WireGuard nodes) on a single public host with
automatic TLS.

| File | Purpose |
|---|---|
| `docker-compose.cloud.yml` | Overlay: adds a Caddy reverse proxy (the only public service, 80/443) and restart policies. Use with the base compose. |
| `docker-compose.demo.yml` | **Public-demo profile** (sim-only): `DEMO_MODE=1`, no privileged WG nodes / `docker.sock`. The E2E / Paper / Physics / BB84 pages run **client-side** (browser JS + Web Worker/WebGPU, real `@noble` crypto), so the backend serves only `/api/config`, param defaults and `/verify`. |
| `Caddyfile` | Caddy config: auto-HTTPS for `$PUBLIC_HOST`, proxies to `webui-frontend`. |
| `deploy.sh` | Bootstrap for the **FULL** real-WireGuard stack (Docker, WG module, IP forwarding, UFW, **swap**, build & up). Heavy: needs **≥4 GB RAM / ~15 GB disk** + a real kernel. |
| `deploy-demo.sh` | Bootstrap for the **lighter public-demo** profile (sim-only, no privileged WG nodes). Recommended for a public demo. |
| `.env.example` | Copy to repo-root `.env`; set `PUBLIC_HOST`, `ACME_EMAIL`, backend profile, ports. |

## ⚠️ Which deploy do I want? (read this first)

- **`deploy/deploy.sh` — FULL real-WireGuard stack.** Builds liboqs + **rosenpass (Rust)** +
  **strongSwan** from source for the privileged `alice`/`bob` nodes. **Requires a real kernel and
  ≥4 GB RAM (8 GB to build everything on-box) + ~15 GB free disk.** On a smaller box the first build
  is OOM-killed / fills the disk, so a container such as `bb84-kme` ends up with a broken image and
  **"fails to start"** — which then aborts everything that depends on it
  (`Error dependency bb84-kme-a failed to start`). `deploy.sh` now adds a 4 GB swapfile automatically
  to reduce this risk.
- **`deploy/deploy-demo.sh` — public DEMO (recommended).** No privileged WG nodes, no rosenpass/
  strongSwan build. The four simulation pages run **client-side**, so the backend is tiny (just
  `webui-backend` in `DEMO_MODE` + `bb84-kme` + `pqc-validator` for `/verify`). Runs on a small box.

```sh
cp deploy/.env.example .env   # set PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy-demo.sh
```

**Leanest (near-$0):** the four simulation pages need **no backend at all** — build the frontend
(`cd services/webui-frontend && npm ci && npx vite build`) and serve `dist/` statically on
GitHub / Cloudflare / Netlify Pages (only `/verify` is then unavailable).

### Troubleshooting "Error dependency bb84-kme-a failed to start"
This means `bb84-kme` never started (usually a build OOM / out-of-disk on a small VPS). Diagnose:
```sh
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml build bb84-kme-a   # see the real build error
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml logs bb84-kme-a    # see the runtime error
free -m && df -h /                                                                        # check RAM + disk
```
Fixes: use `deploy-demo.sh` (much lighter), give the box more RAM/disk, or rely on the auto-added
swap. Ensure submodules are present (`git submodule update --init --recursive`).

## Quick start (VPS)

```sh
git clone --recurse-submodules <repo> pqc-qkd-hybrid
cd pqc-qkd-hybrid
cp deploy/.env.example .env      # edit PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy.sh
```

Then add a DNS **A record** for `PUBLIC_HOST` → the VPS public IP. Caddy
obtains a Let's Encrypt certificate automatically and serves the WebUI at
`https://$PUBLIC_HOST`.

## Why a VPS (not managed PaaS)

The real WireGuard end-to-end tunnel needs the `wireguard` kernel module and
privileged containers (`NET_ADMIN`/`SYS_MODULE`, `/dev/net/tun`). A ConoHa KVM
VPS (root) provides this; managed PaaS (Railway/Render) cannot.

## Local smoke test (through Caddy, plain HTTP)

```sh
PUBLIC_HOST=":80" ACME_EMAIL="" \
  docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
# WebUI now reachable via the proxy at http://localhost/
```

> Detailed business / monetization rationale, recommended ConoHa plan & cost,
> Value-Domain DNS steps, security hardening, and the per-OSS license &
> commercial-use analysis live in the private `MONETIZATION.md` (not committed).
