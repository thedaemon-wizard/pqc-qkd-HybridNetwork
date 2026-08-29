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
[`ARCHITECTURE.md`](../ARCHITECTURE.md), the `/paper-flow` page's Table 1
packet budgets, and the multi-hop trusted-node figure all come from it.

Page 1 of the redistributed file reads "This is the full version of a paper
which appears in the IEEE International Conference ... (C) IEEE, 2026", which
looks at first glance to contradict the licence column. It does not: that line
covers the *conference* version (DOI
[10.1109/QCNC69040.2026.00060](https://doi.org/10.1109/QCNC69040.2026.00060)),
while the arXiv full version this file came from is posted by the authors under
CC BY 4.0 -- confirmed on the arXiv abstract page, which is what governs the
copy shipped here. Recorded because the apparent conflict is on the first page
a reviewer opens, and "why are you redistributing an IEEE PDF" is a reasonable
question to be able to answer without re-deriving the checks.

### Directly comparable work on hybrid QKD/PQC for IPsec

| Work | Identifier | Why it matters here |
|---|---|---|
| *Hybrid Quantum Security for IPsec* | [arXiv:2507.09288](https://arxiv.org/abs/2507.09288) | The first systematic comparison of **sequential vs parallel** hybrid QKD-PQC key establishment for IPsec. This project's `HKDF(QKD ‖ PQC)` is the *parallel* construction: both secrets are obtained independently and combined once. The paper's finding is that parallel schemes avoid the multiplicative latency the sequential ones incur, which is the closest external support for the design chosen here. |
| *Quantum-safe IPsec in the banking industry* | [arXiv:2604.12985](https://arxiv.org/html/2604.12985v1) | 2026 deployment case study in a regulated sector — useful as a reality check on rotation cadence and operational constraints. |
| *Practical hybrid PQC-QKD protocols with enhanced security and performance* | [arXiv:2411.01086](https://arxiv.org/abs/2411.01086) | Security and performance analysis of the hybrid construction itself. |

### A different architecture, considered and not adopted

[`qursa-uc3m/qkd-plugins-strongswan`](https://github.com/qursa-uc3m/qkd-plugins-strongswan)
integrates QKD into strongSwan as an IKEv2 **key-exchange method** (proposals
of the form `aes128-sha256-qkd`), supporting both ETSI GS QKD 014 and 004.

That is a genuinely stronger claim than what this project does: a KE method
feeds the QKD secret into `SKEYSEED` directly, whereas RFC 8784 mixes the PPK in
via `prf+` afterwards. It was not adopted for three reasons, in order of weight:

1. **It does not interoperate.** A custom KE method requires the same plugin on
   both peers. RFC 8784 is a standard that any conforming implementation
   already speaks.
2. **Maintenance.** Nine commits, tested on Ubuntu 22.04/24.04, with no stated
   support for the strongSwan 6.x line this project pins.
3. **Licensing is unclear** from the repository, which fails the requirement
   that dependencies be commercially usable.

Worth revisiting if it matures, because the security argument is better.
Andreas Neuhold, a co-author, maintains [arnika](https://github.com/arnika-project/arnika),
which this project uses as its key-management layer.

### Referenced but **not** redistributed

| Work | Identifier | Licence | Why not included |
|---|---|---|---|
| A. Sanz, E. Salegi, A. Atutxa, D. Franco, J. Astorga, E. Jacob, *QuLore: An Adaptive Security Framework to Extend Quantum-Safe Communications to Real-World Networks* | [arXiv:2511.22416](https://arxiv.org/abs/2511.22416) | **CC BY-NC-ND 4.0** | NonCommercial **and** NoDerivatives. Redistributing it from a repository that documents commercial deployment is not clearly permitted, so only the citation is kept. Read it at the arXiv link. |

### Developments after this project's design freeze (2026-06 → 2026-08)

Re-checked 2026-08-20. These postdate the design and are recorded for the next
revision rather than being implemented here.

| Work | Identifier | Why it matters here |
|---|---|---|
| Dosan, **Spooren**, … **Hühn**, de Vries, *Secure Medical Data Transmission Using QKD and PQC in Real-World Fiber Networks* | [arXiv:2608.18869](https://arxiv.org/abs/2608.18869) (2026-08-19) | The field-deployment sequel to the paper this PoC reproduces, by overlapping authors, and it uses **arnika** for exactly the role it plays here. Gives measured link numbers (below) that bound how fast a PSK can honestly be rotated. |
| Paixão, Tomkelski, Freire *et al.*, *Real-Time VPN Traffic over ETSI GS QKD 014 Key Delivery* | [arXiv:2607.06602](https://arxiv.org/abs/2607.06602) (2026-07-07) | Binds the ETSI `key_ID` into the AES-GCM **AAD**, cryptographically tying the key identifier to the ciphertext. A concrete hardening this project does not yet do. |
| Malik, Anwar, Raza, *Beyond the Quantum Promise: A Security Analysis of Classical Control in QKD* | [arXiv:2608.07626](https://arxiv.org/abs/2608.07626) (2026-08-07) | Tamarin analysis of 23 ETSI/ITU-T QKD documents. Its finding **V3 (message reflection: MAC inputs lack role binding)** is worth checking against any shared-PSK control channel — see the open question in [`vici-ppk.md`](vici-ppk.md). |
| Blanco-Romero, Almenares Mendoza, García Rubio, Campo, Díaz Sánchez, *On the Practical Feasibility of Harvest-Now, Decrypt-Later Attacks* | [arXiv:2603.01091](https://arxiv.org/abs/2603.01091) (2026-03-01, **CC BY 4.0**) | Recasts HNDL as adversary economics rather than a date, with a testbed over TLS 1.2/1.3, QUIC and SSH. Because "retaining intercepted traffic is economically trivial", the levers that act on the adversary alone are **rekeying frequency and key size** — the argument this project's 30 s cadence rests on, previously unstated. Names the absence of in-band ephemeral rekeying in TLS 1.3 and QUIC as a critical protocol gap (§1). **It does not discuss IPsec, IKEv2 or WireGuard**, so applying it to these lanes is this project's inference, marked as such in [`threat-model.md` §2.1](threat-model.md). |
| Raubitzek, Strasser, Ramacher, Lebeth, **Neuhold**, Pacher, on national-scale QKD network planning | [arXiv:2604.06764](https://arxiv.org/abs/2604.06764) (2026-04-08, **CC BY 4.0**) | Monte-Carlo planning method giving **hop-length distributions and trusted-repeater counts** for a country-scale network. Shares an author with the paper this PoC reproduces. Relevant because `/paper-flow`'s hop-count control currently has no empirical basis for its range; this supplies one. **Not yet implemented** — recorded here as the source to use, not as something the UI reflects. |

**Measured field values from arXiv:2608.18869**, useful for calibrating a
simulator against reality rather than lab conditions:

| Link | Length | Loss | Secret key rate | QBER |
|---|---|---|---|---|
| Sundhausen–Erfurt (mostly aerial) | 70 km | > 17 dB | $`12.7 \pm 10.3`$ bit/s | $`13.3 \pm 9.6\,\%`$ |
| Jena–Erfurt (mostly buried) | 69 km | > 21 dB | $`22.2 \pm 4.7`$ bit/s | $`6.1 \pm 0.8\,\%`$ |

Two things follow. The aerial link shows **twice the QBER of the buried link
despite lower attenuation**, with variance tracking wind speed — so loss alone
is a poor predictor and this project's static channel model is optimistic. And
at 12–22 bit/s a single 256-bit key takes **12–20 seconds** to accumulate,
which means a rotation interval is bounded by the link's secret key rate, not
chosen by policy. This project's 30 s default sits just above that floor; the
paper's 120 s is the safer figure.

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
| 1002 km twin-field QKD — longest fibre QKD distance to date, on **spooled laboratory fibre** (<0.157 dB/km, 156.5 dB total), **not** deployed fibre. At that distance the rate is 9.53e-12 per pulse (~0.0034 bit/s) and **asymptotic only**; the longest finite-size distance in the PRL is 952 km. Finite-key security at the full 1002 km (3.11e-12 per pulse) is shown in the companion paper. | Y. Liu *et al.*, Phys. Rev. Lett. **130**, 210801 (2023), [doi:10.1103/PhysRevLett.130.210801](https://doi.org/10.1103/PhysRevLett.130.210801); finite-key: Y. Liu *et al.*, Quantum Front. **2**, 16 (2023), [doi:10.1007/s44214-023-00039-9](https://doi.org/10.1007/s44214-023-00039-9) |
| 254 km twin-field QKD over a **live commercial telecom network** (Frankfurt-Kehl), 110 bit/s, non-cryogenic detectors — the figure that matters for real-world deployment. Longer *installed dark-fibre* spans exist: a 428 km field test, and a 511 km Qingdao-Jinan link that is 430 km deployed trunk plus 81 km of added spool. | M. Pittaluga *et al.*, Nature **640**, 911 (2025), [doi:10.1038/s41586-025-08801-w](https://doi.org/10.1038/s41586-025-08801-w); J.-P. Chen *et al.*, Nat. Photon. **15**, 570 (2021), [doi:10.1038/s41566-021-00828-5](https://doi.org/10.1038/s41566-021-00828-5) |
| 115.8 Mbit/s at 10 km — highest peer-reviewed secret-key rate for discrete-variable QKD as of 2026-08 (decoy-state BB84, 2.5 GHz clock, standard G.652 spooled fibre, composable finite-size security); the same system reaches 328 km of ultralow-loss fibre | W. Li, L. Zhang, F. Xu, J.-W. Pan *et al.*, Nat. Photon. **17**, 416 (2023), [doi:10.1038/s41566-023-01166-4](https://doi.org/10.1038/s41566-023-01166-4) |
| 64 Mbit/s at 10.0 km and 3.0 Mbit/s at 102.4 km (2.5 GHz time-bin QKD with real-time key distillation) — the companion paper in the same issue, pp. 422-426. This table previously labelled it "highest secret-key rate"; it was not the highest even in its own issue. | F. Grünenfelder, A. Boaron *et al.*, Nat. Photon. **17**, 422 (2023), [doi:10.1038/s41566-023-01168-2](https://doi.org/10.1038/s41566-023-01168-2) |
| 12 900 km satellite QKD, portable ground station | Y. Li *et al.*, Nature **640** (2025), [doi:10.1038/s41586-025-08739-z](https://doi.org/10.1038/s41586-025-08739-z) |

> **Records are scope-dependent.** The rate figure above is discrete-variable on spooled
> fibre with finite-size security. The highest peer-reviewed *continuous-variable* rate is
> 18.93 Mbit/s over 25 km (M. Wu *et al.*, Phys. Rev. X **16**, 021039 (2026),
> [doi:10.1103/882y-w4zy](https://doi.org/10.1103/882y-w4zy)). A higher CV figure --
> 153.22 Mbit/s asymptotic / 149.99 Mbit/s finite-size over 24.3 km of anti-resonant
> hollow-core fibre -- exists in preprint only (arXiv:2607.14704, 2026-07) and is not
> peer-reviewed. Verified against Crossref and arXiv on 2026-08-22.

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
| RFC 9954 | Hybrid Key Exchange in TLS 1.3 (Informational, 2026-07) | The framework; defines no named groups. |
| **RFC 10024** | PQ/T Hybrid Key Agreement for TLS 1.3 (**Proposed Standard**, 2026-08) | Standardises `X25519MLKEM768` (0x11EC), `SecP256r1MLKEM768` (0x11EB) and `SecP384r1MLKEM1024` (0x11ED), and marks the Kyber draft groups 25497/25498 **obsolete**. Hybrid ML-KEM in TLS is settled standards-track work; calling it a draft is out of date. |
| **RFC 9370** | Multiple Key Exchanges in IKEv2 | ECP-256 + ML-KEM-768 hybrid (`ke1_mlkem768`) |
| **RFC 9242** | Intermediate Exchange in IKEv2 | Carries the ML-KEM payloads encrypted, so they can be fragmented |
| RFC 9867 | Mixing PSKs in `IKE_INTERMEDIATE` and `CREATE_CHILD_SA` (Nov 2025) | Would let a PPK be refreshed on rekey without a full reauthentication. **strongSwan 6.0.7 does not send it** — verified at source level, and stated as the two reproducible observations rather than a flat claim: `USE_PPK_INT` (16445) and `PPK_IDENTITY_KEY` (16446) appear nowhere under `src/`, and **16444 is the highest Status Type in `notify_payload.h`** (the next entry is `INITIAL_CONTACT_IKEV1 = 24578`), so they sit immediately above the top of the range. The `IKE_SA_INIT` response on this lane carries `N(USE_PPK)`, and RFC 9867 §3.1 has a responder return either that or `USE_PPK_INT`, never both. An earlier version of this row said the header defines *only* 16435-16437, which is false — 16438, 16441, 16442 and 16444 are also there. See [`vici-ppk.md`](vici-ppk.md). Future work here, but **not unimplemented in the world** -- see below. strongSwan marks it unsupported in its standards table: [`docs/modules/ROOT/pages/features/ietf.adoc`](https://github.com/strongswan/strongswan-docs/blob/master/docs/modules/ROOT/pages/features/ietf.adoc) in the separate **`strongswan/strongswan-docs`** repository, rendered at [docs.strongswan.org/docs/latest/features/ietf.html](https://docs.strongswan.org/docs/latest/features/ietf.html). It is **not** in `submodules/strongswan`: the pinned 6.0.7 tree (`5973ff8e`) contains no `docs/` directory and no `.adoc` file at all, so this citation cannot be checked against the submodule. Reading it needs the legend, which inverts the obvious sense -- `:S: footnote:S[S = Status: x = not supported, d = under development]`, and blank means at least partially implemented. RFC 9867 carries `*x*`; RFC 8784, RFC 9242 and RFC 9370 are blank. **RETRACTED 2026-08-29, and it was wrong in the most useful direction.** This row previously said "No open-source IKEv2 implementation exists" and "Libreswan HEAD has no reference to RFC 9867 either, despite Libreswan 5.4 (2026-08-13) shipping ML-KEM" -- naming the exact release that implements it as evidence that nothing does. **libreswan v5.4 implements RFC 9867.** Verified by cloning the tag: `include/ietf_constants.h:1807-1808` defines `v2N_USE_PPK_INT = 16445` and `v2N_PPK_IDENTITY_KEY = 16446` -- the IANA allocations, so it is wire-compatible -- with emit/parse code in `programs/pluto/ikev2_ppk.c` and `ikev2_ike_intermediate.c`, config keywords `ppk=insist` + `ppk-ids=` + `intermediate=yes`, and regression tests under `testing/pluto/ikev2-ppk-intermediate-*`. The in-tree comment still reads `/* RFC-ietf-ipsecme-ikev2-qr-alt */`, which is the draft name, but the VALUES are the RFC's. Two lessons recorded rather than just the correction: **libreswan is not vendored here**, so a source-level negative about it was as uncheckable as the `strongswan-docs` citation this same row criticises two sentences earlier; and [`roadmap.md`](roadmap.md) line 40 had already deleted the identical "no open-source implementation" sentence as not checkable, so the repository contradicted itself. **What this means for the project:** consuming fresh QKD material on every rekey is available today by changing IKE daemon, not only by waiting for strongSwan. |
| RFC 7296 | IKEv2 | §2.15 defines the AUTH payload, i.e. the only place a plain PSK is used |
| RFC 7383 | IKEv2 Fragmentation | Required for ML-KEM-sized payloads |
| RFC 7696 | Guidelines for Cryptographic Algorithm Agility | Crypto-agility framing |
| draft-ietf-ipsecme-ikev2-mlkem-09 | ML-KEM in IKEv2 | IESG-approved 2026-07-07, in the RFC Editor queue (no number yet, "Awaiting First editor" as of 2026-08-13). Assigns transform IDs 35/36/37 to ML-KEM-512/768/1024 — the values this project's proposals already rely on. |
| draft-ietf-ipsecme-ikev2-pqc-auth-11 | PQC signature authentication in IKEv2 | **Not approved.** Went to the 2026-08-20 IESG telechat and picked up a DISCUSS. strongSwan gates its ML-DSA release on this draft, so PQ *authentication* remains unavailable; this project uses PQ *key exchange* plus PPK, which do not depend on it. |
| RFC 9794 | Terminology for Post-Quantum Traditional Hybrid Schemes | Vocabulary |

### NIST

| Publication | Title | Status |
|---|---|---|
| FIPS 203 | ML-KEM | Final, 2024-08-13 |
| FIPS 204 | ML-DSA | Final, 2024-08-13 |
| FIPS 205 | SLH-DSA | Final, 2024-08-13 |
| FIPS 206 | FN-DSA (Falcon) | **No public draft as of 2026-08.** Do not plan around it. |
| **SP 800-227** | Recommendations for Key-Encapsulation Mechanisms | **Final, Sept 2025.** §4.6.1 acknowledges that a multi-algorithm scheme may include a secret established via QKD; §4.6.2 then requires ("shall") an approved key combiner, drawn from SP 800-56C or SP 800-133. See [`vici-ppk.md`](vici-ppk.md) for how far this project meets that. [doi:10.6028/NIST.SP.800-227](https://doi.org/10.6028/NIST.SP.800-227) |
| SP 800-56C Rev. 2 | Key-Derivation Methods in Key-Establishment Schemes | Defines the hybrid shared secret `Z' = Z ‖ T` |
| SP 800-131A Rev. 3 | Transitioning the Use of Cryptographic Algorithms | **Initial public draft, 2024-10-21; still not final.** `/r3/final` returns 404, so **Rev. 2 (2019-03-21) remains the effective version**. |
| SP 800-208 | Stateful Hash-Based Signatures | LMS/XMSS |
| IR 8547 | Transition to Post-Quantum Cryptography Standards | **Initial public draft, 2024-11-12; comments closed 2025-01-10; still not final** (`/ir/8547/final` -> 404). Its 2030-deprecated / 2035-disallowed dates are widely quoted as settled NIST policy and are not. |
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
CANCOM Converged Services GmbH and, since **Q2 2026, actively maintained at
XBC Digital GmbH** -- the maintainer moved with the people, and
`submodules/arnika/README.md:345-352` records both. Neither is an NLnet-funded
project today.

---

## 4. Positions worth reading against this work

QKD is not universally endorsed, and this project should not be read as
claiming otherwise:

- **NSA**, [Quantum Key Distribution (QKD) and Quantum Cryptography (QC)](https://www.nsa.gov/Cybersecurity/Quantum-Key-Distribution-QKD-and-Quantum-Cryptography-QC/) — does not support QKD for national-security systems, and recommends post-quantum cryptography instead.
- **UK NCSC**, [Quantum networking technologies](https://www.ncsc.gov.uk/paper/quantum-networking-technologies) (2025-08-05) — "The NCSC will not support the use of QKD for government or military applications. PQC is the best mitigation to the threat to cryptography from quantum computers." For other sectors, QKD "should not be solely relied upon", and QKD "should not constitute evidence towards assessments of security of data-in-transit under the NCSC's Cyber Assessment Framework". This calls itself "an updated analysis" of the 2020 white paper [Quantum security technologies](https://www.ncsc.gov.uk/paper/quantum-security-technologies), which **remains published**; the legacy `/whitepaper/` alias has redirected here since around August 2025. The change between them is the verb, not the scope: 2020 already read "does not endorse the use of QKD for **any government or military applications**". Quoting the 2020 line without that scope invents a broadening that did not happen.
- **ANSSI / BSI / NLNCSA / Swedish Armed Forces**, [Position Paper on Quantum Key Distribution](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Crypto/Quantum_Positionspapier.pdf) (2024-01-26) — QKD "can however currently only be used in practice in some niche use cases" and is "not yet sufficiently mature from a security perspective"; migration to PQC is "the clear priority". The fourth signatory is the **Swedish** authority, not the UK NCSC, which this list previously named by mistake. The Czech NÚKIB issued a Letter of Support (2024-09-19) but is not a signatory.
- **US Department of War**, [Post Quantum Cryptography Strategy](https://dowcio.war.gov/Portals/0/Documents/Library/DoW-PQC-Strategy.pdf) (signed 2026-04-01) — the most direct objection to what this project builds, and therefore the one most worth stating here. Under "Do Not Introduce New Security Risks" it names, verbatim, "quantum key distribution (QKD) and quantum networking, **solutions combining QKD with other cryptographic key establishment**, or non-local quantum randomness generation" as technologies that "will not be used as a means for achieving security for confidentiality, data or entity authentication, key distribution, or non-local randomness generation". The companion CIO memo [Preparing for Migration to Post Quantum Cryptography](https://dowcio.war.gov/Portals/0/Documents/Library/PreparingForMigrationPQC.pdf) (2025-11-18) adds that Components "will not test, evaluate, pilot, use, or procure" them.

  Two qualifications, so this is neither overstated nor waved away. The prohibition is **scoped** to "providing confidentiality, authenticity, or integrity in DoW networks and communications", and the memo provides a **named waiver path** ("unless provided exception by the point of contact above"). It is a procurement and accreditation rule for one national-security enterprise, not a claim that the construction is cryptographically unsound. But it does mean a PQC-plus-QKD hybrid is disallowed by default in that setting, and no amount of favourable NIST language changes that.

- **BSI**, [TR-02102-1 v2026-01](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Publications/TechGuidelines/TG02102/BSI-TR-02102-1.pdf) (2026-01-23) — Germany's operative crypto guideline now states plainly that "**the BSI does not recommend QKD protocols at this time**". This is a harder line than the 2022 BSI brochure, which recommended QKD "only as an add-on in hybrid mode"; that brochure has not been revised since and should not be cited as the current position.

Worth recording because it is easy to miss: QKD has been written out of the
European policy architecture rather than argued down. It appears **zero times**
in the EU NIS Cooperation Group's [Coordinated Implementation Roadmap for the
Transition to Post-Quantum Cryptography](https://digital-strategy.ec.europa.eu/en/library/coordinated-implementation-roadmap-transition-post-quantum-cryptography)
(2025-06), zero times in the [G7 Cybersecurity Working Group statement](https://www.cyber.gc.ca/en/news-events/g7-cybersecurity-working-group-statement-preparing-post-quantum-cryptography-migration)
(2026-06), and zero times in the ECCG *Agreed Cryptographic Mechanisms* v2.0
(2025-04), which is the approved-algorithm list for EU-certified products.
Those documents set the deadlines the field is now working to: high-risk use
cases off quantum-vulnerable public key by **end-2030**, medium-risk by
**end-2035**.

The counter-argument this project embodies is narrower than "QKD is good", and
worth stating plainly: QKD material is used here **in addition to**
post-quantum cryptography, never instead of it. Nothing above contradicts that
composition -- the agencies' objection is to QKD as a *replacement* for PQC,
which is not what is built here. Note also that Germany is simultaneously
building QKD assurance: BSI certified the ETSI Common Criteria Protection
Profile for prepare-and-measure QKD in January 2024. The European position is
"not yet, and not instead", not "never".

NIST SP 800-227 supports that composition, but the precise wording matters and
an earlier version of this paragraph got both the section and the modality
wrong. QKD is mentioned exactly once in the publication, in the *General
multi-algorithm schemes* discussion of **§4.6.1** — not §4.6.2:

> "such schemes could potentially include pre-shared keys or shared secrets
> established via quantum key distribution. Still, most multi-algorithm schemes
> will likely include a step in which a series of shared secrets are combined
> via a key combiner algorithm of a form similar to KeyCombine above. In those
> cases, an approved key combiner discussed in Sec. 4.6.2 **shall** be used."

So §4.6.2 does not *permit* anything: it imposes a requirement. Including a QKD
secret in a multi-algorithm scheme is acknowledged as possible, and doing so
obliges the design to use an approved combiner. That is a bar this project must
clear, not a licence it enjoys — and it is not currently cleared in full; see
the KDF conformance note in [`vici-ppk.md`](vici-ppk.md).
