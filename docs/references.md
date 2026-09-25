# References

Every external work this project relies on, with a stable identifier and — for
anything redistributed in this repository — its licence.

Verified 2026-09-25. Rows that were checked on a different day say so.

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

Andreas Neuhold, a co-author of this paper, is also an author of QCI-CAT
deliverable D6.1 and one of [arnika](https://github.com/arnika-project/arnika)'s
original developers at CANCOM (section 3); arnika is this project's
key-management layer.

### Directly comparable work on hybrid QKD/PQC for IPsec

| Work | Identifier | Why it matters here |
|---|---|---|
| Blanco-Romero, Otero García, Sobral-Blanco, Almenares Mendoza, Fernández Vilas, Fernández-Veiga, *Hybrid Quantum Security for IPsec* | [arXiv:2507.09288](https://arxiv.org/abs/2507.09288) | The first systematic comparison of **sequential vs parallel** hybrid QKD-PQC key establishment for IPsec, by the UC3M / UVigo group behind QURSA. It supports one layer of this design and criticises another. Supported: arnika's `HKDF(QKD ‖ PQC)` is a *parallel* combination -- both secrets are obtained independently and combined once -- and the paper finds parallel schemes avoid the multiplicative latency of sequential ones. But its own parallel implementation is two strongSwan `key_exchange_t` plugins inside IKEv2, released as the QURSA plugin considered and not adopted below (the paper's reference [55]); and its latency critique names the *"sequential methods mandated by RFC 9370"*, which is what this project's IPsec lane uses (ECP-256, then ML-KEM-768). |
| *Quantum-safe IPsec in the banking industry* | [arXiv:2604.12985](https://arxiv.org/html/2604.12985v1) | 2026 deployment case study in a regulated sector — useful as a reality check on rotation cadence and operational constraints. |
| *Practical hybrid PQC-QKD protocols with enhanced security and performance* | [arXiv:2411.01086](https://arxiv.org/abs/2411.01086) | Security and performance analysis of the hybrid construction itself. |

### A different architecture, considered and not adopted

[`qursa-uc3m/qkd-plugins-strongswan`](https://github.com/qursa-uc3m/qkd-plugins-strongswan)
integrates QKD into strongSwan as an IKEv2 **key-exchange method** (proposals
of the form `aes128-sha256-qkd`), supporting both ETSI GS QKD 014 and 004. It
is the implementation behind arXiv:2507.09288's parallel construction (above).

That is a genuinely stronger claim than what this project does: a KE method
feeds the QKD secret into `SKEYSEED` directly, whereas RFC 8784 mixes the PPK in
via `prf+` afterwards. It was not adopted for two reasons, in order of weight:

1. **It does not interoperate.** A custom KE method requires the same plugin on
   both peers. RFC 8784 is a standard that any conforming implementation
   already speaks.
2. **Maintenance.** Nine commits, all by one author, the latest on 2026-07-15.
   Its build script defaults to strongSwan 6.0.0beta6 (overridable with `-v`),
   its README states testing on Ubuntu 22.04 and 24.04 only, and it is untested
   on the 6.1.0 this project pins.

Licensing is **not** a reason, although an earlier version of this list said it
was "unclear from the repository". The repository ships an MIT `LICENSE.txt`,
added on 2025-05-19; GitHub's detector reports NOASSERTION only because of the
contributor lines in its header. As a charon plugin it links against
GPL-2.0-or-later strongSwan, as any charon plugin does.

Worth revisiting if it matures, because the security argument is better.

### Referenced but **not** redistributed

| Work | Identifier | Licence | Why not included |
|---|---|---|---|
| A. Sanz, E. Salegi, A. Atutxa, D. Franco, J. Astorga, E. Jacob, *QuLore: An Adaptive Security Framework to Extend Quantum-Safe Communications to Real-World Networks* | [arXiv:2511.22416](https://arxiv.org/abs/2511.22416) | **CC BY-NC-ND 4.0** | NonCommercial **and** NoDerivatives. Redistributing it from a repository whose own licence permits commercial use is not clearly permitted, so only the citation is kept. Read it at the arXiv link. |

### Developments after this project's design freeze (2026-06 → 2026-09)

Re-checked 2026-09-25. These postdate the design and are recorded for the next
revision rather than being implemented here.

| Work | Identifier | Why it matters here |
|---|---|---|
| Dosan, **Spooren**, … **Hühn**, de Vries, *Secure Medical Data Transmission Using Quantum Key Distribution and Post-Quantum Cryptography in Real-World Fiber Networks* | [arXiv:2608.18869](https://arxiv.org/abs/2608.18869) (v1 2026-08-19, v2 2026-09-11, **CC BY 4.0**) | The field-deployment sequel to the paper this PoC reproduces, by overlapping authors. Entanglement-based BBM92 over about 140 km of mixed aerial and buried fibre in Thuringia, trusted nodes at Erfurt and Jena, with **arnika** delivering ETSI GS QKD 014 keys to hop-by-hop WireGuard tunnels. It layers post-quantum protection differently from this repository (below the table). Its measured link values (further below) are restated on `/physics` and `/protocol-lab`. |
| Paixão, Tomkelski, Freire *et al.*, *Real-Time VPN Traffic over ETSI GS QKD 014 Key Delivery* | [arXiv:2607.06602](https://arxiv.org/abs/2607.06602) (2026-07-07) | Binds the ETSI `key_ID` into the AES-GCM **AAD**, cryptographically tying the key identifier to the ciphertext. A concrete hardening this project does not yet do. |
| Malik, Anwar, Raza, *Beyond the Quantum Promise: A Security Analysis of Classical Control in QKD* | [arXiv:2608.07626](https://arxiv.org/abs/2608.07626) (2026-08-07) | Tamarin analysis of 23 ETSI/ITU-T QKD documents. Its finding **V3 (message reflection: MAC inputs lack role binding)** is worth checking against any shared-PSK control channel — see the open question in [`vici-ppk.md`](vici-ppk.md). |
| Blanco-Romero, Almenares Mendoza, García Rubio, Campo, Díaz Sánchez, *On the Practical Feasibility of Harvest-Now, Decrypt-Later Attacks* | [arXiv:2603.01091](https://arxiv.org/abs/2603.01091) (2026-03-01, **CC BY 4.0**) | Recasts HNDL as adversary economics rather than a date, with a testbed over TLS 1.2/1.3, QUIC and SSH. Because "retaining intercepted traffic is economically trivial", the levers that act on the adversary alone are **rekeying frequency and key size** — the argument for this project's rotation cadence, which shortens key epochs on the IPsec lane and not on the WireGuard lane ([`threat-model.md` §2.1](threat-model.md)). Names the absence of in-band ephemeral rekeying in TLS 1.3 and QUIC as a critical protocol gap (§1). **It does not discuss IPsec, IKEv2 or WireGuard**, so applying it to these lanes is this project's inference, marked as such in [`threat-model.md` §2.1](threat-model.md). |
| Grover, Haile, Pedersen, Uner, Erickson, *A Scenario-Based Evaluation of CRQC+AI Vulnerability Spectrum for TLS 1.3 Cryptographic Dependencies* | [arXiv:2608.23785](https://arxiv.org/abs/2608.23785) (2026-08-24, v2 2026-09-07, **CC BY 4.0**) | Puts RSA risk crossing **50% between 2030-2032** and PQC risk non-zero only after 2032-2035, and argues explicitly that **"crypto-agility and hybrid cryptographic deployment be considered necessary complements"**. The closest thing published in 2026-07/08 to a revised timeline, and it supports the hybrid thesis directly rather than by analogy. **No revised expert-elicitation survey exists in that window**, and the canonical RSA-2048 resource estimate (arXiv:2505.15917, Gidney) is **still unrevised at v1**. The physical-qubit counts have moved in preprints, though -- see the rows below and [`threat-model.md` §3](threat-model.md). |
| Webster, Peham, Cohen, RSA-2048 on fixed degree-8 connectivity | [arXiv:2609.21249](https://arxiv.org/abs/2609.21249) (2026-09-18, preprint, arXiv non-exclusive licence) | *"a 2048-bit RSA integer can be factored in one month with approximately 120 000 physical qubits"* at a physical error rate of $`10^{-3}`$, 1 µs code cycle and 10 µs reaction time. Builds on the QLDPC-based estimate that first went below $`10^{5}`$ physical qubits (arXiv:2602.11457, "Pinnacle"). Both are preprints under stated hardware assumptions, not demonstrations; they lower the count Gidney's 2025 estimate gave, which is unrevised. |
| Babbush, Zalcman, Gidney et al. (Google Quantum AI and co-authors), ECDLP-256; ECDSA.Fail point-addition circuits | [arXiv:2603.28846](https://arxiv.org/abs/2603.28846) (2026-03-30; v2 of 2026-04-15 fixed a bug that allowed an exploit against the zero-knowledge proof validating its circuits); [arXiv:2609.09582](https://arxiv.org/abs/2609.09582) v2 (2026-09-19) and its companion [arXiv:2609.28882](https://arxiv.org/abs/2609.28882) (2026-09-24), all **CC BY 4.0** | Computed for **secp256k1**, so for the classical halves here -- the IPsec lane's ECP-256 (P-256) and WireGuard's X25519 -- a same-order proxy, not an estimate. Babbush et al.: 256-bit ECDLP in fewer than 1200 logical qubits and 90 million Toffoli gates, under half a million physical qubits. ECDSA.Fail reports point-addition circuits below those thresholds under different accounting; the companion arXiv:2609.28882 says itself that its results *"concern individual window-selected additions, not complete Shor computations"*. |
| Cain, Xu, King, Picard, Levine, Endres, Preskill, Huang, Bluvstein, *Shor's algorithm is possible with as few as 10,000 reconfigurable atomic qubits* | [arXiv:2603.28627](https://arxiv.org/abs/2603.28627) (2026-03-30, preprint, arXiv non-exclusive licence) | The one 2026 estimate computed for **P-256** itself: discrete logarithms on P-256 *"could be just a few days for a system with 26,000 physical qubits"*, and Shor with *"as few as 10,000 reconfigurable atomic qubits"* -- the lowest physical count in this table, for neutral atoms under the paper's stated assumptions. |
| Häner, Tripier, Young, Naehrig et al., *Computing 256-bit elliptic curve discrete logarithms in 26 days on a fault-tolerant trapped-ion quantum computer with 20,000 qubits* | [arXiv:2609.05625](https://arxiv.org/abs/2609.05625) (2026-09-04, CC BY-NC-ND 4.0, cited only) | secp256k1 ECDLP with about 1450 logical qubits and 40 million Toffoli gates, compiled to a trapped-ion architecture. Like the rows above, a preprint under stated hardware assumptions, not a demonstration. |
| Wickramasinghe, Li, Jha, Shaghaghi, *Mind the Gap: Policy vs Reality in Post-Quantum TLS Deployment* | [arXiv:2607.29005](https://arxiv.org/abs/2607.29005) (2026-07-31, accepted to ACM IMC 2026, **CC BY 4.0**) | 2 billion handshakes over 1M domains from 11 vantage points. Finds **"National timelines and sectoral priorities show limited correspondence with observed deployment patterns"** and no meaningful PQ-TLS latency penalty. Useful as feasibility evidence: the gap this project works in is measured, not asserted. |
| Raubitzek, Strasser, Ramacher, Lebeth, **Neuhold**, Pacher, on national-scale QKD network planning | [arXiv:2604.06764](https://arxiv.org/abs/2604.06764) (2026-04-08, **CC BY 4.0**) | Monte-Carlo planning method giving **per-hop lengths and trusted-repeater counts** for a country-scale network: for Austria, a mean hop of 22.9 km and a maximum of 52.3 km after route adjustment (15.3 and 34.9 km raw). Shares an author with the paper this PoC reproduces. It gives **no distribution of hops per end-to-end path**, so it does not by itself justify `/paper-flow`'s 1-8 hop range; an earlier version of this row said it did. |

**How arXiv:2608.18869 layers PQC, and how this repository differs.** In the
paper, arnika injects QKD-only keys into each hop's WireGuard tunnel, and
post-quantum protection is a separate end-to-end tunnel between the two end
nodes, which the trusted nodes forward without holding its key. Here arnika
also HKDF-mixes the Rosenpass key into each hop's WireGuard PSK, so the PQC half
sits inside the per-hop tunnel -- in the multi-hop compose the relay holds both
legs' keys -- and a separate end-to-end layer exists only in the `/paper-flow`
simulation. The paper's PQC tool is **QuantShake**
([github.com/aparcar/quantshake](https://github.com/aparcar/quantshake), MIT, by
an author of the paper, marked unaudited in its own README), run with sntrup761
and, separately, ML-KEM-768 to show agility, renegotiating every 120 s, which is
QuantShake's shipped default.

### European regulator position, and why it cuts both ways

**BSI TR-02102-1** (Federal Office for Information Security, Germany),
[primary PDF](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Publications/TechGuidelines/TG02102/BSI-TR-02102-1.pdf?__blob=publicationFile).
Read directly 2026-08-29; both quotations are verbatim from the PDF text.

**On QKD, BSI is against**, jointly with European partner authorities:

> "the practical restrictions of QKD, such as limited transmission distances and
> the need to use specialised hardware, are severely limiting compared to the use
> of PQC mechanisms. Therefore, QKD is only suitable for specific use cases.
> Furthermore, in the opinion of the BSI, **QKD is currently not ready for use
> from a security point of view. For these reasons, the BSI does not recommend
> QKD protocols at this time.**"

**On the KEM this project actually ships, BSI is for it:**

> "Classic McEliece with the following parameters is considered to be
> cryptographically suitable for **the long-term protection of confidential
> information** at the security level targeted in this Technical Guideline:
> **mceliece460896**, mceliece6688128 and mceliece8192128"

`mceliece460896` is the exact parameter set in the pinned Rosenpass v0.2.3, which
`tests/test_rosenpass_kem_names_match_the_submodule.py` derives from the
submodule's own domain-separation label.

**Read that endorsement with its date attached.** The current TR-02102-1 is
dated **2026-01-23** (still Version 2026-01 on 2026-09-25), and a line of
cryptanalysis preprints on Classic McEliece began in **August 2026** — seven
months later. BSI has not revisited the Technical Guideline since, so the recommendation above is not a response to that
work; it predates it. The estimates, their explicit "not close to practical"
qualifiers, the objection to part of the line, and the designers' posting record
are set out in [`threat-model.md`](threat-model.md) section 4.1 rather than
summarised here, because the numbers are easy to quote without the conditions
they depend on.

| Source | Date | What it is |
|---|---|---|
| [ePrint 2026/1630](https://eprint.iacr.org/2026/1630) | recv. 2026-08-07, rev. 2026-08-27 | Ghoshal, Ishai, Jain, Sun — the hold-out distinguisher the line starts from |
| [ePrint 2026/1747](https://eprint.iacr.org/2026/1747) | recv. 2026-08-20, 8 revisions, last 2026-09-06 | Vedenev — turns the relations into key recovery |
| [ePrint 2026/1786](https://eprint.iacr.org/2026/1786) | recv. 2026-08-24, rev. 7 on 2026-09-15 | Saarinen — per-parameter-set conditional arithmetic estimates, incl. `mceliece460896` |
| [ePrint 2026/1810](https://eprint.iacr.org/2026/1810) | 2026-08-26 | Apon — algebraic-geometry lower bound **against** the Vedenev route |
| [ePrint 2026/1984](https://eprint.iacr.org/2026/1984) | 2026-09-11, rev. 2026-09-18 | Weis — key recovery from the distinguisher, with the "not close to practical" qualifier |
| [ePrint 2026/1986](https://eprint.iacr.org/2026/1986) | 2026-09-11, rev. 2026-09-24 (abstract unchanged) | Saarinen — solves the TII-254 **toy challenge**; makes no claim about any NIST parameter set |

All six are Creative Commons Attribution. IACR ePrint has had no default licence
since 2022, so each was checked on its own page rather than assumed.

**What this changes, and what it does not.** The judgement recorded in
[`vici-ppk.md`](vici-ppk.md) -- that the PQC half is not an approved KEM -- is a
statement about **NIST SP 800-227**, and it stays true. It is not a statement
about every authority: under BSI the same parameter set is recommended for
long-term confidentiality. Both framings are correct about different standards
and neither should be quoted as the other.

**Do not read the McEliece endorsement as European support for QKD.** BSI is on
record against QKD protocols in the same document. A project that mixes QKD with
PQC has to say which half each authority is endorsing.

**Nor is it the EU-level position on the KEM.** The approved-mechanism list for
EU-certified products, ECCG *Agreed Cryptographic Mechanisms* v2 (April 2025),
recommends ML-KEM and FrodoKEM for post-quantum key establishment and does not
list Classic McEliece; the v3.0 draft (April 2026, in public review until the
end of July 2026) lists the same two. Classic McEliece is a national (BSI)
recommendation, not an EU-agreed mechanism. The companion ENISA report
*Hybridization of traditional cryptographic mechanisms with PQC --
Standardisation Status* (2026-04-30) covers the RFC 9370 / ML-KEM IKEv2 route
this project's IPsec lane uses, and states that it does not itself establish a
recommendation. All three are linked from ENISA's
[EUCC cryptography guidelines page](https://certification.enisa.europa.eu/publications/eucc-guidelines-cryptography_en).

---

**Measured field values from arXiv:2608.18869** (Table I, v2). They are shown
beside this project's model on `/physics` and used as the Thuringia preset on
`/protocol-lab`, but never fitted into the model. Fed these campaign-mean
losses and QBERs, this project's weak-coherent decoy-BB84 model gives
**0 bit/s on both links**, for reasons that differ by link:

- **Sundhausen–Erfurt** (17 dB, mean QBER 13.3 %) is past the model's error
  threshold: about 6 % in the infinite-block limit, and about 2.4 % with the
  shipped block of $`10^{9}`$ pulses. The paper says the same of its own link.
  The campaign-mean QBER was above the key-generation threshold, key came only
  from intervals in which the instantaneous QBER stayed low, and the reported
  average rate *"cannot be inferred directly from the average QBER"* (v2,
  section IV.A; the sentence is absent from v1). So the model's zero beside a
  measured 12.7 bit/s is not a model-versus-link gap: a campaign mean is the
  wrong input for either.
- **Jena–Erfurt** (21 dB, 6.1 %) fails on two counts. It is past the
  finite-key loss cut-off of about 19.7 dB that the shipped block size and
  misalignment give, and 6.1 % is just past the model's roughly 6 % asymptotic
  error threshold. The loss cut-off moves with block size; the error threshold
  does not. The averaging caveat above does not apply here: this link's QBER
  varied little (6.1 ± 0.8 %).

Both are set against 12.7 and 22.2 bit/s measured by an entanglement-based
BBM92 system the model does not describe. The two campaigns ran separately, for
22 and 2 days:

| Link | Length | Loss | Secret key rate | QBER | Coincidences |
|---|---|---|---|---|---|
| Sundhausen–Erfurt (51 km aerial, 19 km buried) | 70 km | > 17 dB | $`12.7 \pm 10.3`$ bit/s | $`13.3 \pm 9.6\,\%`$ | $`311.9 \pm 15.7`$ Hz |
| Jena–Erfurt (4 km aerial, 65 km buried) | 69 km | > 21 dB | $`22.2 \pm 4.7`$ bit/s | $`6.1 \pm 0.8\,\%`$ | $`398.6 \pm 14.3`$ Hz |

The coincidence rates were taken with different coincidence windows and are not
comparable across the two links: the paper attributes their difference mainly
to the windows, not to fibre attenuation (v2, section IV.A).

Two things follow. The mostly aerial link shows **about twice the QBER of the
mostly buried one despite lower attenuation**, measured in separate campaigns
that the paper notes also differ in fibre type, season and equipment, and its
QBER correlates with the 10 m gust peak (r = 0.78 at 15-minute resolution,
section IV.B) -- so loss alone is a poor predictor and this project's static
channel model is optimistic. And at
12-22 bit/s a single 256-bit key takes **12-20 seconds** to accumulate, so on
links like these a rotation interval is bounded by the secret key rate, not
chosen by policy; this project's 30 s default would sit just above that floor.
The paper's **120 s is its PQC renegotiation interval** (QuantShake's shipped
default, section IV.B), not a QKD key rotation; it does not say how often
arnika rotated the WireGuard PSK. arnika v1.x's recommended interval was also
120 s (D6.1, section 3 below) -- a separate source for the same number, and one
that describes v1.x, not the pinned code.

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
| 1002 km twin-field QKD — longest fibre QKD distance to date, on **spooled laboratory fibre** (<0.157 dB/km, 156.5 dB total), **not** deployed fibre. At that distance the rate is $`9.53 \times 10^{-12}`$ per pulse (~0.0034 bit/s) and **asymptotic only**; the longest finite-size distance in the PRL is 952 km. Finite-key security at the full 1002 km ($`3.11 \times 10^{-12}`$ per pulse) is shown in the companion paper. | Y. Liu *et al.*, Phys. Rev. Lett. **130**, 210801 (2023), [doi:10.1103/PhysRevLett.130.210801](https://doi.org/10.1103/PhysRevLett.130.210801); finite-key: Y. Liu *et al.*, Quantum Front. **2**, 16 (2023), [doi:10.1007/s44214-023-00039-9](https://doi.org/10.1007/s44214-023-00039-9) |
| 254 km twin-field QKD over a **live commercial telecom network** (Frankfurt-Kehl), 110 bit/s, non-cryogenic detectors — the figure that matters for real-world deployment. Longer *installed dark-fibre* spans exist: a 428 km field test, and a 511 km Qingdao-Jinan link that is 430 km deployed trunk plus 81 km of added spool. | M. Pittaluga *et al.*, Nature **640**, 911 (2025), [doi:10.1038/s41586-025-08801-w](https://doi.org/10.1038/s41586-025-08801-w); J.-P. Chen *et al.*, Nat. Photon. **15**, 570 (2021), [doi:10.1038/s41566-021-00828-5](https://doi.org/10.1038/s41566-021-00828-5) |
| 115.8 Mbit/s at 10 km — highest peer-reviewed secret-key rate for discrete-variable QKD as of 2026-09-25 (a Crossref title search of QKD papers published 2026-09-01 to 09-25 found no higher discrete-variable rate; not exhaustive) (decoy-state BB84, 2.5 GHz clock, standard G.652 spooled fibre, composable finite-size security); the same system reaches 328 km of ultralow-loss fibre | W. Li, L. Zhang, F. Xu, J.-W. Pan *et al.*, Nat. Photon. **17**, 416 (2023), [doi:10.1038/s41566-023-01166-4](https://doi.org/10.1038/s41566-023-01166-4) |
| 64 Mbit/s at 10.0 km and 3.0 Mbit/s at 102.4 km (2.5 GHz time-bin QKD with real-time key distillation) — the companion paper in the same issue, pp. 422-426. This table previously labelled it "highest secret-key rate"; it was not the highest even in its own issue. | F. Grünenfelder, A. Boaron *et al.*, Nat. Photon. **17**, 422 (2023), [doi:10.1038/s41566-023-01168-2](https://doi.org/10.1038/s41566-023-01168-2) |
| 12 900 km satellite QKD, portable ground station | Y. Li *et al.*, Nature **640** (2025), [doi:10.1038/s41586-025-08739-z](https://doi.org/10.1038/s41586-025-08739-z) |

> **Records are scope-dependent.** The rate figure above is discrete-variable on spooled
> fibre with finite-size security. The highest peer-reviewed *continuous-variable* rate is
> 18.93 Mbit/s over 25 km (M. Wu *et al.*, Phys. Rev. X **16**, 021039 (2026),
> [doi:10.1103/882y-w4zy](https://doi.org/10.1103/882y-w4zy)). A higher CV figure --
> 153.22 Mbit/s asymptotic / 149.99 Mbit/s finite-size over 24.3 km of anti-resonant
> hollow-core fibre -- exists in preprint only (arXiv:2607.14704, 2026-07) and is not
> peer-reviewed. Verified against Crossref and arXiv on 2026-08-22.

### Topology presets for `/protocol-lab`

Numbers restated with references in
`services/webui-frontend/src/lib/sim/protocolLab/publishedNetworks.ts`; licences
and what is and is not reused are in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). A "Czech National 13-node"
network, named in an early plan, was not used: no source for one was found.

| Network | Source |
|---|---|
| Cambridge quantum network (3 nodes, 2019) | Dynes et al., npj Quantum Inf. 5, 101 (2019), [doi:10.1038/s41534-019-0221-4](https://doi.org/10.1038/s41534-019-0221-4) |
| SECOQC, Vienna (6 nodes, 2008) | Peev et al., New J. Phys. 11, 075001 (2009), [doi:10.1088/1367-2630/11/7/075001](https://doi.org/10.1088/1367-2630/11/7/075001) |
| Tokyo QKD Network (6 nodes, 2010) | Sasaki et al., Opt. Express 19, 10387 (2011), [doi:10.1364/OE.19.010387](https://doi.org/10.1364/OE.19.010387) |
| MadQCI, Madrid (9 nodes, 2024) | Martin et al., npj Quantum Inf. 10, 80 (2024), [doi:10.1038/s41534-024-00873-2](https://doi.org/10.1038/s41534-024-00873-2) |
| Thuringia medical-data chain (4 nodes, 2026) | Dosan et al., [arXiv:2608.18869](https://arxiv.org/abs/2608.18869) (above) |

### Simulators

| Work | Identifier |
|---|---|
| D. Soler *et al.*, *QKDNetSim+: Improvement of the quantum network simulator for NS-3*, SoftwareX **26** (2024). Earlier versions of this row credited M. Mehic, who wrote the original QKDNetSim; Crossref lists Soler, Cillero, Dafonte, Fernández-Veiga, Fernández Vilas and Nóvoa (checked 2026-09-25) | [doi:10.1016/j.softx.2024.101685](https://doi.org/10.1016/j.softx.2024.101685) |
| X. Wu *et al.*, *SeQUeNCe: a customizable discrete-event simulator of quantum networks*, Quantum Sci. Technol. **6**, 045027 (2021) | [doi:10.1088/2058-9565/ac22f6](https://doi.org/10.1088/2058-9565/ac22f6) |

---

## 2. Standards

### ETSI — QKD

| Standard | Version | Status (re-checked 2026-09-25) |
|---|---|---|
| **GS QKD 014** — Protocol and data format of REST-based key delivery API | V1.1.1 (2019-02) | Current. Implemented by [`services/bb84-kme/app/etsi014.py`](../services/bb84-kme/app/etsi014.py). [PDF](https://www.etsi.org/deliver/etsi_gs/QKD/001_099/014/01.01.01_60/gs_qkd014v010101p.pdf) |
| GS QKD 014 **Edition 2** | draft (`RGS/QKD-014ed2_KeyDeliv`) | Stable draft since 2025-06-02 (ETSI work item 69542, v1.3.1), unpublished as of 2026-09-25. Breaking: paths move to `/kdapi/v2/`, GET is removed, SAE IDs move into the body, master/slave → initiator/target. **Not implemented here.** [forge](https://forge.etsi.org/rep/qkd/gs014-key-deliv) |
| GS QKD 004 — Application interface | V2.1.1 (2020-08) | Current. Edition 3 (`RGS/QKD-004ed3_AppIntf`) was a stable draft, V3.1.1 dated 2026-05-23, unpublished on 2026-09-25 and incompatible (it renumbers the status codes); its next status is TB approval, targeted for 2026-12-02. V2.1.1 is simulated on `/protocol-lab` and implemented in `bb84-kme` over this project's own HTTP/JSON binding, off by default -- see [`etsi004-binding.md`](etsi004-binding.md). The specification defines no wire format. [PDF](https://www.etsi.org/deliver/etsi_gs/QKD/001_099/004/02.01.01_60/gs_qkd004v020101p.pdf) |
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
| RFC 9867 | Mixing PSKs in `IKE_INTERMEDIATE` and `CREATE_CHILD_SA` (Nov 2025) | Would let a PPK be refreshed on rekey without a full reauthentication. **strongSwan 6.1.0 does not send it**; libreswan has implemented the mechanism since v5.2 and uses the RFC's codepoints since v5.4. See [RFC 9867 implementations](#rfc-9867-implementations) below. |
| RFC 7296 | IKEv2 | §2.15 defines the AUTH payload, i.e. the only place a plain PSK is used |
| RFC 7383 | IKEv2 Fragmentation | Required for ML-KEM-sized payloads |
| RFC 7696 | Guidelines for Cryptographic Algorithm Agility | Crypto-agility framing |
| draft-ietf-ipsecme-ikev2-mlkem-09 | ML-KEM in IKEv2 | IESG-approved 2026-07-07, in the RFC Editor queue (no number yet, "Awaiting First editor"; unchanged from 2026-08-13 to 2026-09-25). Assigns transform IDs 35/36/37 to ML-KEM-512/768/1024 — the values this project's proposals already rely on. |
| draft-ietf-ipsecme-ikev2-pqc-auth-12 | PQC signature authentication in IKEv2 | **IESG-approved 2026-08-24**, after the only DISCUSS (entered 2026-08-18) was cleared on -12 on 2026-08-21. In the RFC Editor queue since 2026-08-25; no RFC number as of 2026-09-25. strongSwan 6.1.0 ships no ML-DSA (nothing under `src/` at `b43f6bfe`); ML-DSA IKEv2 authentication exists only on the unmerged `ml-dsa` branch (strongswan/strongswan#2626, open on 2026-09-25). strongSwan's standards table nonetheless leaves this draft and the ML-DSA certificate draft blank, which by its own legend means supported: the table is not release-scoped (see below). An earlier version of this row said strongSwan "gates its ML-DSA release on this draft"; no source for that was found. PQ *authentication* is therefore unavailable on this lane; this project uses PQ *key exchange* plus PPK, which do not depend on it. |
| draft-ietf-lamps-pq-composite-sigs-19 | Composite ML-DSA for X.509 | IESG-approved, in the RFC Editor queue since 2026-04-23 ("Awaiting Second editor" since 2026-09-23). Composite ML-DSA plus traditional signatures in certificates: the certificate side of PQ authentication, which this lane does not have. |
| RFC 9794 | Terminology for Post-Quantum Traditional Hybrid Schemes | Vocabulary |

#### RFC 9867 implementations

**strongSwan 6.1.0 does not send RFC 9867**, stated as two reproducible
observations rather than a flat claim, and re-checked against 6.1.0 on
2026-09-16 when the pin moved up from 6.0.7: `USE_PPK_INT` (16445) and
`PPK_IDENTITY_KEY` (16446) appear nowhere under `src/`, just above the top of
the Status Type range; and the `IKE_SA_INIT` response on this lane carries
`N(USE_PPK)`, and RFC 9867 section 3.1 has a responder return that or
`N(USE_PPK_INT)`, never both, so the notify settles which specification is
running. Both are set out, with the notify values around them, in
[`vici-ppk.md`](vici-ppk.md) section 2, which is where this analysis lives.

strongSwan's own standards table agrees, and is corroboration rather than
proof. It lives in the separate
[`strongswan/strongswan-docs`](https://github.com/strongswan/strongswan-docs/blob/master/docs/modules/ROOT/pages/features/ietf.adoc)
repository, rendered at
[docs.strongswan.org/docs/latest/features/ietf.html](https://docs.strongswan.org/docs/latest/features/ietf.html),
and not in `submodules/strongswan` (the pinned 6.1.0 tree has no `docs/`
directory), so it cannot be checked against the submodule. Its legend reads
`S = Status: x = not supported, d = under development`, with blank meaning at
least partially implemented. RFC 9867 carries `x`; RFC 8784, RFC 9242 and
RFC 9370 are blank. **The table is not release-scoped**: it also leaves
draft-ietf-ipsecme-ikev2-pqc-auth and draft-ietf-lamps-dilithium-certificates
blank, although 6.1.0 contains no ML-DSA code. So its `x` for RFC 9867 agrees
with the source-level observations but could not stand in for them.

**libreswan implements the mechanism, and the version history matters.**
libreswan added PPK in the `IKE_INTERMEDIATE` exchange in **v5.2**
(2025-02-26), as draft-ietf-ipsecme-ikev2-qr-alt-04, on private-use notify
values 50208 and 50209. **v5.4** (2026-08-13) is the first tag to use the IANA
allocations 16445 and 16446 (`include/ietf_constants.h`, commented
`RFC-ietf-ipsecme-ikev2-qr-alt`), which makes it wire-compatible with RFC 9867's
codepoints. `USE_PPK_INT` is handled in `programs/pluto/ikev2_ike_sa_init.c`;
`ikev2_ppk.c` and `ikev2_ike_intermediate.c` carry `PPK_IDENTITY_KEY`. v5.4's
release notes do not mention PPK or RFC 9867, and its code comments still cite
draft -04, while the RFC was published from -10. **Conformance with the final
RFC is not verified here**; only the codepoints are.

An earlier version of this entry said "No open-source IKEv2 implementation
exists", and the correction that replaced it overshot to "libreswan v5.4
implements RFC 9867". libreswan is not vendored here, so neither statement was
checkable against this repository, and the second credited v5.4 with work that
landed in v5.2. What it means for the project is unchanged: consuming fresh QKD
material on every rekey is available today by changing IKE daemon, not only by
waiting for strongSwan.

### NIST

| Publication | Title | Status |
|---|---|---|
| FIPS 203 | ML-KEM | Final, 2024-08-13. Planning note of 2025-11-17: an issue will be corrected in a future update; see the "Errata (potential updates)" spreadsheet on the [FIPS 203 page](https://csrc.nist.gov/pubs/fips/203/final). |
| FIPS 204 | ML-DSA | Final, 2024-08-13. Planning note of 2026-07-31: several minor issues will be corrected in a future update; see the "Errata (potential updates)" spreadsheet on the [FIPS 204 page](https://csrc.nist.gov/pubs/fips/204/final). |
| FIPS 205 | SLH-DSA | Final, 2024-08-13 |
| FIPS 206 | FN-DSA (Falcon) | **No public draft as of 2026-09-25** (`/pubs/fips/206/ipd` -> 404; the FIPS index stops at 205). Do not plan around it. |
| **SP 800-227** | Recommendations for Key-Encapsulation Mechanisms | **Final, Sept 2025.** §4.6.1 acknowledges that a multi-algorithm scheme may include a secret established via QKD, and requires ("shall") an approved key combiner of the kinds §4.6.2 describes, from SP 800-56C or SP 800-133. See the appendix of [`vici-ppk.md`](vici-ppk.md) for how far this project meets that. [doi:10.6028/NIST.SP.800-227](https://doi.org/10.6028/NIST.SP.800-227) |
| SP 800-56C Rev. 2 | Key-Derivation Methods in Key-Establishment Schemes | Defines the hybrid shared secret $`Z' = Z \parallel T`$. **Revision announced 2026-01-06** ([planning note](https://csrc.nist.gov/pubs/sp/800/56/c/r2/final)), with the stated goals of letting $`Z`$ incorporate a shared secret from an approved KEM and allowing more flexible formatting of hybrid shared secrets -- both bear on the combiner analysis in `vici-ppk.md`. No draft yet: `/pubs/sp/800/56/c/r3/ipd` returned 404 on 2026-09-25. |
| SP 800-133 Rev. 2 | Recommendation for Cryptographic Key Generation | The other source of approved combiners that SP 800-227 §4.6.2 draws on (key combining in §6.3). **Rev. 3 initial public draft, 2026-04-17** ([page](https://csrc.nist.gov/pubs/sp/800/133/r3/ipd); comments closed 2026-06-16): renumbers key combining to §5.3 and asks for comments on hybrid implementations. Rev. 2 remains current. |
| SP 800-131A Rev. 3 | Transitioning the Use of Cryptographic Algorithms | **Initial public draft, 2024-10-21; still not final.** `/r3/final` returns 404, so **Rev. 2 (2019-03-21) remains the effective version**. |
| SP 800-208 | Stateful Hash-Based Signatures | LMS/XMSS |
| SP 800-230 | Additional SLH-DSA Parameter Sets for Limited Signature Use Cases | **Initial public draft, 2026-04-13** ([page](https://csrc.nist.gov/pubs/sp/800/230/ipd); comments closed 2026-06-12). New SLH-DSA parameter sets for use cases that need only a limited number of signatures; not in FIPS 205 and not among the sets the WebUI's agility matrix covers. |
| CSWP 39 | Considerations for Achieving Cryptographic Agility: Strategies and Practices | **Final, 2025-12-19** ([page](https://csrc.nist.gov/pubs/cswp/39/considerations-for-achieving-cryptographic-agility/final)). NIST's own crypto-agility paper; this project's agility framing otherwise rests on RFC 7696. |
| IR 8547 | Transition to Post-Quantum Cryptography Standards | **Initial public draft, 2024-11-12; comments closed 2025-01-10; still not final** (`/ir/8547/final` and `/2pd` -> 404, re-checked 2026-09-25). Its 2030-deprecated / 2035-disallowed dates are widely quoted as settled NIST policy and are not. Binding US civilian dates do exist independently of it: EO 14412 and OMB M-26-15 set 2030-12-31 for PQC key establishment and 2031-12-31 for PQC signatures on federal HVAs and high-impact systems ([`threat-model.md` §5](threat-model.md)). |
| IR 8545 | Status Report on the Fourth Round | HQC selected 2025-03-11 as backup KEM. No draft FIPS for it yet: `/pubs/fips/207/ipd` returned 404 on 2026-09-25. |
| IR 8610 | Status report advancing nine candidates to the third round of the additional digital signature process | **Published 2026-05-14** ([page](https://csrc.nist.gov/pubs/ir/8610/final)). The pinned liboqs 0.16.0 includes several additional-signature candidates (CROSS, MAYO, MQOM, SNOVA, UOV); none is standardised, and which of them advanced is recorded in the report itself. |

### Cryptographic combiners

| Work | Identifier |
|---|---|
| F. Giacon, F. Heuer, B. Poettering, *KEM Combiners*, PKC 2018 | [ePrint 2018/024](https://eprint.iacr.org/2018/024) |
| N. Bindel, J. Brendel, M. Fischlin, B. Goncalves, D. Stebila, *Hybrid Key Encapsulation Mechanisms and Authenticated Key Exchange*, PQCrypto 2019 | [ePrint 2018/903](https://eprint.iacr.org/2018/903) |
| M. Barbosa *et al.*, *X-Wing: The Hybrid KEM You've Been Looking For* | [IACR CiC 1(1) (2024)](https://cic.iacr.org/) · [draft-connolly-cfrg-xwing-kem](https://datatracker.ietf.org/doc/html/draft-connolly-cfrg-xwing-kem) (despite the name, in the Independent Submission stream, not a CFRG document; -11 posted 2026-09-23) |

---

## 3. Software

Licences for everything vendored under `submodules/` are recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Key upstreams:

| Project | Role | Licence |
|---|---|---|
| [arnika](https://github.com/arnika-project/arnika) | QKD/PQC key management; the key-writer port this project extends | Apache-2.0 |
| [strongSwan](https://github.com/strongswan/strongswan) | IKEv2 daemon (pinned 6.1.0) | GPL-2.0 + OpenSSL exception |
| [govici](https://github.com/strongswan/govici) | Official VICI client (pinned v0.8.2) | MIT |
| [Rosenpass](https://github.com/rosenpass/rosenpass) | Post-quantum key exchange for WireGuard | MIT / Apache-2.0 |
| [liboqs](https://github.com/open-quantum-safe/liboqs) | PQC reference implementations | MIT |
| [TNO-Quantum `qkd_key_rate`](https://github.com/TNO-Quantum/communication.qkd_key_rate) | Independent key-rate cross-check | Apache-2.0 |

Rosenpass was funded by NLnet **NGI Assure** (grant agreement No. 957073); that
grant period **ended in 2024**. arnika v1.x is a result of the EU **EUROQCI /
QCI-CAT** project (DIGITAL-2021-QCI-01, No. 101091642), co-funded by Austria's
National Foundation for Research, Technology and Development. QCI-CAT started
on 2023-01-01, and the end date on its deliverable covers moved in stages --
2025-06-30 on D6.1, 2025-12-31 on D8.3, 2026-03-31 on D4.2 v1.1 and D8.2 v1.3 --
so the project has ended. The initial prototype and earlier versions were
developed at CANCOM Converged Services GmbH; since **Q2 2026** the people behind
arnika have maintained it at **XBC Digital GmbH**, and the pinned `main` is that
later work rather than the QCI-CAT v1.x line. The Credits section of
`submodules/arnika/README.md` records both.

### arnika v1.x's design document, and what it settles

[**QCI-CAT D6.1**](https://qci-cat.at/wp-content/uploads/2026/03/QCICAT-D6.1-Report-on-HSM-key-wrapping-via-QKD-based-VPN_v1.0-2025-02-27.pdf)
(v1.0, dated 2025-02-17 in its revision history and 2025-02-27 in its file
name; 42 pp) is the deliverable arnika v1.x was built for. Its document owner is
CANCOM / A. Neuhold, and its authors are A. Neuhold and G. Swoboda of CANCOM,
arnika's original developers.

**Their use case is not this one**, and the distinction matters before anything
below is quoted: their subject is key-wrapping between a pair of hardware
security modules, and this repository implements no HSM, no PKCS#11 and no
partition cloning. The deliverable is cited here for what it records about
arnika, which this project does use.

The **project web page** for that use case is three paragraphs of summary and
names none of the terms below. The site's news posts mention arnika, WireGuard
and Rosenpass at summary level -- a Grazer Linuxtage 2025 talk and the IDSF
2025 demonstration -- and none of them mentions strongSwan, IPsec, rekeying or
rotation (the site's own search, 2026-09-25). Read the PDF, not the pages.

D6.1 describes **arnika v1.x**, and three things in it bear on this
repository, each with that scope:

1. **Rotation cadence.** D6.1 recommends an interval of *"120 seconds (default
   value)"*, to align with WireGuard, which rekeys *"after 120 seconds or after
   $`2^{60}`$ messages"*. The exponent is a superscript in the PDF, and
   plain-text extraction flattens it to "260"; an earlier version of this entry
   quoted the flattened form. The "default value" is v1.x's: the pinned
   `config/config.go` defaults `INTERVAL` to 10 s, and upstream's README
   examples use 120 s. This deployment runs `ARNIKA_INTERVAL=30s`, a deviation
   recorded at the setting itself in `docker-compose.strongswan.yml`; on the
   WireGuard lane it means the key epoch is WireGuard's rekey interval, not the
   rotation interval ([`threat-model.md` §2.1](threat-model.md)).
2. **A failed rule yields a mismatched key, by design.** D6.1 describes v1.x's
   peer synchronisation as a few simple rules -- the peer that receives a
   `key_id` first becomes the passive backup for the interval -- and says that
   any event that breaks one of them produces a different pre-shared key and so
   a non-working tunnel. The pinned code no longer uses that election. Since
   upstream commit `acc2387` (2026-03-10) the role is drawn afresh every
   interval from an HMAC-SHA256 of the interval number, keyed with
   `ARNIKA_PSK` and XORed with `ARNIKA_ID` (`IsPrimary` in
   `config/config.go`), which is why the peers' IDs must differ in parity. What
   survives is the exchange itself: PRIMARY sends the `key_id` and BACKUP
   resolves it, and that handover is where this project's intermittent PPK
   mismatch was investigated ([`vici-ppk.md`](vici-ppk.md), "Known
   limitation"). D6.1's statement is v1.x design intent, not evidence about the
   current code path.
3. **IPsec was evaluated and not chosen, partly over patents.** D6.1 says the
   use case *"favored WireGuard over IPSEC"* for its simplicity, efficiency and
   modern design, and records that several methods for post-quantum IPsec have
   been patented, naming US7602919B2 and CN101142779A. Two consequences,
   opposite in sign: the IPsec/VICI lane here is **not** duplicated work
   relative to QCI-CAT, and a patent landscape flagged by a partner in that
   consortium is a risk item any QKD-over-IPsec plan should read before relying
   on it. Google Patents lists US7602919B2 as active with an anticipated expiry
   of 2027-06-20 (read 2026-09-25); this is not legal advice.

**Licence position.** D6.1 says arnika was published on GitHub *"under
open-source license Apache 2.0"*, while its own copyright statement makes the
document the property of the QCI-CAT Consortium and grants no right or licence
in it. **The code is Apache-2.0 and unencumbered; the deliverable is not.** So
it is cited and linked, facts are drawn from it, and quotations from it are
kept to a few words each; its figures and longer passages are paraphrased or
left out. That matches the position [`threat-model.md`](threat-model.md)
section 7 takes for qci-cat.at itself: the site's legal notice leads to AIT's
imprint, whose terms have not been reviewed here, so nothing relies on a
licence from either.

**A related deliverable.**
[QCI-CAT D8.3, *PQC-hardened Key Management Systems for QKD*](https://qci-cat.at/wp-content/uploads/2026/03/QCI-CAT-D8.3-PQC-Hardened-KMS-V1.1-2025-05-21.pdf)
(AIT, v1.1, 2025-05-31) extends AIT's KMS with post-quantum key exchange,
including on the ETSI 014 interface between a security application and its KMS.
It is the reference design for a post-quantum transport on that link, which
this repository runs as plain HTTP between arnika and the KMEs.

---

## 4. Positions worth reading against this work

QKD is not universally endorsed, and this project should not be read as
claiming otherwise:

- **NSA**, [Quantum Key Distribution (QKD) and Quantum Cryptography (QC)](https://www.nsa.gov/Cybersecurity/Quantum-Key-Distribution-QKD-and-Quantum-Cryptography-QC/) — does not support QKD for national-security systems, and recommends post-quantum cryptography instead.
- **UK NCSC**, [Quantum networking technologies](https://www.ncsc.gov.uk/paper/quantum-networking-technologies) (2025-08-05) — "The NCSC will not support the use of QKD for government or military applications. PQC is the best mitigation to the threat to cryptography from quantum computers." For other sectors, QKD "should not be solely relied upon", and QKD "should not constitute evidence towards assessments of security of data-in-transit under the NCSC's Cyber Assessment Framework". This calls itself "an updated analysis" of the 2020 white paper [Quantum security technologies](https://www.ncsc.gov.uk/paper/quantum-security-technologies), which **remains published**; the legacy `/whitepaper/` alias has redirected here since around August 2025. The change between them is the verb, not the scope: 2020 already read "does not endorse the use of QKD for **any government or military applications**". Quoting the 2020 line without that scope invents a broadening that did not happen.
- **ANSSI / BSI / NLNCSA / Swedish Armed Forces**, [Position Paper on Quantum Key Distribution](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Crypto/Quantum_Positionspapier.pdf) (2024-01-26) — QKD "can however currently only be used in practice in some niche use cases" and is "not yet sufficiently mature from a security perspective"; migration to PQC is "the clear priority". The fourth signatory is the **Swedish** authority, not the UK NCSC, which this list previously named by mistake. The Czech NÚKIB issued a Letter of Support (2024-09-19) but is not a signatory.
- **US Department of War**, [Post Quantum Cryptography Strategy](https://dowcio.war.gov/Portals/0/Documents/Library/DoW-PQC-Strategy.pdf) (signed 2026-04-01) — the most direct objection to what this project builds, and therefore the one most worth stating here. Under "Do Not Introduce New Security Risks" it names, verbatim, "quantum key distribution (QKD) and quantum networking, **solutions combining QKD with other cryptographic key establishment**, or non-local quantum randomness generation" as technologies that "will not be used as a means for achieving security for confidentiality, data or entity authentication, key distribution, or non-local randomness generation". The companion CIO memo [Preparing for Migration to Post Quantum Cryptography](https://dowcio.war.gov/Portals/0/Documents/Library/PreparingForMigrationPQC.pdf) (2025-11-18) says Components "will not test, evaluate, pilot, use, or procure" them (item 2.a, *"Quantum Confidentiality or Keying Technologies"*), and goes further, into the mechanism this project uses to deliver the key. Item 3.a phases out *"Use of cryptographic pre-shared keys (PSK) for providing quantum resistance in solutions where the PSK is not provisioned through NSA KMI for Type 1 devices"*, to be replaced by NIST-approved (for NSS, CNSA 2.0-listed) asymmetric PQC key establishment *"no later than December 31, 2030, unless otherwise directed or provided exception by the point of contact above"*, and adds that Components *"will not test, pilot, use, or procure commercial PSK-based solutions for quantum resistance effective immediately."* Item 3.b does the same for *"Symmetric key establishment protocols, symmetric key agreement protocols, and symmetric key distribution protocols"*, by 2030-12-31 or 2031-12-31 for solutions registered with NSA CSfC, with the same waiver wording and an exemption for use cases in place before 2010.

  Qualifications, so this is neither overstated nor waved away. The two items are **scoped differently**. Item 2 bars testing, evaluating, piloting, using or procuring the technologies it lists "for the purposes of providing confidentiality, authenticity, or integrity in DoW networks and communications". Item 3 carries no such phrase: it binds DoW Components directly (*"will phase out and replace all of the following types of cryptographic solutions"*), and its only qualifier of purpose is quantum resistance, in 3.a and in both no-procurement sentences. Items 2.a, 3.a and 3.b each name a **waiver path** ("provided exception by the point of contact above"); the two no-procurement sentences, effective immediately, carry none of their own. It is a procurement and accreditation rule for one national-security enterprise, not a claim that the construction is cryptographically unsound. The memo names no protocol, so reading item 3.a as covering an RFC 8784 / RFC 9867 PPK used for quantum resistance is this project's inference -- a direct one, set out in [`threat-model.md` §5](threat-model.md). By that reading both the QKD half and the PPK delivery are disallowed by default in that setting, and no amount of favourable NIST language changes that.

- **EU NIS Cooperation Group**, [*EU Roadmap on PQC -- Frequently Asked Questions*](https://ec.europa.eu/newsroom/dae/redirection/document/132120) (2026-04-15) — where the roadmap itself is silent on QKD (below), its FAQ is explicit: *"QKD is currently not considered a viable quantum-safe alternative"* (section 5.6), and *"The EU Roadmap on PQC does not consider hybrids mechanisms using quantum key distribution (QKD) or using more than one PQC mechanism"* (section 3.1). Under that definition neither arnika's QKD ‖ PQC combination nor Rosenpass's McEliece + Kyber pairing is a "hybrid". The FAQ also asks Member States for initial national roadmaps by the end of 2026.
- **Japan**, inter-ministerial liaison council on PQC use in government agencies, [interim summary](https://www.cas.go.jp/jp/seisaku/pqc/pdf/report_202511.pdf) (2025-11, in Japanese) — besides Singapore's handbook ([`threat-model.md` §5](threat-model.md)), the one national instrument surveyed that treats QKD as an option. In this project's translation, it says that "depending on the usage environment" one could consider combined use of PQC with current cryptography, or "introducing quantum key distribution (QKD)"; the original says such options "could be considered", which is weaker than an endorsement, and it does not describe the composite built here. It targets migration of government systems by 2035, with a roadmap to follow. Japan's approved list, [CRYPTREC LS-0001-2022R2](https://www.cryptrec.go.jp/list/cryptrec-ls-0001-2022r2.pdf) (updated 2026-03-30), adds ML-KEM-768 and ML-KEM-1024 as its only post-quantum key-establishment entries: no Classic McEliece and no ML-KEM-512.
- **BSI**, [TR-02102-1 v2026-01](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Publications/TechGuidelines/TG02102/BSI-TR-02102-1.pdf) (2026-01-23) — Germany's operative crypto guideline now states plainly that "**the BSI does not recommend QKD protocols at this time**". This is a harder line than the 2022 BSI brochure, which recommended QKD "only as an add-on in hybrid mode"; that brochure has not been revised since and should not be cited as the current position.

Worth recording because it is easy to miss: in the European and G7 policy
documents QKD is mostly written out rather than argued down. It appears **zero
times** in the EU NIS Cooperation Group's [Coordinated Implementation Roadmap for the
Transition to Post-Quantum Cryptography](https://digital-strategy.ec.europa.eu/en/library/coordinated-implementation-roadmap-transition-post-quantum-cryptography)
(2025-06), zero times in the [G7 Cybersecurity Working Group statement](https://www.cyber.gc.ca/en/news-events/g7-cybersecurity-working-group-statement-preparing-post-quantum-cryptography-migration)
(2026-06) and in the G7 group's follow-up
[*Preparing for the Post-Quantum Era: A Call to Action*](https://www.cyber.gc.ca/en/news-events/g7-cybersecurity-working-group-call-action-preparing-post-quantum-era)
(2026-09-03), and zero times in the ECCG *Agreed Cryptographic Mechanisms* v2.0
(2025-04) and its v3.0 draft (2026-04), the approved-mechanism list for
EU-certified products. The one place it is argued is the NIS Cooperation
Group's FAQ, above, and there the verdict is "not viable". Those documents set
the deadlines the field is now working to: initial national roadmaps by
**end-2026**, high-risk use cases off quantum-vulnerable public key by
**end-2030**, medium-risk by **end-2035**.

The counter-argument this project embodies is narrower than "QKD is good", and
worth stating plainly: QKD material is used here **in addition to**
post-quantum cryptography, never instead of it. Nothing above contradicts that
composition -- the agencies' objection is to QKD as a *replacement* for PQC,
which is not what is built here. Note also that Germany is simultaneously
building QKD assurance: BSI certified the ETSI Common Criteria Protection
Profile for prepare-and-measure QKD in January 2024. The European position is
"not yet, and not instead", not "never".

NIST SP 800-227 accommodates that composition, on a condition. Its only
mention of QKD is in §4.6.1, which acknowledges that a multi-algorithm scheme
may include a secret established via QKD and requires ("shall") that the
secrets then be combined with an approved key combiner of the kinds §4.6.2
describes. SP 800-227 does not *permit* the construction so much as set a bar
for it -- one this project does not currently clear in full. The sentence, the
section numbering and the analysis are in the appendix of
[`vici-ppk.md`](vici-ppk.md).
