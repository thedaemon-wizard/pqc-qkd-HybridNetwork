# Threat model: what this project is defending against, and why hybrid

This document existed nowhere. `README.md`, `ARCHITECTURE.md` and
`docs/LIMITATIONS.md` contained no mention of Q-Day, harvest-now-decrypt-later,
or Mosca's inequality — while `docs/references.md` documented every agency
objection to QKD in full. The repository built a QKD-plus-PQC hybrid whose
entire justification is long-lifetime confidentiality and never stated the
threat it exists for. A reader could not tell whether the design was a response
to an argument or an assembly of interesting parts.

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

That second axis is the argument for this PoC's rotation cadence. Rotating
every 30 s makes no single recovery harder; it makes each recovery worth 30 s
of traffic. Worth stating explicitly, because "we rotate often" otherwise
reads as hygiene rather than as the counter to a specific adversary model.

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

## 4. Why hybrid, specifically

Two independent hardness assumptions, combined so that breaking either alone is
insufficient:

| Lane | Mechanism | Fails to |
|---|---|---|
| QKD | BB84 decoy-state, ETSI GS QKD 014 delivery | a computational break of any kind — its security is information-theoretic, conditioned on the device model |
| PQC | Rosenpass (Classic McEliece 460896 + Kyber512) | a break of *both* a code-based and a lattice-based assumption |

`arnika` derives the tunnel key as `HKDF-SHA3-256(QKD ‖ PQC)`, so an attacker
needs both. See [`vici-ppk.md`](vici-ppk.md) for how that key reaches IKEv2, and
for the SP 800-227 combiner analysis — including where this construction does
**not** meet the approved form.

**The mitigation this buys is specific.** Kyber512 is the pre-standardisation
parameter set and is not approved under FIPS 203 or CNSA 2.0. What limits the
damage is that Classic McEliece is a *different* hardness assumption — code
based, not lattice based — so the composite survives a Kyber512 break. That is
an argument for the hybrid construction, not an excuse for the parameter set.

### 4.1 The code-based half is under active analysis, as of September 2026

**What the numbers are.** A line of preprints beginning August 2026 gives
conditional, heuristic cost estimates for recovering a Classic McEliece private
key that fall below the claimed level. For the set this ships, mceliece460896 —
claimed Category 3, $`2^{207}`$ classical gates:

| Source | Estimate for mceliece460896 | Stated basis |
|---|---|---|
| Saarinen, [ePrint 2026/1786](https://eprint.iacr.org/2026/1786) (7 revisions, latest 2026-09-15) | $`2^{145.22}`$ bit operations, working memory $`2^{59.10}`$ bits | *"conditional arithmetic estimate"*; the model *"excludes address generation and memory traffic and uses budget estimates for some stages"* |
| Weis, [ePrint 2026/1984](https://eprint.iacr.org/2026/1984) (2026-09-11) | $`2^{94}`$–$`2^{102}`$ in the GIJS cost model, or $`2^{114}`$–$`2^{124}`$ with GIJS's conditions unchanged — against information-set decoding at $`2^{151}`$–$`2^{287}`$ | extends the Ghoshal-Ishai-Jain-Sun hold-out distinguisher ([2026/1630](https://eprint.iacr.org/2026/1630)) to key recovery |

**What they do not say, stated first because the numbers invite the wrong
reading.** Weis's abstract is explicit: *"None of the Classic McEliece
computations is close to practical, and several ingredients are heuristic."* The
demonstrations are on toy challenge instances, not parameter sets — Weis solved
TII label 253 ($`m=8`$, $`t=9`$, $`n=214`$); Saarinen solved TII-254 ($`m=8`$,
$`t=12`$, $`n=223`$, a $`[223,127]`$ code) using 27.2 GPU-hours on GH200s
([2026/1986](https://eprint.iacr.org/2026/1986), a separate paper that makes **no
claim about any NIST parameter set**). No key has been recovered at any NIST
size, and nothing in this deployment is broken.

**The line is contested, and the scope of the objection matters.** Apon
([ePrint 2026/1810](https://eprint.iacr.org/2026/1810)) proves an
algebraic-geometry lower bound forcing $`c_{\text{need}} > 2t + 3`$, which for
mceliece8192128 puts that attack *"in excess of $`2^{1500}`$ bit operations"*.
But it is aimed at **Vedenev's route** ([2026/1747](https://eprint.iacr.org/2026/1747))
specifically and predates Weis's extraction, so it is not a refutation of the
whole line. Citing it as one would be the mirror image of citing the cost
estimates as a break.

**What this changes here, precisely.** The hybrid argument in the table above is
untouched: code-based and lattice-based remain different assumptions, and a
composite still requires breaking both. What is being re-estimated is the stated
*reason* for the choice. The pinned `rosenpass/src/pqkem.rs` says: *"Classic
McEliece is chosen because of its high security margin and its small
ciphertexts."* The margin is the thing under scrutiny.

**Two dates belong together.** BSI TR-02102-1 recommends mceliece460896
([`references.md`](references.md)) and its current version is dated 2026-01-23 —
seven months before this line began. It has not been revisited since.

**The team's silence is informative because responding is their habit.**
`classic.mceliece.org/nist.html` (page version 2026.06.23) carries dated
responses to exactly this class of claim three times over: 2025-04-17 on a
distinguisher cost claim, 2025-06-23 on a key-recovery cost claim, and
2025-11-20 on *"You Only Decapsulate Once"* — all three concerning
mceliece348864. The latest posting is still 2025-11-20; nothing addresses the
2026 line. Checked 2026-09-16. An absence of comment from a team that has
commented three times is worth more than an absence from a silent one, and it is
the reason this section reports estimates rather than conclusions.

## 5. Migration mandates in force

Dates matter here because they bound $`Y`$ for anyone deploying this.

**Two 2026 policy documents point opposite ways about this design, and both
are quoted rather than summarised because the disagreement is the point.**

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

**For, from Singapore.** CSA's *Quantum-Safe Migration Handbook V1*
(2026-07-16) is the one national instrument found that endorses this exact
shape: it treats QKD substantively, says **"QKD should be considered for
layered defence or niche use cases"**, endorses hybrid PQC + classical + QKD as
a fail-safe, and states that **"PSK with AES-256 is among the strongest options
for CII operators with existing secure distribution infrastructure"** -- which
is the PPK lane described. It sets CII deadlines of 2027-03-31 (migration plan),
2028-01-01 (procurement) and 2031-12-31 (complete). It self-describes as *"not
mandatory, prescriptive or exhaustive"*; the enforcing instrument is the CCoP.

**How to hold these together.** No authority surveyed endorses the whole
construction. BSI recommends the McEliece parameter set this ships and does not
recommend QKD ([`references.md`](references.md)); OMB is wary of both hybrid
complexity and symmetric-key protocols; Singapore endorses layered QKD and
AES-256 PSK. A proposal that quotes only the supportive one is overclaiming,
and the honest framing is the **crypto-agility and implementation-gap** case --
which no authority disputes -- rather than QKD advocacy.

**NSA does not recommend QKD for National Security Systems**, and says so on
the same page that announces its PQC selections. Read in a browser 2026-09-02
(`nsa.gov` returns 403 to scripted fetches and to the Internet Archive, so
earlier rounds recorded this as unverifiable; it is reachable interactively):

> "NSA continues to evaluate the usage of cryptography solutions to secure the
> transmission of data in National Security Systems. **NSA does not recommend
> the usage of quantum key distribution and quantum cryptography for securing
> the transmission of data in National Security Systems (NSS) unless the
> limitations below are overcome.**"

The page's PQC section points at **CNSS Policy 15, released 4 March 2025**, and
the CNSA 2.0 FAQ. Nothing dated after that appears on it, so the CNSA 2.0
timeline is unchanged as far as this page shows -- which is the question three
earlier rounds could not answer.

That makes **three of the four authorities surveyed sceptical of QKD** and none
endorsing the whole construction: NSA does not recommend it for NSS, BSI does
not recommend it at all, OMB's stack never mentions it, and only Singapore's
CSA endorses it for layered defence. The conditional matters -- NSA's objection
is "unless the limitations are overcome", not "never" -- but a proposal that
cites Singapore without citing these three is selecting its evidence.

**CNSA 2.0** (US National Security Systems) names **ML-KEM-1024** and
**ML-DSA-87** — and only those. Every new NSS acquisition must support CNSA 2.0
from **1 January 2027**; software and firmware signing and networking equipment
target exclusive use by **2030**; operating systems, custom applications and
cloud services by **2033**, ahead of the **2035** goal in NSM-10.

**This repository's IKEv2 lane negotiates `ke1_mlkem768`.** That is
NIST-approved and IETF-conformant, and it is **outside CNSA 2.0 scope**, which
approves only the 1024 parameter set. `IKE_PROPOSALS` in
`docker-compose.strongswan.yml` is environment-driven, so `ke1_mlkem1024` is a
one-variable change. Stated as available, not as done.

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
| CNSA 2.0 algorithms and dates | NSA CNSA 2.0 FAQ and transition guidance; see also [thequantuminsider.com, 2026-05-08](https://thequantuminsider.com/2026/05/08/post-quantum-migration-timelines-government-industry-impact/) |


## 7. Relationship to QCI-CAT, and what this repository does not implement

`submodules/arnika`'s README states that arnika was developed within the EU
EUROQCI / QCI-CAT programme for the use case **"HSM BACKUP USING QKD"**
(<https://qci-cat.at/hsm-backup-using-qkd>). Because this repository vendors
arnika and cites that lineage, a reader could reasonably assume it implements
that use case. It does not, and the difference is worth stating precisely.

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

So the honest statement of scope is: **this project implements the transport
half of that architecture and none of the HSM half.** Its claim is "a WireGuard
or IPsec key was rotated from QKD-derived material". QCI-CAT's is "HSM key
material crossed a QKD-protected link". The first does not imply the second.

**A note on how not to close that gap.** SoftHSM2 emulates a PKCS#11 surface,
which would make a Demo App runnable, but it does not implement HA partition
cloning and has no cross-instance replication — the very thing the use case is
about. Standing one up and calling the result "HSM backup over QKD" would
manufacture exactly the overstatement this document exists to prevent.

**Licence position.** Nothing from qci-cat.at is reproduced here — no text, no
diagram. The use case is described in this project's own words and cited by URL.

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
publishes. The imprint resolves; its contents could not be read programmatically
because AIT serves a bot-check to automated fetches, so this document does not
characterise them either way.

Which leaves the honest position: **the terms are unread, not absent.** Since
nothing is reproduced, no permission is being relied on and none needs to be
established.
