# Build details

Extracted from the README, which had grown to 490 lines with this section
alone accounting for 93 of them. The README keeps a pointer; the detail lives
here so it can grow without making the entry point unreadable.

See also [`../deploy/README.md`](../deploy/README.md) for deploying to a host,
and [`deployment-economics.md`](deployment-economics.md) for what each option
costs and which pages survive it.

### 5.1 Host prerequisites (AlmaLinux 9.7)

```bash
sudo dnf install -y epel-release
sudo dnf config-manager --set-enabled crb
# WireGuard ships in AlmaLinux 9.7's mainline kernel — only the userspace
# tools are needed; ELRepo's kmod-wireguard is NOT required.
sudo dnf install -y wireguard-tools gcc cmake ninja-build git \
                    python3.12 python3.12-devel openssl-devel libsodium-devel \
                    docker-ce docker-compose-plugin nodejs
sudo modprobe wireguard
echo wireguard | sudo tee /etc/modules-load.d/wireguard.conf
sudo systemctl enable --now docker
sudo usermod -aG docker $USER && newgrp docker
```

### 5.2 liboqs + oqs-provider (host install, optional)

For the `services/pqc-tls-demo/` sanity check only; the main hybrid pipeline does NOT
require liboqs on the host (Rosenpass is bundled in the node image).

```bash
make build-liboqs
make build-oqs-provider
make pqc-list    # should show ML-KEM-768 etc.
```

### 5.3 WireGuard kernel module fallback

If `modprobe wireguard` fails on your host, **the stack still works and you
need to do nothing.** The node image installs `wireguard-go`, and `wg-quick`
falls back to it automatically:

```
# wg-quick, verbatim from the node image
[[ -e /sys/module/wireguard ]] || ! command -v \
  "${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}" >/dev/null && exit $ret
cmd "${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}" "$INTERFACE"
```

Confirm it is present with:

```bash
docker run --rm --entrypoint wireguard-go pqcqkd/node-alice:local --version
```

`docker-compose.boringtun.yml` is therefore redundant and kept only to document
the override mechanism. Until 2026-08 no userspace implementation was installed
at all, and that overlay pointed `wg-quick` at a `boringtun` binary the image
did not contain -- so the documented recovery path could not work for the
people who needed it.

### 5.4 Multi-hop (Alice—Charlie—Bob)

```bash
make up-multihop
```

This launches the `charlie` relay (compose profile `multihop`).

### 5.5 Cloud deployment (single host + TLS)

To run the full real-WireGuard stack on a single public host (any KVM
KVM VPS) behind automatic HTTPS, use the artifacts in [`deploy/`](../deploy/):

```bash
cp deploy/.env.example .env       # set PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy.sh        # Docker + WireGuard module + UFW + build & up
# or manually:
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
```

A Caddy reverse proxy is the only public service (80/443, auto Let's Encrypt);
the KME/backend and WireGuard nodes stay on the internal networks. The
privileged WG nodes need a real kernel (fine on a KVM VPS, not on managed PaaS).
See [`deploy/README.md`](../deploy/README.md). Per-dependency licence terms are
in [`docs/THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

### 5.6 Public-demo profile — client-side simulation (near-zero backend load)

The **Quantum-Secure E2E**, **Paper Data Exchange**, **Physics Params** and
**BB84 Live** pages run their simulation **entirely client-side** in the browser
— real HKDF-SHA3-256 + ChaCha20-Poly1305 via [`@noble`](https://github.com/paulmillr/noble-hashes),
the closed-form Lo-Ma key-rate ported to TypeScript, and a **Web Worker**
Monte-Carlo for BB84 (~70–100M pulses/s) with an optional **WebGPU** compute
path (WGSL + atomics) that auto-falls-back to the Worker. No `/ws/*` sockets are
opened for these pages, so each visitor runs an independent sim on their own
device and a public multi-user demo puts ~no load on the server.

```bash
# Sim-only public-demo profile (DEMO_MODE=1, no privileged WG nodes / docker.sock):
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml \
  up -d --build bb84-kme-a bb84-kme-b pqc-validator webui-backend webui-frontend
```

The backend then only serves `/api/config`, `/api/sim/params` defaults and the
`/verify` cross-check; only container-control (`/api/stack/*`) is disabled and
POSTs are per-IP rate-limited (backend switching + bounded export-save allowed).
Leaner still, the simulation pages need **no backend at all** and the bundle can
be served statically for a near-$0 demo. Be precise about what that costs,
though: **eight** pages call the API, not one. `/e2e`, `/paper-flow`,
`/keyflow` and `/hil` are fully self-contained; `/bb84` and `/pqc` degrade to
bundled defaults; `/`, `/benchmarks`, `/console`, `/physics`, `/topology`,
`/verify` and `/vpn` need the backend. See
[`docs/deployment-economics.md`](deployment-economics.md).

---
