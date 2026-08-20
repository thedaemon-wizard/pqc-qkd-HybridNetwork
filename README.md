# PQC-QKD Hybrid Security Layer — Research PoC

[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Research%20PoC-orange.svg)](#12-limitations)

> Research PoC that fuses Quantum Key Distribution (QKD) and Post-Quantum
> Cryptography (PQC) into a single **HKDF-SHA3-256**-derived PSK and rotates
> the WireGuard VPN on a configurable interval (30 s for demos; the paper
> uses 120 s). A pluggable BB84 physical simulator -- seven selectable
> backends, QuTiP among them -- is
> wrapped behind the ETSI GS QKD 014 REST API and wired into
> [arnika](https://github.com/arnika-project/arnika) (Go, reused unchanged) and
> [Rosenpass](https://github.com/rosenpass/rosenpass) (Rust) for an end-to-end path that
> mirrors a production deployment.

Reference papers:
- [PQC-Enhanced QKD Networks: A Layered Approach](https://arxiv.org/abs/2604.05599)
  (Spooren et al., CC BY 4.0 — included under [`references/`](references/))
- [QuLore: An Adaptive Security Framework to Extend Quantum-Safe Communications to Real-World Networks](https://arxiv.org/abs/2511.22416)
  (Sanz et al., CC BY-NC-ND — cited only, not redistributed)

Design documents:
- [`docs/keyrate.md`](docs/keyrate.md) — the decoy-state BB84 key-rate model,
  derived, with the golden vector CI asserts against
- [`docs/vici-ppk.md`](docs/vici-ppk.md) — how the QKD key reaches strongSwan
  (RFC 8784 PPK + RFC 9370 hybrid KE), and why a plain IKEv2 PSK would not work
- [`docs/references.md`](docs/references.md) — every citation, with identifiers
  and licences
- [`VERIFICATION_CHECKLIST.md`](VERIFICATION_CHECKLIST.md) — what must be
  checked before a release

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
11.5 [Implementation phases](#115-implementation-phases)
12. [Limitations](#12-limitations)
13. [References](#13-references)
14. [License](#14-license)
15. [Recommendations & future research](#15-recommendations--future-research)

---

## 1. Introduction

The goal of this PoC is to reproduce the three-layer model from
*"PQC-Enhanced QKD Networks: A Layered Approach"* (Spooren et al.) inside a
**research environment that has no physical QKD hardware**.

| Layer | Role | Implementation |
|---|---|---|
| End-to-End (PQC) | Post-quantum key exchange between nodes | Rosenpass (ML-KEM-768) |
| Transport | Fetches QKD/PQC keys, fuses them via HKDF and injects the derived key | **arnika (Go, upstream unchanged; this project adds a strongSwan VICI key-writer adapter)** |
| Hop (WireGuard) | Real encryption with ChaCha20-Poly1305 + Noise + PSK | WireGuard kernel module |

The QKD layer is supplied by a **pluggable BB84 physical simulator** wrapped
behind the ETSI GS QKD 014 REST API; seven backends are selectable at runtime
(QuTiP, SimQN, SeQUeNCe, CV-QKD, TNO, composite and a QKDNetSim proxy). The
key-rate model they share is derived in [`docs/keyrate.md`](docs/keyrate.md). Eve's intercept-resend attack can be
toggled from the WebUI, and the resulting QBER jump and arnika's fall-back
behaviour are visible in real time.

---

## 2. Architecture

```
                     ┌────────────────────────────────────┐
                     │   WebUI (React + Plotly + D3)     │
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
        │  - rosenpass       │ PSK = HKDF(│  - rosenpass     │
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
├── references/                        # Reference papers (only where the licence permits)
├── submodules/                        # Git submodules (unmodified)
│   ├── arnika/                     # Go binary baked into node image
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
│   ├── webui-frontend/                # React/Vite/Plotly/D3 dashboard (13 pages incl.
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

To run the full real-WireGuard stack on a single public host (any KVM
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
See [`deploy/README.md`](deploy/README.md). Per-dependency licence terms are
in [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).

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
| `ARNIKA_MODE` | `QkdAndPqcRequired` | One of 4 modes: `QkdAndPqcRequired` / `AtLeastQkdRequired` / `AtLeastPqcRequired` / `EitherQkdOrPqcRequired` | `submodules/arnika/config/config.go:34` |
| `ARNIKA_INTERVAL` | `30s` | PSK rotation period (paper uses 120s) | `submodules/arnika/config/config.go` |
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
2. **Quantum-Secure E2E** (`/e2e`) — **client-side** 4-phase orchestration (Quantum Plane → QKD Key IDs → PQC Handshake → Data Exchange) with **real in-browser HKDF-SHA3-256 + ChaCha20-Poly1305** (`@noble`), over the arnika architecture diagram, Run/Pause/Resume/Reset/Step + Mode A/B/C
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

> Note: The WebUI Backend mounts `/var/run/docker.sock:ro` to query container state.
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

| Paper claim | Status |
|---|---|
| KMS-free layered overlay | Implemented |
| ETSI GS QKD 014 client/server contract | Implemented; contract tested in CI against two live KMEs |
| arnika as key injector | Implemented, upstream unchanged. This project adds a strongSwan VICI key-writer adapter alongside the WireGuard one. |
| Rosenpass PQC layer | Implemented with the real binary. There is **no** fallback: if the keypair or the peer public key is missing, the sidecar exits non-zero rather than substituting local randomness. |
| Multi-hop trusted-node chain | Implemented (`docker-compose.multihop.yml`) |
| Adaptive security levels (QuLore L1-L4) | Not implemented. See [`docs/roadmap.md`](docs/roadmap.md). |

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
- **WireGuard**: in-tree kernel module (AlmaLinux 9.7 mainline); only
  `wireguard-tools` userspace is installed. ELRepo's `kmod-wireguard` is not
  required. If `modprobe wireguard` fails on your host, see the userspace
  `boringtun` fallback in section 5.3.

Host-side Python venv (for running `pytest` and Manim outside Docker):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install httpx pytest qutip numpy manim matplotlib
```

---

## 11.5 Implementation phases

The phase-by-phase implementation record - what each phase added, which files
carry it, and how it was verified - lives in
[`docs/phases.md`](docs/phases.md). It covers the multi-backend QKD simulator,
the Quantum-Secure VPN lanes, the live E2E page, the shared UI and export
layer, and the Paper Data Exchange page.

## 12. Limitations

When citing or releasing the PoC, **please always disclose the limitations below.**

### 12.1 QKD physical simulation
- **Reinforced from seven complementary backends**:
  - `qutip` — lightweight, educational, photon-level
  - `simqn` — Cascade error correction + Toeplitz privacy amplification + fibre attenuation (`submodules/SimQN`, 2026-05-25 active)
  - `sequence` — the SeQUeNCe physical-layer model (`submodules/SeQUeNCe`, 2026-05-12 active, Argonne National Lab)
  - `cvqkd` — Strawberry Fields GG02 continuous-variable QKD (`submodules/strawberryfields`)
  - `composite_sim_to_net` — SimQN physical layer + qkdnetsim NS-3 v3.46 network layer
  - `tno_keyrate` — TNO-Quantum's independently developed decoy-state BB84/BBM92
    key-rate engine (`submodules/tno-qkd-key-rate`, Apache-2.0), used to
    cross-check this project's own rate model against a third-party one
  - `qkdnetsim_proxy` — fetches keys from the NS-3 reference KME's own C++
    ETSI GS QKD 014 implementation, for cross-validating the REST contract
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

Every paper, standard and dependency, with a stable identifier and - for
anything redistributed here - its licence, is in
[`docs/references.md`](docs/references.md).

Primary sources for the design:

- Spooren et al., *PQC-Enhanced QKD Networks: A Layered Approach*,
  [arXiv:2604.05599](https://arxiv.org/abs/2604.05599) - the layered model this
  PoC reproduces
- ETSI GS QKD 014 V1.1.1 - the key-delivery API
- RFC 8784 and RFC 9370 - how the QKD key reaches IPsec, explained in
  [`docs/vici-ppk.md`](docs/vici-ppk.md)
- Ma et al., Phys. Rev. A **72**, 012326 (2005) - the key-rate model, derived
  in [`docs/keyrate.md`](docs/keyrate.md)

## 14. License

Apache-2.0. Compatible with arnika (Apache-2.0), liboqs (MIT), and Rosenpass (MIT/Apache-2.0).

NOTICE: This software re-distributes cryptographic implementations. Verify your jurisdiction's
export-control regulations (e.g. US ECCN 5D002) before public deployment.

---

## 15. Recommendations & future research

Release gates are in
[`VERIFICATION_CHECKLIST.md`](VERIFICATION_CHECKLIST.md); future work, known
gaps and their consequences are in [`docs/roadmap.md`](docs/roadmap.md).

## Contributing

PRs are welcome. Please open an issue to discuss larger changes before
submitting. Every change must pass `make smoke && pytest tests/`.

## Contact / Acknowledgements

- arnika: CANCOM Converged Services GmbH (EU EUROQCI/QCI-CAT program)
- liboqs / oqs-provider: Open Quantum Safe project
- Rosenpass: Rosenpass project contributors
