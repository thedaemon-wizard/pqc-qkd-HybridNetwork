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

**Measured field values from arXiv:2608.18869**, useful for calibrating a
simulator against reality rather than lab conditions:

| Link | Length | Loss | Secret key rate | QBER |
|---|---|---|---|---|
| Sundhausen–Erfurt (mostly aerial) | 70 km | > 17 dB | $12.7 \pm 10.3$ bit/s | $13.3 \pm 9.6\,\%$ |
| Jena–Erfurt (mostly buried) | 69 km | > 21 dB | $22.2 \pm 4.7$ bit/s | $6.1 \pm 0.8\,\%$ |

Two things follow. The aerial link shows **twice the QBER of the buried link
despite lower attenuation**, with variance tracking wind speed — so loss alone
is a poor predictor and this project's static channel model is optimistic. And
at $12$–$22$ bit/s a single 256-bit key takes **12–20 seconds** to accumulate,
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
| RFC 9867 | Mixing PSKs in `IKE_INTERMEDIATE` and `CREATE_CHILD_SA` (Nov 2025) | Would let a PPK be refreshed on rekey without a full reauthentication. **strongSwan 6.0.7 does not implement it** — verified 2026-08-20 at source level: `notify_payload.h` on `master` defines only `USE_PPK` (16435), `PPK_IDENTITY` (16436) and `NO_PPK_AUTH` (16437); neither `USE_PPK_INT` (16445) nor `PPK_IDENTITY_KEY` (16446) exists, and no branch implements them. Future work. |
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
- **ANSSI / BSI / NLNCSA / Swedish Armed Forces**, [Position Paper on Quantum Key Distribution](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Crypto/Quantum_Positionspapier.pdf) (2024-01-26) — QKD "can however currently only be used in practice in some niche use cases" and is "not yet sufficiently mature from a security perspective"; migration to PQC is "the clear priority". The fourth signatory is the **Swedish** authority, not the UK NCSC, which this list previously named by mistake. The Czech NÚKIB issued a Letter of Support (2024-09-19) but is not a signatory.
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
