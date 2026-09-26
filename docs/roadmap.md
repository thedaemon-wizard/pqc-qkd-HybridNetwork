# Roadmap - future research extensions

Actionable work items beyond the current PoC. The code base must remain stable
before starting any of these.

Status is stated and dated per entry, and reviewed against the implemented
tree rather than carried forward untouched. Last full review: 2026-09-25; the
entries dated 2026-09-26 came with the arnika #51 adoption and were checked
against the tree that day. A review date older than the newest entry below is
a defect in this file.

## Completed since this roadmap was written

These were on the list, or implied by it, and are now done. They are recorded
here so the roadmap does not keep proposing work that already exists.

| Item | Where |
|---|---|
| Crypto-agility matrix across ML-KEM **and HQC** KEMs and ML-DSA **and SLH-DSA** signatures -- two mathematical families on each side, so a break in module lattices does not take out every option (HQC added 2026-09-25). Rendered on `/verify` from `POST /api/pqc/agility`; the browser side of the same claim is `src/lib/sim/pqc.ts`. Until 2026-08 the SERVER matrix was ML-KEM + ML-DSA only -- six algorithms, all module-lattice -- so the page called it agility while showing none. |
| Independent key-rate cross-check | TNO-Quantum backend, plus a golden vector pinned to Ma et al. 2005 in `tests/test_keyrate_golden_vector.py` |
| CI enforcement of the ETSI 014 contract | `.github/workflows/ci.yml`, job `live-stack` |
| A written key-rate derivation | [`keyrate.md`](keyrate.md) |
| Secret scanning in CI | `.github/workflows/ci.yml`, job `secrets` (was listed as "recommended" for months) |
| Reproducible seeded simulation runs | `reconcile()` now takes an injectable RNG |
| Userspace WireGuard fallback | The node image installs `wireguard-go` from Debian bookworm `main`, and `wg-quick` falls back to it with no configuration when the kernel module is absent. See [`BUILD.md`](BUILD.md) section 5.3 |
| Protocol Lab: trusted-node key relay, re-routing, and the ETSI GS QKD 014 / 004 message sequence, over published networks | `/protocol-lab`, client-side and labelled a simulation; see the decision record below (2026-09-25) |
| ETSI GS QKD 004 V2.1.1 application interface | `bb84-kme`, over this project's HTTP/JSON binding, off by default; [`etsi004-binding.md`](etsi004-binding.md) (2026-09-25) |

## Known gaps - model and protocol

Recorded rather than scheduled. These are limitations of the physics and
protocol modelling, and are not expected to close without new work upstream.
Implementation gaps are tracked separately, under "Implementation gaps still
open" below.

| Gap | Consequence |
|---|---|
| No real error correction | `reconciliation.py` hashes Alice's bits and applies a heuristic entropy margin. $`f_{\mathrm{EC}}`$ is an assumed constant, and no leakage is measured. |
| ~~First-order finite-key term only~~ **CLOSED 2026-08-28** | Was "not a composable security proof". It now is one: Lim et al. PRA 89, 022307 (2014) with $`\varepsilon_{\text{sec}}`$ and $`\varepsilon_{\text{cor}}`$ tracked separately and a key LENGTH in bits. See [`keyrate.md`](keyrate.md) section 5. The residual caveat is different in kind and is stated there -- the counts fed to the estimators are EXPECTED under the channel model, not observed, so the output is an expected key length and the $`\varepsilon_{\text{sec}}`$ guarantee does not attach to a simulated number. |
| ~~Upstream plans to remove the file-based PQC handover~~ **ADOPTED 2026-09-26** | Open arnika PR [#51](https://github.com/arnika-project/arnika/pull/51), *feat(keyreader): pqc-hpke (RFC 9180)*, replaced the file handover this PoC's PQC half used (Rosenpass wrote `/var/lib/rosenpass/pqc.psk`, arnika read it through `PQC_PSK_FILE`) with an in-band HPKE key agreement between the arnika peers. This repository now pins `f4cf9ba`, the PR's head (2026-09-24), ahead of its merge: every arnika instance runs `PQC_ENABLED=true` with `QkdAndPqcRequired`, and Rosenpass keys the separate `wg1` data tunnel inside `wg0`, the layering of the reference paper. The three files the build asserts on moved as recorded here before (`repositories/kms/kms.go`, `repositories/wgnetlink/netlink.go`, `wire_wireguard_netlink.go`), and the VICI adapter moved to the one-method port. What remains open is listed under "Follow-ups from adopting arnika #51" below. |
| Static channel model | Measured field data (arXiv:2608.18869): the mostly aerial link showed about twice the QBER of the mostly buried one despite lower attenuation, measured in separate campaigns, and its QBER correlates with wind speed (r = 0.78 at 15-minute resolution, section IV.B). See [`references.md`](references.md). The model cannot express that. |
| The asymptotic decoy bound takes $`Y_0`$ as known | `asymptotic_skr_per_pulse` and its TypeScript port use the configured dark-count yield directly. A real protocol bounds it from the vacuum decoy ($`Y_0^L`$). The finite-key rate the backends report already estimates the vacuum term from decoy counts; see [`keyrate.md`](keyrate.md) sections 4 and 5. Recorded 2026-09-25. |
| Rotation cadence set by policy, not by link capacity | At the measured 12-22 bit/s a 256-bit key needs 12-20 s to accumulate; `ARNIKA_INTERVAL` should be derived from measured SKR. |
| RFC 9867 not available on this lane | Stated as two reproducible observations rather than the flat "no open-source IKEv2 implementation has it" that stood here -- that claim is not checkable, and the supporting one ("strongSwan marks it unsupported in its own features table") pointed at a file that is **not in the pinned tree**: it lives in the separate `strongswan/strongswan-docs` repository. What can be established: (1) `USE_PPK_INT` (16445) and `PPK_IDENTITY_KEY` (16446) appear nowhere under `submodules/strongswan/src/`, and **16444 is the highest Status Type** in `notify_payload.h`, so they sit immediately above the top of the range; (2) the `IKE_SA_INIT` response on this lane carries `N(USE_PPK)`, and RFC 9867 §3.1 has a responder return either that or `USE_PPK_INT`, never both. Both are pinned by `tests/test_claims_about_the_pinned_strongswan_hold.py`. Consuming fresh QKD material therefore needs a full reauthentication per rotation. See [`vici-ppk.md`](vici-ppk.md). |
| ETSI `key_ID` not bound to the ciphertext | arXiv:2607.06602 binds it into the AEAD AAD; neither arnika nor this project does. |

## A. Shor's Algorithm Attack Simulator
**Goal:** Quantify the threat that motivates the entire PQC/QKD investment.

**Tasks:**
1. Add `services/shor-attack-sim/` (Python + CUDA-Q + PennyLane + pyzx)
2. Implement period-finding circuit for small N (N=15, 21, 35) end-to-end
3. Add ZX-calculus T-count optimisation (`pyzx`) and report the optimised gate count
4. Add NVIDIA cuQuantum / Tsim tensor-network backend for ≥ 30-qubit demonstrations
5. WebUI page "Attack Lab" with side-by-side: classical brute force vs Shor scaling curve

**Files to add:**
- `services/shor-attack-sim/app/shor.py`
- `services/shor-attack-sim/app/zx_optimize.py`
- `services/webui-frontend/src/pages/AttackLab.tsx`

**References:**
- NVIDIA CUDA-Q docs
- `pyzx` GitHub
- NIST IR 8545, *Status Report on the Fourth Round of the NIST Post-Quantum
  Cryptography Standardization Process* (2025-03), and NIST IR 8610, *Status
  Report on the Second Round of the Additional Digital Signature Schemes*
  (2026-05). These replace NIST IR 8413, the 2022 third-round report.

## B. HNDL (Harvest Now, Decrypt Later) Simulator
**Goal:** Make the time-shifted attack tangible for stakeholders.

**Tasks:**
1. `services/hndl-simulator/` captures `tcpdump` of the `wan-net` UDP/51820 traffic
2. Stores ciphertext blobs into a "cold archive" volume
3. WebUI timeline: rotation interval ↔ HNDL exposure window plot
4. Manim animation: "captured today, decrypted once a CRQC exists" -- the date
   is deliberately unspecified, as in [`threat-model.md`](threat-model.md)

**References:**
- NIST IR 8547, *Transition to Post-Quantum Cryptography Standards* (initial
  public draft, 2024-11-12; not final)
- CISA, NSA and NIST, *Quantum-Readiness: Migration to Post-Quantum
  Cryptography* (factsheet, 2023-08-21)

## C. QLSTM-IDS for QKD attack detection
**Goal:** Detect side-channel and protocol attacks on the BB84 link.

**Tasks:**
1. Generate labelled dataset from `app/bb84/simulator.py` with 8 attack scenarios:
   normal / intercept-resend / PNS / Trojan / RNG-bias / wavelength-trojan /
   detector-blinding / combined
2. Implement QLSTM with PennyLane (see `rdisipio/qlstm`)
3. Train + benchmark vs classical RandomForest + GradientBoosting
4. WebUI page "IDS Live" — per-photon attack probability stream

**Reference figures**, from Al-kuwari et al., *Resisting Quantum Key
Distribution Attacks Using Quantum Machine Learning*, IET Quantum Communication
(2026), doi:[10.1049/qtc2.70028](https://doi.org/10.1049/qtc2.70028),
[arXiv:2509.14282](https://arxiv.org/abs/2509.14282): the hybrid QLSTM at 50
epochs reports accuracy 94.7 %, precision 95.1 %, recall 94.7 % and F1 94.7 %.
The authors evaluate on a semi-realistic, simulation-generated decoy-state BB84
dataset and describe the result as a proof of concept, not an assessment on
field-deployed QKD systems -- so these are figures to compare against, not
targets a detector here would be expected to reach on real data.

## D. NIST PQC Algorithm Sweep
**Goal:** Benchmark the NIST post-quantum algorithms exposed by `liboqs`, with
their standardisation status stated per row.

**Tasks:**
1. `services/pqc-benchmark/` runs liboqs-python on the host
2. Algorithms, in two groups that must not be merged:
   - **NIST-standardised (FIPS 203/204/205):** ML-KEM-{512,768,1024},
     ML-DSA-{44,65,87}, SLH-DSA parameter sets.
   - **Selected or draft, not yet standardised:** FN-DSA / Falcon (FIPS 206,
     no public draft), HQC (FIPS 207, no public draft; the pinned liboqs
     already builds it), and the additional SLH-DSA parameter sets of
     SP 800-230 (initial public draft, 2026-04-13).
3. Compare key/signature sizes, handshake time, RAM, CPU
4. WebUI page "PQC Catalogue" — sortable table + bar chart

## E. NIST CSF 2.0 / SP 800-56C / SP 800-208 compliance mapping
**Goal:** Make the PoC defensible in audit conversations.

**Tasks:**
1. Add `docs/compliance.md` with explicit mapping:
   - NIST CSF 2.0 functions (GOVERN/IDENTIFY/PROTECT/DETECT/RESPOND/RECOVER) ↔ PoC components
   - SP 800-56C Rev 2 ↔ HKDF-SHA3-256 implementation in `submodules/arnika/kdf/kdf.go`.
     NIST announced a revision of SP 800-56C Rev. 2 on 2026-01-06, to let the
     shared secret Z include a KEM shared secret; map against the revision
     once a draft exists. See [`references.md`](references.md).
   - SP 800-208 ↔ optional LMS/XMSS signing of WireGuard config (D-stage)
2. CI job to fail if mapping drifts

## F. QuLore-style adaptive security
**Goal:** Implement the 4-level dynamic security model.

**Tasks:**
1. Add `services/qusec/` (central controller in Python)
2. Per-link security level selection (L1 direct QKD, L2 multi-hop OTP relay, L3 hybrid KDF, L4 PQC-only)
3. WebUI Topology page colours edges by current level

## G. QRNG + AI quality evaluation
- Replace classical numpy RNG in BB84 with QRNG model output
- CNN-based quality evaluation (no source selected yet; an earlier entry cited
  a journal without an identifier)

## H. Quantum Federated Learning + FHE
- Use QKD-derived keys to securely distribute FHE parameters across federated participants
- Reference: `elucidator8918/QFL-MLNCP-NeurIPS`

## Implementation order
1. **D** (PQC sweep) — pure compute, low risk, immediate research value
2. **C** (QLSTM-IDS) — leverages existing BB84 simulator data
3. **A** (Shor sim) — needs CUDA-Q and time
4. **B** (HNDL) — mostly visualisation; small lift
5. **E** (Compliance) — documentation
6. **F**, **G**, **H** — longer-term

## Decision record: the word "phase" appears in three unrelated schemes

Recorded because a request to delete the Phase labels if they were not needed
was raised repeatedly and never actioned, and the reason was never written
down, so it kept coming back. It is written down now.

There are three numbering schemes, all called "phase":

| Scheme | Numbers | Owner |
|---|---|---|
| Build phases | 0, 2-4, 8-14 | this project's own milestones, `docs/phases.md` |
| Protocol phases | 1-5 | this project's split of the paper's four numbered stages (arXiv:2604.05599, 4.2 and 4.3), laid out against its Table 1 |
| `/e2e` orchestration | 1-4 | this project's own invention |

**The second is ours, not the paper's.** arXiv:2604.05599 never uses the word
"phase". It numbers the components (1)-(4) in 4.2 (Integration Workflow) and
4.3 (Fail-Safe Mechanism), calls them the "stages" of the setup Figure 3
illustrates, and captions Table 1 "Packets and Traffic per Handshake or Key
Negotiation". The five-way split is this repository's: phase 1 is stage (1),
phase 2 is (2), phases 3 and 4 split (3) into the WireGuard hop handshake and
the Rosenpass exchange carried over it, so each Table 1 row is its own phase,
and phase 5 is (4). `services/webui-backend/app/paper_budgets.py` holds Table 1
in that layout and quotes its caption verbatim, `/paper-flow` draws it, and
`tests/test_paper_budgets.py` pins the totals to the three rows the paper
prints.

It keeps the word "phase" anyway, because the obvious alternative collides:
"stage" is the paper's word for a four-way count, and calling this five-way
split stages as well would make "stage 4" mean two different things.

**So the fix is disambiguation, not deletion.** `/e2e`'s scheme has no
counterpart in the paper, so it now says **step** -- "Active step", "Step
history" -- which removes one of the three collisions at no cost to fidelity.
`/paper-flow` keeps "phase" as its own label and puts the paper's stage number
beside it: "this page's 5 phases, splitting the paper's stages (1)-(4)",
"phase 5 = paper stage (4)". A reader who sees `Phase 8` in the docs and
`phase 5 = paper stage (4)` in the UI can now tell they are unrelated, which
was the actual problem behind the request.

The build phases keep the bare word because `docs/phases.md` is where a reader
already expects project history.

---

## Decision record: client-side compute stack

The public demo must not put simulation load on the server, so every simulation
page computes in the browser. Several runtimes are routinely suggested for that.
Recording which are used and which are not, so each reads as a decision rather
than an oversight.

**What is used.** Pure-TypeScript `@noble/*` for the cryptography, and a Web
Worker for the BB84 Monte-Carlo with optional **WASM**, WebGL2 and WebGPU
compute paths for the pulse loop.

**WASM was rejected below and later adopted.** The rejection rested on bundle
cost. That prior was then measured -- the Rust kernel compiles to **907 bytes**
-- and the decision was reversed; `services/webui-frontend/src/lib/sim/bb84Sim.ts`
ships an engine named `WASM (Rust, 907 B)` and `/bb84` offers it in the
accelerator picker. This section's summary was not updated at the time, and
neither was checklist row 4.6.5, which went on asserting "zero occurrences" of
WASM in the frontend source until 2026-08-29 while row 4.5.14b twelve lines
above pinned WASM as a measured tier. Both are corrected; the paragraph below
is kept because the reasoning it records still applies to the ML runtimes, and
because a reversal is more useful with its original argument visible than
without.

The tier is chosen by measurement rather than preference: each GPU rung is
benchmarked against the Worker for one round and adopted only if it wins. On
the public demo that currently keeps the Worker, and the console records why --
`[bb84] WebGPU 34M/s <= Worker 62M/s -- keeping Worker`.

> **Correction.** This paragraph previously said "every rung produces identical
> results because the physics is seeded through `pure-rand`". No part of that
> held. `pure-rand` was declared in `package.json`, imported nowhere, and has
> been removed. The Worker seeds a **mulberry32** (`bb84.worker.ts`) while both
> shaders run **xorshift32**, and every rung reseeds from `Math.random()` each
> round -- so the rungs are statistically equivalent, not identical, and no run
> is reproducible.
>
> **Closed 2026-08-29 for the run, not for the rungs.** `?seed=1234` on `/bb84`
> pins the per-round seeds through `lib/sim/runSeed.ts`, so the SAME rung
> replays exactly and `/bb84`'s stats panel reports `seed` and
> `reproducible: true`. Without the parameter the path is exactly what it
> was, which matters because the demo's throughput figures were measured on it.
> What is still NOT closed is cross-rung agreement: Worker mulberry32 and
> shader xorshift32 give the same seed different samples, and making them
> identical means one PRNG in three languages. The seed buys reproducibility,
> not tier equivalence -- do not conflate them.
>
> What IS bit-exact is narrower and worth keeping straight: `Xorshift32` in
> `bb84Channel.ts` reproduces the shader PRNG exactly, so the photon-frame
> replay shows the pulses the shader actually computed rather than an unrelated
> sample. That is the only place identical output is claimed, or needed.

**WebAssembly.** Rejected for the cryptography. `@noble` is already constant
time by construction and small enough that the bundle cost of a WASM build
outweighs the throughput gain at the sizes used here (a few ML-KEM operations
per page view, not a stream). It remains the right answer if the PQC sweep in
section D grows to thousands of keygen operations per run, at which point the
tradeoff reverses; the interface is deliberately narrow enough to swap.

**WebNN and WebLLM.** Rejected on correctness grounds, not performance. Both
target neural inference, where approximate arithmetic and non-deterministic
operator scheduling are acceptable. This project needs exact integer arithmetic
for ML-KEM and bit-reproducible results for the physics, since a seeded run must
produce the same key rate on every machine for the golden vector in
`tests/test_keyrate_golden_vector.py` to mean anything. An inference runtime is
the wrong tool for both.

**ONNX Runtime Web.** Same objection, plus it would add a multi-megabyte
dependency to serve a workload with no model in it.

The QLSTM-IDS work in section C is the first item that genuinely wants an ML
runtime. If it lands in the browser rather than server-side, ONNX Runtime Web is
the candidate to revisit, and it should be scoped to that page alone rather than
adopted as the general compute story.


---

## Decision record: Protocol Lab (2026-09-25)

**The commitment.** An early plan promised a "Protocol Lab" page: a side-by-side
view of ETSI GS QKD 014 and 004, key buffers at each node, trusted-node relay,
re-routing around a failed link, and a route controller's view, backed by an
NS-3 / qkdnetsim simulation and a "Czech National 13-node" topology.

**What shipped** is route 14, `/protocol-lab`, computed entirely in the browser
and labelled a simulation before anything runs:

- five published networks -- Cambridge 2019, SECOQC Vienna 2008, Tokyo 2010,
  MadQCI 2024 and the Thuringia chain of arXiv:2608.18869 -- with every number
  stored as the source printed it, with its reference;
- three cited scenarios that replay the sources' own runs and state where the
  replay departs from them (SECOQC section 5.1.2, Tokyo section 4, Cambridge
  Fig. 3);
- per-link key stores following this repository's KeyPool rules, a service-side
  store, trusted-node relay with real one-time pads (prefixes only ever leave
  the simulator), and a route controller panel that displays and does not act;
- a timeline pairing this stack's 014 message shapes per hop (sizes in bits)
  with a simulated 004 V2.1.1 stream end to end (sizes in bytes, status codes
  from Table 2), driven by `etsi004SpecV211.json` -- the same file the KME's
  real endpoint loads;
- this project's key-rate model beside each reported rate in the link table,
  never in the simulation.

**What was withdrawn, and why.**

- *NS-3 / qkdnetsim backend.* No qkdnetsim binary is run anywhere in this
  repository; `qkdnetsim-kme` is a Flask facade that builds NS-3 and does not
  execute it. Driving a live page from NS-3 would need its real-time emulation
  path: qkdnetsim's own ETSI 014 emulation examples attach to real interfaces
  through `EmuFdNetDevice` (raw sockets, `CAP_NET_RAW`) or, in the `_tap`
  variant, `TapFdNetDevice` (TAP, `CAP_NET_ADMIN`) under
  `RealtimeSimulatorImpl`, and the image does not build the `fd-net-device`
  module. That is a privileged server-side process per demo, for a view the
  browser can compute. The licence is not the reason: GPL-2.0 does not
  restrict running or hosting the program and permits commercial use; its
  source obligations arise only if the image or binaries are distributed (see
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)).
- *A 004 endpoint on qkdnetsim-kme (port 81).* Depends on the above, and
  qkdnetsim's own 004 application is partial: point to point, reads only
  Key_chunk_size, returns no status codes and ignores a requested index. The
  real 004 endpoint went into `bb84-kme` instead.
- *Live buffers on `/topology` and a qkdnetsim statistics poller.* Nothing
  produces those statistics, and a page that reports live state must not show
  browser-simulated values.
- *A re-routing API.* There is no route controller in the running stack.
- *Benchmarks fed by qkdnetsim callbacks.* `/benchmarks` is a live-state page.
- *Cross-validating relay and the 004 lifecycle against live KMEs.* The running
  stack relays nothing; the 004 endpoint is tested by its own contract suite.
- *Czech National 13-node.* No source for a 13-node network was found. The one
  Czech paper models a six-node chain whose rates are calculated, not measured,
  whose segment lengths do not add up to its stated spans, and which says itself
  that no equipment data is available.
- *Beijing-Shanghai backbone.* Paywalled, with no per-link table.

Two citations were corrected on the way: the QKDNetSim+ paper is by Soler et
al., not Mehic (checked on Crossref), and a claim that a DRCN 2023 paper was the
basis of a route controller had never been verified and is not repeated.

**Still open.**

- MadQCI's Table 1 rates are per system, some per direction, and from different
  periods; binding one to each span is left undone rather than guessed.
- Maximum-flow capacity between two nodes (SECOQC section 5.2) and more than one
  concurrent demand.
- Edition 3 of GS QKD 004, once published, as a separate spec file.
- qkdnetsim commit `7a99fc17` (2026-08-24) adds QKD+PQC key mixing to the key
  management layer upstream; worth reading before any further qkdnetsim work.

---

## Decision record: withdrawn or deferred from the early plans (2026-09-25)

The early plans promised more than the Protocol Lab. Each item below is either
withdrawn or deferred, with the reason, so none of them reads as an oversight
or comes back as new work.

| Item | Status | Reason |
|---|---|---|
| CV-QKD Lab page (homodyne histogram, PLOB bound curve) | Deferred | The `cvqkd` backend (GG02) is a full KME backend: whenever it is selected (`SIMULATOR_BACKEND=cvqkd`, which `deploy/.env.example` sets, or the `/physics` selector where live overrides are enabled), both KMEs produce keys with it and both VPN lanes draw from them. It is not the repository default (`simqn`). What is missing is the page: a teaching view would need its own key-rate model derived and tested first. |
| Protocol Zoo (B92, E91, SARG04) | Withdrawn | Only decoy-state BB84 is modelled end to end. Each further protocol needs its own derivation in [`keyrate.md`](keyrate.md) and a golden vector, which is the bar BB84 had to meet. |
| MDI-QKD backend and its detector-side-channel immunity test | Withdrawn | Needs a two-sender channel model and a separate finite-key analysis, and nothing in the stack would consume its keys. |
| Hardware-in-the-loop compose profile, dry-run test and a fake HIL device | Deferred | No hardware has been tested against this PoC, and a fake device would test the fake. Blocked on the ETSI 014 TLS gap listed under "Implementation gaps still open" below; `/hil` documents the manual path. |
| QOSST (CV-QKD software stack) as a backend | Withdrawn | Not vendored; `cvqkd` already covers GG02 in simulation, and the CV-QKD Lab above is deferred. |
| Cross-validating the Rust ETSI 014 KME | Deferred | `submodules/qkd_kme_server` is vendored and in no compose profile ([`phases.md`](phases.md), Phase 14). Running `tests/test_etsi014_contract.py` against it needs a build stage and a service definition first. |
| Paper-baseline overlay on `/benchmarks` | Withdrawn | `/benchmarks` shows live state only, and no local measurement exists to overlay ([`benchmarks.md`](benchmarks.md)). The paper's figures are on `/paper-flow` and `/verify`. |
| Prometheus and Grafana containers | Deferred | The KMEs already expose `/metrics`; a scraper and dashboards would duplicate the WebUI's polling on a single-host demo. |
| Generated SBOM (CycloneDX or SPDX) for the images | Deferred | [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) is the hand-maintained inventory, checked against the pins by `tests/test_notices_match_the_pins.py`. |
| A running `wgephemeralpeer` container | Withdrawn | Reasons in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`IMAGE1_VPN_SCOPE.md`](IMAGE1_VPN_SCOPE.md). |
| QuNetSim and NetSquid | Withdrawn | Reasons in [`keyrate.md`](keyrate.md) section 8. |

## Deferred from the 2026-09-25 batch

Found or decided during the 2026-09-25 batch and left for a later change of
its own. Related items live elsewhere in this file and are not repeated:
$`Y_0^L`$ in the asymptotic bound (Known gaps); the arnika bump past PR #51,
done on 2026-09-26 (Known gaps, and its follow-ups below); Protocol Lab
maximum-flow capacity and concurrent demands, under that decision record's
"Still open".

| Item | What is wrong or missing | What closing it involves |
|---|---|---|
| `/bb84` click model | The per-pulse detection probability is `etaTotal + Y0`, which omits the signal intensity $`\mu`$ (section 2 of [`keyrate.md`](keyrate.md) has $`Q_\mu = Y_0 + 1 - e^{-\eta\mu}`$), and a dark-count click carries Alice's bit instead of a uniformly random one ($`e_0 = \tfrac12`$). | The same change in all four engines -- the TypeScript Worker, the WGSL and GLSL shaders and the WASM kernel -- which must keep agreeing (`wasmAgreesWithWorker.test.ts`, `bb84Channel.test.ts`). |
| Docker socket on `webui-backend` | The full profile mounts `/var/run/docker.sock` read-only into the internet-facing backend to enumerate containers and read logs. Container control is off by default, but the socket is still there. | A separate status service that holds the socket and exposes only the fields `/api/stack` and `/api/logs` use. Architectural; the highest-priority item in this table. |
| `/bb84` variability mode | The field data of arXiv:2608.18869 varies with time; `/bb84` draws every round from one static channel. | A mode drawing per-round parameters from a distribution. Deferred because the distribution's parameters would be this project's derivation, not the source's. |
| SeQUeNCe v1.2.0 | The pin is `v1.0.0` (2026-06-17); v1.2.0 was released 2026-09-12 and is 64 commits ahead ([`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)). | A before/after on the `sequence` backend, and a check of v1.2.0's numpy range against the KME's `numpy==2.5.3` pin. |
| oqs-provider | The pin is `5fd81fb` (2026-05-12), 37 commits past 0.10.0 on `main`. `main` has 20 commits more, among them four fixes the pin lacks -- a heap overflow (#810), a double free (#816), a use-after-free (#829) and missing length checks on hybrid KEM public keys (#814), listed in the header of `services/pqc-tls-demo/Dockerfile.oqs-provider` -- and the re-activation of HQC (#787). 0.11.0 (2025-12-24) is on a release branch that does not contain the pin, and 0.12.0 is at rc2 (2026-09-16). | Bump once 0.12.0 is final, rebuilding against the pinned liboqs; the Dockerfile's per-group negotiation check then shows whether HQC groups can join `TLS_GROUPS`. |
| qkdnetsim v3.1.4 | The pin `1cda34c` (2026-05-03) is three commits before v3.1.3 and four before v3.1.4 (2026-09-21). Those four add QKD+PQC key mixing to the key-management layer (`7a99fc17`) and move qkdnetsim to NS-3 v3.48, while `services/qkdnetsim-kme/Dockerfile` builds NS-3 v3.46. | Low priority: nothing runs qkdnetsim. Bump the pin and `NS3_REF` together, and build the image by hand, since CI does not build it. |
| Strawberry Fields | Archived upstream on 2026-01-16, and still installed in the `bb84-kme` image (editable, from `submodules/strawberryfields`) because the `cvqkd` backend runs its Gaussian simulator. It imports `pkg_resources`, which holds `setuptools<81` in `services/bb84-kme/requirements.txt` and `constraints.txt`. | Replace the dependency in `cvqkd_backend.py`, then drop the submodule and the `setuptools` hold. `tests/test_cvqkd_is_a_cv_protocol.py` must keep passing. |
| Base images | The WireGuard node image (`nodes/alice/Dockerfile`) is still on bookworm: its runtime (`debian:bookworm-slim`), its Rust stage (`rust:1.90-bookworm`) and its arnika stage (`golang:1.26-bookworm`). The strongSwan node's runtime is on trixie, but its arnika stage is `golang:1.26-bookworm` too (`nodes/strongswan/Dockerfile`). `services/qkdnetsim-kme/Dockerfile` is on `ubuntu:22.04`. | Move the bookworm stages to trixie and the Rust stage to a current image, each verified by the `images` CI job. The Go stages must stay on Go 1.26 or later (arnika uses `runtime/secret`). |

## Follow-ups from adopting arnika #51 (2026-09-26)

The pin moved to `f4cf9ba`, the head of the open arnika PR #51, for release
0.2.0, which is not tagged yet (see Known gaps above and
[`phases.md`](phases.md)). What that left open:

| Item | What is open | What closing it involves |
|---|---|---|
| Re-pin on merge | `submodules/arnika` points at the head of a pull request that is open and has no upstream review (checked 2026-09-26), not at a commit on upstream `main`. A change to the branch before it merges would change what the pin means, while the notices, the build guards and these documents describe `f4cf9ba`. | Re-pin to the merge commit on `main` as soon as #51 merges: diff it against `f4cf9ba`, re-run the build guards and CI, and update the `arnika` row of [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Until then, move the pin only after reading what changed on the branch. |
| Before/after measurement of the IPsec lane's authentication failures | Planned, not done. Two arms of 168 hours on the same host and configuration, one at the previous pin `3a8cc13` and one at `f4cf9ba`, with the counting rules fixed before either run. | Run both arms, then report each arm's rotations and failures split by alice's role and by class, with exact binomial confidence intervals. The design, the held-constant settings and the counting rules are in [`vici-ppk.md`](vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race). |
| What `3e02741` does to the rotation race | Expected to move, not close, the window -- unmeasured. Reading the code, the BACKUP now installs before it ACKs and the PRIMARY after, so intervals where alice is PRIMARY are expected to be safe from this race and intervals where alice is BACKUP to become the exposed ones, since alice is always the IKE initiator. | The measurement above decides it. If failures appear in alice-BACKUP intervals, the candidate mitigations are a generation-scoped `PPK_ID` ([`vici-ppk.md`](vici-ppk.md), "The actual fix") or delaying the initiator's reauthentication; neither is started before the numbers exist. |
| New fail-closed paths and start offsets | Under `QkdAndPqcRequired` the pinned arnika installs a random key when a BACKUP interval ends without a `key_id`, when the PRIMARY gets no ACK, and when no PQC-HPKE key exists yet. Its interval counter is per process, so two processes started at different moments disagree about which interval a `key_id` belongs to: local runs without alignment showed `no key_id from the peer` invalidations on the later-started node, at the end of 13 of its 21 BACKUP intervals over three WireGuard runs and twice in one IPsec run of about 6 minutes (observations, not a measurement). The WireGuard entrypoint now starts arnika on a wall-clock interval boundary, which restores the start synchronisation that lane had before; the IPsec entrypoint deliberately does not, so that both arms of the measurement run the same entrypoint start behaviour, with the start offset measured in each arm ([`BUILD.md` 7.3](BUILD.md#73-starting-arnika-on-the-interval-boundary)). Neither is a mitigation of the rotation race. The alignment also holds only at the start: each ticker re-bases after its own processing, so the offset between the two ends wanders by milliseconds per interval (in that IPsec run, from about 255 ms to about 217 ms over 12 intervals). From reading the code, a BACKUP that lags its PRIMARY by more than the PRIMARY's KMS fetch time can receive the `key_id` before its own boundary and count it in its previous interval, and it then fails closed at the end of the current interval if the next `key_id` is not early too, in practice at its BACKUP-to-PRIMARY transitions; in the IPsec run bob received early `key_id`s in intervals 2 to 8, 10 and 11 and invalidated only at 8 and 11. | Count `no key_id from the peer` on both nodes of each lane over a long window (on the IPsec lane, arm B's), beside the offset between the two ends' interval boundaries over time, the early `key_id`s and any interval in which their interval numbers differ, so the effect of the start offset and its drift is a number rather than an expectation. `scripts/ppk_race_report.py` records these for the IPsec pair; no tool records them for the WireGuard pair yet, whose lines are compared by hand. |
| Raise the single-restart case on arnika#51 | Neither lane's start timing helps a node restarted alone: its count starts again at 0 while its peer's does not, the two HMAC elections stop being complementary, and in each interval where both come out BACKUP both ends fail closed. On the WireGuard lane two containers that reach the alignment on either side of a boundary start whole intervals apart, with the same result. This is #51's behaviour, from reading the code; not measured. | Measure it first: a local run that recreates only `bob-ipsec`, counting both-BACKUP intervals and invalidations on both nodes against a run that recreates both. Then raise it on #51 with those numbers and the drift above, leaving the design (for example a shared interval epoch) to upstream. Until then the operating rule stands: the two nodes of a pair are recreated together. |
| The PQC-HPKE read gap | Each peer reads the latest published PQC-HPKE key when it builds its PSK: the PRIMARY before it sends the `key_id` (`main.go:369`), the BACKUP after its `dec_keys` request. The two reads are apart by the `key_id` delivery plus a KME round trip, and a round published between them gives the peers different keys until the next rotation. Upstream's `docs/pqc-hpke.md` calls closing it an open design question. | Upstream's to settle. Here, compare the two nodes' `round agreed a fresh PQC key` lines for any failing interval, so this cause is not confused with the race. |
| SP 800-227, the PQC input | The combiner's PQC input is now an HPKE export over MLKEM1024-P384. Whether that counts as derived from an approved KEM is open, and FixedInfo is still absent ([`vici-ppk.md`](vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner)). | Revisit when draft-ietf-hpke-pq is published as an RFC or a draft of SP 800-56C Rev. 3 appears. |
| One Rosenpass initiator per pair | Only the node with the lower `wg0` address initiates the Rosenpass exchange; the other answers and never initiates, which is how rosenpass v0.2.3 behaves when a peer has no endpoint, not an interface it documents ([`BUILD.md` 7.2](BUILD.md#72-arnika-and-the-two-wireguard-interfaces)). With both ends initiating, cold starts left the two ends on different `wg1` keys for 120 s. | `tests/test_rosenpass_responder_never_initiates.py` ties the assumption to the pinned rosenpass commit (`512fe42`, v0.2.3) and checks the source lines it rests on. Re-check the behaviour whenever `submodules/rosenpass` moves; that test fails on the new commit until it is updated, so a bump cannot skip the re-check. |
| Upstream's description of this project | The arnika README, at `f4cf9ba` too, describes this project's lanes as fusing the key of a McEliece + Kyber512 PQC sidecar, which stopped being true on 2026-09-26. | Offer the maintainers replacement text; the wording of their README is theirs to decide. |

## Status as of 2026-08-21

Closed by 2026-08-21, with the evidence rather than the intention:

- **VICI lane** verified in CI on `main`: both peers negotiate
  `AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK`, hold exactly
  one IKE_SA, and rotate. The residual rotation race (the responder loads its
  PPK after the initiator has sent IKE_AUTH) was **1 failure in 45
  rotations** on the first two-node run; its later, much lower rate is in
  [`vici-ppk.md`](vici-ppk.md). The CI job observes only ~6 rotations in its
  240 s window, so its 20 % ceiling tolerates one failure per run.
- **Dead backend removed.** `e2e_orchestrator.py` and `paper_flow.py` are gone
  along with ~200 lines of unreachable routes; `main.py` 842 -> 684. The paper
  budgets moved to `paper_budgets.py` and are now pinned by a test.
- **rosenpass** 2024 pin -> v0.2.3, which forced `rust:1.83` -> `rust:1.90`
  because a transitive dependency declares edition 2024.
- **README** 490 -> 380 lines; build detail and limitations split out.
- **Formulas** all render on GitHub -- `\boxed{}` and `aligned` are not in its
  MathJax subset and were showing as raw source.
- **Two shell scripts were unrunnable** (CRLF), including the repository's own
  secret scanner. Fixed by normalisation; `.gitattributes` prevents recurrence.
> **On the 12.07 Mbps figure.** It is the closed-form rate the SHIPPED
> configuration implies, not something any run measured. `skr_bps_from_config`
> takes only `cfg`; two demo nodes at 6 and 12126 rounds report it
> bit-identically. It is the right number to compare a backend against -- that
> is the whole point of the comparison below -- but it is a prediction, and
> "an actual 12.07 Mbps" said otherwise. See `modelled_skr_bps` on /sim/stats.

- **`skr_bps` reported a sifting fraction, not a secret-key rate**, in all
  three backends -- 500 Mbps against a closed-form 12.07 Mbps, a factor of 41. All
  now route through the golden-vector-tested GLLP/Lo-Ma model. SimQN also
  flags synthesised rounds, which the default configuration produces.
- **The CV-QKD backend emitted zero keys** (165 rounds, 165 aborts on the live
  demo). Five defects: transmittance applied twice, excess noise passed as a
  thermal photon number, modulation at twice the intended variance,
  `Coherent(r, phi)` used as if Cartesian, and a BB84 QBER threshold gating a
  continuous-variable protocol. The Holevo bound is now the symplectic form.
- **The liboqs "independent cross-check" compared byte counts.** It asserted
  `ss_len` and `ct_len` against the browser's values -- two implementations
  agreeing that ML-KEM-768 ciphertext is 1088 bytes shows only that both read
  the same table in FIPS 203. `/api/interop/mlkem` now has liboqs encapsulate
  to a key the browser generated, and the two must derive the same shared
  secret. `/api/kat`, which accepted a seed and used it only for `len(seed)`,
  no longer describes itself as a known-answer test or reports a PQClean check
  it never performed. Building PQClean was rejected as the remedy: archived
  2026-08-04, its notice redirects to mlkem-native / mldsa-native / slhdsa-c.
- **ML-KEM now has a known-answer test.** Pinned to NIST ACVP
  (`ML-KEM-keyGen-FIPS203` tgId 2 tcId 26, commit `15c0f3de`) in both liboqs
  and `@noble`, plus a cross-derived vector covering all three parameter sets.
  The C2SP/CCTV intermediate vectors were tested and discarded -- they target
  FIPS 203 ipd, not the final standard, and every value mismatches.
- **Two view-layer defects that no test could see.** The `/e2e` failure banner
  recomputed the fatality rule in JSX and mislabelled the two cells where a
  mode never used the failed layer; the `/pqc` panel heading was a hardcoded
  "FIPS 204" over correct FIPS 205 sizes. In both the data was right and only
  the label was wrong, so the suites passed. Both now read the model.
- **GIF playback ran faster than the recording.** Frame delays are timed as
  captured rather than assumed from the nominal interval.
- **`/bb84`'s photon table is now the run** on the GPU tiers: the round is
  replayed from its own seed instead of resampled with `Math.random()`.
- **The QBER threshold line reads `qber_threshold_abort`** rather than a
  literal `0.11`, and the key-pool model is one shared function instead of
  three verbatim copies.
- **`/bb84`'s offline defaults had drifted from `qkd_params.yaml`** -- 25 km
  against a configured 10 km, and 1e7 against 1e9 pulses per second. A test now
  compares the two files.
- **The paper-budget match check could not fail.** It compared the sum of the
  phase table against a constant defined as that same sum; the paper totals are
  now transcribed independently.

## Implementation gaps still open

Re-verified 2026-09-25 against the code.

- **`PQC_PROVIDER` is not implemented.** Withdrawn from the documentation
  rather than faked; wiring the two TLS lanes into compose behind a real switch
  is the remaining work for that RFC 7696 claim. Neither lane appears in any
  compose file today.
- **ETSI GS QKD 014 runs without TLS.** The KMEs serve plain HTTP and arnika
  connects without a client certificate, while ETSI 014 specifies mutually
  authenticated TLS between SAE and KME. arnika at the pin already reads
  `CERTIFICATE`, `PRIVATE_KEY` and `CA_CERTIFICATE` (`config/config.go:26-28`,
  used at `wire_qkd_kms.go:30`); this repository's compose files and entrypoints set none
  of them, the KME configures no TLS, and nothing consumes `pki/`. Required
  before any hardware-in-the-loop run against a real KMS; see
  [`LIMITATIONS.md`](LIMITATIONS.md).
- **The IPsec lane's CI-only authentication failures.** Open. The full account,
  with each observation and what it rules out, is kept in one place:
  [`vici-ppk.md`](vici-ppk.md#2026-08-27-the-ci-failures-are-a-different-fault-from-the-race-above).
  It is a different fault from the rotation race in
  [`vici-ppk.md`](vici-ppk.md#known-limitation-the-rotation-race), and has not
  been seen outside CI. State on 2026-09-25:
  * The two causes found on 2026-08-28 are both fixed. Ours: `KeyPool.run`
    gated production on buffered peer replicas it could never dispense, so a
    KME could read FULL while answering `enc_keys` with 503; it now gates on
    `dispensable()`. Upstream: given that 503, `kmsRequest` read a closed
    response body after its retry loop
    ([arnika#43](https://github.com/arnika-project/arnika/issues/43)). That was
    fixed by #44 and #49, both merged 2026-09-02 (#44 as `40f96ec`), and both
    the previous pin `3a8cc13` and the current `f4cf9ba` contain them. Both
    node Dockerfiles assert it (the KMS sentinel, `ErrUnavailable` in package
    `kms` since #51), so a bump to a revision without the fix fails the build.
  * The failing run of 2026-09-25 carries neither signature: no retrieval
    failure, and both sides fed HKDF the same QKD half. The PQC half written by
    the Rosenpass sidecar was the input not yet ruled out for that run; the
    2026-08-23 finding that both nodes held byte-identical PQC halves held for
    that run only. Since 2026-09-26 there is no such file on this lane: the PQC
    half is arnika's own PQC-HPKE key, and the corresponding suspect is the
    read gap described in [`vici-ppk.md`](vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race).
  * How often runs fail has not been measured on either of the last two pins,
    so no rate is stated here; the per-run figures of 2026-08-29 predate both.
    The 20 % ceiling in `.github/workflows/ci.yml` is unchanged.

  Withdrawn readings, kept so they are not re-derived: that the failure count
  was "bimodal, 4 or 0, never 1 to 3" (the series once the dump was made
  unconditional was 0, 0, 1, 4, 8, 4 -- checklist row 2.13), and that the
  condition was "specific to the CI environment, not to the code path" (the
  2026-08-28 trigger was in this project's own `KeyPool`).

## Implementation gaps closed

Kept with their dates so the roadmap does not argue for work that exists.

- ~~**Multi-hop cannot relay.**~~ **Done.** Every layer now carries a
  QKD-derived key, and each fix was smaller than the entry that preceded it
  claimed:

  | layer | what was actually wrong |
  |---|---|
  | Rosenpass | `exchange` was always variadic; only our sidecar was single-peer |
  | WireGuard | one more `wg set peer` was needed |
  | arnika lookup | upstream returned "not found" on the first NON-match, so it worked only with exactly one peer |
  | arnika instances | it manages one `WIREGUARD_PEER_PUBLIC_KEY`, so a node facing two neighbours needs two instances |

  Measured with `charlie` up: alice runs both instances (bob on :9999, charlie
  on :9998), **2 of 2 peers carry a preshared key**, 7 PSK installs and 0
  lookup errors, HKDF over QKD+PQC on both legs, and the KME issues keys for
  the `BOB` and `CHARLIE` SAE paths. Ping is 0 % loss over both.

  Two traps worth keeping, because both produced a confident wrong reading:

  * **Ping is not the check.** After the WireGuard fix it was 0 % loss in all
    directions while alice had installed no PSK at all -- WireGuard runs
    perfectly well unprotected. Count PSK installs. Checklist rows 2.11 and 3.5.
    Since version 0.2.0 both halves of this changed: every `wg0` and `wg1`
    peer starts with a random placeholder PSK, so a `preshared key` line no
    longer shows that a daemon wrote it, and an unkeyed tunnel no longer
    passes traffic. The evidence is arnika's install lines together with a
    recent handshake and a ping that answers over the interface.
  * **`docker compose up` does not rebuild.** One attempt at "the second
    instance never started" was the old entrypoint still in the image; the
    running container had no trace of the variable it was supposed to read.

  Also corrected here: charlie's `KMS_URL` named `CHARLIE`. ETSI 014 names the
  **peer**, never yourself -- the same inversion previously found in
  `ARCHITECTURE.md`'s trace.

- **Exports no longer round-trip through the backend** (closed 2026-08-29).
  `saveToBackendAndDownload` used to POST every JSON/PNG/CSV/GIF/WebM to
  `/api/exports/save` and then download it from the URL that returned. The file
  is now delivered from memory FIRST and offered to the catalogue afterwards,
  which removes the visitor's wait on a round trip for bytes their browser
  already held -- base64 inflates a high-DPI PNG or a 10 s WebM by a third --
  and takes every export off the server, which is what the standing
  browser-computes rule is about. It also deletes a failure mode instead of
  reporting one: by the time the POST can fail the file is on disk, so the
  toolbar notice now says the saved-exports list missed a copy rather than that
  the download degraded. Since 2026-09-25 the copy is sent only when the
  visitor ticks "copy to shared gallery" (off by default). **Still true:** a
  static-only deployment cannot populate the saved-exports gallery, because
  that gallery is the backend. See
  [`deployment-economics.md`](deployment-economics.md).

- **`/verify` is no longer server-only** (closed 2026-08-29). It still calls
  `/api/pqc/agility`, `/api/verify/keyrate` and `/api/verify/paper-budgets`,
  and without a backend it degrades, but the agility matrix can now also be
  run in the browser and compared -- see the cross-check button on that page.
  The panel labels which half of the comparison is strong (both
  implementations ran a real round-trip) and which is weak (byte lengths,
  where both are reading the same FIPS table).

- ~~**Export toolbars are on 5 of 13 pages.**~~ **Done.** Thirteen of
  fourteen pages carry one (since 2026-09-25 including `/vpn`, which exports
  the per-node PPK, ESP-counter and SPI-pairing evidence for checklist rows 2.3
  and 2.11, `/topology`, and `/keyflow`, which exports its Sankey as PNG and
  its edge list as JSON); the one without, `/hil`, is display-only. `/bb84`
  exports its QBER history, key-pool history and photon frames (`BB84.tsx`).
- ~~**`/e2e` has no failure-injection control.**~~ **Done.** `/e2e` injects on
  `qkd`, `pqc` and `data` with a `clear`, and decides fatality from the mode
  rather than the layer -- see `e2eSim.injectFailure` and `e2eFailure.test.ts`.
- **DONE 2026-08-28 — the finite-key analysis is now Lim et al. PRA 89, 022307
  (2014), arXiv:1311.7129.** This entry previously recorded that a paper was
  cited for a formula it does not contain. Checking the formula against the
  paper found three further faults, so it was replaced outright rather than
  re-cited; what was wrong with it is set out once, in
  [`keyrate.md`](keyrate.md) section 5, "What this replaced, and why".
  Implemented from the paper and cross-checked to 8 significant figures against
  an independent transcription. The zero-crossing moved from 93.3 km to 98.49 km
  at $`N = 10^9`$, and the curve now saturates against the asymptotic wall
  rather than gaining ~25 km per decade of $`N`$ without limit — the old shape
  would have claimed key past 500 km at $`N = 10^{30}`$.
  `tools/precompute_keyrate_table_fallback.py` held a SECOND copy of the same
  wrong formula and wrote it into `config/qkd_keyrate_table.json` as shipped
  data; it now delegates to `_skr.py`, and the table has been regenerated.
- **Operator-private working files are inside `/private/`** (closed
  2026-09-25). The tracked `.gitignore` rule for that directory travels to
  every clone, unlike a per-clone `.git/info/exclude`, and the files now sit
  under it. The move is a local action no test can observe;
  `tests/test_private_files_have_a_safe_harbour.py` guards the rest: the
  directory stays ignored by the tracked rule, and neither `.gitignore` nor
  any other tracked file names a private file.

## Status as of 2026-08-22 — external claims

The two pages that had never been systematically fact-checked, `/hil` and
`/console`, were both checked. All thirteen routes of the time had then had
their computed numbers or their factual claims verified against a source
outside the codebase (`/protocol-lab`, route 14, was added on 2026-09-25).

Everything found in that review was one class, and a different class from the
earlier reviews: not *a plausible number nobody executed* but **a plausible
reference nobody followed**. Nothing in a build can contradict a citation or a
product name, so these survive every green CI run.

- ~~**`/hil` listed hardware that does not exist.**~~ **Fixed.** Under the
  heading "Reported interoperable devices": "Toshiba MUSE Q-KMS" and
  "Thinkquantum TQ-KME" are not real products (they are Toshiba **Q-KMS** and
  ThinkQuantum **QUKY**), ThinkQuantum documents ETSI 014 + **004** rather than
  020, Toshiba's ETSI 014 API is the default rather than a "compatibility
  mode", and ID Quantique exposes the ETSI interface from **Clarion KX** rather
  than natively. The heading also asserted interoperability nobody had tested.
  Now checklist row 7.12; the vendor list itself is kept in
  [`LIMITATIONS.md`](LIMITATIONS.md).
- ~~**Every citation of the reference paper pointed nowhere.**~~ **Fixed.**
  Thirteen files said "§IV-B Table III"; the paper has no Roman-numeral
  sections and one table. See row 7.13 — the guard now derives Table 1 from the
  redistributed PDF instead of trusting the transcription.
- ~~**`/console` never exported the container it displayed.**~~ **Fixed.** All
  four selections were wrong, and two returned HTTP 200 with a comment in place
  of a log. Rows 4.5.15 and 4.5.16.
