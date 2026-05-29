# PQC-QKD Hybrid Security Layer — Research PoC

[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Research%20PoC-orange.svg)](#12-limitations)

> 量子鍵配送 (QKD) と耐量子暗号 (PQC) を **HKDF-SHA3-256** で融合し、
> WireGuard VPN を 30秒毎に再鍵化する研究用 PoC。
> BB84 物理シミュレーション (QuTiP) を ETSI GS QKD 014 REST API でラップし、
> [arnika-vq](submodules/arnika-vq) (Go, 無変更で再利用) と
> [Rosenpass](submodules/rosenpass) (Rust) で実運用に近い経路を完結させる。

参考論文:
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
12. [Limitations](#12-limitations)
13. [References](#13-references)
14. [License](#14-license)
15. [Recommendations & Future Research](#15-recommendations--future-research)

---

## 1. Introduction

本 PoC は「PQC-Enhanced QKD Networks: A Layered Approach」(Spooren et al.) の 3 層モデルを
**実機 QKD 装置が無い研究環境**で再現することを目的とします。

| 層 | 役割 | 実装 |
|---|---|---|
| End-to-End (PQC) | ノード間で Post-Quantum 鍵交換 | Rosenpass (ML-KEM-768) |
| Transport | QKD/PQC 鍵を取得し HKDF で融合し WG PSK に注入 | **arnika-vq (Go, 無変更で再利用)** |
| Hop (WireGuard) | ChaCha20-Poly1305 + Noise + PSK で実暗号化 | WireGuard kernel module |

QKD 層は **QuTiP による BB84 物理シミュレータ**を ETSI GS QKD 014 REST API でラップして提供します。
Eve による intercept-resend 攻撃を WebUI から ON/OFF でき、QBER の変化と arnika のフォールバックが
リアルタイムに観測できます。

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

詳細は [ARCHITECTURE.md](ARCHITECTURE.md) を参照。

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
│   └── PQClean/                       # (Phase 8) NIST PQC reference implementations
├── config/                            # (Phase 8) Central tunables
│   ├── qkd_params.yaml                # Single source of truth (hot-reloaded)
│   └── qkd_keyrate_table.json         # Pre-computed SKR table (arXiv:2511.21253)
├── services/
│   ├── bb84-kme/                      # Python: 5-backend BB84/CV-QKD + ETSI-014 REST
│   │   └── app/backends/              # qutip / simqn / sequence / cvqkd / composite / qkdnetsim_proxy
│   ├── webui-backend/                 # FastAPI orchestrator
│   ├── webui-frontend/                # React/Vite/Plotly/D3 dashboard (9 pages)
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

Open <http://localhost:5173>. Six pages are available:

1. **Overview** — Layered architecture SVG + live container status badges
2. **BB84 Live** — Real-time QBER chart, key-pool size, sample photon frames table, **Eve toggle** + intercept probability slider, "Force rotate" button
3. **Key Flow** — Plotly Sankey of QKD raw → sifted → reconciled + Rosenpass → HKDF → WireGuard PSK
4. **Topology** — D3-force graph of nodes (alice/bob/Charlie) and KMEs
5. **Benchmarks** — Round latency, QBER history, KPI cards (accepted/aborted/avg ms)
6. **Console** — Live log tail of any container (alice / bob / KMEs)

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

Phase 8 addresses the §12 "QKD は物理シミュレーション" limitation by adding 4 additional
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
Set via `SIMULATOR_BACKEND` env or `simulator.backend` YAML key, or change live
from the WebUI "Physics Params" page:

| Backend | Source | Purpose |
|---|---|---|
| `qutip` | built-in | Lightweight teaching demo |
| `simqn` | `submodules/SimQN` | Realistic Cascade + Toeplitz PA + fiber loss |
| `sequence` | `submodules/SeQUeNCe` | Photonic noise (depolarizing + measurement error) |
| `cvqkd` | `submodules/strawberryfields` | GG02 continuous-variable QKD |
| `qkdnetsim_proxy` | `services/qkdnetsim-kme` | ETSI 014 reference (NS-3 v3.46) |
| `composite_sim_to_net` | SimQN + qkdnetsim | Physical layer feeds network layer |

### Parameter optimisation
```bash
source .venv/bin/activate
python -c "
from app import config_loader; config_loader.reload()
from app.optimizer import optimize_from_yaml
print(optimize_from_yaml())
"
# or via WebUI Physics Params page → "Run Bayesian Optimization"
```

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
| 2 | `/bb84` | BB84 Live (QBER chart, Eve toggle, photon frames) |
| 3 | `/keyflow` | Hybrid Key Derivation Sankey |
| 4 | `/topology` | D3-force network graph |
| 5 | `/benchmarks` | KPI cards + latency/QBER charts |
| 6 | `/console` | Container log tail |
| 7 | `/physics` | PhysicsParams (live YAML + Bayesian Opt) |
| 8 | `/pqc` | PQC Validator (liboqs vs PQClean vs OpenSSL 3.5) |
| 9 | `/hil` | Hardware-In-The-Loop bridge instructions |
| 10 | `/vpn` | **VPN Protocols (WireGuard ⟷ strongSwan, Phase 9-A)** |

Verified via Claude Preview MCP (Vite dev server on :5174):
- 10 React Router paths all render correct `<h2>` headings
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

## 12. Limitations

本 PoC を引用・公開する際、以下の制限を**必ず併記してください**。

### 12.1 QKD 物理シミュレーション
- **5 つの異種 backend で多角的に補強済**:
  - `qutip` — 教育用 (lightweight, 軽量 photon-level)
  - `simqn` — Cascade error correction + Toeplitz PA + fiber attenuation (`submodules/SimQN`, 2026-05-25 active)
  - `sequence` — SeQUeNCe 物理モデル (`submodules/SeQUeNCe`, 2026-05-12 active, Argonne National Lab)
  - `cvqkd` — Strawberry Fields GG02 連続変数 QKD (`submodules/strawberryfields`)
  - `composite_sim_to_net` — SimQN 物理 + qkdnetsim ネットワーク (NS-3 v3.46)
- パラメータは **科学的根拠あり** (`config/qkd_keyrate_table.json` を openQKDsecurity の Winick SDP + arXiv:2511.21253 closed-form formula で事前計算済み)
- それでも **実機の装置温度ドリフト・帯域フィルタ・波長依存量子効率** などデバイス固有非理想性は未モデル化

### 12.2 ハードウェア接続
- **ETSI GS QKD 014 標準 I/F** に準拠するため、商用装置 (ID Quantique Cerberis, Toshiba MUSE, Thinkquantum TQ-KME 等) は **`KMS_URL` 1 行変更で透過接続可能** (HIL モード — WebUI "Hardware-In-Loop" ページ参照)
- 装置固有ドライバ (USB/serial) や HSM ベース API 統合は本 PoC 範囲外
- **Xanadu cloud (CV-QKD 実機) は 2026-01 に decommissioning**。CV-QKD ローカルシミュレーションは継続利用可

### 12.3 残存制限事項
- **シングルホスト PoC**。全コンテナが同一物理ホスト上で稼働するため、実 QKD ネットワークの遅延・損失・物理的隔離は再現していません。
- **KME 間鍵同期は HTTP**。本来は量子チャネル + 認証付き古典チャネルで対称鍵が成立しますが、本 PoC では `bb84-kme-a` ↔ `bb84-kme-b` の `POST /internal/sync` で同期します (`qkd-net` を `internal: true` で隔離)。
- **PQC は ML-KEM-768 中心** だが **liboqs vs PQClean cross-validator** (`services/pqc-validator/`) で NIST 準拠を独立検証可能。WebUI "PQC Validator" ページから他アルゴリズムも試行可能。
- **HKDF-SHA3-256 は arnika 既定**。他流派 (Concatenate-then-HMAC, XOR, Cascade KDF 等) との比較はスコープ外。
- **VPN プロトコル 2 系統対応** (Phase 9-A):
  - WireGuard PSK モード (デフォルト): Noise Protocol 自体は古典暗号 (Curve25519/ChaCha20-Poly1305) のまま、arnika が PSK ローテで加算的保護を提供
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (推奨実機): ML-KEM-768 を IKE_SA_INIT の KE1 payload で直接交換、古典 ECDH と組み合わせ forward secrecy 強化
- **FIPS / Common Criteria 認証なし**。本実装は研究 PoC であり、本番運用は禁止です。
- **法規制・輸出管理**。暗号ソフトウェアの再配布は ECCN 5D002 等の対象になり得るため、利用時は所在国の規制を確認してください。

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

### 15.1 公開前チェックリスト (必須)

- [ ] `.gitignore` で `pki/*.pem`, `*.psk`, `.env`, `node_modules/`, build artefacts が除外されている
- [ ] `pki/` 配下に生成された秘密鍵が `git status` に出てこない
- [ ] `make smoke` がパスする
- [ ] `pytest tests/` が全てパスする
- [ ] `submodules/` の commit hash が pin 済み
- [ ] `references/` の PDF/docx が公開許諾範囲内
- [ ] [Apache-2.0 NOTICE](LICENSE) と各依存 OSS のライセンス文を同梱
- [ ] (推奨) `gitleaks detect` を CI に組み込む

### 15.2 運用上の推奨事項

- **可観測性**: Prometheus + Grafana を追加 (`docker-compose.observability.yml`)、`qkd_qber`, `arnika_psk_rotation_total`, `wg_handshake_age_seconds` を可視化。
- **再現性**: `Dockerfile` の `ARG ARNIKA_REF` / `ARG ROSENPASS_REF` を git tag で固定し、SBOM (CycloneDX) を出力。
- **デモ運用**: `ARNIKA_INTERVAL=30s` は demo 向け。本番想定なら 120s (paper 値) に戻す。
- **mTLS**: `pki/gen-certs.sh` で証明書を発行後、`ETSI_MTLS_ENABLED=true` で有効化 (Phase 7)。
- **VPN 2 系統運用** (Phase 9-A): WireGuard と strongSwan IPsec を等価に保ち、運用要件 (帯域・MTU・NAT-T) に応じて切替可能にする。
- **Cryptographic Agility 設計指針** (Phase 9-C, RFC 7696 / NIST SP 800-131A Rev.3 準拠):
  - 第 1 層 `oqs-provider` — algorithm space = NIST 標準 + 実験/将来候補 (HQC, Falcon, SLH-DSA, Classic McEliece)
  - 第 2 層 `OpenSSL 3.5 native PQC` — FIPS 経路 (ML-KEM, ML-DSA のみ)
  - アプリケーションは環境変数 `PQC_PROVIDER={oqs|native}` で動的切替
- **ホスト WireGuard**: AlmaLinux 9.7 標準カーネル + `dnf install wireguard-tools` + `modprobe wireguard` で導入可能。ELRepo `kmod-wireguard` は不要。
- **論文値との直接比較を `tools/compare_to_paper.py` で CI 化**、regression を検知。

### 15.3 将来の研究拡張 (Recommended Future Research)

詳細は [`docs/roadmap.md`](docs/roadmap.md)。各項目は独立した PoC ブランチとして段階的に追加することを推奨します。

| ID | Topic | 概要 | NIST/学術参照 |
|---|---|---|---|
| **A** | **Shor's Algorithm 攻撃シミュレーション** | **CUDA-Q + cuQuantum**(RTX 6000 PRO Blackwell 96GB) でテンソルネットワーク、**`pyzx` で ZX-calculus** T-count 最適化により、Shor の RSA-2048/ECDSA-P256 への現実的なリソース見積もりを行う。古典 vs 量子スケーリング曲線を WebUI で可視化。 | NIST IR 8413 |
| **B** | **HNDL (Harvest Now, Decrypt Later) シミュレーション** | `wan-net` 上の WireGuard 暗号文を `tcpdump` で大量保管し、「2030年に量子計算機で復号」のタイムラインを可視化。`ARNIKA_INTERVAL` と HNDL リスク窓のトレードオフを WebUI に追加。経営層・顧客向け ROI 説明資料として有効。 | NIST IR 8547、CISA Quantum-Readiness |
| **C** | **QLSTM-IDS (QKD 攻撃検知)** | 本 PoC の BB84 シミュレータから 8 種類のラベル付きデータ (normal / intercept-resend / PNS / Trojan-horse / RNG-bias / wavelength-trojan / detector-blinding / combined) を自動生成し、QLSTM (PennyLane) + 古典 RandomForest アンサンブルで検知。WebUI に "IDS Live" ページ追加。目標 F1=93.9%。 | Wiley IET Quantum Comm. 2026 |
| **D** | **NIST PQC アルゴリズム網羅検証** | liboqs/oqs-provider が提供する全 NIST 標準 (ML-KEM-512/768/1024, ML-DSA-44/65/87, SLH-DSA 各パラ, Falcon) を `services/pqc-benchmark/` で網羅ベンチ。`X25519MLKEM768` 等のハイブリッド TLS 1.3 cipher suite (IETF Draft) を含む。 | NIST FIPS 203/204/205 |
| **E** | **NIST 推奨セキュリティ対策の網羅検証** | NIST SP 800-208 (Stateful Hash-Based Signatures, LMS/XMSS) を OTA 更新署名へ応用、NIST CSF 2.0 の 6 機能と本 PoC コンポーネントの対応表 (`docs/compliance.md`) を作成。 | SP 800-208、CSF 2.0 |
| **F** | **QuLore 適応セキュリティ実装** | `references/QuLore_*.pdf` の 4 段階セキュリティレベル (L1-L4) を、中央コントローラ `services/qusec/` で動的割当。WebUI Topology のエッジ色で現行レベル表示。 | Sanz et al. (UPV) |
| **G** | **QRNG + AI 品質評価** | BB84 シミュレータの classical RNG を QRNG モデル出力に差し替え、CNN ベース品質評価フレームワーク (MDPI Electronics 2026) を統合。 | MDPI Electronics 2026 |
| **H** | **Quantum Federated Learning + FHE** | QKD で交換した鍵で FHE パラメータを安全配布する分散学習ユースケース (`elucidator8918/QFL-MLNCP-NeurIPS` 参照)。 | NeurIPS 2024 |

優先順位の推奨: **D → C → A → B → E → F/G/H**。

### 15.4 商用展開上の考慮

本 PoC は単独で課金 SaaS にする想定ではなく、以下の組み合わせを想定:
- **教育コンテンツ**: Udemy/YouTube/Zenn 向けの実装解説素材 (Manim アニメ + WebUI スクリーンキャスト + コード読解)
- **企業 PoC / コンサル**: NIST CSF 2.0 (E) や QuLore L4 (F) と組み合わせた段階的 PQC 移行の参照実装
- **R&D**: A (Shor) / C (IDS) / D (PQC 網羅) を組み合わせ、IEEE/Wiley/MDPI 系学会・誌への投稿素材

---

## Contributing

PR welcome. 大きな変更を提案する前に Issue で議論してください。
すべての変更は `make smoke && pytest tests/` をパスする必要があります。

## Contact / Acknowledgements

- arnika-vq: CANCOM Converged Services GmbH (EU EUROQCI/QCI-CAT program)
- liboqs / oqs-provider: Open Quantum Safe project
- Rosenpass: Rosenpass project contributors
