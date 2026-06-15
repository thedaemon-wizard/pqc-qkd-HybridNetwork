# PQC-QKD Hybrid Security Layer — Research PoC

[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Research%20PoC-orange.svg)](#12-limitations)

> Research PoC that fuses Quantum Key Distribution (QKD) and Post-Quantum
> Cryptography (PQC) into a single **HKDF-SHA3-256**-derived PSK and rotates
> the WireGuard VPN every 30 s. A QuTiP-based BB84 physical simulator is
> wrapped behind the ETSI GS QKD 014 REST API and wired into
> [arnika-vq](https://github.com/Veriqloud/arnika-vq) (Go, reused unchanged) and
> [Rosenpass](https://github.com/rosenpass/rosenpass) (Rust) for an end-to-end path that
> mirrors a production deployment.

Reference papers:
- `references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf` (Spooren et al.)
- `references/QuLore_An_Adaptive_Security_Framework...pdf` (Sanz et al.)

---

## Table of Contents
1. [Introduction](#1-introduction)
2. [Architecture](#2-architecture)
3. [Repository Layout](#3-repository-layout)
4. [Quickstart](#4-quickstart)
5. [Build details](#5-build-details)
6. [Configuration](#6-configuration)
7. [Running the WebUI](#7-running-the-webui)
8. [Verification & Tests](#8-verification--tests)
9. [Benchmarks](#9-benchmarks)
10. [Paper Mapping](#10-paper-mapping)
11. [Dev Environment](#11-dev-environment)
11.5 [Phase 8 — Multi-backend QKD simulation & optimisation](#115-phase-8--multi-backend-qkd-simulation--parameter-optimisation)
11.6 [Phase 9 — Real Quantum-Secure VPN extensions](#116-phase-9--real-quantum-secure-vpn-extensions)
11.7 [Phase 10 — Quantum-Secure E2E live simulation page](#117-phase-10--quantum-secure-e2e-live-simulation-page)
11.8 [Phase 12 — Logger / shared UI / per-page exports](#118-phase-12--logger--shared-ui--per-page-exports)
11.9 [Phase 14 — Paper Data Exchange page + /e2e SVG polish + Rust ETSI 014 KME](#119-phase-14--paper-data-exchange-page--e2e-svg-polish--rust-etsi-014-kme)
12. [Limitations](#12-limitations)
13. [References](#13-references)
14. [License](#14-license)
15. [Recommendations & Future Research](#15-recommendations--future-research)

---

## 1. Introduction

The goal of this PoC is to reproduce the three-layer model from
*"PQC-Enhanced QKD Networks: A Layered Approach"* (Spooren et al.) inside a
**research environment that has no physical QKD hardware**.

| Layer | Role | Implementation |
|---|---|---|
| End-to-End (PQC) | Post-quantum key exchange between nodes | Rosenpass (ML-KEM-768) |
| Transport | Fetches QKD/PQC keys, fuses them via HKDF and injects the resulting WG PSK | **arnika-vq (Go, reused unchanged)** |
| Hop (WireGuard) | Real encryption with ChaCha20-Poly1305 + Noise + PSK | WireGuard kernel module |

The QKD layer is supplied by a **QuTiP-based BB84 physical simulator** wrapped
behind the ETSI GS QKD 014 REST API. Eve's intercept-resend attack can be
toggled from the WebUI, and the resulting QBER jump and arnika's fall-back
behaviour are visible in real time.

---

## 2. Architecture

```
                     ┌────────────────────────────────────┐
                     │   WebUI  (React + Plotly + D3)     │
                     │   localhost:5173                   │
                     └──────────────┬─────────────────────┘
                                    │ REST + WS
                     ┌──────────────▼─────────────────────┐
                     │  webui-backend (FastAPI)           │
                     │  /api/stack /api/stats /ws/frames  │
                     └──┬───────────────────────┬─────────┘
                        │                       │
        ┌───────────────▼───┐               ┌───▼──────────────┐
        │  bb84-kme-a       │ /internal/sync│  bb84-kme-b      │
        │  QuTiP BB84 + ETSI│◄─────────────►│  QuTiP BB84+ETSI │
        └────────▲──────────┘               └──────────▲───────┘
                 │ HTTP (mTLS opt.)                    │
        ┌────────┴───────────┐               ┌─────────┴────────┐
        │  alice (node)      │ WireGuard wg0 │  bob (node)      │
        │  - arnika (Go)     │◄─────────────►│  - arnika (Go)   │
        │  - rosenpass       │ PSK = HKDF(   │  - rosenpass     │
        │  - wg0 10.0.0.1/24 │   QKD || PQC) │  - wg0 10.0.0.2  │
        └────────────────────┘               └──────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the detailed design.

---

## 3. Repository Layout

```
pqc-qkd-hybrid/
├── README.md                          # ← you are here
├── ARCHITECTURE.md                    # Detailed design & paper mapping
├── docker-compose.yml                 # Main topology
├── docker-compose.boringtun.yml       # WG kernel fallback (userspace)
├── docker-compose.multihop.yml        # Adds Charlie relay (paper §III)
├── .env.example                       # Sample environment
├── Makefile                           # build / up / smoke / bench
├── references/                        # Reference papers (PDF, .docx)
├── submodules/                        # Git submodules (unmodified)
│   ├── arnika-vq/                     # Go binary baked into node image
│   ├── liboqs/                        # NIST PQC (ML-KEM, ML-DSA, SLH-DSA, Falcon)
│   ├── oqs-provider/                  # OpenSSL 3.x provider for PQC TLS
│   ├── rosenpass/                     # (after `make init`) PQC handshake daemon
│   ├── SimQN/                         # (Phase 8) Python BB84 + Cascade + TPA (2026-05-25)
│   ├── SeQUeNCe/                      # (Phase 8) Argonne photonic-realism DES (2026-05-12)
│   ├── qkdnetsim/                     # (Phase 8) NS-3 v3.46 ETSI 014/004 reference KMS
│   ├── openQKDsecurity/               # (Phase 8) MATLAB SDP — used offline only
│   ├── strawberryfields/              # (Phase 8) CV-QKD GG02
│   ├── tno-qkd-key-rate/             # (Phase 8) TNO-Quantum decoy-state BB84/BBM92 key-rate (Apache-2.0, v2.0.4)
│   ├── PQClean/                       # (Phase 8) NIST PQC reference implementations
│   ├── qkd_kme_server/               # (Phase 14) Rust ETSI GS QKD 014 KME server
│   └── qkd-pqc-paper-supplementary/  # (Phase 14) Spooren et al. containerlab multi-hop emulation
├── config/                            # (Phase 8) Central tunables
│   ├── qkd_params.yaml                # Single source of truth (hot-reloaded)
│   └── qkd_keyrate_table.json         # Pre-computed SKR table (arXiv:2511.21253)
├── services/
│   ├── bb84-kme/                      # Python: 6-backend BB84/CV-QKD + ETSI-014 REST
│   │   └── app/backends/              # qutip / simqn / sequence / cvqkd / composite / qkdnetsim_proxy / tno
│   ├── webui-backend/                 # FastAPI orchestrator
│   ├── webui-frontend/                # React/Vite/Plotly/D3 dashboard (12 pages incl.
│   │                                  #   /e2e Quantum-Secure E2E + /paper-flow Paper Data Exchange)
│   ├── pqc-tls-demo/                  # Optional: oqs-provider TLS sanity
│   ├── pqc-validator/                 # (Phase 8) liboqs vs PQClean cross-check
│   └── qkdnetsim-kme/                 # (Phase 8) NS-3 ETSI 014 reference KME (separate container)
├── tools/                             # (Phase 8) Precompute scripts (MATLAB + Python fallback)
├── nodes/{alice,bob,charlie}/         # Per-node Docker context
├── pki/                               # mTLS cert generation
├── animations/                        # Manim scenes (.py)
├── benchmarks/                        # Latency / throughput scripts
├── tests/                             # pytest contract & unit tests
└── docs/                              # paper_mapping.md, roadmap.md
```

---

## 4. Quickstart

```bash
# 1) Clone with submodules
git clone --recurse-submodules https://github.com/<you>/pqc-qkd-hybrid.git
cd pqc-qkd-hybrid

# 2) Initialise: writes .env, fetches submodules, generates mTLS certs
make init

# 3) Build all images (≈3-5 min first time: arnika Go + Rosenpass Rust + Python)
make build

# 4) Bring up the full stack (detached)
make up

# 5) Open the WebUI
xdg-open http://localhost:5173    # Linux
# or just navigate manually

# 6) Quick end-to-end smoke
make smoke
```

`make smoke` verifies the ETSI-014 contract, pings `bob` from `alice` over `wg0`,
and greps for `PSK configured` + `HKDF derivation completed` in arnika's logs.

---

## 5. Build details

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

If `modprobe wireguard` fails on your host, use the userspace `boringtun` build:

```bash
make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.boringtun.yml"
```

### 5.4 Multi-hop (Alice—Charlie—Bob)

```bash
make up-multihop
```

This launches the `charlie` relay (compose profile `multihop`).

### 5.5 Cloud deployment (single host + TLS)

To run the full real-WireGuard stack on a single public host (e.g. a ConoHa
KVM VPS) behind automatic HTTPS, use the artifacts in [`deploy/`](deploy/):

```bash
cp deploy/.env.example .env       # set PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy.sh        # Docker + WireGuard module + UFW + build & up
# or manually:
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
```

A Caddy reverse proxy is the only public service (80/443, auto Let's Encrypt);
the KME/backend and WireGuard nodes stay on the internal networks. The
privileged WG nodes need a real kernel (fine on a KVM VPS, not on managed PaaS).
See [`deploy/README.md`](deploy/README.md). Detailed deployment/business and
per-OSS license & commercial-use notes live in the private `MONETIZATION.md`.

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
Leaner still, the four sim pages need **no
backend at all** — the frontend bundle can be served statically (GitHub /
Cloudflare / Netlify Pages) for a near-$0 demo (only `/verify` is then disabled).

---

## 6. Configuration

All variables in `.env` (copy from `.env.example`):

| Variable | Default | Purpose | Source of truth |
|---|---|---|---|
| `ARNIKA_MODE` | `QkdAndPqcRequired` | One of 4 modes: `QkdAndPqcRequired` / `AtLeastQkdRequired` / `AtLeastPqcRequired` / `EitherQkdOrPqcRequired` | `submodules/arnika-vq/config/config.go:39-45` |
| `ARNIKA_INTERVAL` | `30s` | PSK rotation period (paper uses 120s) | `submodules/arnika-vq/config/config.go` |
| `KMS_HTTP_TIMEOUT` | `10s` | ETSI 014 HTTP timeout | arnika config |
| `BB84_BATCH` | `2048` | Photons per BB84 round | `services/bb84-kme/app/keypool.py` |
| `BB84_CHANNEL_NOISE` | `0.01` | Bit-flip probability (channel) | `services/bb84-kme/app/bb84/simulator.py` |
| `BB84_QBER_THRESHOLD` | `0.11` | Reconciliation abort threshold | `services/bb84-kme/app/bb84/reconciliation.py` |
| `BB84_POOL_LOW` / `BB84_POOL_MAX` | `8` / `64` | Key pool watermarks | `services/bb84-kme/app/keypool.py` |
| `BB84_EVE_ENABLED` / `BB84_EVE_PROB` | `false` / `0.0` | Initial Eve attack (also runtime-controllable from WebUI) | `services/bb84-kme/app/bb84/eve.py` |
| `WEBUI_BACKEND_PORT` | `8000` | Backend port (host) | docker-compose |
| `WEBUI_FRONTEND_PORT` | `5173` | Frontend nginx port (host) | docker-compose |
| `ETSI_MTLS_ENABLED` | `false` | Enable mTLS between arnika ↔ KME | Phase 7 |

---

## 7. Running the WebUI

Open <http://localhost:5173>. Thirteen pages are available:

1. **Overview** (`/`) — Layered architecture SVG + live container status badges
2. **Quantum-Secure E2E** (`/e2e`) — **client-side** 4-phase orchestration (Quantum Plane → QKD Key IDs → PQC Handshake → Data Exchange) with **real in-browser HKDF-SHA3-256 + ChaCha20-Poly1305** (`@noble`), over the arnika-vq architecture diagram, Run/Pause/Resume/Reset/Step + Mode A/B/C
3. **Paper Data Exchange** (`/paper-flow`) — **client-side** multi-hop trusted-node Data Exchange (Spooren et al. arXiv:2604.05599): swimlane sequence, hop-count slider (1–8), layer-aware failure-cascade timeline, ChaCha20-Poly1305 payload
4. **BB84 Live** (`/bb84`) — **client-side** Monte-Carlo photon simulation in a **Web Worker** (~70–100M pulses/s; optional WebGPU), real-time QBER chart, key-pool size, photon-frame table, **Eve toggle** + intercept-probability slider, live engine badge
5. **Key Flow** (`/keyflow`) — Plotly Sankey of QKD raw → sifted → reconciled + Rosenpass → HKDF → WireGuard PSK
6. **Topology** (`/topology`) — D3-force graph of nodes (alice/bob/Charlie) and KMEs
7. **Benchmarks** (`/benchmarks`) — Round latency, QBER history, KPI cards (accepted/aborted/avg ms)
8. **Console** (`/console`) — Live log tail of any container (alice / bob / KMEs)
9. **Physics Params** (`/physics`) — **Editable** parameter inputs (Apply/Reset). `config/qkd_params.yaml` provides the defaults (best-effort synced to the KMEs); a **client-side** live key-rate (closed-form Lo-Ma) + **client-side** μ/ν optimiser recompute in-browser as you edit, plus the backend selector (incl. `tno`)
10. **PQC Validator** (`/pqc`) — liboqs (production) vs PQClean (NIST reference) roundtrip
11. **Verification** (`/verify`) — Research-implementation evidence: crypto-agility matrix (ML-KEM 512/768/1024 + ML-DSA 44/65/87), key-rate cross-check (our closed-form vs the independent **TNO-Quantum** engine), and arXiv:2604.05599 packet-budget match
12. **Hardware-In-Loop** (`/hil`) — Checklist for wiring real ETSI 014 KMS hardware (mTLS)
13. **VPN Protocols** (`/vpn`) — WireGuard + strongSwan IPsec/IKEv2 (RFC 9370 ML-KEM-768 hybrid) status

Most pages provide per-page export buttons below the description — **high-DPI PNG (2×)**, JSON, CSV, **WebM (HQ)** + **full-resolution GIF** animation, and logs; artefacts are stored on the backend and re-downloadable via the "Saved exports" picker.

**Public-demo profile (`DEMO_MODE=1`).** For an unattended, multi-user public demo set `DEMO_MODE=1` on `webui-backend`. The demo is **functionally equivalent to full mode except the one genuinely dangerous operation** — **container lifecycle control** (`/api/stack/*`), which could take the shared demo offline and stays **403** (its restart buttons are hidden) — plus a per-IP rate limit (`DEMO_RATE_MAX` / `DEMO_RATE_WINDOW_S`, 429) for abuse protection. **Backend switching, parameter overrides, and server-side export saves are all allowed** (reversible / capacity-bounded by `EXPORT_MAX_FILES`+`EXPORT_MAX_BYTES` / rate-limited). Local full-stack and the `deploy/` cloud real-WG stack run with `DEMO_MODE` unset (unchanged).

> ⚠️ The WebUI Backend mounts `/var/run/docker.sock:ro` to query container state.
> This is acceptable for a single-host PoC but should not be exposed in production.

---

## 8. Verification & Tests

| Check | Command | Expected |
|---|---|---|
| ETSI-014 contract | `pytest tests/test_etsi014_contract.py -v` | All pass; JSON has exactly `{key_ID, key}` fields |
| BB84 simulator unit | `pytest tests/test_bb84_simulator.py -v` | QBER < 5% no-Eve; QBER > 15% with full intercept |
| wg0 reachability | `docker exec alice ping -c 3 10.0.0.2` | All replies received |
| PSK injection log | `docker logs alice \| grep "PSK configured"` | One match per `ARNIKA_INTERVAL` |
| HKDF fusion log | `docker logs alice \| grep "HKDF derivation completed for QKD+PQC"` | Present in `QkdAndPqcRequired` mode |
| Eve raises QBER | toggle Eve in WebUI → QBER chart spikes ≥ 25% within 2 rounds; arnika falls back per mode | observable in WebUI |
| Encrypted on the wire | `docker exec alice tcpdump -i eth1 -X udp port 51820 -c 5` | only opaque ciphertext, no ICMP plaintext |
| Multi-hop ping (optional) | `make up-multihop && docker exec alice ping 10.0.0.2` | Replies via charlie |

`make smoke` runs the critical subset automatically.

---

## 9. Benchmarks

```bash
make bench
python3 benchmarks/plot_results.py
```

Outputs to `benchmarks/results/`:
- `handshake_age.csv` — WG handshake age (drops to ~0 at each rotation)
- `ping_*.log` — RTT/jitter samples
- `iperf3_*.log` — throughput JSON
- `plots/handshake_age.png` — visualisation

**Paper reference numbers** to aim for (Spooren et al.):
- Setup time: ~10.27s @ 10 intermediate nodes, ~10.62s @ 100 nodes
- Handshake overhead: 3 WG packets (398B), 2 arnika packets (78B), 4 Rosenpass packets (4772B)

---

## 10. Paper Mapping

Detailed claim-by-claim mapping is in [`docs/paper_mapping.md`](docs/paper_mapping.md).

Quick summary:
- ✅ KMS-free layered overlay
- ✅ ETSI 014 client/server contract
- ✅ Arnika as PSK injector (unmodified upstream binary)
- ✅ Rosenpass PQC layer (real binary; falls back to urandom if build fails)
- ✅ Multi-hop trusted-node chain (`docker-compose.multihop.yml`)
- ⚠️ Adaptive security levels (QuLore L1-L4) — **not yet implemented**, see [`docs/roadmap.md`](docs/roadmap.md)

---

## 11. Dev Environment

Tested on:
- **OS**: AlmaLinux 9.7
- **CPU**: Intel i5-13600K (14C/20T)
- **RAM**: 128 GB DDR5 5200
- **GPU**: NVIDIA RTX 6000 PRO Blackwell 96GB (CUDA 13.0)
  — *GPU is optional*; the BB84 simulator is CPU-bound by design for portability.
  Future Shor-attack-simulator (roadmap A) will leverage CUDA-Q + cuQuantum.
- **Python**: 3.12 in a `.venv` for host-side scripts (tests, benchmarks, manim)
- **Docker**: 24+ with Compose v2
- **WireGuard**: kernel module via `kmod-wireguard` (ELRepo)

Host-side Python venv (for running `pytest` and Manim outside Docker):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install httpx pytest qutip numpy manim matplotlib
```

---

## 11.5 Phase 8 — Multi-backend QKD simulation & parameter optimisation

Phase 8 addresses the §12 "QKD is only physically simulated" limitation by adding 4 additional
2026-active OSS backends and a science-grounded parameter pipeline.

### Design principle — no hardcoded numbers
Every numeric tunable lives in `config/qkd_params.yaml`. The Python source under
`services/bb84-kme/app/backends/` is guarded by `tests/test_no_hardcoded_params.py`
which walks the AST and rejects magic floats / ints (allow-list only for unit
conversions, π/2 etc., and explicitly documented CV-QKD defaults).

### Parameter source priority
```
1. WebUI live slider          (PhysicsParams page)        →
2. config/qkd_params.yaml     (hot-reloaded via watchdog) →
3. config/qkd_keyrate_table.json (pre-computed, openQKDsecurity SDP +
                                  arXiv:2511.21253 closed-form)
4. scikit-optimize gp_minimize  (Bayesian Optimization on closed-form SKR)
```

### Backend selection
Set via `SIMULATOR_BACKEND` env or `simulator.backend` YAML key, or switch the
**runtime** backend live from the WebUI "Physics Params" page's selector (which
reflects the actual running backend from `/api/stats`). This controls the
bb84-kme physics backend used by the full-stack real KME; the Physics page's
key-rate panel is computed **client-side** and is backend-independent. The
selector is **enabled in `DEMO_MODE`** too — switching the shared backend is
reversible and rate-limited, so it's safe on a public host (its effect is visible
on the Benchmarks page).

| Backend | Source | Purpose |
|---|---|---|
| `qutip` | built-in | Lightweight teaching demo |
| `simqn` | `submodules/SimQN` | Realistic Cascade + Toeplitz PA + fiber loss |
| `sequence` | `submodules/SeQUeNCe` | Photonic noise (depolarizing + measurement error) |
| `cvqkd` | `submodules/strawberryfields` | GG02 continuous-variable QKD |
| `tno` | `submodules/tno-qkd-key-rate` | TNO-Quantum decoy-state BB84/BBM92 key-rate (Apache-2.0) |
| `qkdnetsim_proxy` | `services/qkdnetsim-kme` | ETSI 014 reference (NS-3 v3.46) |
| `composite_sim_to_net` | SimQN + qkdnetsim | Physical layer feeds network layer |

### Parameter optimisation
The bb84-kme **backend** optimiser (scikit-optimize `gp_minimize`, Bayesian) is
available via the CLI / API:
```bash
source .venv/bin/activate
python -c "
from app import config_loader; config_loader.reload()
from app.optimizer import optimize_from_yaml
print(optimize_from_yaml())
"
```
The WebUI **Physics Params** page's "Optimize μ / ν" button runs a fast
**client-side** μ/ν grid search over the closed-form Lo-Ma SKR (no backend call).

### Verification (host venv)
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install fastapi 'uvicorn[standard]' pydantic httpx 'numpy<2.3' qutip pyyaml \
            prometheus-client scikit-optimize pandas 'Cython<3.0' pytest
pip install -e submodules/SimQN
QKD_PARAMS_FILE=config/qkd_params.yaml \
  python -m pytest tests/test_no_hardcoded_params.py \
                    tests/test_backend_cross_qber.py \
                    tests/test_bb84_simulator.py -v
# Expected: 7 passed
```

### Pre-computed key-rate table
```bash
source .venv/bin/activate
python tools/precompute_keyrate_table_fallback.py
# wrote 1170 rows to config/qkd_keyrate_table.json
```

The table is committed to git so users without MATLAB get production defaults.

---

## 11.6 Phase 9 — Real Quantum-Secure VPN extensions

Phase 9 takes the PoC from "research demo" toward "real quantum-safe VPN stack" by
adding parallel VPN protocols, a documented crypto-agility strategy, paper-baseline
comparison, and end-to-end browser verification.

### VPN protocol lanes (WireGuard + strongSwan IPsec/IKEv2)

| Lane | Tunnel impl | Key exchange | PSK injection path |
|---|---|---|---|
| `wireguard` (Phase 0-7 default) | kernel module `wg` | Curve25519/ChaCha20-Poly1305 + Noise + PSK | `arnika` → `wgctrl` netlink |
| `strongswan` (Phase 9-A) | `charon` daemon | **RFC 9370** hybrid (ECP-256 + KE1=ml_kem_768) | `arnika-vici-bridge.sh` → `swanctl --load-creds` |

Bring up either lane (or both):

```bash
make up                                   # WireGuard (default profile)
make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.strongswan.yml" \
   --profile ipsec                        # IPsec/IKEv2 (RFC 9370) lane
```

Verify RFC 9370 hybrid handshake:

```bash
docker exec alice-ipsec swanctl --list-sas | grep -E "ESTABLISHED|ML_KEM"
docker exec alice-ipsec tcpdump -i eth0 -nn udp port 500 -c 4
```

### Cryptographic agility strategy (RFC 7696 / NIST SP 800-131A Rev.3)

The PoC ships **two parallel PQC stacks** so users can choose between maximum
algorithm coverage and FIPS-stable production:

| Lane | Image | Algorithm space | Use case |
|---|---|---|---|
| `oqs-provider` (default) | `services/pqc-tls-demo/Dockerfile.oqs-provider` | ML-KEM, ML-DSA, **SLH-DSA, Falcon, HQC, Classic McEliece**, future NIST round 4 | Research, experiments, algorithm agility |
| `openssl35-native` | `services/pqc-tls-demo/Dockerfile.openssl35-native` | **NIST standards only** (FIPS 203/204) | Production, FIPS compliance |

```bash
make pqc-tls-demo-both                    # Start both lanes side-by-side
# Test:
openssl s_client -tls1_3 -groups X25519MLKEM768 -connect tls35:4433
openssl s_client -tls1_3 -groups X25519MLKEM768 -provider oqsprovider \
                 -connect tls-oqs:4433
```

The `PQC_PROVIDER` env (oqs / native) selects which lane the WebUI "PQC Validator"
page targets.

### Paper baseline comparison (`tools/compare_to_paper.py`)

`submodules/qkd-pqc-paper-supplementary/` (added in Phase 9-B) contains the raw
experimental data from Spooren et al. (arXiv:2604.05599). Run:

```bash
source .venv/bin/activate
python tools/compare_to_paper.py
cat benchmarks/results/paper_comparison.json | head -n 30
```

Sample output (after `make bench`): rosenpass-scalability experiment-summary.csv
mean handshake time is within ±15 % of the paper's 10.27 s @ 10 nodes.

### End-to-end browser verification (10 pages)

| # | Path | Page |
|---|---|---|
| 1 | `/` | Overview (architecture SVG + live container status) |
| 2 | `/e2e` | Quantum-Secure E2E — **client-side** 4-phase orchestration (real @noble HKDF-SHA3 + ChaCha20) |
| 3 | `/paper-flow` | Paper Data Exchange — **client-side** multi-hop + failure cascade (arXiv:2604.05599) |
| 4 | `/bb84` | BB84 Live — **client-side** Monte-Carlo (Web Worker/WebGPU), QBER chart, Eve toggle, photon frames |
| 5 | `/keyflow` | Hybrid Key Derivation Sankey |
| 6 | `/topology` | D3-force network graph |
| 7 | `/benchmarks` | KPI cards + latency/QBER charts |
| 8 | `/console` | Container log tail |
| 9 | `/physics` | PhysicsParams — editable params + **client-side** key-rate & μ/ν optimiser (closed-form Lo-Ma) |
| 10 | `/pqc` | PQC Validator (liboqs vs PQClean) |
| 11 | `/verify` | Implementation Verification (crypto-agility matrix + TNO key-rate cross-check + paper budgets) |
| 12 | `/hil` | Hardware-In-The-Loop bridge instructions |
| 13 | `/vpn` | VPN Protocols (WireGuard ⟷ strongSwan) |

Verified via Chrome DevTools MCP: all 13 React Router paths render their correct headings,
the four simulation pages run client-side (no `/ws/*`), and console errors = 0.
- 0 console errors (only Electron CSP + React Router v7 future-flag warnings, both benign)
- `/api/*` proxy targets backend; pages with API dependencies show "Loading…" gracefully

---

## 11.7 Phase 10 — Quantum-Secure E2E live simulation page

Phase 10 adds a single **Quantum-Secure E2E** page (route `/e2e`, sidebar starred entry)
that drives an actual background simulation from Alice to Bob across the full 4-phase
Data Exchange depicted in the reference architecture image, with live buttons.

### What runs in the background

A coroutine-based state machine
(`services/webui-backend/app/e2e_orchestrator.py`) cycles through four phases:

| Phase | Name | What actually happens |
|---|---|---|
| **1** | Quantum Plane | Poll `bb84-kme-a` `/api/v1/keys/ALICE/status` until SimQN backend produces a key |
| **2** | QKD Key IDs (ETSI 014) | `GET /enc_keys` from KME-A, mirror retrieval via `GET /dec_keys?key_ID=…` at KME-B (matches `submodules/arnika-vq/kms/kms.go:69-176`) |
| **3** | PQC Handshake (HKDF-SHA3) | `HKDF-SHA3-256(qkd ‖ random_pqc, salt="pqcqkd-e2e", info=mode)` → 32 B PSK |
| **4** | Data Exchange (ChaCha20-Poly1305) | Encrypt 64 ping-sized payloads per cycle, count bytes and packets |

Verified: 5 seconds @ default settings produces **~60 cycles, ~3 900 packets, ~280 KB
encrypted**, with rotating QKD key IDs and per-cycle PSK derivation.

### What the UI shows

`services/webui-frontend/src/pages/QuantumSecureE2E.tsx` renders, top-to-bottom:

1. **SVG architecture diagram** faithful to the reference image — Site A / Site B,
   ARNIKA (orange) · ROSENPASS (pink) · WIREGUARD (purple), KMS keystores
   (ETSI 014, green) at each edge. Active phase highlights the relevant elements
   with a coloured glow.
2. **Mode buttons A / B / C** — `A · QKD-only`, `B · PQC-only`, `C · Hybrid (QKD ‖ PQC)`.
3. **Control buttons** — `▶ Run` / `⏸ Pause` / `▶ Resume` / `⏹ Reset` / `⏭ Step` +
   live status badge.
4. **Phase progress strip** — 4 boxes turning red-active or green-done as the
   state machine progresses.
5. **KPI cards** — Completed cycles, packets encrypted, bytes encrypted, throughput Mbps.
6. **Latest derived material** — most recent QKD `key_ID` and HKDF PSK prefix.
7. **Phase history table** — last 8 phase entries with detail JSON.

State streams live over WebSocket (`/ws/e2e`) at ~4 Hz.

### REST + WebSocket surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/e2e/state` | GET | Current snapshot (status, phase, mode, cycles, history…) |
| `/api/e2e/start` | POST | Kick the orchestrator into `running` |
| `/api/e2e/pause` | POST | Freeze the state machine (counter halts) |
| `/api/e2e/resume` | POST | Resume from `paused` |
| `/api/e2e/reset` | POST | Clear cycles/packets/history back to `idle` |
| `/api/e2e/step` | POST | Single-step one cycle even while paused |
| `/api/e2e/mode` | POST | Set mode A / B / C |
| `/ws/e2e` | WS | Live snapshot pushed on every state transition |

### Browser verification (Chrome via Claude Preview MCP)

Verified end-to-end against the live Docker stack (bb84-kme-a/b + webui-backend +
webui-frontend, all healthy):

- `Pause` → counter froze at cycles=1489 across 3 seconds
- `Resume` → counter advanced 1489 → 1517
- `Reset` → counter → 0 (idle state)
- `Mode A` / `Mode B` / `Mode C` → backend `mode_label` updated to "QKD-only" /
  "PQC-only" / "Hybrid (QKD ‖ PQC)" respectively
- WebSocket delivered 3 snapshots in 250 ms intervals with phase transitions visible
- **0 console errors** (only React Router v7 future-flag warnings, benign)
- Screenshots captured for idle / running / paused states

### Layout v2 (Phase 11)

The initial SVG (880×280, ~30 elements) was rewritten to **1240×620 with 145 SVG
elements** so the on-screen architecture is now 1:1 faithful to the reference image:

- Three dashed boundary boxes — VPN scope (red), Secure Application Entity (purple,
  per site), Quantum Key Distribution Infrastructure (blue, far left + right)
- Top key-colour legend with A/B/C key icons, mirrored on Site A and Site B
- KMS Keystore [ETSI 014] + QKD sub-box + ETSI Interface "E" badge per side
- Centre "VPN" lock icon between sites
- Three separated bottom rows: **PQC KEY exchange** (Rosenpass A⇄B), **QKD key_ID
  exchange** (ETSI 014), and **Quantum Channel** (BB84 photonic) — each on its own
  y-band, no overlapping labels
- Bottom-left legend explaining A = QKD Mode / B = PQC Mode / C = Hybrid /
  E = ETSI Interface

A new submodule **`mullvad/wgephemeralpeer`** (2026-05-08 active, GPL-3.0) is added
as a reference for the alternative "PQC-only PSK rotation" approach used in
production by Mullvad VPN; see [`docs/IMAGE1_VPN_SCOPE.md`](docs/IMAGE1_VPN_SCOPE.md)
for a head-to-head comparison with arnika-vq.

Screenshots: `docs/images/screenshots/e2e-v2-idle.png`, `e2e-v2-phase1.png`.

---

## 11.8 Phase 12 — Logger / shared UI / per-page exports

Three improvements that make the PoC easier to operate, inspect, and reproduce:

### 12-A: Rotating file logger

All Python services (webui-backend, bb84-kme-a, bb84-kme-b, pqc-validator) now log
through `services/<svc>/app/logging_setup.py`. Output is duplicated to:

- stdout — keeps `docker logs <svc>` behaviour intact
- **`/var/log/pqcqkd/<svc>.log`** — `RotatingFileHandler`, 10 MB × 5 backups, mounted
  as the shared `pqcqkd-logs` volume

Two REST endpoints expose the files to the browser:

```bash
curl http://localhost:5173/api/logs/files
# {"files":[{"name":"alice.log","size":863,...},
#           {"name":"bob.log","size":742,...},
#           {"name":"webui-backend.log","size":388,...}]}

curl http://localhost:5173/api/logs/download/alice?lines=200
# (downloads the last 200 lines of /var/log/pqcqkd/alice.log)
```

Also: `make tail-logs` follows the live rotation inside the container.

### 12-B: Shared React components

Seven reusable building blocks live under
`services/webui-frontend/src/components/` so individual pages stop re-implementing
their own button / panel / row / badge / KPI:

| Component | Purpose |
|---|---|
| `PageHeader` | `<h2>` + lead `<p>` + right-aligned `ExportToolbar` slot |
| `Panel` | Card with optional left-border accent colour |
| `Row` | Aligned key/value display |
| `Badge` | Coloured status pill (`running`, `paused`, `healthy`, ...) |
| `Button` | Variant-aware button (`primary`/`secondary`/`danger`/`success`/`warn`/`ghost`) |
| `KPI` | Dashboard number tile |
| `ExportToolbar` | The download buttons described below |

Dark theme tokens are centralised in `services/webui-frontend/src/lib/commonStyles.ts`.

The `Quantum-Secure E2E` page (Phase 11 SVG) is **unchanged** in layout; only the
heading and the toolbar are added on top.

### 12-C: Per-page export toolbar

A new `<ExportToolbar>` ships on every refactored page. Each button is opt-in: the
page only declares the providers it can supply.

| Button | Action |
|---|---|
| 💾 **Logs** | Download `/api/logs/download/<service>` as `.log` |
| 🖼 **PNG** | High-DPI (2×) PNG — SVG diagrams via XMLSerializer→Canvas at 2× scale; other pages via `html-to-image` `pixelRatio: 2` |
| 📋 **JSON** | Serialise the page's snapshot from `jsonProvider()` |
| 📊 **CSV** | Serialise tabular data from `csvProvider()` |
| 🎬 **WebM (HQ)** | High-quality animation — records ~4 s via `MediaRecorder` + `canvas.captureStream` (VP9/VP8 WebM, no 256-colour limit) |
| 🎞 **GIF** | Animated GIF (universally compatible) — full-resolution frames + `gifshot` `sampleInterval: 2` |

All downloads are produced client-side (`Blob` + `URL.createObjectURL`), with a
best-effort backend save for re-download; **no server-side generation is required**.

### Browser verification (Chrome DevTools MCP)

- `/e2e` export toolbar exposes `["💾 Logs","🖼 PNG","📋 JSON","🎬 WebM (HQ)","🎞 GIF","📂 Saved"]`;
  verified PNG = 2480×1200 (2×), GIF = 1240×600 (full-res), WebM = valid VP9 video
- Pressing 💾 Logs produces a `text/plain` blob of 388 B (matches the file size on disk)
- Pressing 📋 JSON produces an `application/json` blob of 308 B
- `/api/logs/files` returns the three rotating log files actually written under
  `/var/log/pqcqkd/` (verified inside the container)
- **0 console errors**
- Screenshot: `docs/images/screenshots/e2e-v3-export-toolbar-top.png`

---

## 11.9 Phase 14 — Paper Data Exchange page + /e2e SVG polish + Rust ETSI 014 KME

Phase 14 introduces a brand-new page that implements the *paper-faithful* Data
Exchange (vs the single-tunnel concept on `/e2e`), polishes the existing E2E
SVG layout, and adds a third independent ETSI 014 KME (Rust) as 2026-active
OSS reference.

### A new page: `/paper-flow` — Paper Data Exchange

Route: `/paper-flow` (sidebar entry "Paper Data Exchange ◆" right after the
existing "Quantum-Secure E2E ★"). The page is intentionally distinct from
`/e2e`:

| | `/e2e` (image 1) | `/paper-flow` (image 2 + arXiv:2604.05599) |
|---|---|---|
| Source figure | `Veriqloud/arnika-vq` single-tunnel diagram | **Multi-hop trusted-node diagram** (End Node Alice \| Trusted Node × N \| End Node Bob) |
| Focus | key fusion in one Site A ↔ Site B tunnel | **5-phase daisy chain** with paper-quoted packet budgets |
| Failure model | Eve attack on BB84 | **240-720 s layer cascade** per §VI |
| Data Exchange | conceptual ChaCha20 over derived PSK | live `ChaCha20-Poly1305` payload per cycle, packet/byte counters track paper §IV-B Table III |

Backend orchestrator (`services/webui-backend/app/paper_flow.py`):
- 5-phase state machine: **Quantum Plane → Arnika QKD key_ID → WG hop handshake → Rosenpass PQC handshake → Final data tunnel**
- Paper budgets embedded as the source of truth (`PHASE_BUDGETS` constant):
  Phase 2 = 2 pkt / 78 B; Phase 3 = 3 pkt / 398 B; Phase 4 = 4 pkt / 4772 B;
  **total handshake = 9 pkt / 5248 B**
- Failure cascade scheduler with 7 stages (0/180/240/360/420/540/720 s)
- WebSocket `/ws/paper-flow` at ~4 Hz
- REST: `/api/paper-flow/{state,start,pause,resume,reset,config,inject-failure,clear-failure}`

Frontend (`services/webui-frontend/src/pages/PaperDataExchange.tsx`):
- `MultiHopTopologySvg` — image-2 faithful 3-column-or-more SVG (Alice \|
  TN×N \| Bob), hop slider 1 → 8, per-phase glow highlighting
- `PhaseSequenceSvg` — 5-lane swimlane with time axis 0..540 s, byte-proportional bars
- `PacketFlowTable` — Phase × (packets, bytes, period, grace, status)
- `FailureCascadeTimeline` — 7-event timeline with a moving head; events flip
  red as wall-clock crosses them
- 5 KPI cards (paper packets, paper bytes, mean 10-hop setup, live cycles,
  live bytes)
- Layer-failure injection buttons: `qkd / arnika / wireguard / rosenpass /
  data + clear`
- `ExportToolbar` (Phase 13) wired with `pngTargetSelector="#paper-flow-topology-svg"`

### `/e2e` SVG polish (Phase 11 v2 unchanged in spirit)

Four coordinate fixes to remove subtle text-to-box collisions. Element count
145 and viewBox `1240×620` are preserved:

| Element | Before | After |
|---|---|---|
| KMS→ARNIKA `QKD KEY` label | y=232 (collided with ARNIKA tag y=238) | **y=208** (clear above box) |
| ARNIKA→KMS `key_ID` label | y=278 (10 px below box) | **y=288** (20 px below box) |
| Center `VPN tunnel (ChaCha20-Poly1305)` label | y=206 (touching WIREGUARD title y=220) | **y=174** (just under Site A/B headings) |
| HKDF SHA3 badge inside ARNIKA | x=244 (mid-box, over title text) | **x=222** (top-left corner of box) |

Browser verification confirmed the four labels render at the new
coordinates: `QKD KEY y=[208,208], key_ID y=[288,288], VPN tunnel y=174`.

### A third ETSI 014 KME (Rust, 2026-04-01 active)

`submodules/qkd_kme_server` is now part of the repo —
[`thomasarmel/qkd_kme_server`](https://github.com/thomasarmel/qkd_kme_server)
with its most recent commit on **2026-04-01**, Rust + ETSI GS QKD 014 v1.1.1
compliant. Together with our existing Python `bb84-kme` (Phase 1) and NS-3
C++ `qkdnetsim-kme` (Phase 9), this gives **three independent ETSI 014
implementations** for cross-validation:

| Implementation | Language | Phase | Last commit |
|---|---|---|---|
| `services/bb84-kme` (this repo) | Python + SimQN | 1 | live |
| `services/qkdnetsim-kme` (NS-3 contrib) | C++ | 9 | 2026-05-03 |
| `submodules/qkd_kme_server` | Rust | 14 | **2026-04-01** |

Note: `pq-wireguard` (Kudelski Security) was previously listed as a
candidate but was **archived on 2024-09-03** ("not actively maintained
anymore"), so it has been excluded; only the verifiably 2026-active option
above was added.

### Browser verification (Claude Preview MCP)

- 12 sidebar nav links including the new "Paper Data Exchange ◆"
- `#paper-flow-topology-svg` viewBox `0 0 1060 720`, 160 elements
- `#paper-flow-sequence-svg` 91 elements
- Hop slider 1 → 8 renders 3 → 10 columns
  ("End Node Alice + Trusted Node 1..N + End Node Bob")
- Inject `qkd` failure → 7 cascade events scheduled
  (t=0/180/240/360/420/540/720 s)
- Backend orchestrator: 389 live cycles after ~1.3 s with
  `paper_packets=9 / paper_bytes=5248` (paper-quoted values)
- **0 console errors**

---

## 12. Limitations

When citing or releasing the PoC, **please always disclose the limitations below.**

### 12.1 QKD physical simulation
- **Reinforced from five complementary backends**:
  - `qutip` — lightweight, educational, photon-level
  - `simqn` — Cascade error correction + Toeplitz privacy amplification + fibre attenuation (`submodules/SimQN`, 2026-05-25 active)
  - `sequence` — the SeQUeNCe physical-layer model (`submodules/SeQUeNCe`, 2026-05-12 active, Argonne National Lab)
  - `cvqkd` — Strawberry Fields GG02 continuous-variable QKD (`submodules/strawberryfields`)
  - `composite_sim_to_net` — SimQN physical layer + qkdnetsim NS-3 v3.46 network layer
- All parameters are **scientifically grounded** — `config/qkd_keyrate_table.json` is precomputed offline from the openQKDsecurity Winick SDP and the arXiv:2511.21253 closed-form formula.
- Device-specific non-idealities such as **temperature drift, bandpass filtering, and wavelength-dependent quantum efficiency** are still not modelled.

### 12.2 Hardware connectivity
- Because we speak the **ETSI GS QKD 014 standard interface**, commercial QKD devices (ID Quantique Cerberis, Toshiba MUSE, Thinkquantum TQ-KME, etc.) can be plugged in by **changing a single `KMS_URL` line** — see the WebUI "Hardware-In-Loop" page for the HIL mode.
- Vendor-specific drivers (USB / serial) and HSM-backed key-management APIs are out of scope.
- **Xanadu's cloud CV-QKD service was decommissioned in 2026-01**, but local CV-QKD simulation remains available.

### 12.3 Residual limitations
- **Single-host PoC**: all containers run on a single physical host, so a real QKD network's latency, loss and physical isolation are not reproduced.
- **KME-to-KME synchronisation is over HTTP**: in a real deployment both ends derive a symmetric key over a quantum channel plus an authenticated classical channel, but here `bb84-kme-a` ↔ `bb84-kme-b` simply exchange material via `POST /internal/sync` (isolated by `qkd-net` with `internal: true`).
- **The PQC focus is ML-KEM-768**, but NIST conformance can be independently verified via the **liboqs vs PQClean cross-validator** (`services/pqc-validator/`) and other algorithms can be tried from the "PQC Validator" page.
- **HKDF-SHA3-256 is the arnika default**; alternative constructions (concatenate-then-HMAC, XOR-only, Cascade KDF, etc.) are out of scope.
- **Two parallel VPN protocol lanes** (Phase 9-A):
  - WireGuard PSK mode (default): the Noise Protocol itself still uses classical primitives (Curve25519 / ChaCha20-Poly1305); arnika layers PSK rotation on top for additive protection.
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (recommended for real hardware): ML-KEM-768 is exchanged directly inside the IKE_SA_INIT KE1 payload and combined with classical ECDH to strengthen forward secrecy.
- **No FIPS or Common Criteria certification**: this is a research PoC, not for production deployment.
- **Regulation and export control**: re-distributing cryptographic software may be covered by ECCN 5D002 or similar — check your jurisdiction before redistribution.

---

## 13. References

### Papers (in `references/`)
1. Spooren, J. et al., **"PQC-Enhanced QKD Networks: A Layered Approach"**, IEEE QCNC 2026.
2. Sanz, A. et al., **"QuLore: An Adaptive Security Framework to Extend Quantum-Safe Communications to Real-World Networks"**, EHU/UPV.

### Standards
- [ETSI GS QKD 014](https://www.etsi.org/deliver/etsi_gs/QKD/001_099/014/) — Protocol and data format of REST-based key delivery API
- [ETSI GS QKD 020](https://www.etsi.org/committee/qkd) — KMS interoperability (in development)
- [NIST FIPS 203](https://csrc.nist.gov/pubs/fips/203/final) — ML-KEM (Module-Lattice-based Key Encapsulation)
- [NIST FIPS 204](https://csrc.nist.gov/pubs/fips/204/final) — ML-DSA
- [NIST FIPS 205](https://csrc.nist.gov/pubs/fips/205/final) — SLH-DSA
- [NIST SP 800-56C Rev2](https://csrc.nist.gov/pubs/sp/800/56/c/r2/final) — Key Derivation through Extraction-then-Expansion
- [NIST IR 8413](https://csrc.nist.gov/pubs/ir/8413/final) — Status Report on the PQC Standardisation Process
- [NIST IR 8547](https://csrc.nist.gov/pubs/ir/8547/ipd) — Transition to PQC Standards

### Implementations (Phase 0–7 — core PoC-A)
- [open-quantum-safe/liboqs](https://github.com/open-quantum-safe/liboqs)
- [open-quantum-safe/oqs-provider](https://github.com/open-quantum-safe/oqs-provider)
- [cancom/arnika-vq](https://github.com/cancom/arnika-vq) — Apache-2.0
- [rosenpass/rosenpass](https://github.com/rosenpass/rosenpass) — MIT/Apache-2.0
- [WireGuard](https://www.wireguard.com/)
- [QuTiP](https://qutip.org/)
- [Manim Community](https://www.manim.community/)
- [mullvad/wgephemeralpeer](https://github.com/mullvad/wgephemeralpeer) — GPL-3.0, 2026-05-08 active (alternative PSK injection, kept as architectural reference)

### QKD Simulators (Phase 8 — physical-layer realism, 2026-active OSS)
- [SimQN](https://github.com/ertuil/SimQN) — Python DES, BB84 + Cascade + Toeplitz PA (last commit 2026-05-25)
- [SeQUeNCe](https://github.com/sequence-toolbox/SeQUeNCe) — Argonne National Lab photonic-realism DES (last commit 2026-05-12)
- [qkdnetsim](https://github.com/QKDNetSim/qkdnetsim) — NS-3 v3.46 contrib, ETSI 014/004 KMS (v3.1.2 / 2026-02-03)
- [openQKDsecurity](https://github.com/nlutkenhaus/openQKDsecurity) — MATLAB SDP key-rate prover (used offline to pre-compute `config/qkd_keyrate_table.json`)
- [XanaduAI/strawberryfields](https://github.com/XanaduAI/strawberryfields) — CV-QKD GG02 (Apache-2.0)
- [PQClean](https://github.com/PQClean/PQClean) — NIST reference PQC implementations (used by `services/pqc-validator/`)

### Phase 9 Quantum-Secure VPN (RFC 9370 + crypto agility)
- [strongSwan](https://github.com/strongswan/strongswan) — RFC 9370 ML-KEM hybrid IKEv2 (last commit 2026-05-28)
- [aparcar/qkd-pqc-paper-supplementary-files](https://github.com/aparcar/qkd-pqc-paper-supplementary-files) — Spooren et al. raw experimental data
- [RFC 9370 (2023)](https://datatracker.ietf.org/doc/rfc9370/) "Multiple Key Exchanges in IKEv2"
- [RFC 7696](https://datatracker.ietf.org/doc/rfc7696/) "Guidelines for Cryptographic Algorithm Agility"
- [NIST SP 800-131A Rev.3](https://csrc.nist.gov/pubs/sp/800/131/a/r3/ipd) "Transitioning the Use of Cryptographic Algorithms"
- [OpenSSL 3.5.0 release notes](https://github.com/openssl/openssl/blob/openssl-3.5/CHANGES.md) — native ML-KEM / ML-DSA (2025-07)

### Phase 8 Papers
- arXiv:2511.21253 (2026) — Closed-form finite-key SKR for decoy-state BB84
- arXiv:2412.20265 (2024) — Bayesian intensity selection for long-distance QKD
- Lo-Ma-Chen, PRL 94, 230504 (2005) — Decoy state QKD
- Pirandola et al., Adv. Opt. Photon. 12, 1012 (2020) — Quantum cryptography survey (CV-QKD PLOB bound)
- Grosshans & Grangier, PRL 88, 057902 (2002) — GG02 protocol
- Lo-Curty-Qi, PRL 108, 130503 (2012) — MDI-QKD
- Mehic et al., *SoftwareX* 26 (2024) — QKDNetSim+
- Mehic et al., *IEEE Network* 39(3) (2025) — Czech National QKD Network
- Wu et al., *Quantum Sci. Technol.* 6, 045027 (2021) — SeQUeNCe
- arXiv:2510.00203 (2025-26) — Review of quantum networking software

---

## 14. License

Apache-2.0. Compatible with arnika-vq (Apache-2.0), liboqs (MIT), and Rosenpass (MIT/Apache-2.0).

NOTICE: This software re-distributes cryptographic implementations. Verify your jurisdiction's
export-control regulations (e.g. US ECCN 5D002) before public deployment.

---

## 15. Recommendations & Future Research

### 15.1 Pre-release checklist (mandatory)

- [ ] `.gitignore` excludes `pki/*.pem`, `*.psk`, `.env`, `node_modules/`, build artefacts
- [ ] Generated private keys under `pki/` do not appear in `git status`
- [ ] `make smoke` passes
- [ ] `pytest tests/` passes in full
- [ ] `submodules/` commit hashes are pinned
- [ ] PDFs / .docx under `references/` are inside the redistribution licence
- [ ] [Apache-2.0 NOTICE](LICENSE) and the licence text of every dependency are bundled
- [ ] (Recommended) `gitleaks detect` is wired into CI

### 15.2 Operational recommendations

- **Observability**: add Prometheus + Grafana (`docker-compose.observability.yml`) and surface `qkd_qber`, `arnika_psk_rotation_total`, `wg_handshake_age_seconds`.
- **Reproducibility**: pin `ARG ARNIKA_REF` / `ARG ROSENPASS_REF` in the Dockerfiles to git tags and emit a CycloneDX SBOM.
- **Demo vs production**: `ARNIKA_INTERVAL=30s` is for demos; revert to 120 s (the paper's value) for production-style scenarios.
- **mTLS**: issue certificates with `pki/gen-certs.sh` and enable `ETSI_MTLS_ENABLED=true` (Phase 7).
- **Run both VPN lanes** (Phase 9-A): keep WireGuard and strongSwan IPsec at parity and switch based on bandwidth / MTU / NAT-T requirements.
- **Cryptographic Agility design** (Phase 9-C, RFC 7696 / NIST SP 800-131A Rev.3):
  - Lane 1 — `oqs-provider`: algorithm space = NIST standards + experimental / future candidates (HQC, Falcon, SLH-DSA, Classic McEliece).
  - Lane 2 — `OpenSSL 3.5 native PQC`: FIPS lane (ML-KEM, ML-DSA only).
  - Applications swap lanes via the `PQC_PROVIDER={oqs|native}` environment variable.
- **Host WireGuard**: AlmaLinux 9.7 mainline kernel supports WireGuard out of the box (`dnf install wireguard-tools` + `modprobe wireguard`); the ELRepo `kmod-wireguard` package is not required.
- **CI-grade paper-value comparison**: run `tools/compare_to_paper.py` in CI to catch regressions against the paper's numbers.

### 15.3 Recommended Future Research

See [`docs/roadmap.md`](docs/roadmap.md). Each item below is recommended as an independent PoC branch.

| ID | Topic | Summary | Reference |
|---|---|---|---|
| **A** | **Shor's-algorithm attack simulator** | Use **CUDA-Q + cuQuantum** (RTX 6000 PRO Blackwell 96 GB) tensor networks and **ZX-calculus T-count optimisation with `pyzx`** to derive realistic resource estimates against RSA-2048 / ECDSA-P256, and plot the classical-vs-quantum scaling curves in the WebUI. | NIST IR 8413 |
| **B** | **HNDL (Harvest Now, Decrypt Later) simulator** | Stockpile WireGuard ciphertext over `wan-net` with `tcpdump` and visualise the "decrypt-in-2030" timeline; add an `ARNIKA_INTERVAL` vs HNDL-risk trade-off to the WebUI Benchmarks page. Useful as an executive ROI artefact. | NIST IR 8547, CISA Quantum-Readiness |
| **C** | **QLSTM-IDS for QKD attack detection** | Generate eight labelled scenarios (normal / intercept-resend / PNS / Trojan-horse / RNG-bias / wavelength-trojan / detector-blinding / combined) from this PoC's BB84 simulator and detect them with a QLSTM (PennyLane) + classical RandomForest ensemble. Target F1 = 93.9 %. | Wiley IET Quantum Comm. 2026 |
| **D** | **Full NIST PQC algorithm sweep** | Use `services/pqc-benchmark/` to benchmark every NIST standard offered by liboqs / oqs-provider (ML-KEM-512/768/1024, ML-DSA-44/65/87, SLH-DSA variants, Falcon), including hybrid TLS 1.3 cipher suites such as `X25519MLKEM768` per the IETF draft. | NIST FIPS 203/204/205 |
| **E** | **Sweep of NIST-recommended controls** | Apply NIST SP 800-208 (stateful hash-based signatures, LMS/XMSS) to OTA update signing and produce a six-function NIST CSF 2.0 mapping in `docs/compliance.md`. | SP 800-208, CSF 2.0 |
| **F** | **QuLore adaptive-security implementation** | Implement the QuLore 4-level security model (L1-L4 in `references/QuLore_*.pdf`) with a central controller in `services/qusec/` and colour-code WebUI Topology edges by the active level. | Sanz et al. (UPV) |
| **G** | **QRNG + AI quality assessment** | Replace the BB84 simulator's classical RNG with a QRNG model output and integrate the CNN-based quality-assessment framework from MDPI Electronics 2026. | MDPI Electronics 2026 |
| **H** | **Quantum Federated Learning + FHE** | Distribute FHE parameters securely using QKD-exchanged keys (`elucidator8918/QFL-MLNCP-NeurIPS`). | NeurIPS 2024 |

Suggested priority: **D → C → A → B → E → F / G / H**.

### 15.4 Commercial deployment considerations

See the private `MONETIZATION.md` (not committed) for personal-monetisation
workflows and the 2026-06 industry-trend snapshot.

---

## Contributing

PRs are welcome. Please open an issue to discuss larger changes before
submitting. Every change must pass `make smoke && pytest tests/`.

## Contact / Acknowledgements

- arnika-vq: CANCOM Converged Services GmbH (EU EUROQCI/QCI-CAT program)
- liboqs / oqs-provider: Open Quantum Safe project
- Rosenpass: Rosenpass project contributors
