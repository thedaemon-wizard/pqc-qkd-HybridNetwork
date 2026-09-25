# PQC-QKD Hybrid Security Layer — Research PoC

[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Research%20PoC-orange.svg)](docs/LIMITATIONS.md)

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

## Documentation

| Document | What it answers |
|---|---|
| [`docs/threat-model.md`](docs/threat-model.md) | What this defends against and why hybrid: harvest-now-decrypt-later, Mosca's inequality, the CRQC estimates, and the CNSA 2.0 gap this repository does not close |
| [`docs/keyrate.md`](docs/keyrate.md) | The decoy-state BB84 key-rate model, derived, with the golden vector CI asserts against |
| [`docs/vici-ppk.md`](docs/vici-ppk.md) | How the QKD key reaches strongSwan (RFC 8784 PPK + RFC 9370 hybrid key exchange), and why a plain IKEv2 PSK would not work |
| [`docs/etsi004-binding.md`](docs/etsi004-binding.md) | The ETSI GS QKD 004 V2.1.1 endpoint and this project's HTTP binding for it |
| [`docs/webui-pages.md`](docs/webui-pages.md) | The fourteen WebUI routes: what each computes in the browser and what it needs the backend for |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The detailed design and the annotated repository layout |
| [`docs/BUILD.md`](docs/BUILD.md) | Toolchains, per-service builds, configuration variables, the dev environment |
| [`deploy/README.md`](deploy/README.md), [`docs/deployment-economics.md`](docs/deployment-economics.md) | Deploying, redeploying, and what each hosting option costs |
| [`docs/benchmarks.md`](docs/benchmarks.md) | The benchmark scripts, and what has (not yet) been measured |
| [`docs/paper_mapping.md`](docs/paper_mapping.md) | The paper's claims, one by one, against this implementation |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), [`docs/roadmap.md`](docs/roadmap.md) | What is simulated rather than measured, known gaps, and future work |
| [`docs/phases.md`](docs/phases.md) | The phase-by-phase implementation record |
| [`docs/references.md`](docs/references.md) | Every paper, standard and dependency, with identifiers and licences |
| [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md), [`NOTICE`](NOTICE) | Submodules and packages: licences, pins, and what a redistributor must know |
| [`VERIFICATION_CHECKLIST.md`](VERIFICATION_CHECKLIST.md) | What must be checked before a release, and how |

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
reach a KME or arnika, so it does not exercise arnika's fall-back path.

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
                 │ HTTP (mTLS NOT implemented)         │
        ┌────────┴───────────┐               ┌─────────┴────────┐
        │  alice (node)      │ WireGuard wg0 │  bob (node)      │
        │  - arnika (Go)     │◄─────────────►│  - arnika (Go)   │
        │  - rosenpass       │ PSK = HKDF(   │  - rosenpass     │
        │  - wg0 10.0.0.1/24 │   QKD || PQC) │  - wg0 10.0.0.2  │
        └────────────────────┘               └──────────────────┘
```

A second lane, strongSwan IKEv2 with ML-KEM-768 and an RFC 8784 PPK fed by the
same arnika output, runs under the `ipsec` compose profile. See
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## 3. Quickstart

```bash
git clone --recurse-submodules https://github.com/thedaemon-wizard/pqc-qkd-HybridNetwork.git
cd pqc-qkd-HybridNetwork
make init      # writes .env and fetches submodules
make build     # about 3-5 min the first time: arnika (Go), Rosenpass (Rust), Python
make up        # the full stack, detached
make smoke     # ETSI 014 contract, a ping over wg0, PSK rotation in arnika's logs
```

Then open <http://localhost:5173>. Configuration variables are listed in
[`docs/BUILD.md` section 7](docs/BUILD.md#7-configuration); numeric BB84
parameters live in `config/qkd_params.yaml`, not in the environment.

## 4. Verification

`make test` runs the host test suite through the project venv, and `make
smoke` the live end-to-end subset. The release gates -- CI-checked and manual,
including the browser pass over every page -- are in
[`VERIFICATION_CHECKLIST.md`](VERIFICATION_CHECKLIST.md).

## 5. Paper mapping

| Paper claim | Status |
|---|---|
| KMS-free layered overlay | Implemented |
| ETSI GS QKD 014 client/server contract | Implemented; contract tested in CI against two live KMEs |
| arnika as key injector | Implemented, upstream unchanged; this project adds a strongSwan VICI key-writer adapter |
| Rosenpass PQC layer | Implemented with the real binary and no fallback: a missing keypair or peer key makes the sidecar exit rather than substitute local randomness |
| Multi-hop trusted-node chain | Implemented under the `multihop` profile; checklist row 3.5 counts PSK installs per leg, since a clean ping proves nothing about protection |
| Adaptive security levels (QuLore L1-L4) | Not implemented; see [`docs/roadmap.md`](docs/roadmap.md) |

Claim by claim, with the evidence for each: [`docs/paper_mapping.md`](docs/paper_mapping.md).

## 6. License

Apache-2.0 for this repository's own code: the full text is in
[`LICENSE`](LICENSE), and [`NOTICE`](NOTICE) lists the submodules and their
terms, including the copyleft ones a redistributor must know about. This
software redistributes cryptographic implementations; check your
jurisdiction's export-control rules (for example US ECCN 5D002) before a
public deployment.

## Contributing

PRs are welcome. Please open an issue to discuss larger changes before
submitting. Every change must pass `make smoke && make test`.

## Acknowledgements

- arnika: CANCOM Converged Services GmbH (EU EUROQCI/QCI-CAT program)
- liboqs / oqs-provider: Open Quantum Safe project
- Rosenpass: Rosenpass project contributors
