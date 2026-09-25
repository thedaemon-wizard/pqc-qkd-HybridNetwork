# Build details

Host prerequisites, per-service builds, deployment entry points, the dev
environment and the configuration variables. The README keeps a pointer here.

See also [`../deploy/README.md`](../deploy/README.md) for deploying to a host,
and [`deployment-economics.md`](deployment-economics.md) for what each option
costs and which pages survive it.

### 5.1 Host prerequisites (AlmaLinux 9.7)

`docker-ce` and `docker-compose-plugin` come from Docker's own repository, not
from EPEL, so it is added first:

```bash
sudo dnf install -y epel-release dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
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

This is the development host. The deployment scripts in `deploy/` assume a
different one; see 5.5.

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
need to do nothing.** The node image installs `wireguard-go`, and
`nodes/alice/entrypoint.sh` uses it when the kernel interface cannot be
created:

```sh
if ! ip link add dev "$WG_IFACE" type wireguard 2>/dev/null; then
    userspace="${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}"
    "$userspace" "$WG_IFACE"
fi
```

Nothing in this repository invokes `wg-quick`; the fallback is the entrypoint's
own. Confirm the binary is present with:

```bash
docker run --rm --entrypoint wireguard-go pqcqkd/node-alice:local --version
```

No override is needed. `WG_QUICK_USERSPACE_IMPLEMENTATION` can only select a
userspace implementation the image actually contains, and the image ships
`wireguard-go` alone; naming anything else makes the entrypoint exit on a host
without the kernel module, which is exactly the host the fallback is for.

### 5.4 Multi-hop (Alice—Charlie—Bob)

```bash
make up-multihop
```

This launches the `charlie` relay (compose profile `multihop`).

### 5.5 Cloud deployment (single host + TLS)

The scripts in [`deploy/`](../deploy/) target **Ubuntu 22.04 or 24.04** on a
KVM VPS, and both should be treated as Ubuntu-only: they install packages with
`apt-get` and manage the firewall with `ufw`. On a host without `apt-get` they
fail differently. `deploy.sh` runs under `set -euo pipefail`, and its bare
`apt-get update -y` stops the script at the WireGuard step. `deploy-demo.sh`
writes its `apt-get` line as `... || true`, so it carries on and builds. Both
skip the firewall step with a one-line log when `ufw` is absent, so a host that
gets past them can be left with no firewall rules from the script.
To run the full real-WireGuard stack on a supported host behind automatic
HTTPS:

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
Monte-Carlo for BB84 (throughput depends on the visitor's device). Optional
WASM, WebGL2 and **WebGPU** tiers are each benchmarked against the Worker and
adopted only when at least 15 % faster (`UPGRADE_MARGIN` in
`services/webui-frontend/src/lib/sim/bb84Sim.ts`); otherwise the Worker keeps
running. No `/ws/*` sockets are opened for these pages, so each visitor runs an
independent sim on their own device and a public multi-user demo puts ~no load
on the server.

```bash
# Sim-only public-demo profile (DEMO_MODE=1, no privileged WG nodes / docker.sock):
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml \
  up -d --build bb84-kme-a bb84-kme-b pqc-validator webui-backend webui-frontend
```

What the backend then allows is set by the switches in section 7.1, not by
`DEMO_MODE` alone: the per-IP rate limit on mutating requests (`POST`, `PUT`,
`PATCH`, `DELETE`) is always on, container control is off (`DEMO_MODE` vetoes
it even where `ENABLE_CONTAINER_CONTROL` is set), and live parameter overrides
are off unless `ENABLE_LIVE_PARAM_OVERRIDES` is set, which the demo overlay
does not do. Which pages need the backend at all, and which degrade to
bundled defaults without it, is tabulated once, in
[`deployment-economics.md`](deployment-economics.md).

---

## 6. Dev Environment

Tested on:
- **OS**: AlmaLinux 9.7
- **CPU**: Intel i5-13600K (14C/20T)
- **RAM**: 128 GB DDR5 5200
- **GPU**: NVIDIA RTX 6000 PRO Blackwell 96GB (CUDA 13.0)
  — *GPU is optional*; the BB84 simulator is CPU-bound by design for portability.
  Future Shor-attack-simulator (roadmap A) will leverage CUDA-Q + cuQuantum.
- **Python**: 3.12 in a `.venv` for host-side scripts (tests, benchmarks, manim)
- **Docker**: 24+ with Compose v2
- **WireGuard**: in-tree kernel module (AlmaLinux 9.7 mainline); only
  `wireguard-tools` userspace is installed. Without the module, see 5.3.

Host-side Python venv. The first install line is what CI's `python` job
installs, so `make test` (which runs `pytest tests/` with the venv's
interpreter) has the same imports as CI; the second is optional and only for
the animations and plots:

```bash
python3.12 -m venv .venv
.venv/bin/pip install ruff pytest pytest-asyncio httpx \
    -r services/bb84-kme/requirements.txt \
    -r services/webui-backend/requirements.txt
.venv/bin/pip install manim matplotlib     # optional: animations/, benchmarks/plot_results.py
```

Run helper scripts with the venv's interpreter, either through their `make`
targets or directly as `.venv/bin/python tools/<script>.py`. Their
`#!/usr/bin/env python3` shebang resolves to whatever `python3` is first on the
`PATH`, which on AlmaLinux 9 is the system Python 3.9, not the venv's 3.12.

---

## 7. Configuration

Deployment variables live in `.env` (copy from `.env.example`;
`scripts/check_env_example.sh` checks it covers every mandatory variable).
Compose reads `.env` only to fill in the `${VAR}` references of the compose
files, so a variable reaches a container only where a compose file forwards
it. Every variable in this table is referenced by a compose file.

| Variable | Default | Purpose | Source of truth |
|---|---|---|---|
| `ARNIKA_MODE` | `QkdAndPqcRequired` | One of 4 modes: `QkdAndPqcRequired` / `AtLeastQkdRequired` / `AtLeastPqcRequired` / `EitherQkdOrPqcRequired` | `submodules/arnika/config/config.go` |
| `ARNIKA_INTERVAL` | `30s` | PSK rotation period. arnika's own default is `10s`, and upstream recommends aligning with WireGuard's 120 s rekey; on the WireGuard lane that rekey bounds the key epoch whatever this is set to ([`threat-model.md` §2.1](threat-model.md)) | `submodules/arnika/config/config.go` |
| `ARNIKA_ID_*` | `1` / `2` (`4` for charlie) | Per-node ID in the primary election; peers must differ in **parity** | `.env.example` |
| `ARNIKA_PSK` | none | Keys the arnika peer channel and the election; must be identical on both peers | `.env.example` |
| `KMS_HTTP_TIMEOUT` | `10s` | ETSI 014 HTTP timeout | arnika config |
| `WEBUI_BACKEND_PORT` | `8000` | Backend port (host) | docker-compose |
| `WEBUI_FRONTEND_PORT` | `5173` | Frontend nginx port (host) | docker-compose |
| `ENABLE_LIVE_PARAM_OVERRIDES` | `false` | Lets `POST /api/sim/params`, `POST /api/sim/params/reset` and `POST /api/sim/backend` change the running simulator. Off, they return 403 and `/physics` applies edits to the in-browser model only; `GET /api/config` reports it as `live_param_overrides` | `services/webui-backend/app/main.py`, forwarded by `docker-compose.yml` |

**Numeric BB84 tunables are not environment variables.** They come from
`config/qkd_params.yaml`, which `services/bb84-kme/app/config_loader.py`
declares the single source of truth, and which
`tests/test_no_hardcoded_params.py` and
`tests/test_frontend_defaults_match_config.py` enforce. An earlier version of
this table listed seven `BB84_*` variables and an `ETSI_MTLS_ENABLED`, each
naming a Python file as its source of truth; no Python file read any of them.

### 7.1 Backend variables that `.env` does not reach

`services/webui-backend/app/main.py` reads the variables below from its own
environment, but `docker-compose.yml` sets only `KME_A_URL`, `KME_B_URL`,
`PQC_VALIDATOR_URL`, `LOG_LEVEL`, `ARNIKA_INTERVAL` and
`ENABLE_LIVE_PARAM_OVERRIDES` on `webui-backend`. Of these, only
`ARNIKA_INTERVAL` and `ENABLE_LIVE_PARAM_OVERRIDES` come from `.env`; the rest
are fixed service URLs and `LOG_LEVEL=INFO`. **Setting any of the variables
below in `.env` has no effect.** Set them in the `environment:` block of
`webui-backend` in a compose override, as the two overlays in `deploy/` do
(with fixed values, not `${VAR}` references).

| Variable | Default in code | Purpose | Set by |
|---|---|---|---|
| `ENABLE_CONTAINER_CONTROL` | off | Enables `/api/stack/*` container start/stop/restart through the mounted Docker socket. Opt-in, and vetoed by `DEMO_MODE` | no compose file; opting in takes an override |
| `DEMO_MODE` | off | Removes capability for a shared public host: vetoes container control. The demo overlay also runs no privileged WireGuard nodes and mounts no Docker socket. It does not switch the rate limit on or off | `deploy/docker-compose.demo.yml` (`"1"`) |
| `DEMO_RATE_MAX` / `DEMO_RATE_WINDOW_S` | `120` / `60` s | Per-IP token bucket on every `POST`, `PUT`, `PATCH` and `DELETE`; over budget, 429. Always on, whatever `DEMO_MODE` says; the names are kept for compatibility | `deploy/docker-compose.demo.yml`, at the code defaults |
| `EXPORT_MAX_BYTES` | 25 MiB | Largest single file `POST /api/exports/save` accepts (413 above it, or above `EXPORT_MAX_TOTAL_BYTES` if that is smaller) | both `deploy/` overlays, at the code default |
| `EXPORT_MAX_FILES` | `100` | Files kept in the server-side export store; the oldest are deleted first | both `deploy/` overlays, at the code default |
| `EXPORT_MAX_TOTAL_BYTES` | 512 MiB | Total size of the export store; the oldest files are deleted first | no compose file |
| `STATS_TTL_S` | `1.0` s | Cache lifetime of `GET /api/stats`, which `/benchmarks` polls once a second, so any number of viewers costs one KME sample per second | no compose file |
| `PQC_AGILITY_ERROR_TTL_S` | `10.0` s | How long a failed validator call behind `POST /api/pqc/agility` is cached, so an unreachable validator does not cost every viewer a full timeout. A successful matrix is cached for `PQC_AGILITY_TTL_S`, default `300.0` s | no compose file |

The remaining cache and size knobs follow the same pattern and have their
defaults beside the line that reads them in `main.py`: `STACK_TTL_S`,
`LOGS_TTL_S`, `LOGS_MAX_TAIL`, `KEYRATE_TTL_S`, `VPN_SAMPLE_TTL_S`,
`VPN_ROTATION_TTL_S`, `VPN_ROTATION_WINDOW_MAX_S` and `EXPORT_DIR`.

The three boolean switches (`ENABLE_LIVE_PARAM_OVERRIDES`,
`ENABLE_CONTAINER_CONTROL`, `DEMO_MODE`) accept `1`, `true`, `yes` or `on`
(any case) as on; anything else, including unset, is off.
