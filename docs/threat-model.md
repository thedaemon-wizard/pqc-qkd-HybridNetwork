# Threat model: what this project is defending against, and why hybrid

The adversary this QKD-plus-PQC hybrid is built against, the estimates and
mandates that bound when it matters, and what the project does not claim. The
design's whole justification is long-lifetime confidentiality, so the threat is
stated here rather than left for a reader to infer from the parts.

## 1. The adversary

**Harvest now, decrypt later (HNDL).** The adversary records ciphertext today
and decrypts it once a cryptographically relevant quantum computer (CRQC)
exists. Nothing about the recording is detectable, and no future key rotation
helps: the traffic is already captured.

This is the only threat model under which a QKD lane is worth its cost here. A
classical adversary is adequately handled by ML-KEM alone.

## 2. Mosca's inequality

Migration must start before the threat arrives, by the shelf life of the data:

```math
X + Y \;>\; Z \quad\Longrightarrow\quad \text{you are already late}
```

- $`X`$ — how long the data must stay confidential
- $`Y`$ — how long migration takes
- $`Z`$ — time until a CRQC exists

The term this project addresses is $`Y`$: the *mechanism* for delivering
quantum-derived key material into a running IPsec or WireGuard tunnel, so that
$`Y`$ is not itself measured in years. It does not shorten $`Z`$ and makes no
claim about it.

### 2.1 Why rotation cadence is a defence at all

Mosca's inequality says *when* to migrate. It says nothing about how much the
attack costs the attacker, and Blanco-Romero et al., *On the Practical
Feasibility of Harvest-Now, Decrypt-Later Attacks* (arXiv:2603.01091,
2026-03-01, CC BY 4.0) call the framework "influential but deliberately
abstract: it provides no mechanism for quantifying the adversary's operational
cost during the harvest phase" (§2.1). They recast HNDL as an economic problem
instead, with a testbed over TLS 1.2, TLS 1.3, QUIC and SSH. Their result is
that the recording side costs the adversary almost nothing — "retaining
intercepted traffic is economically trivial" — so a defence aimed at raising
the cost of *capture* has nothing to push against.

They separate two cost axes, and the distinction is the useful part:

- **Storage overhead** — Encrypted Client Hello forces indiscriminate bulk
  collection, inflating the archive. But storage cost "penalizes both sides".
- **Quantum workload** — aggressive rekeying and larger key-exchange
  parameters multiply the computations needed to recover plaintext. This axis
  "targets the adversary alone", which is why the paper concludes that
  "rekeying and key size selection offer the strongest defensive levers".

That second axis is the argument for this PoC's rotation cadence, and how far
it reaches depends on the lane, because the two lanes consume a new key at
different moments:

- **IPsec lane.** Every rotation reauthenticates the IKE SA (VICI `rekey` with
  `reauth=yes`, in `services/arnika-vici/repositories/swanvici/vici.go`), so
  each rotation starts a new key epoch. Rotating every 30 s makes no single
  recovery harder; it makes each recovery worth one 30 s epoch of traffic.
- **WireGuard lane.** arnika only overwrites the `wg0` peer's preshared key,
  and nothing forces a handshake. The new PSK enters the session keys at WireGuard's
  next handshake, which the initiator starts about every 120 s
  (`REKEY_AFTER_TIME`) while traffic flows, and the nodes' 25 s keepalive keeps
  it flowing. So the epoch here is WireGuard's rekey interval, and the 30 s
  `ARNIKA_INTERVAL` does not shorten it: most PSKs installed at that cadence are
  replaced before any handshake uses them. arnika's v1.x design document
  recommends a 120 s interval for exactly this alignment (see
  [`references.md`](references.md) section 3). The same holds for the `wg1`
  data tunnel, whose preshared key Rosenpass renews on its own schedule: each
  new key is used from `wg1`'s next handshake.

Worth stating explicitly, because "we rotate often" otherwise reads as hygiene
rather than as the counter to a specific adversary model, and because the
cadence buys the property on one lane and not on the other.

**Where the paper stops, and where this project begins.** It names "the
absence of in-band ephemeral rekeying in TLS 1.3 and QUIC" as a critical
protocol gap (§1), and finds those two "locked at E=1" — one epoch, so
recovering the handshake secret exposes every later epoch (§7). **It does not
discuss IPsec, IKEv2 or WireGuard at all**; the following is this project's
inference from its framework, not a claim the paper makes.

Both lanes built here *do* have in-band rekeying, which is why an external key
source can be fed to them. But the RFC 8784 limitation recorded on the `/vpn`
page means the QKD material specifically reaches only the initial IKE SA, so
consuming fresh material needs a reauthentication rather than a rekey. Read
through this paper's cost model that is not cosmetic: cadence on the quantum
axis *is* the defence, so the heavier operation buys the property rather than
wasting effort. RFC 9867 (Nov 2025) lifts the restriction and names QKD as its
motivating case; see [`vici-ppk.md`](vici-ppk.md) for what does and does not
implement it.

## 3. What the estimates actually say — and what they do not

**No date is defensible, and this document does not give one.** What exists are
elicited expert probabilities, and they are moving in one direction.

The **Quantum Threat Timeline Report 2025** (Mosca and Piani, Global Risk
Institute / evolutionQ, published 9 March 2026, 26 surveyed experts) puts the
averaged probability of a CRQC within **10 years at 28–49 %**, and within
**15 years at 51–70 %**. That 10-year figure is the highest in the survey's
seven-year history: the averaged optimistic estimate rose from **34 % in 2024 to
49 % in 2025**, the sharpest single-year shift the series has recorded, which
the authors attribute to progress in error correction and logical-qubit storage.
The pessimistic floor moved with it, from 14 % to 28 %.

**The panel is not the same panel.** It has shrunk each year — **37 experts in
2023, 32 in 2024, 26 in 2025** — so a 15-point year-on-year jump is measured
across a respondent set roughly a fifth smaller than the one it is compared
against, with no guarantee the departures were random. That does not explain the
shift away, and the movement is in the same direction on both the optimistic and
pessimistic ends, which is harder to attribute to composition alone. But a
year-on-year delta from a changing panel is weaker evidence than the same delta
from a fixed one, and this document should not borrow strength it does not have.

Read these as a distribution over expert belief, not a forecast. The honest
statement is that the estimates have compressed, not that a year is known.

**Physical resource estimates have fallen too, and they bear on the classical
halves of both lanes.** Those halves are elliptic-curve: ECP-256 (NIST P-256)
in the IPsec lane's IKE exchange and X25519 in WireGuard's handshake, both
prime-field curves of about 256 bits, and P-384 inside the hybrid KEM of
arnika's PQC-HPKE half. The 2025-2026 preprints, each under stated hardware
assumptions and none of them a demonstration:

| Preprint | Target | Estimate | Assumptions |
|---|---|---|---|
| Gidney, [arXiv:2505.15917](https://arxiv.org/abs/2505.15917) (2025-05) | RSA-2048 | under a week, fewer than a million noisy qubits | square grid, 0.1 % gate error, 1 µs cycle, 10 µs reaction |
| Webster et al., "Pinnacle", [arXiv:2602.11457](https://arxiv.org/abs/2602.11457) (2026-02) | RSA-2048 | fewer than 100 000 physical qubits | QLDPC codes, $`10^{-3}`$ error, 1 µs cycle, 10 µs reaction |
| Webster, Peham, Cohen, [arXiv:2609.21249](https://arxiv.org/abs/2609.21249) (2026-09) | RSA-2048 | one month, about 120 000 physical qubits | as Pinnacle, with fixed degree-8 connectivity |
| Babbush, Zalcman, Gidney et al., [arXiv:2603.28846](https://arxiv.org/abs/2603.28846) (2026-03) | 256-bit ECDLP (secp256k1) | fewer than 1200 logical qubits and 90 million Toffoli gates; minutes with fewer than half a million physical qubits | superconducting, $`10^{-3}`$ error, planar connectivity |
| Cain et al., [arXiv:2603.28627](https://arxiv.org/abs/2603.28627) (2026-03) | P-256 discrete log | "just a few days" with 26 000 physical qubits; Shor with as few as 10 000 | reconfigurable neutral atoms, "under plausible assumptions" |
| Häner et al., [arXiv:2609.05625](https://arxiv.org/abs/2609.05625) (2026-09) | 256-bit ECDLP (secp256k1) | 26 days with 20 000 qubits, about 1450 logical qubits | trapped ions, Walking Cat architecture |

The secp256k1 figures are a proxy for P-256 and Curve25519, not an estimate for
them: Shor's cost is of the same order for any prime-field curve of that size,
but the circuits were built for secp256k1. Cain et al. is the one row computed for
P-256 itself and the lowest physical count here. None of this dates a CRQC. It
does say that the elliptic-curve halves of both lanes are no harder a target
than RSA-2048 on current preprints (Cain et al. put RSA-2048 one to two orders
of magnitude slower than P-256), which is the case for mixing post-quantum
material into both.

## 4. Why hybrid, specifically

Independent hardness assumptions, combined so that breaking one alone is
insufficient:

| Component | Mechanism | Fails to |
|---|---|---|
| QKD | BB84 decoy-state, ETSI GS QKD 014 delivery | a computational break of any kind — its security is information-theoretic, conditioned on the device model |
| PQC-HPKE (arnika's PQC half: the `wg0` key and the IPsec PPK) | HPKE with the KEM MLKEM1024-P384, a hybrid of ML-KEM-1024 and P-384 ECDH | a break of *both* ML-KEM-1024 (module lattice) and P-384. Against a quantum adversary P-384 falls to Shor, so against that adversary this half rests on the module-lattice assumption alone |
| Rosenpass (the `wg1` data tunnel only) | Classic McEliece 460896 + Kyber512 | a break of *both* a code-based and a lattice-based assumption |

`arnika` derives the `wg0` key and the IPsec PPK as
$`\mathrm{HKDF\text{-}SHA3\text{-}256}(\mathrm{QKD} \parallel \mathrm{PQC})`$, with
the PQC half from its PQC-HPKE round, so an attacker needs both halves. On the
WireGuard lane the data then travels in `wg1` inside `wg0`, and `wg1`'s
session keys mix in Rosenpass's key, which is independent of arnika's: reading
that traffic off the wire also needs the `wg1` layer. See
[`vici-ppk.md`](vici-ppk.md) for how arnika's key reaches IKEv2, and for the
SP 800-227 combiner analysis — including where this construction does **not**
meet the approved form.

**The mitigation this buys in the Rosenpass layer is specific.** Kyber512 is the
pre-standardisation parameter set and is not approved under FIPS 203 or
CNSA 2.0. What limits the damage is that Classic McEliece is a *different*
hardness assumption — code based, not lattice based — so the composite
survives a Kyber512 break. That is an argument for the hybrid construction,
not an excuse for the parameter set. Since 2026-09-26 this applies to `wg1`
only: arnika's combiner no longer takes Rosenpass's key.

**arnika's PQC-HPKE half uses no liboqs.** It is the Go standard library's
`crypto/hpke` and `crypto/mlkem`, compiled into the `arnika` binary by the
node images' Go 1.26 toolchain, and it depends on `draft-ietf-hpke-pq`, which
is not yet an RFC; for that reason upstream's own documentation says to pin
the Go version and re-verify interoperability on upgrade.

**The KEM code in the Rosenpass exchange is liboqs 0.8.0, not the liboqs pin.** Rosenpass
v0.2.3 depends on `oqs-sys` 0.8, which vendors and statically compiles liboqs
0.8.0 (2023) into the `rosenpass` binary; the `submodules/liboqs` pin (0.16.0)
is built only into the `pqc-validator` and `pqc-tls-demo` images and does not
reach this lane. liboqs 0.9.1, 0.9.2 and 0.10.1 were security releases for
non-constant-time Kyber code (KyberSlash), and 0.8.0 predates all three. What
was found in this build: a disassembly of the `rosenpass` binary in the
x86-64 node image (built 2026-08-22) shows no `div`/`idiv` instruction in the
reference Kyber512 functions the KyberSlash timing channel lives in
(`poly_tomsg`, `poly_compress`, `polyvec_compress`), and the AVX2 variants are
compiled in. That is a property of this compiler and target, not of the source,
and it does not stand in for the upstream fixes. The upgrade belongs upstream:
moving `oqs-sys` past 0.8 breaks Rosenpass wire compatibility (rosenpass#880),
so it is not a local bump. Licences and advisories are recorded in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

### 4.1 The code-based half is under active analysis, as of September 2026

**What the numbers are.** A line of preprints beginning August 2026 gives
conditional, heuristic cost estimates for recovering a Classic McEliece private
key that fall below the claimed level. For the set this ships, mceliece460896 —
claimed Category 3, $`2^{207}`$ classical gates:

| Source | Estimate for mceliece460896 | Stated basis |
|---|---|---|
| Saarinen, [ePrint 2026/1786](https://eprint.iacr.org/2026/1786) (7 revisions, latest 2026-09-15) | $`2^{145.22}`$ bit operations, working memory $`2^{59.10}`$ bits | *"conditional arithmetic estimate"*; the model *"excludes address generation and memory traffic and uses budget estimates for some stages"* |
| Weis, [ePrint 2026/1984](https://eprint.iacr.org/2026/1984) (2026-09-11; last of 2 revisions 2026-09-25, abstract unchanged from 2026-09-18) | $`2^{94}`$–$`2^{102}`$ in the GIJS cost model, or $`2^{114}`$–$`2^{124}`$ with GIJS's conditions unchanged (v1 abstract); the 2026-09-18 revision adds $`2^{110}`$–$`2^{128}`$ when memory is charged as the Classic McEliece security guide does — against information-set decoding at $`2^{151}`$–$`2^{287}`$ | extends the Ghoshal-Ishai-Jain-Sun hold-out distinguisher ([2026/1630](https://eprint.iacr.org/2026/1630)) to key recovery |

**What they do not say, stated first because the numbers invite the wrong
reading.** Weis's abstract is explicit: *"None of this is close to practical,
and several ingredients are heuristic."* (abstract as revised on 2026-09-18 and
unchanged on 2026-09-25; v1 read *"None of the Classic McEliece computations is
close to practical"*). The 2026-09-25 revision changes only the note on the
paper's page, which now says that earlier versions over-estimated the McEliece
parameter sizes needed for the claimed security levels and had *"some errors in
the cost analysis"* (re-checked 2026-09-26). The
demonstrations are on toy challenge instances, not parameter sets — Weis solved
TII label 253 ($`m=8`$, $`t=9`$, $`n=214`$); Saarinen solved TII-254 ($`m=8`$,
$`t=12`$, $`n=223`$, a $`[223,127]`$ code) using 27.2 GPU-hours on GH200s
([2026/1986](https://eprint.iacr.org/2026/1986), a separate paper, revised
2026-09-24 with its abstract unchanged, that still makes **no claim about any
NIST parameter set**). No key has been recovered at any NIST
size, and nothing in this deployment is broken.

**The line is contested, and the scope of the objection matters.** Apon
([ePrint 2026/1810](https://eprint.iacr.org/2026/1810)) proves an
algebraic-geometry lower bound forcing $`c_{\text{need}} > 2t + 3`$, which for
mceliece8192128 puts that attack *"in excess of $`2^{1500}`$ bit operations"*.
But it is aimed at **Vedenev's route** ([2026/1747](https://eprint.iacr.org/2026/1747))
specifically and predates Weis's extraction, so it is not a refutation of the
whole line. Citing it as one would be the mirror image of citing the cost
estimates as a break.

**What this changes here, precisely.** The hybrid argument in the Rosenpass row
of the table above is untouched: code-based and lattice-based remain different
assumptions, and a composite still requires breaking both. Since 2026-09-26 its
reach is also smaller: mceliece460896 protects the key of the `wg1` data tunnel
only, because arnika's combiner, and so the `wg0` key and the IPsec PPK, no
longer takes Rosenpass's output. What is being re-estimated is the stated
*reason* for the choice. The pinned `rosenpass/src/pqkem.rs` says: *"Classic
McEliece is chosen because of its high security margin and its small
ciphertexts."* The margin is the thing under scrutiny.

**Two dates belong together.** BSI TR-02102-1 recommends mceliece460896
([`references.md`](references.md)) and its current version is dated 2026-01-23 —
seven months before this line began. It has not been revisited since.

**The team's silence is informative because responding is their habit.**
`classic.mceliece.org/nist.html` (page version 2026.06.23) carries dated
responses to exactly this class of claim three times over, all three
concerning mceliece348864: 2025-04-17 on a distinguisher cost claim, 2025-11-20
on *"You Only Decapsulate Once"*, and a note on a key-recovery cost claim that
the page dates **2025-06-23** but whose PDF is `mceliece-610-20260623.pdf`.
The page's own version number is 2026.06.23 and the note is absent from the
page's 2025-12-29 version, so this project reads that date as a typo for
**2026-06-23**. An earlier version of this paragraph took the page's date at
face value and called 2025-11-20 the latest posting. The latest posting is
June 2026, before the August 2026 line began, and nothing addresses that line.
Re-checked 2026-09-25. An absence of comment from a team that has commented
three times is worth more than an absence from a silent one, and it is the
reason this section reports estimates rather than conclusions.

## 5. Migration mandates in force

Dates matter here because they bound $`Y`$ for anyone deploying this. One row
per instrument, each read at its source:

| Instrument | Scope | Dates | Force |
|---|---|---|---|
| EO 14412 (2026-06-22) and OMB [M-26-15](https://www.whitehouse.gov/wp-content/uploads/2026/06/M-26-15-Execution-of-the-Migration-to-Post-Quantum-Cryptography.pdf) (2026-06-24) | US federal High Value Assets and high-impact systems, **excluding** National Security Systems | PQC key establishment by **2030-12-31**; PQC digital signatures by **2031-12-31** | binding on agencies |
| FAR proposed rule directed by EO 14412 | covered federal contractors | comply with NIST's FIPS, including the PQC FIPS, by **2030-12-31** | the EO orders the FAR Council to *publish a proposed rule* within 180 days; not in force |
| NSA CNSA 2.0 / CNSS Policy 15 | US National Security Systems | new acquisitions support CNSA 2.0 from **2027-01-01**; VPNs and routers exclusive by **2030**; all NSS by **2035** (NSM-10) | mandated for NSS |
| DoW CIO memo, *Preparing for Migration to Post Quantum Cryptography* (2025-11-18) | DoW Components (the QKD prohibition, item 2, is scoped to DoW networks and communications; the phase-outs, item 3, are not) | PSK-for-quantum-resistance and symmetric key distribution phased out by **2030-12-31** (**2031-12-31** for NSA CSfC-registered solutions); no new commercial procurement of either, effective immediately | binding within DoW; the prohibition and phase-outs name a waiver path, the no-procurement sentences do not |
| EU NIS Cooperation Group, *Coordinated Implementation Roadmap* (2025-06) and its [FAQ](https://ec.europa.eu/newsroom/dae/redirection/document/132120) (2026-04-15) | EU Member States | initial national roadmaps by **end-2026**; high-risk use cases by **end-2030**; medium-risk by **end-2035** | coordinated roadmap, not legislation |
| UK NCSC, [PQC migration timelines](https://www.ncsc.gov.uk/guidance/pqc-migration-timelines) | UK organisations | discovery and an initial plan by **2028**; highest-priority migrations by **2031**; complete by **2035** | guidance, not statute |
| Japan, inter-ministerial liaison council on PQC use in government agencies, [interim summary](https://www.cas.go.jp/jp/seisaku/pqc/pdf/report_202511.pdf) (2025-11) | Japanese government agencies | migrate "in principle" by **2035**; a roadmap is to follow | interim, government-internal |
| Singapore CSA, *Quantum-Safe Migration Handbook V1* (2026-07-16) | Critical Information Infrastructure operators | migration plan **2027-03-31**; procurement **2028-01-01**; complete **2031-12-31** | guidance; the enforcing instrument is the CCoP |
| ANSSI, *Transition post-quantique d'IPsec*, technical sheet [ANSSI-FT-117](https://messervices.cyber.gouv.fr/documents-guides/transition_post_quantique_ipsec.pdf), version 1.0 (2026-02-02) | IPsec/IKEv2 deployments | none; a pre-shared key "can be a temporary measure" in the transition, and hybridisation must follow | recommendations, stated as non-normative |

The Japanese report and the ANSSI sheet are in Japanese and French, and their
phrases below are this project's translation.

**These instruments do not agree about this design, and the disagreement is
quoted rather than summarised because it is the point.**

**Against, from the US.** OMB **M-26-15**, *Execution of the Migration to
Post-Quantum Cryptography* (2026-06-24, executing EO 14412 of 2026-06-22),
calls hybrid *"a useful tool for managing risk"* and *"defense-in-depth"* while
also calling it *"an intricate and resource-intensive stopgap"* requiring *"a
thorough evaluation of its tradeoffs"*. And Appendix A, immediately after the
table of quantum-vulnerable **asymmetric** algorithms, states flatly:

> "Symmetric-key-based protocols should also be avoided."

Quoted verbatim and deliberately not interpreted. The sentence is terse and its
scope is genuinely ambiguous -- AES-256 is not quantum-vulnerable, so it most
plausibly targets pre-shared-key *distribution* schemes rather than symmetric
primitives -- but **as written it is a headwind for an RFC 8784 / RFC 9867 PPK
design**, which is exactly what this project builds. Recorded here rather than
left out, because a reader who finds it independently should not find it as a
surprise. Neither EO 14412 nor its companion EO 14413 mentions QKD at all; the
EO anchors "key establishment" to FIPS 203.

**A second US instrument says the same thing explicitly, within its scope.**
The DoW CIO memo prohibits using QKD (item 2.a, quoted in
[`references.md`](references.md) section 4) *"for the purposes of providing
confidentiality, authenticity, or integrity in DoW networks and
communications"*; that phrase belongs to item 2. Item 3 is not
scoped by it. It binds DoW Components directly -- they *"will phase out and
replace all of the following types of cryptographic solutions"* -- and its
only qualifier of purpose is quantum resistance. It names two classes:

> "a. Use of cryptographic pre-shared keys (PSK) for providing quantum
> resistance in solutions where the PSK is not provisioned through NSA KMI for
> Type 1 devices. These solutions will be phased out and replaced with
> solutions using NIST-approved (respectively, CNSA 2.0-listed for National
> Security Systems) asymmetric PQC algorithms for key establishment no later
> than December 31, 2030, unless otherwise directed or provided exception by
> the point of contact above.
>
> Additionally, DoW Components will not test, pilot, use, or procure
> commercial PSK-based solutions for quantum resistance effective
> immediately."
>
> "b. Symmetric key establishment protocols, symmetric key agreement
> protocols, and symmetric key distribution protocols. These solutions shall
> be phased out and replaced no later than December 31, 2030 (or no later than
> December 31, 2031, for solutions currently registered with NSA CSfC), unless
> otherwise directed or provided exception by the point of contact above.
>
> Use cases where symmetric key distribution protocols have been in use prior
> to 2010 are exempt from this requirement as not introducing new risks.
> [...]
>
> Additionally, DoW Components will not test, pilot, use, or procure
> commercial solutions of this type (i. e., symmetric key establishment
> protocols, symmetric key agreement protocols, and symmetric key distribution
> protocols) for quantum resistance effective immediately."

The elided sentence adds that upgrading those pre-2010 use cases to asymmetric
PQC key establishment "should be investigated". The final paragraphs of 3.a
and 3.b are the source of the table's "no new commercial procurement of
either, effective immediately"; unlike the phase-out dates, neither carries a
waiver clause of its own.

The memo names no protocol, so applying it here is this project's reading:
item 3.a covers the RFC 8784 PPK on the IPsec lane, which supplies a
pre-shared key for quantum resistance, and the WireGuard preshared key that
arnika installs is the same kind of mechanism. For DoW Components both lanes
are therefore phase-out and no-new-procurement by default, whatever their
cryptographic merits, and the pre-2010 exemption does not reach a new
deployment. This does not resolve the ambiguity in OMB's sentence -- it is a
separate instrument with a narrower scope -- but it points the same way, and
it does so in words that leave no room for the reading that only symmetric
primitives are meant.

**For, from Singapore.** CSA's *Quantum-Safe Migration Handbook V1*
(2026-07-16) is the one national instrument found that endorses this exact
shape: it treats QKD substantively, says **"QKD should be considered for
layered defence or niche use cases"**, endorses hybrid PQC + classical + QKD as
a fail-safe, and states that **"PSK with AES-256 is among the strongest options
for CII operators with existing secure distribution infrastructure"** -- which
is the PPK lane described. It self-describes as *"not mandatory, prescriptive
or exhaustive"*; the enforcing instrument is the CCoP.

**Conditionally open, from Japan.** The interim summary asks for
crypto-agility and adds that, "depending on the usage environment", one could
consider "combined use of PQC with currently mainstream cryptography rather
than a complete migration to PQC", or "introducing quantum key distribution
(QKD) as a technology that quantum computers cannot break". That lists QKD as
an option, and a PQC-plus-classical hybrid as another. It does not endorse the
composite this project builds, and it is weaker than an endorsement: the
original says such options "could be considered". Japan's approved list moved
the same way on the PQC side only: [CRYPTREC LS-0001-2022R2](https://www.cryptrec.go.jp/list/cryptrec-ls-0001-2022r2.pdf)
(updated 2026-03-30) adds a PQC table whose only key-establishment entries are
ML-KEM-768 and ML-KEM-1024 -- no Classic McEliece and no ML-KEM-512.

**Conditionally, from France, on this exact mechanism.** ANSSI-FT-117 is the
one instrument found that addresses the delivery mechanism here, an IKEv2 PPK,
by RFC number. Its section 3.1 accepts a pre-shared key for post-quantum
confidentiality, "notably if" the key's classical and post-quantum
confidentiality and integrity are assured, and says that using one "can be a
temporary measure" in the transition; hybridisation is "the solution preferred
by ANSSI" and has to follow. It states RFC 8784's limitation -- the pre-shared
key protects the keys of later Child SAs, not the IKEv2 exchanges themselves
-- and cites RFC 9867 as the extension that lifts it, the limitation
[`vici-ppk.md`](vici-ppk.md) section 2 records for this lane. And it warns that
a compromise of the pre-shared key is **retroactive**: every IKEv2 session that
used it falls with it to a store-now-decrypt-later attacker, so classical
forward secrecy survives and post-quantum forward secrecy does not. That is the
case for rotating the PPK (§2.1). QKD appears nowhere in it.

**Against, from the EU, more explicitly than the roadmap itself.** The NIS
Cooperation Group's roadmap never mentions QKD; its FAQ does. It defines a
hybrid as a post-quantum algorithm combined with a quantum-vulnerable one and
says *"The EU Roadmap on PQC does not consider hybrids mechanisms using quantum
key distribution (QKD) or using more than one PQC mechanism"* (section 3.1),
and it concludes that *"QKD is currently not considered a viable quantum-safe
alternative"* (section 5.6). Under that definition arnika's QKD ‖ PQC
combination does not count as a hybrid, and neither does Rosenpass's McEliece +
Kyber pairing, which joins two post-quantum mechanisms. Two constructions here
do: the IPsec lane's ECP-256 + ML-KEM-768 exchange, and the MLKEM1024-P384 KEM
inside arnika's PQC-HPKE half, which pairs ML-KEM-1024 with P-384 ECDH.

**How to hold these together.** No authority surveyed endorses the whole
construction. BSI recommends the McEliece parameter set this ships and does not
recommend QKD ([`references.md`](references.md)); OMB is wary of both hybrid
complexity and symmetric-key protocols, and the DoW memo phases PSK-based
quantum resistance out across its Components; ANSSI accepts a PPK only as a
temporary measure and prefers hybridisation; the EU treats QKD as not viable;
Singapore endorses layered QKD and AES-256 PSK; Japan lists QKD as something
that could be considered. A reading that quotes only the supportive ones is
overclaiming, and the honest framing is the **crypto-agility and
implementation-gap** case -- which no authority disputes -- rather than QKD
advocacy.

**NSA does not recommend QKD for National Security Systems**, and says so on
the same page that announces its PQC selections. Read in a browser on
2026-09-02 and in a Wayback snapshot of 2026-09-08 (`nsa.gov` and
`media.defense.gov` refuse non-interactive fetches; the Internet Archive's
snapshots are readable, which this paragraph once denied):

> "NSA continues to evaluate the usage of cryptography solutions to secure the
> transmission of data in National Security Systems. **NSA does not recommend
> the usage of quantum key distribution and quantum cryptography for securing
> the transmission of data in National Security Systems (NSS) unless the
> limitations below are overcome.**"

The page's PQC section points at **CNSS Policy 15, released 4 March 2025**, and
the CNSA 2.0 FAQ. Nothing dated after that appears on it, so the CNSA 2.0
timeline is unchanged as far as this page shows.

Counting the instruments in this section and in [`references.md`](references.md)
section 4: of nine surveyed, **five are sceptical of QKD** (NSA, BSI, the DoW,
the EU NIS Cooperation Group, the UK NCSC), **two never mention it** (OMB and
EO 14412; ANSSI-FT-117), and **two treat it as an option** (Singapore for
layered defence, Japan as something that could be considered). ANSSI's
scepticism about QKD is on record elsewhere, in the 2024 joint position paper
listed in [`references.md`](references.md) section 4; the IPsec sheet itself
is silent. None endorses the whole construction. The conditionals matter --
NSA's objection is "unless the limitations are overcome", not "never" -- but a
reading that cites Singapore without the other eight is selecting its
evidence.

**CNSA 2.0** (US National Security Systems) names **ML-KEM-1024** for key
establishment and **ML-DSA-87** for signatures as its only general-purpose
public-key algorithms, alongside AES-256 and SHA-384/512; LMS and XMSS
(SP 800-208) and SHA3-384/512 are allowed in specific applications such as
firmware signing. Every new NSS acquisition must support CNSA 2.0 from
**1 January 2027**; software and firmware signing and networking equipment
target exclusive use by **2030**; operating systems, custom applications and
cloud services by **2033**, ahead of the **2035** goal in NSM-10. For this
repository's category the algorithms advisory is specific: *"Traditional
networking equipment (e.g., virtual private networks, routers): support and
prefer CNSA 2.0 by 2026, and exclusively use CNSA 2.0 by 2030."* The FAQ
(Ver. 2.1, December 2024) adds that CNSA 2.0 algorithms are mandated for use by
31 December 2031, and that *"NSS owners should not use or research QKD at this
time without consulting NSA directly."* Both read from Wayback copies of the
NSA PDFs on 2026-09-25.

**This repository's IKEv2 lane negotiates `ecp256-ke1_mlkem768`.** ML-KEM-768
is NIST-approved and IETF-conformant, and it is **outside CNSA 2.0 scope**,
which approves only the 1024 parameter set. Moving toward CNSA 2.0 is not a
one-variable change. The FAQ's IKEv2 answer is that *"NSA's profile of this
solution will continue the use of CNSA 1.0 key establishment algorithms, but
fortified by key establishment using ML-KEM-1024"*. CNSA 1.0 key
establishment is, for example, ECDH over P-384; DH and RSA with a modulus of
3072 bits or more are also permitted (Table V, "CNSA 1.0 algorithms", of
*Announcing the CNSA 2.0 Algorithms*, listed under Sources). Keeping ECDH,
both `IKE_PROPOSALS` and `ESP_PROPOSALS` in `docker-compose.strongswan.yml`
would change curve and KEM together (`ecp384-ke1_mlkem1024`). Even then the
lane would not conform: it authenticates with a PSK and a PPK rather than
ML-DSA-87, and it mixes in a QKD-derived key, which the same FAQ tells NSS
owners not to use without consulting NSA. arnika's PQC-HPKE half happens to
pair ML-KEM-1024 with P-384, but it reaches IKEv2 only as part of a PPK derived
with HKDF-SHA3-256 alongside the QKD key, so it does not change that
conclusion. Stated as a direction, not as done.

## 6. What this project does not claim

- It does not shorten $`Z`$, predict Q-Day, or assert a CRQC date.
- It does not claim CNSA 2.0 conformance. See §5.
- It does not claim the QKD lane is unconditionally secure in practice. The
  information-theoretic argument is conditioned on a device model, and the
  simulated channel here is not a device. `docs/LIMITATIONS.md` is the
  authority on what is simulated versus measured.
- It does not claim the key combiner is NIST-approved. It is not; see
  [`vici-ppk.md`](vici-ppk.md).

## Sources

| Claim | Source |
|---|---|
| CRQC probability 28–49 % in 10 years, 51–70 % in 15; optimistic 34 % (2024) to 49 % (2025), pessimistic 14 % to 28 %; panel 37 (2023) / 32 (2024) / 26 (2025) | Mosca and Piani, *Quantum Threat Timeline Report 2025*, Global Risk Institute / evolutionQ, 9 March 2026. Re-verified against the publishers 2026-08-28. [globalriskinstitute.org](https://globalriskinstitute.org/publication/quantum-threat-timeline-report-2025b/) · [evolutionq.com](https://www.evolutionq.com/publications/quantum-threat-timeline-research-report-2025) |
| Mosca's inequality $`X + Y > Z`$ | M. Mosca, *Cybersecurity in an era with quantum computers: will we be ready?*, IEEE Security & Privacy 16(5), 2018 |
| CNSA 2.0 algorithms and dates | NSA, *CNSA 2.0 FAQ*, Ver. 2.1, December 2024 ([Wayback 2026-09-13](http://web.archive.org/web/20260913123116/https://media.defense.gov/2022/Sep/07/2003071836/-1/-1/0/CSI_CNSA_2.0_FAQ_.PDF)); NSA, *Announcing the CNSA 2.0 Algorithms* ([Wayback 2024-12-15](http://web.archive.org/web/20241215203633/https://media.defense.gov/2022/Sep/07/2003071834/-1/-1/0/CSA_CNSA_2.0_ALGORITHMS_.PDF)). This row cited a news site until 2026-09-25; `media.defense.gov` refuses non-interactive fetches, the archived copies do not. |
| DoW items 2 and 3 | DoW CIO, *Preparing for Migration to Post Quantum Cryptography*, memorandum of 2025-11-18 ([PDF](https://dowcio.war.gov/Portals/0/Documents/Library/PreparingForMigrationPQC.pdf)), read 2026-09-25 |
| US federal dates | EO 14412 (2026-06-22), sections 4(b) and 6(c); OMB M-26-15 (2026-06-24) ([PDF](https://www.whitehouse.gov/wp-content/uploads/2026/06/M-26-15-Execution-of-the-Migration-to-Post-Quantum-Cryptography.pdf)) |
| EU hybrid definition and QKD position | NIS Cooperation Group, *EU Roadmap on PQC -- Frequently Asked Questions*, 2026-04-15, sections 3.1, 5.6 and 6 ([PDF](https://ec.europa.eu/newsroom/dae/redirection/document/132120)) |
| Japan | Inter-ministerial liaison council on PQC use in government agencies, interim summary, November 2025 ([PDF](https://www.cas.go.jp/jp/seisaku/pqc/pdf/report_202511.pdf), in Japanese); CRYPTREC LS-0001-2022R2, updated 2026-03-30 |
| France, IKEv2 pre-shared keys | ANSSI, *Transition post-quantique d'IPsec*, ANSSI-FT-117, version 1.0, 2026-02-02 ([PDF](https://messervices.cyber.gouv.fr/documents-guides/transition_post_quantique_ipsec.pdf), in French), section 3.1; read 2026-09-26. Published under Licence Ouverte v2.0, which permits reuse with attribution to the source and the date of its last update |
| Physical resource estimates | the arXiv preprints linked in section 3, each read at its abstract page 2026-09-25 |


## 7. Relationship to QCI-CAT, and what this repository does not implement

`submodules/arnika`'s README states that arnika **v1.x** was developed within
the EU EUROQCI / QCI-CAT programme for the use case **"HSM BACKUP USING QKD"**
(<https://qci-cat.at/hsm-backup-using-qkd>). The pin is later work -- the head
of the open pull request arnika#51, built on `main` -- and upstream credits
CANCOM Converged Services GmbH with the initial prototype and earlier versions,
and says development has continued at XBC Digital GmbH since Q2 2026. Because
this repository vendors arnika and cites that lineage, a
reader could reasonably assume it implements that use case. It does not, and
the difference is worth stating precisely.

**What QCI-CAT's use case is**, from its own page (re-verified in a browser 2026-08-28; the page's own text confirms HSM-to-backup-HSM over a QKD-protected VPN, ETSI 014 inside conventional VPN frameworks, PKCS#11, HA partition cloning and the Demo App):
cryptographic material is transferred from a Hardware Security Module to a
**backup HSM** over a VPN whose link is QKD-protected. The specific link being
protected is **HA partition synchronisation / cloning** between two HSMs, and a
**Demo App** exercises typical operations — signing key material — through the
HSMs' **PKCS#11** interface. The page names ETSI 014 integration into
conventional VPN frameworks explicitly.

**What this repository shares with it:**

| Component | QCI-CAT use case | Here |
|---|---|---|
| ETSI GS QKD 014 key delivery | yes | `services/bb84-kme/app/etsi014.py` |
| QKD-protected VPN link | yes | WireGuard and strongSwan IPsec lanes |
| Key control fetching QKD material and installing it | yes (arnika) | same component, vendored |

**What it does not:**

| Component | QCI-CAT use case | Here |
|---|---|---|
| Hardware Security Modules | yes | **none** |
| PKCS#11 interface | yes | **none** — no first-party source references it. The vendored strongSwan ships a pkcs11 plugin and this project does not build it (`configure.ac` makes it opt-in; `nodes/strongswan/Dockerfile` never enables it). An earlier version of this row offered a `grep` as proof and said it "returns nothing"; the grep matches 40 paths, two of them outside `submodules/` — this document and the test that guards the claim. There is no checkout state in which it returns nothing, because the row contained the string it said could not be found. |
| HA partition synchronisation / cloning | yes, the actual payload | **none** |
| Real QKD hardware | yes | **no** — simulated, see `docs/LIMITATIONS.md` |

**The reference deployment, as QCI-CAT deliverable D6.1 records it** (facts
only; see [`references.md`](references.md) section 3 for the document):

| Item | D6.1 |
|---|---|
| Sites | a CANCOM data centre at Euro Plaza, Vienna, and NTT's "Vienna 1" data centre, about 2.5 km apart by road and joined by dark fibre about 3.8 km long (D6.1 pp. 27-28; the link budget assumed 4 km of fibre, p. 30). This row said "about 3.8 km apart" until 2026-09-26, which is the fibre length |
| QKD | ID Quantique Cerberis XG, provided by AIT; arnika reads keys over ETSI 014 from its embedded KMS |
| HSMs | two Thales Luna A700 network HSMs, firmware LunaSA 7.8.4 |
| VPN | WireGuard only; IPsec was evaluated and not chosen |
| arnika | v1.x; D6.1 v1.0 is dated 2025-02-17 in its revision history |

So the honest statement of scope is: **this project implements the transport
half of that architecture and none of the HSM half.** Its claim is "a WireGuard
or IPsec key was rotated from QKD-derived material". QCI-CAT's is "HSM key
material crossed a QKD-protected link". The first does not imply the second.

**A note on how not to close that gap.** SoftHSM2 emulates a PKCS#11 surface,
which would make a Demo App runnable, but it does not implement HA partition
cloning and has no cross-instance replication — the very thing the use case is
about. Standing one up and calling the result "HSM backup over QKD" would
manufacture exactly the overstatement this document exists to prevent.

**Licence position.** Nothing from qci-cat.at is reproduced here beyond short,
attributed quotations from the public deliverable D6.1 in
[`references.md`](references.md) section 3 — no page text, no diagram, no
figure. The use case is described in this project's own words and is
cited by URL, and the reference-deployment table above records facts only. D6.1's own
copyright statement grants no right or licence in the document, so those
quotations rest on ordinary citation, and are kept short for that reason, not
on any permission.

That is the right posture regardless of terms, and it is deliberately not
justified by a claim about what those terms are. An earlier version of this
paragraph did make such a claim — that the footer "LEGAL NOTICE" link returns
404 and only a privacy page exists — and it was **false**. Re-checked in a
browser 2026-08-28:

| link | result |
|---|---|
| footer *Legal Notice* → <https://www.ait.ac.at/en/imprint> | **200** |
| footer *Privacy* → <https://qci-cat.at/privacy/> | 200 |
| `qci-cat.at/legal-notice` | 404 — but this path is not linked from anywhere |

The 404 came from a guessed path, not from the link the site actually
publishes. The imprint resolves, but AIT serves a bot check to non-browser
clients. An Internet Archive copy of the imprint body carries company-register
details and no licence clause; the surrounding footer, though, links AIT's
General Terms and Conditions and a disclaimer page that this document has not
reviewed, so it does not characterise AIT's terms either way.

Which leaves the honest position: **the terms are unread, not absent.** Since
nothing beyond short citations is reproduced, no permission is being relied on
and none needs to be established.
