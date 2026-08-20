# References

Every external work this project relies on, with a stable identifier and — for
anything redistributed in this repository — its licence.

Verified 2026-08-20.

---

## 1. Papers

### Redistributed here

| Work | Identifier | Licence | File |
|---|---|---|---|
| P. Spooren, A. Neuhold, S. Ramacher, T. Hühn, *PQC-Enhanced QKD Networks: A Layered Approach* | [arXiv:2604.05599](https://arxiv.org/abs/2604.05599) | **CC BY 4.0** — redistribution permitted with attribution | [`references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf`](../references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf) |

This is the paper the PoC reproduces: the layered model in
[`ARCHITECTURE.md`](../ARCHITECTURE.md), the `/paper-flow` page's Table III
packet budgets, and the multi-hop trusted-node figure all come from it.
Andreas Neuhold, a co-author, maintains [arnika](https://github.com/arnika-project/arnika),
which this project uses as its key-management layer.

### Referenced but **not** redistributed

| Work | Identifier | Licence | Why not included |
|---|---|---|---|
| A. Sanz, E. Salegi, A. Atutxa, D. Franco, J. Astorga, E. Jacob, *QuLore: An Adaptive Security Framework to Extend Quantum-Safe Communications to Real-World Networks* | [arXiv:2511.22416](https://arxiv.org/abs/2511.22416) | **CC BY-NC-ND 4.0** | NonCommercial **and** NoDerivatives. Redistributing it from a repository that documents commercial deployment is not clearly permitted, so only the citation is kept. Read it at the arXiv link. |

### QKD physics and key-rate theory

| Work | Identifier |
|---|---|
| X. Ma, B. Qi, Y. Zhao, H.-K. Lo, *Practical decoy state for quantum key distribution*, Phys. Rev. A **72**, 012326 (2005) | [doi:10.1103/PhysRevA.72.012326](https://doi.org/10.1103/PhysRevA.72.012326) · [quant-ph/0503005](https://arxiv.org/abs/quant-ph/0503005) |
| H.-K. Lo, X. Ma, K. Chen, *Decoy state quantum key distribution*, Phys. Rev. Lett. **94**, 230504 (2005) | [doi:10.1103/PhysRevLett.94.230504](https://doi.org/10.1103/PhysRevLett.94.230504) |
| C. C. W. Lim, M. Curty, N. Walenta, F. Xu, H. Zbinden, *Concise security bounds for practical decoy-state QKD*, Phys. Rev. A **89**, 022307 (2014) | [doi:10.1103/PhysRevA.89.022307](https://doi.org/10.1103/PhysRevA.89.022307) |
| D. Gottesman, H.-K. Lo, N. Lütkenhaus, J. Preskill, *Security of QKD with imperfect devices* (GLLP), Quantum Inf. Comput. **4**, 325 (2004) | [quant-ph/0212066](https://arxiv.org/abs/quant-ph/0212066) |
| I. Devetak, A. Winter, *Distillation of secret key and entanglement from quantum states*, Proc. R. Soc. A **461**, 207 (2005) | [doi:10.1098/rspa.2004.1372](https://doi.org/10.1098/rspa.2004.1372) |
| F. Grosshans, P. Grangier, *Continuous variable QKD using coherent states* (GG02), Phys. Rev. Lett. **88**, 057902 (2002) | [doi:10.1103/PhysRevLett.88.057902](https://doi.org/10.1103/PhysRevLett.88.057902) |
| H.-K. Lo, M. Curty, B. Qi, *Measurement-device-independent QKD*, Phys. Rev. Lett. **108**, 130503 (2012) | [doi:10.1103/PhysRevLett.108.130503](https://doi.org/10.1103/PhysRevLett.108.130503) |
| S. Pirandola *et al.*, *Advances in quantum cryptography*, Adv. Opt. Photon. **12**, 1012 (2020) | [doi:10.1364/AOP.361502](https://doi.org/10.1364/AOP.361502) |

The formulas actually implemented, and where, are set out in
[`keyrate.md`](keyrate.md).

### Experimental benchmarks cited for context

| Result | Work |
|---|---|
| 1002 km twin-field QKD (current fibre distance record) | Y. Liu *et al.*, Phys. Rev. Lett. **130**, 210801 (2023), [doi:10.1103/PhysRevLett.130.210801](https://doi.org/10.1103/PhysRevLett.130.210801) |
| 64 Mbit/s at 10 km (highest secret-key rate) | F. Grünenfelder, A. Boaron *et al.*, Nat. Photon. **17**, 422 (2023), [doi:10.1038/s41566-023-01168-2](https://doi.org/10.1038/s41566-023-01168-2) |
| 12 900 km satellite QKD, portable ground station | Y. Li *et al.*, Nature **640** (2025), [doi:10.1038/s41586-025-08739-z](https://doi.org/10.1038/s41586-025-08739-z) |

### Simulators

| Work | Identifier |
|---|---|
| M. Mehic *et al.*, *QKDNetSim+*, SoftwareX **26** (2024) | [doi:10.1016/j.softx.2024.101685](https://doi.org/10.1016/j.softx.2024.101685) |
| X. Wu *et al.*, *SeQUeNCe: a customizable discrete-event simulator of quantum networks*, Quantum Sci. Technol. **6**, 045027 (2021) | [doi:10.1088/2058-9565/ac22f6](https://doi.org/10.1088/2058-9565/ac22f6) |

---

## 2. Standards

### ETSI — QKD

| Standard | Version | Status (Aug 2026) |
|---|---|---|
| **GS QKD 014** — Protocol and data format of REST-based key delivery API | V1.1.1 (2019-02) | Current. Implemented by [`services/bb84-kme/app/etsi014.py`](../services/bb84-kme/app/etsi014.py). [PDF](https://www.etsi.org/deliver/etsi_gs/QKD/001_099/014/01.01.01_60/gs_qkd014v010101p.pdf) |
| GS QKD 014 **Edition 2** | draft (`RGS/QKD-014ed2_KeyDeliv`) | Stable draft, unpublished. Breaking: paths move to `/kdapi/v2/`, GET is removed, SAE IDs move into the body, master/slave → initiator/target. **Not implemented here.** [forge](https://forge.etsi.org/rep/qkd/gs014-key-deliv) |
| GS QKD 004 — Application interface | V2.1.1 (2020-08) | Current; Edition 3 in drafting. Stateful alternative to 014. |
| GS QKD 015 — Control interface for SDN | V2.1.1 (2022-04) | Current |
| GS QKD 016 — Common Criteria Protection Profile | V2.1.1 (2024-01) | BSI-certified (PP-0120) |
| GS QKD 018 — Orchestration interface for SDN | V1.1.1 (2022-04) | Published |
| **GS QKD 020** — Interoperable KMS API | **V1.1.1 (2026-06-29)** | **Published** — inter-KME key transfer |

### IETF — IPsec / IKEv2

| RFC | Title | Relevance |
|---|---|---|
| **RFC 8784** | Mixing Preshared Keys in IKEv2 for Post-quantum Security | The mechanism this project uses to deliver QKD material. See [`vici-ppk.md`](vici-ppk.md). |
| **RFC 9370** | Multiple Key Exchanges in IKEv2 | ECP-256 + ML-KEM-768 hybrid (`ke1_mlkem768`) |
| **RFC 9242** | Intermediate Exchange in IKEv2 | Carries the ML-KEM payloads encrypted, so they can be fragmented |
| RFC 9867 | Mixing PSKs in `IKE_INTERMEDIATE` and `CREATE_CHILD_SA` (Nov 2025) | Would let a PPK be refreshed on rekey. **strongSwan 6.0.7 does not implement it** — future work. |
| RFC 7296 | IKEv2 | §2.15 defines the AUTH payload, i.e. the only place a plain PSK is used |
| RFC 7383 | IKEv2 Fragmentation | Required for ML-KEM-sized payloads |
| RFC 7696 | Guidelines for Cryptographic Algorithm Agility | Crypto-agility framing |
| RFC 9794 | Terminology for Post-Quantum Traditional Hybrid Schemes | Vocabulary |

### NIST

| Publication | Title | Status |
|---|---|---|
| FIPS 203 | ML-KEM | Final, 2024-08-13 |
| FIPS 204 | ML-DSA | Final, 2024-08-13 |
| FIPS 205 | SLH-DSA | Final, 2024-08-13 |
| FIPS 206 | FN-DSA (Falcon) | **No public draft as of 2026-08.** Do not plan around it. |
| **SP 800-227** | Recommendations for Key-Encapsulation Mechanisms | **Final, Sept 2025.** §4.6 governs how a QKD key may be combined with a KEM secret — see [`keyrate.md`](keyrate.md) and [`vici-ppk.md`](vici-ppk.md). [doi:10.6028/NIST.SP.800-227](https://doi.org/10.6028/NIST.SP.800-227) |
| SP 800-56C Rev. 2 | Key-Derivation Methods in Key-Establishment Schemes | Defines the hybrid shared secret `Z' = Z ‖ T` |
| SP 800-131A Rev. 3 | Transitioning the Use of Cryptographic Algorithms | Deprecation timelines |
| SP 800-208 | Stateful Hash-Based Signatures | LMS/XMSS |
| IR 8547 | Transition to Post-Quantum Cryptography Standards | Migration guidance |
| IR 8545 | Status Report on the Fourth Round | HQC selected 2025-03-11 as backup KEM |

### Cryptographic combiners

| Work | Identifier |
|---|---|
| F. Giacon, F. Heuer, B. Poettering, *KEM Combiners*, PKC 2018 | [ePrint 2018/024](https://eprint.iacr.org/2018/024) |
| N. Bindel, J. Brendel, M. Fischlin, B. Goncalves, D. Stebila, *Hybrid Key Encapsulation Mechanisms and Authenticated Key Exchange*, PQCrypto 2019 | [ePrint 2018/903](https://eprint.iacr.org/2018/903) |
| M. Barbosa *et al.*, *X-Wing: The Hybrid KEM You've Been Looking For* | [IACR CiC 1(1) (2024)](https://cic.iacr.org/) · [draft-connolly-cfrg-xwing-kem](https://datatracker.ietf.org/doc/html/draft-connolly-cfrg-xwing-kem) |

---

## 3. Software

Licences for everything vendored under `submodules/` are recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Key upstreams:

| Project | Role | Licence |
|---|---|---|
| [arnika](https://github.com/arnika-project/arnika) | QKD/PQC key management; the key-writer port this project extends | Apache-2.0 |
| [strongSwan](https://github.com/strongswan/strongswan) | IKEv2 daemon (pinned 6.0.7) | GPL-2.0 + OpenSSL exception |
| [govici](https://github.com/strongswan/govici) | Official VICI client (pinned v0.8.2) | MIT |
| [Rosenpass](https://github.com/rosenpass/rosenpass) | Post-quantum key exchange for WireGuard | MIT / Apache-2.0 |
| [liboqs](https://github.com/open-quantum-safe/liboqs) | PQC reference implementations | MIT |
| [TNO-Quantum `qkd_key_rate`](https://github.com/TNO-Quantum/communication.qkd_key_rate) | Independent key-rate cross-check | Apache-2.0 |

Rosenpass was funded by NLnet **NGI Assure** (grant agreement No. 957073); that
grant period **ended in 2024**. arnika is a result of the EU **EUROQCI /
QCI-CAT** project (DIGITAL-2021-QCI-01, No. 101091642), originally developed at
CANCOM Converged Services GmbH. Neither is an NLnet-funded project today.

---

## 4. Positions worth reading against this work

QKD is not universally endorsed, and this project should not be read as
claiming otherwise:

- **NSA**, [Quantum Key Distribution (QKD) and Quantum Cryptography (QC)](https://www.nsa.gov/Cybersecurity/Quantum-Key-Distribution-QKD-and-Quantum-Cryptography-QC/) — does not support QKD for national-security systems, and recommends post-quantum cryptography instead.
- **UK NCSC**, [Quantum security technologies](https://www.ncsc.gov.uk/whitepaper/quantum-security-technologies) — advises against QKD for government and critical national infrastructure.
- **BSI / ANSSI / NLNCSA / NCSC**, [Position Paper on Quantum Key Distribution](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Crypto/Quantum_Positionspapier.pdf) — QKD is not yet suitable for most use cases without substantial further development.

The counter-argument this project embodies is narrower and worth stating
plainly: QKD material is used here **in addition to** post-quantum
cryptography, never instead of it. NIST SP 800-227 §4.6.2 permits exactly this
composition — a QKD key may participate in an approved key combiner **provided
at least one input comes from an approved KEM**. A QKD key alone would not
qualify.
