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
- [`docs/threat-model.md`](docs/threat-model.md) — **what this defends against
  and why hybrid**: harvest-now-decrypt-later, Mosca's inequality, the 2026
  CRQC probability estimates, and the CNSA 2.0 parameter gap this repository
  does not close
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
3. [Repository Layout](#3-repository-layout) → [`ARCHITECTURE.md`](ARCHITECTURE.md#6-repository-layout)
4. [Quickstart](#4-quickstart)
5. [Build details](#5-build-details)
6. [Configuration](#6-configuration)
7. [Running the WebUI](#7-running-the-webui) → [`docs/webui-pages.md`](docs/webui-pages.md)
8. [Verification & Tests](#8-verification--tests)
9. [Benchmarks](#9-benchmarks)
10. [Paper Mapping](#10-paper-mapping)
11. [Dev Environment](#11-dev-environment) → [`docs/BUILD.md`](docs/BUILD.md#6-dev-environment)
    - [Implementation phases](#115-implementation-phases)
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
| End-to-End (PQC) | Post-quantum key exchange between nodes | Rosenpass v0.2.3 (Classic McEliece 460896 + Kyber512) |
| Transport | Fetches QKD/PQC keys, fuses them via HKDF and injects the derived key | **arnika (Go, upstream unchanged; this project adds a strongSwan VICI key-writer adapter)** |
| Hop (WireGuard) | Real encryption with ChaCha20-Poly1305 + Noise + PSK | WireGuard kernel module |

The QKD layer is supplied by a **pluggable BB84 physical simulator** wrapped
behind the ETSI GS QKD 014 REST API; seven backends are selectable at runtime
(QuTiP, SimQN, SeQUeNCe, CV-QKD, TNO, composite and a QKDNetSim proxy). The
key-rate model they share is derived in [`docs/keyrate.md`](docs/keyrate.md). Eve's intercept-resend attack can be
toggled from the WebUI, and the resulting QBER jump is visible in real time.
The toggle reconfigures the in-browser simulation engine only -- it does not
reach a KME or arnika, so it does not exercise arnika's fall-back path. (An
earlier version of this sentence claimed it did.)

---

## 2. Architecture

```
                     ┌────────────────────────────────────┐
                     │   WebUI (React + Plotly + D3)      │
                     │   localhost:5173                   │
                     └──────────────┬─────────────────────┘
                                    │ REST
                     ┌──────────────▼─────────────────────┐
                     │  webui-backend (FastAPI)           │
                     │  /api/stack /api/stats /api/verify │
                     └──┬───────────────────────┬─────────┘
                        │                       │
        ┌───────────────▼───┐               ┌───▼──────────────┐
        │  bb84-kme-a       │ /internal/sync│  bb84-kme-b      │
        │  BB84 sim + ETSI  │◄─────────────►│  BB84 sim + ETSI │
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

The annotated directory tree lives in
[`ARCHITECTURE.md` section 6](ARCHITECTURE.md#6-repository-layout). It was
here, at 47 lines, which is longer than this README's introduction and
architecture sections combined and is reference material rather than
orientation.

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

Toolchain versions, per-service build steps, the submodule build graph and the
platform notes are in [`docs/BUILD.md`](docs/BUILD.md).

For deployment see [`deploy/README.md`](deploy/README.md); for what each hosting
option costs and which pages survive it, see
[`docs/deployment-economics.md`](docs/deployment-economics.md).

## 6. Configuration

All variables in `.env` (copy from `.env.example`):

| Variable | Default | Purpose | Source of truth |
|---|---|---|---|
| `ARNIKA_MODE` | `QkdAndPqcRequired` | One of 4 modes: `QkdAndPqcRequired` / `AtLeastQkdRequired` / `AtLeastPqcRequired` / `EitherQkdOrPqcRequired` | `submodules/arnika/config/config.go:34` |
> **Numeric BB84 tunables are not environment variables.** They come from
> `config/qkd_params.yaml`, which `services/bb84-kme/app/config_loader.py`
> declares the single source of truth, and which
> `tests/test_no_hardcoded_params.py` and
> `tests/test_frontend_defaults_match_config.py` enforce. This table used to
> list seven `BB84_*` variables and an `ETSI_MTLS_ENABLED`, each with a
> "source of truth" column naming a Python file. No Python file read any of
> them; they were set in compose and consumed by nothing.

| `ARNIKA_INTERVAL` | `30s` | PSK rotation period (paper uses 120s) | `submodules/arnika/config/config.go` |
| `KMS_HTTP_TIMEOUT` | `10s` | ETSI 014 HTTP timeout | arnika config |
| `WEBUI_BACKEND_PORT` | `8000` | Backend port (host) | docker-compose |
| `WEBUI_FRONTEND_PORT` | `5173` | Frontend nginx port (host) | docker-compose |

---

## 7. Running the WebUI

Open <http://localhost:5173>. Thirteen pages are available; each one is
described, with what it computes client-side and what it needs the backend
for, in [`docs/webui-pages.md`](docs/webui-pages.md).

Most pages carry an export toolbar below the description -- high-DPI PNG (2x),
JSON, CSV, WebM and GIF (duration and frame rate both settable in-page), and
logs.

**Public-demo profile (`DEMO_MODE=1`)** and the note on the mounted Docker
socket are in that document too, under "Demo mode".

---

## 8. Verification & Tests

| Check | Command | Expected |
|---|---|---|
| ETSI-014 contract | `pytest tests/test_etsi014_contract.py -v` | All pass; JSON has exactly `{key_ID, key}` fields |
| BB84 simulator unit | `pytest tests/test_bb84_simulator.py -v` | QBER < 5% no-Eve; QBER > 15% with full intercept |
| wg0 reachability | `docker exec alice ping -c 3 10.0.0.2` | All replies received |
| PSK injection log | `docker logs alice \| grep "PSK configured"` | One match per `ARNIKA_INTERVAL` |
| HKDF fusion log | `docker logs alice \| grep "HKDF derivation completed for QKD+PQC"` | Present in `QkdAndPqcRequired` mode |
| Eve raises QBER | toggle Eve in WebUI → QBER chart spikes ≥ 25% within 2 rounds | observable in WebUI; client-side engine only, arnika is not involved |
| Encrypted on the wire | `docker exec alice tcpdump -i eth1 -X udp port 51820 -c 5` | only opaque ciphertext, no ICMP plaintext |
| Multi-hop ping (optional) | `make up-multihop && docker exec alice ping 10.0.0.2` | **Does not relay yet** -- see the multi-hop row in section 12 |

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
| Multi-hop trusted-node chain | **Implemented.** Alice-Charlie-Bob relays end to end and every hop carries a QKD-derived preshared key. The sidecar takes `RP_EXTRA_PEERS`, `nodes/alice/entrypoint.sh` takes `WG_EXTRA_PEERS` and `ARNIKA_EXTRA_PEERS`, and `docker-compose.multihop.yml` wires all three. Verify with checklist row 3.5, which counts **PSK installs, not ping replies** -- WireGuard forwards traffic perfectly well with no PSK at all, so a clean ping proves nothing about protection. This row previously read "Partial ... the relay does not complete", blaming a single `RP_PEER_HOST`; [`docs/roadmap.md`](docs/roadmap.md) records what each of the four layers actually needed. |
| Adaptive security levels (QuLore L1-L4) | Not implemented. See [`docs/roadmap.md`](docs/roadmap.md). |

---

## 11. Dev Environment

The tested host specification, the WireGuard kernel-module note and the
host-side venv recipe are in
[`docs/BUILD.md` section 6](docs/BUILD.md#6-dev-environment).

---

## 11.5 Implementation phases

The phase-by-phase implementation record - what each phase added, which files
carry it, and how it was verified - lives in
[`docs/phases.md`](docs/phases.md). It covers the multi-backend QKD simulator,
the Quantum-Secure VPN lanes, the live E2E page, the shared UI and export
layer, and the Paper Data Exchange page.

## 12. Limitations

This is a research proof of concept. What it does not do -- the error-correction,
finite-key, channel-model and standards gaps -- is set out in full in
[`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), alongside the carried-forward
items in [`docs/roadmap.md`](docs/roadmap.md).

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
