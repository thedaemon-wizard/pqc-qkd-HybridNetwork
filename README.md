# PQC-QKD Hybrid Security Layer — Research PoC

[![License](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Research%20PoC-orange.svg)](docs/LIMITATIONS.md)

> Research PoC that fuses Quantum Key Distribution (QKD) and Post-Quantum
> Cryptography (PQC) into a single **HKDF-SHA3-256**-derived key and rotates
> it into two VPN lanes on a configurable interval (30 s for demos; the paper
> uses 120 s). A pluggable BB84 physical simulator -- seven selectable
> backends, QuTiP among them -- is wrapped behind the ETSI GS QKD 014 REST API
> and wired into [arnika](https://github.com/arnika-project/arnika) (Go, not
> modified here), which agrees the PQC half with its peer over HPKE and
> installs the fused key. The WireGuard lane follows the reference paper's
> layering: a QKD-keyed hop tunnel, a
> [Rosenpass](https://github.com/rosenpass/rosenpass) (Rust) exchange carried
> through it, and an end-to-end data tunnel keyed by Rosenpass.
>
> Version 0.2.0, not yet released (the `v0.2.0` tag comes after the merge);
> see [Releases and citation](#releases-and-citation).

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
| [`docs/IMAGE1_VPN_SCOPE.md`](docs/IMAGE1_VPN_SCOPE.md), [`docs/IMAGE2_MULTIHOP.md`](docs/IMAGE2_MULTIHOP.md) | The two reference-architecture figures mapped to code: the single tunnel, and the trusted-node multi-hop chain |
| [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md), [`docs/roadmap.md`](docs/roadmap.md) | What is simulated rather than measured, known gaps, and future work |
| [`docs/phases.md`](docs/phases.md), [`CHANGELOG.md`](CHANGELOG.md) | The phase-by-phase implementation record, and the release history it is summarised into |
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
| End-to-End (PQC) | Post-quantum key exchange between alice and bob, carried inside the hop tunnel; its key protects the end-to-end data tunnel `wg1` | Rosenpass v0.2.3 (Classic McEliece 460896 + Kyber512), which writes `wg1`'s WireGuard preshared key through its own WireGuard output |
| Transport | Fetches the QKD key over ETSI 014, agrees a PQC-HPKE key with its peer, fuses the two with HKDF-SHA3-256 and injects the result | **arnika (Go), pinned to the head of the open upstream PR #51 and not modified here; this project adds a strongSwan VICI key-writer adapter** |
| Hop (WireGuard) | Real encryption with ChaCha20-Poly1305 + Noise + PSK, keyed by arnika | WireGuard `wg0` (kernel module, or `wireguard-go` without one) |

**PQC-HPKE** is arnika's own key agreement: HPKE in Base mode (RFC 9180) with
the KEM MLKEM1024-P384, the KDF HKDF-SHA384 and an export-only AEAD, run over
the UDP socket the two arnika peers already share, one round per interval. The
KEM is itself a hybrid of ML-KEM-1024 and P-384 ECDH, and its codepoint
(0x0051) comes from draft-ietf-hpke-pq, which is **not yet an RFC**. The arnika
pin (`f4cf9ba`, 2026-09-24) is the head of arnika's **unmerged** PR #51, which
adds PQC-HPKE, not a commit on upstream `main`; it will be re-pinned to the
merge commit once #51 merges. See [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md#arnika).

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
                     │ /api/stack /api/stats /api/verify/*│
                     └──┬───────────────────────┬─────────┘
                        │                       │
        ┌───────────────▼───┐               ┌───▼──────────────┐
        │  bb84-kme-a       │ /internal/sync│  bb84-kme-b      │
        │  BB84 sim + ETSI  │◄─────────────►│  BB84 sim + ETSI │
        └────────▲──────────┘               └──────────▲───────┘
                 │ HTTP (mTLS NOT implemented)         │
        ┌────────┴───────────┐               ┌─────────┴────────┐
        │  alice (node)      │ wg0 hop tunnel│  bob (node)      │
        │  - arnika (Go)     │◄─────────────►│  - arnika (Go)   │
        │  - rosenpass       │ PSK = HKDF(QKD│  - rosenpass     │
        │  - wg0 10.0.0.1/24 │ || PQC-HPKE)  │  - wg0 10.0.0.2  │
        │  - wg1 10.0.1.1/24 │ wg1 inside wg0│  - wg1 10.0.1.2  │
        │                    │ PSK: Rosenpass│                  │
        └────────────────────┘               └──────────────────┘
```

Each WireGuard node runs two interfaces. `wg0` is the hop tunnel between the
two nodes, keyed by arnika. `wg1` is the end-to-end data tunnel: its peer
endpoint is the other node's `wg0` address, so its packets travel inside `wg0`,
and its preshared key is written by Rosenpass, whose own exchange also runs
between the two `wg0` addresses (UDP 9997): the node with the lower `wg0`
address initiates it, and the other only answers. Every peer of both
interfaces starts with a random placeholder PSK, so neither tunnel completes a
handshake until its keying daemon has installed the same key on both ends.
Section 4.2 of the reference paper describes the same layering, with one
difference: the paper's hop key is the QKD key alone, while arnika here also
mixes in the PQC-HPKE half.

A second lane, strongSwan IKEv2 with ML-KEM-768 (RFC 9370) and an RFC 8784 PPK,
runs under the `ipsec` compose profile. Its PPK is arnika's
HKDF-SHA3-256(QKD ‖ PQC-HPKE) output, produced by a second pair of arnika
instances that use the same KMEs and agree their own PQC-HPKE keys; Rosenpass
plays no part in that lane. See
[`ARCHITECTURE.md` section 4](ARCHITECTURE.md#4-the-ipsec-lane).

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
| arnika as key injector | Implemented; the pin is the head of open upstream PR #51, not modified here, and this project adds a strongSwan VICI key-writer adapter |
| Rosenpass PQC layer | Implemented with the real binary, as the paper layers it: the exchange runs through the `wg0` hop tunnel and its key becomes the preshared key of the `wg1` data tunnel |
| Multi-hop trusted-node chain | Implemented under the `multihop` profile, both layers per leg; unlike the paper, the relay also terminates each leg's `wg1`. Checklist row 3.5 checks every leg |
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

## Releases and citation

Releases are git tags (`v0.1.0`, `v0.2.0`, ...) numbered by
[Semantic Versioning](https://semver.org/spec/v2.0.0.html); while the major
version is 0, any release may change configuration or interfaces.
[`CHANGELOG.md`](CHANGELOG.md) says what each one changed.
[`CITATION.cff`](CITATION.cff) carries the citation metadata, which GitHub
offers as "Cite this repository".

## Acknowledgements

- arnika: developed at CANCOM Converged Services GmbH within the QCI-CAT
  project (EU DIGITAL-2021-QCI-01, No. 101091642, and Austria's National
  Foundation for Research, Technology and Development), which covered
  arnika v1.x; maintained by XBC Digital GmbH since Q2 2026. The pinned
  revision is later than the QCI-CAT-funded v1.x line: `f4cf9ba`, the head of
  the open pull request arnika#51 (2026-09-24), which adds the PQC-HPKE key
  agreement.
- liboqs / oqs-provider: Open Quantum Safe project
- Rosenpass: Rosenpass project contributors
