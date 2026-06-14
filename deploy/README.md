# Cloud deployment (`deploy/`)

Artifacts to run the **full real-WireGuard stack** (all 7 services, including
the privileged `alice`/`bob` WireGuard nodes) on a single public host with
automatic TLS.

| File | Purpose |
|---|---|
| `docker-compose.cloud.yml` | Overlay: adds a Caddy reverse proxy (the only public service, 80/443) and restart policies. Use with the base compose. |
| `docker-compose.demo.yml` | **Public-demo profile** (sim-only): `DEMO_MODE=1`, no privileged WG nodes / `docker.sock`. The E2E / Paper / Physics / BB84 pages run **client-side** (browser JS + Web Worker/WebGPU, real `@noble` crypto), so the backend serves only `/api/config`, param defaults and `/verify`. |
| `Caddyfile` | Caddy config: auto-HTTPS for `$PUBLIC_HOST`, proxies to `webui-frontend`. |
| `deploy.sh` | Idempotent bootstrap for a fresh ConoHa/Ubuntu VPS (Docker, WireGuard module, IP forwarding, UFW, build & up). |
| `.env.example` | Copy to repo-root `.env`; set `PUBLIC_HOST`, `ACME_EMAIL`, backend profile, ports. |

## Public-demo profile (client-side simulation, low backend load)

```sh
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml \
  up -d --build bb84-kme-a bb84-kme-b pqc-validator webui-backend webui-frontend
```

The four simulation pages run entirely in the browser (no `/ws/*`), so a public
multi-user demo barely touches the backend. Leaner still: those pages need **no
backend** — serve the `webui-frontend` bundle statically (GitHub/Cloudflare/
Netlify Pages) for a near-$0 demo (only `/verify` is then disabled).

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
