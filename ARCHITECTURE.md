# Architecture

## -2. Phase 10 — Quantum-Secure E2E live simulation

A single WebUI page (`/e2e`) drives an actual background simulation through the
4-phase Data Exchange depicted in the reference architecture image:

```
   ┌─────────────────────────────────────────────────────────────────┐
   │ services/webui-frontend/src/pages/QuantumSecureE2E.tsx          │
   │  SVG arch (Site A / Site B, ARNIKA/ROSENPASS/WIREGUARD, KMS)    │
   │  Mode A/B/C buttons + Run/Pause/Resume/Reset/Step + 4 KPI cards │
   └────────────────────────────┬────────────────────────────────────┘
                                │ REST + WS
   ┌────────────────────────────▼────────────────────────────────────┐
   │ services/webui-backend/app/e2e_orchestrator.py                  │
   │  state: idle → running ↔ paused; reset → idle                   │
   │  cycle: phase1 → phase2 → phase3 → phase4 → phase1 …            │
   │  pub/sub WS at ~4 Hz                                             │
   └─────┬──────────────┬───────────────┬──────────────────┬──────────┘
         │              │               │                  │
   Phase 1            Phase 2         Phase 3            Phase 4
   Poll KME           ETSI 014        HKDF-SHA3-256      ChaCha20-Poly1305
   /status            enc/dec_keys    (qkd ‖ pqc)        × 64 packets
   (bb84-kme-a/b)     (arnika sim)    (Rosenpass sim)    (WireGuard sim)
```

REST surface:
- `GET /api/e2e/state`
- `POST /api/e2e/{start,pause,resume,reset,step,mode}`
- `WS /ws/e2e` (~4 Hz live snapshots)

Mode mapping:
- `A` → `mode_label = "QKD-only"` (skips PQC in Phase 3)
- `B` → `mode_label = "PQC-only"` (skips QKD in Phase 2)
- `C` → `mode_label = "Hybrid (QKD ‖ PQC)"` (default — both phases active)

Detailed image-to-code mapping: see `docs/IMAGE1_VPN_SCOPE.md`.

## -1. Phase 9 — Real Quantum-Secure VPN (RFC 9370 + crypto agility)

```
                ┌─────────────────────────────────────────────────────────┐
                │ WebUI 10 pages (Phase 9-WebUI)                          │
                │  Overview / BB84 / KeyFlow / Topology / Benchmarks      │
                │  Console / PhysicsParams / PQCValidator / HIL / VPN     │
                └──────────────┬──────────────────────────────────────────┘
                               │
                ┌──────────────▼──────────────────────────────────────────┐
                │  webui-backend (FastAPI orchestrator)                   │
                │   /api/vpn/protocols      — both lanes' live status     │
                │   /api/sim/optimize       — Bayesian Opt trigger        │
                │   /api/pqc/{algorithms,roundtrip}                       │
                └──┬───────────────────────────────────────────────┬──────┘
                   │                                               │
        ┌──────────▼──────────┐                       ┌────────────▼─────────┐
        │ alice + bob (WG)    │                       │ alice-ipsec +        │
        │  arnika → wgctrl    │                       │ bob-ipsec (strongSwan)│
        │  Curve25519+Noise   │                       │ RFC 9370 hybrid IKE  │
        │  + PSK rotation     │                       │ ECP-256 + ML-KEM-768 │
        │  every 30 s         │                       │ + vici PSK injection │
        └──────────┬──────────┘                       └─────────┬────────────┘
                   │                                            │
                   └────────────── arnika HKDF(QKD‖PQC) ────────┘
                                              │
                ┌─────────────────────────────▼─────────────────────────────┐
                │ Phase 8: 6 QKD backends + paper supplementary             │
                │ ┌──────┬─────┬────────┬───────┬──────────┬──────────┐    │
                │ │qutip │simqn│sequence│cvqkd  │qkdnetsim │composite │    │
                │ └──────┴─────┴────────┴───────┴──────────┴──────────┘    │
                │ openQKDsecurity (offline SKR) + PQClean (NIST reference) │
                │ aparcar/qkd-pqc-paper-supplementary (Phase 9-B baseline) │
                └───────────────────────────────────────────────────────────┘
```

PQC TLS lanes (Phase 9-C, crypto agility per RFC 7696 + NIST SP 800-131A Rev.3):
- `Dockerfile.oqs-provider` — broadest algorithm space (ML-KEM, ML-DSA, SLH-DSA,
  Falcon, HQC, Classic McEliece) for research and crypto agility
- `Dockerfile.openssl35-native` — FIPS-stable native ML-KEM / ML-DSA (OpenSSL 3.5+)
- Application chooses via `PQC_PROVIDER={oqs|native}` env

## 0. Phase 8 — 5-backend pluggable QKD pipeline

```
                ┌─────────────────────────────────────────────────────────┐
                │ WebUI (9 pages)  Overview / BB84 / KeyFlow / Topology   │
                │   Benchmarks / Console / PhysicsParams / PQCValidator   │
                │   Hardware-In-Loop                                       │
                └──────────────┬──────────────────────────────────────────┘
                               │  REST + WebSocket
                ┌──────────────▼──────────────────────────────────────────┐
                │  webui-backend  (FastAPI)                               │
                │   /api/sim/params, /api/sim/backend, /api/sim/optimize  │
                │   /api/pqc/algorithms, /api/pqc/roundtrip               │
                └──┬─────────────────────────────────────────────┬────────┘
                   │                                             │
                ┌──▼──────────────────────────────┐         ┌────▼────────┐
                │  bb84-kme (per SAE)             │         │ pqc-validator│
                │                                  │         │ liboqs vs    │
                │  KeyProducer ABC                 │         │ PQClean      │
                │  ┌──────┬─────┬────────┬───────┐│         └──────────────┘
                │  │qutip │simqn│sequence│cvqkd  ││
                │  └──────┴─────┴────────┴───────┘│
                │  + composite_sim_to_net          │
                │  + qkdnetsim_proxy               │
                │                                  │
                │  config/qkd_params.yaml          │
                │   (hot-reload via watchdog)      │
                │                                  │
                │  optimizer.py                    │
                │   scikit-optimize gp_minimize    │
                │   ↔ closed-form Lo-Ma 2005       │
                │   ↔ arXiv:2511.21253 finite-key  │
                └────────┬───────────────────────┬─┘
                         │                       │
                         │ ETSI 014              │ ETSI 014 (cross-validate)
                         ▼                       ▼
                ┌────────────────┐      ┌────────────────────┐
                │ arnika (Go)    │      │ qkdnetsim-kme      │
                │ HKDF-SHA3-256  │      │ NS-3 v3.46 + ETSI  │
                │ → WG PSK       │      │ 014/004 reference  │
                └────────────────┘      └────────────────────┘
```

Backends (all implement `services/bb84-kme/app/backends/base.py::KeyProducer`):
- `qutip_backend.py` — lightweight QuTiP photon physics (original PoC core)
- `simqn_backend.py` — SimQN BB84 + QubitLossChannel + our Cascade+TPA
- `sequence_backend.py` — SeQUeNCe physical layer (depolarising + measurement noise)
- `cvqkd_backend.py` — Strawberry Fields homodyne / GG02 protocol
- `qkdnetsim_proxy.py` — pulls keys from the NS-3 reference KME (ETSI 014 cross-check)
- `composite_sim_to_net.py` — SimQN computes per-link SKR → injected into qkdnetsim

Parameter pipeline:
- `config_loader.py` watches YAML and pushes `BackendConfig` on change
- `_skr.py` holds the closed-form Lo-Ma 2005 / arXiv:2511.21253 SKR helper
- `optimizer.py` calls `skopt.gp_minimize` on the closed-form objective
  to maximise the secret key rate per pulse over (μ, ν₁, ν₂, p_z)

Tests (host venv):
- `test_no_hardcoded_params.py` — AST guard against magic numbers in backends
- `test_backend_cross_qber.py` — every backend's QBER stays under threshold
- `test_bb84_simulator.py` — QuTiP simulator sanity (Eve/no-Eve QBER bands)

## 1. Layered model (matches `references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf`)

```
+---------------------------------------------------------------------+
|  Layer 3 — End-to-End PQC                                           |
|    Rosenpass sidecar in each node                                   |
|    Output: /var/lib/rosenpass/pqc.psk  (32B, refreshed periodically) |
+---------------------------------------------------------------------+
|  Layer 2 — Transport orchestration                                  |
|    arnika (Go, unmodified from submodules/arnika-vq/)               |
|    - ETSI 014 client (HTTP/mTLS)                                    |
|    - reads pqc.psk file                                             |
|    - HKDF-SHA3-256(qkd || pqc) -> 32B PSK                           |
|    - wgctrl netlink call -> writes PSK to wg0 peer entry            |
+---------------------------------------------------------------------+
|  Layer 1 — Hop encryption                                           |
|    WireGuard wg0 between alice and bob (or alice-charlie-bob)       |
|    ChaCha20-Poly1305 + Noise + PSK                                  |
|    PSK rotated by arnika every `ARNIKA_INTERVAL` (30s default)      |
+---------------------------------------------------------------------+
```

## 2. Container topology

| Container | Image source | Networks | Capabilities |
|---|---|---|---|
| `bb84-kme-a` | `services/bb84-kme/` | qkd-net, mgmt-net | none |
| `bb84-kme-b` | `services/bb84-kme/` | qkd-net, mgmt-net | none |
| `alice` | `nodes/alice/Dockerfile` | qkd-net, wan-net | NET_ADMIN, SYS_MODULE |
| `bob` | `nodes/alice/Dockerfile` (same image) | qkd-net, wan-net | NET_ADMIN, SYS_MODULE |
| `charlie` | same | wan-net | NET_ADMIN, SYS_MODULE |
| `webui-backend` | `services/webui-backend/` | mgmt-net, qkd-net | docker.sock RO |
| `webui-frontend` | `services/webui-frontend/` | mgmt-net | none |

Networks:
- `qkd-net` — `internal: true`. KME ↔ arnika and KME-KME sync. No host bridge.
- `wan-net` — simulated public Internet. WireGuard endpoints.
- `mgmt-net` — WebUI plane. Exposes 5173 and 8000 to host.

## 3. Data flow (a single PSK rotation)

```
T+0   bb84-kme-a runs a BB84 round (QuTiP photon simulation)
T+0.1 reconciliation produces a 256-bit secret key, base64-encoded
T+0.1 KME-a stores key by UUID and POSTs /internal/sync to KME-b
T+0.2 arnika@alice polls /api/v1/keys/ALICE/enc_keys?number=1&size=256
T+0.2 arnika receives {keys: [{key_ID, key}]}, opens TCP to bob:9999, sends key_ID
T+0.3 arnika@bob receives key_ID, calls /api/v1/keys/BOB/dec_keys?key_ID=...
T+0.3 Both sides now hold the SAME 256-bit QKD key
T+0.3 Both read /var/lib/rosenpass/pqc.psk (independently produced by Rosenpass)
T+0.3 Both compute HKDF-SHA3-256(qkd || pqc) -> 32B PSK
T+0.3 Both `wg set wg0 peer <pub> preshared-key <psk>` via netlink
T+0.4 WireGuard re-handshakes within ~5s; tunnel keys derive from new PSK
```

## 4. Critical reused arnika code paths

These are the points we depend on; changing them in upstream arnika would require
contract updates here:

| Symbol | File:Lines | Why we depend |
|---|---|---|
| `setPSK()` | `submodules/arnika-vq/main.go:140-196` | Drives the rotation; logs we grep in smoke tests |
| `KMSHandler.GetNewKey()` | `submodules/arnika-vq/kms/kms.go:126` | Defines `enc_keys?number=N&size=B` URL |
| `KMSHandler.GetKeyByID()` | `submodules/arnika-vq/kms/kms.go:134` | Defines `dec_keys?key_ID=...` URL |
| `type Key struct` | `submodules/arnika-vq/kms/kms.go:69-76` | JSON field names `key_ID` + `key` — exactly what our Python KME emits |
| `DeriveKey()` | `submodules/arnika-vq/kdf/kdf.go:12-27` | HKDF-SHA3-256 contract visualised in the Sankey/Manim |
| Operational modes | `submodules/arnika-vq/config/config.go:39-45` | 4 modes drive WebUI ControlPanel choices |

## 5. Why this matches the paper

| Paper claim | Implementation correspondence |
|---|---|
| WireGuard PSK rotated periodically per hop | `ARNIKA_INTERVAL` (default 30s in PoC, 120s in paper) |
| ETSI GS QKD 014 between KME and Arnika | `services/bb84-kme/app/etsi014.py` mounts `/api/v1/keys/{SAE}/...` matching `kms.go:126-134` |
| PQC E2E via Rosenpass | `nodes/alice/rosenpass-sidecar.sh` produces pqc.psk; arnika fuses it via HKDF (`kdf/kdf.go`) |
| Layered composability (compromise of one layer ≠ catastrophe) | Three Docker networks isolate planes; mode `QkdAndPqcRequired` enforces both layers |
| Setup time scales with slowest QKD hop, not cumulative | `benchmarks/handshake_timer.py` measures this |
| Forward secrecy at both QKD and PQC layers | Independent rotation: BB84 producer triggers QKD refresh, Rosenpass sidecar triggers PQC refresh |
