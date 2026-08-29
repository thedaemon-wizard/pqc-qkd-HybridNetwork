# Roadmap - future research extensions

Actionable work items beyond the current PoC. The code base must remain stable
before starting any of these.

Status is stated per item, and reviewed against the implemented tree rather
than carried forward untouched. Reviewed 2026-08-28.

A header date that trails the entries below it is its own small false
claim: this line read 2026-08-20 while the file carried items dated the
21st, 22nd, 23rd and 28th, so a reader checking whether the roadmap had
kept up would have concluded it had not.

## Completed since this roadmap was written

These were on the list, or implied by it, and are now done. They are recorded
here so the roadmap does not keep proposing work that already exists.

| Item | Where |
|---|---|
| Crypto-agility matrix across ML-KEM, ML-DSA **and SLH-DSA** parameter sets -- two mathematical families, so a break in module lattices does not take out every option. Rendered on `/verify` from `POST /api/pqc/agility`; the browser side of the same claim is `src/lib/sim/pqc.ts`. Until 2026-08 the SERVER matrix was ML-KEM + ML-DSA only -- six algorithms, all module-lattice -- so the page called it agility while showing none. |
| Independent key-rate cross-check | TNO-Quantum backend, plus a golden vector pinned to Ma et al. 2005 in `tests/test_keyrate_golden_vector.py` |
| CI enforcement of the ETSI 014 contract | `.github/workflows/ci.yml`, job `live-stack` |
| A written key-rate derivation | [`keyrate.md`](keyrate.md) |
| Secret scanning in CI | `.github/workflows/ci.yml`, job `secrets` (was listed as "recommended" for months) |
| Reproducible seeded simulation runs | `reconcile()` now takes an injectable RNG |

## Known gaps - model and protocol

Recorded rather than scheduled. These are limitations of the physics and
protocol modelling, and are not expected to close without new work upstream.
Implementation gaps are tracked separately, under "Status" below.

| Gap | Consequence |
|---|---|
| No real error correction | `reconciliation.py` hashes Alice's bits and applies a heuristic entropy margin. `f_EC` is an assumed constant, and no leakage is measured. |
| ~~First-order finite-key term only~~ **CLOSED 2026-08-28** | Was "not a composable security proof". It now is one: Lim et al. PRA 89, 022307 (2014) with eps_sec and eps_cor tracked separately and a key LENGTH in bits. See [`keyrate.md`](keyrate.md) section 5. The residual caveat is different in kind and is stated there -- the counts fed to the estimators are EXPECTED under the channel model, not observed, so the output is an expected key length and the eps_sec guarantee does not attach to a simulated number. |
| Static channel model | Measured field data (arXiv:2608.18869) shows aerial fibre at twice the QBER of buried fibre despite lower loss, with variance tracking wind speed. The model cannot express that. |
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
- NIST IR 8413 (PQC standardisation status)

## B. HNDL (Harvest Now, Decrypt Later) Simulator
**Goal:** Make the time-shifted attack tangible for stakeholders.

**Tasks:**
1. `services/hndl-simulator/` captures `tcpdump` of the `wan-net` UDP/51820 traffic
2. Stores ciphertext blobs into a "cold archive" volume
3. WebUI timeline: rotation interval ↔ HNDL exposure window plot
4. Manim animation: "captured today, decrypted in 2030"

**References:**
- NIST IR 8547 (Migration to PQC)
- CISA Quantum-Readiness Roadmap

## C. QLSTM-IDS for QKD attack detection
**Goal:** Detect side-channel and protocol attacks on the BB84 link.

**Tasks:**
1. Generate labelled dataset from `app/bb84/simulator.py` with 8 attack scenarios:
   normal / intercept-resend / PNS / Trojan / RNG-bias / wavelength-trojan /
   detector-blinding / combined
2. Implement QLSTM with PennyLane (see `rdisipio/qlstm`)
3. Train + benchmark vs classical RandomForest + GradientBoosting
4. WebUI page "IDS Live" — per-photon attack probability stream

**Target metrics** (per Wiley IET QC 2026 paper): Precision 94.7%, Recall 93.2%, F1 93.9%.

## D. NIST PQC Algorithm Sweep
**Goal:** Benchmark every NIST-standardised algorithm exposed by `liboqs`.

**Tasks:**
1. `services/pqc-benchmark/` runs liboqs-python on the host
2. Algorithms: ML-KEM-{512,768,1024}, ML-DSA-{44,65,87}, SLH-DSA variants, Falcon
3. Compare key/signature sizes, handshake time, RAM, CPU
4. WebUI page "PQC Catalogue" — sortable table + bar chart

## E. NIST CSF 2.0 / SP 800-56C / SP 800-208 compliance mapping
**Goal:** Make the PoC defensible in audit conversations.

**Tasks:**
1. Add `docs/compliance.md` with explicit mapping:
   - NIST CSF 2.0 functions (GOVERN/IDENTIFY/PROTECT/DETECT/RESPOND/RECOVER) ↔ PoC components
   - SP 800-56C Rev 2 ↔ HKDF-SHA3-256 implementation in `kdf/kdf.go`
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
- CNN-based quality evaluation (per MDPI Electronics 2026)

## H. Quantum Federated Learning + FHE
- Use QKD-derived keys to securely distribute FHE parameters across federated participants
- Reference: `elucidator8918/QFL-MLNCP-NeurIPS`

## Implementation order
1. **D** (PQC sweep) — pure compute, low risk, immediate research value
2. **C** (QLSTM-IDS) — leverages existing BB84 simulator data
3. **A** (Shor sim) — needs CUDA-Q and time
4. **B** (HNDL) — partly product/marketing; small lift
5. **E** (Compliance) — documentation
6. **F**, **G**, **H** — longer-term

## Decision record: the word "phase" appears in three unrelated schemes

Recorded because the instruction "delete the Phase labels if they are not
needed" was given four times across successive rounds and never actioned. The
reason it was never actioned was never written down, so it kept coming back.
It is written down now.

There are three numbering schemes, all called "phase":

| Scheme | Numbers | Owner |
|---|---|---|
| Build phases | 0, 2-4, 8-14 | this project's own milestones, `docs/phases.md` |
| Protocol phases | 1-5 | **the paper's**, arXiv:2604.05599 Table 1 |
| `/e2e` orchestration | 1-4 | this project's own invention |

**The second cannot be deleted or renamed.** `services/webui-backend/app/paper_budgets.py`
quotes "Table 1: per-phase handshake cost of one multi-hop cycle" -- "phase" is
the paper's word for these, `/paper-flow` reproduces that table per phase, and
`tests/test_paper_budgets.py` pins the totals. Renaming it would put this
project's vocabulary between a reader and the source it claims to reproduce.

**So the fix is disambiguation, not deletion.** `/e2e`'s scheme is ours alone,
so it now says **step** -- "Active step", "Step history" -- which removes one
of the three collisions at no cost to fidelity. `/paper-flow` keeps the word
and qualifies it: "the paper's 5 protocol phases", "paper phase 5". A reader
who sees `Phase 8` in the docs and `paper phase 5` in the UI can now tell they
are unrelated, which was the actual complaint behind the instruction.

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

## Status as of 2026-08-21

Closed this round, with the evidence rather than the intention:

- **VICI lane** verified in CI on `main`: both peers negotiate
  `AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK`, hold exactly
  one IKE_SA, and rotate. The residual sub-millisecond race is **1 failure in
  45 rotations** ([`vici-ppk.md`](vici-ppk.md)). This entry previously said
  "one per ~9 rotations" -- that is the rate measured while the un-retired
  bootstrap credential made two keys answer one `PPK_ID`, a defect that was
  fixed, not the race that remains. Note also that the CI job observes only
  ~6 rotations in its 240 s window, so its 20 % ceiling tolerates one failure
  per run, not nine.
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

### Implementation gaps still open

Re-verified 2026-08-22 against the deployed demo and the code. Entries are
grouped by what is required to close them, because that is the useful axis: a
wrong sentence and a missing dependency are not the same kind of work.

**Blocked on a dependency decision** -- these need a new vendored submodule, so
they are not something to close silently:

- **No userspace WireGuard fallback exists.** `docs/BUILD.md` 5.3 offers the
  `boringtun` overlay to anyone whose `modprobe wireguard` fails.
  `command -v boringtun` in the node image finds nothing, and neither boringtun
  nor wireguard-go is packaged for `debian:bookworm`. wg-quick exits when the
  kernel module is absent AND the binary is missing -- exactly that case. The
  documented recovery path cannot work for the people who need it. Closing it
  means vendoring boringtun plus a cargo stage; the image already builds Rust
  for rosenpass, so it is feasible.
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
  * **`docker compose up` does not rebuild.** One round of "the second instance
    never started" was the old entrypoint still in the image; the running
    container had no trace of the variable it was supposed to read.

  Also corrected here: charlie's `KMS_URL` named `CHARLIE`. ETSI 014 names the
  **peer**, never yourself -- the same inversion previously found in
  `ARCHITECTURE.md`'s trace.

**Open, unexplained** -- do not close by re-running:

- **The `strongswan-lane` auth-failure count has now fired twice**, both on
  branches touching no lane file: **4 failures in 6 rotations**, then 0 in 6 on
  an immediate re-run, then **4 in 8**. Both nodes, both times, and both times
  exactly four.

  Six CI observations, per node, identical across the two nodes in every run,
  plus two local reproduction attempts:

  | failures | rotations | result |
  |---|---|---|
  | 4 | 6 | fail |
  | 0 | 6 | pass (re-run of the same commit) |
  | 4 | 8 | fail |
  | 0 | 9 | pass |
  | 0 | 5 | pass |
  | 0 | 9 | pass |
  | 0 | 7 | pass, **local** |
  | 0 | 7 | pass, **local** |

  The count is **bimodal -- 4 or 0, never 1 to 3**. That is the useful clue,
  and it rules out the obvious readings. A per-rotation race would scatter
  (0, 1, 2 ...) and scale with the denominator; it does neither. A fixed
  startup cost would appear in every run; it does not. Something either happens
  once per run and costs exactly four failures, or does not happen at all --
  which points at a startup condition that is itself intermittent, most likely
  the interval during which the bootstrap credential and the first QKD-derived
  key can both answer `PPK_ID`.

  Attempted locally on 2026-08-22 and **could not be reproduced**: the lane
  brings up an SA with `AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/KE1_ML_KEM_768/PPK`
  and two full 240 s windows gave 7 rotations and **0 failures** each, with no
  clustering at startup when sampled at 15/30/45/60/90/120/180/240 s. So the
  condition is specific to the CI environment, not to the code path.

  The job originally printed only the count, so a failure left nothing to
  diagnose. It now dumps the `AUTH_FAILED`, bootstrap-unload, orphan-unload and
  rotation lines with timestamps whenever there is **any** failure, not only
  when the ceiling trips -- a passing run with one or two failures is precisely
  the data point that separates a startup window from a per-rotation race, and
  dumping only on failure threw those away.

  The threshold was deliberately NOT loosened. If these are genuinely
  post-bootstrap failures then the peers are resolving different PPKs and the
  guard is doing its job, and loosening it is exactly how that gets waved
  through.

**Manual step remaining** -- the mechanism is in place, the action is the
operator's:

- Private working files now have a tracked `/private/` rule that travels to
  every clone. Protection was previously `.git/info/exclude`, which is
  per-clone; a simulated fresh clone staged those files. Moving them into
  `/private/` is a local action this repository cannot verify without naming
  them, which is the thing the rule exists to avoid.


Four entries previously listed here have been closed and are recorded above
instead; leaving them would have kept the roadmap arguing for work that exists.

- **Exports still round-trip through the backend.** `saveToBackendAndDownload`
  POSTs every JSON/PNG/CSV/GIF/WebM to `/api/exports/save` before handing it
  over. It no longer fails silently -- a local-only save is now reported in the
  toolbar -- but a static-only deployment still cannot populate the
  saved-exports gallery. See [`deployment-economics.md`](deployment-economics.md).

- **`PQC_PROVIDER` is not implemented.** Withdrawn from the documentation
  rather than faked; wiring the two TLS lanes into compose behind a real switch
  is the remaining work for that RFC 7696 claim. Neither lane appears in any
  compose file today.
- **`/verify` is server-side.** It calls `/api/pqc/agility`,
  `/api/verify/keyrate` and `/api/verify/paper-budgets`, so it is one of the
  seven routes that degrade without a backend.
- **`/physics` renders nothing without the backend.** The editable field list
  comes from `/api/sim/params/editable`; the key-rate mathematics beside it is
  already client-side.
- ~~**Export toolbars are on 5 of 13 pages.**~~ **Done.** Nine of thirteen
  pages carry one; the four without (`/topology`, `/vpn`, `/keyflow`, `/hil`)
  are display-only prose. `/bb84` exports its QBER history, key-pool history
  and photon frames (`BB84.tsx`), which this entry said it could not.
- ~~**`/e2e` has no failure-injection control.**~~ **Done.** `/e2e` injects on
  `qkd`, `pqc` and `data` with a `clear`, and decides fatality from the mode
  rather than the layer -- see `e2eSim.injectFailure` and `e2eFailure.test.ts`.

## Status as of 2026-08-22 — external claims

The two pages that had never been systematically fact-checked, `/hil` and
`/console`, were both checked. All thirteen routes have now had their computed
numbers or their factual claims verified against a source outside the codebase.

Everything found this round was one class, and it is a different class from the
earlier rounds: not *a plausible number nobody executed* but **a plausible
reference nobody followed**. Nothing in a build can contradict a citation or a
product name, so these survive every green CI run.

- ~~**`/hil` listed hardware that does not exist.**~~ **Fixed.** Under the
  heading "Reported interoperable devices": "Toshiba MUSE Q-KMS" and
  "Thinkquantum TQ-KME" are not real products (they are Toshiba **Q-KMS** and
  ThinkQuantum **QUKY**), ThinkQuantum documents ETSI 014 + **004** rather than
  020, Toshiba's ETSI 014 API is the default rather than a "compatibility
  mode", and ID Quantique exposes the ETSI interface from **Clarion KX** rather
  than natively. The heading also asserted interoperability nobody had tested.
  Now checklist row 7.12.
- ~~**Every citation of the reference paper pointed nowhere.**~~ **Fixed.**
  Thirteen files said "§IV-B Table III"; the paper has no Roman-numeral
  sections and one table. See row 7.13 — the guard now derives Table 1 from the
  redistributed PDF instead of trusting the transcription.
- ~~**`/console` never exported the container it displayed.**~~ **Fixed.** All
  four selections were wrong, and two returned HTTP 200 with a comment in place
  of a log. Rows 4.5.15 and 4.5.16.

### Still open

- **The VICI lane intermittently reauthenticates with mismatched PPKs.**
  Characterised properly on 2026-08-22 after the CI dump was made
  unconditional; two earlier readings of it were wrong and are recorded here so
  they are not re-derived.

  A **failing** run (8 of 8 rotations, both nodes) rejects every
  reauthentication with

  ```
  tried 1 shared key for 'bob@pqcqkd.local' - 'alice@pqcqkd.local', but MAC mismatched
  ```

  Exactly one credential, correct generation, and the MAC still fails -- so the
  two peers hold **different 32 bytes**. That eliminates ordering, id
  namespacing and a missing credential by observation rather than by argument,
  and it is not the documented sub-millisecond race, which is 1-in-45 and
  self-correcting. The IKE_SA stays at `pqcqkd-vpn[1]` for the whole window.

  A **passing** run, by contrast, retires the bootstrap credential and then
  establishes a *new* SA on every rotation -- `[2]`, `[3]`, `[4]`, `[5]` ... --
  with 0 failures over 9 rotations. So the QKD-derived PPK does enter the key
  schedule when the lane is healthy.

  **Two hypotheses tested and refuted**, both of which looked convincing:

  1. *"The lane has always run on the static bootstrap PPK."* False. The
     bootstrap is retired on passing runs too; retirement is not the
     discriminator. This one came from reading an ABSENCE as evidence -- the
     timeline used to dump only when `authfail > 0`, so a passing run printed
     nothing and appeared to show the bootstrap surviving.
  2. *"The PQC half diverges"* (crossing Rosenpass initiations leaving each
     peer holding the other's OSK). **False, and now on the evidence that
     counts.** The first measurement of this was the green CI run
     (`e5f54ee7a7309ddd77132fc7` on both nodes) plus the live deployment --
     which refutes nothing, because a run that works is expected to have
     matching halves. It reads as circular the moment anyone checks.

     A **failing** run settles it: 4 failures in 10 rotations on 2026-08-23,
     and the two nodes' PQC halves were byte-identical at
     `630b22dc...` **on that run**. So the Rosenpass half is excluded on the
     only kind of run where exclusion means anything.

  So the defect is real and proven, and the localisation is **half done**: the
  PQC half is ruled out, and what remains is the QKD half -- specifically the
  `key_id` exchange, since arnika elects a PRIMARY per interval which fetches
  `enc_keys`, sends the id, and leaves the BACKUP to resolve it via `dec_keys`.
  An id sent on one node with no matching receipt on the other puts the two
  ends on different QKD keys, which with the PQC halves identical is the whole
  defect.

  **DEMONSTRATED 2026-08-28, and it is not a `key_id` delivery gap.** The
  2026-08-23 run showed two ids on alice absent from bob's list, which looked
  conclusive and was not: `tail` truncates, so "bob never received it" and "the
  tail cut it off" produce the same output. With `SND`/`RCV`/`REQ` captured, the
  failing runs since then carry the actual cause:

  ```
  [ERROR] failed to retrieve QKD key for key_id <uuid> from
          http://bb84-kme-b:8080/api/v1/keys/ALICE,
          http: read on closed response body
  ```

  The `[RCV]` lines prove the id WAS received, so the UDP exchange is fine. What
  fails is the subsequent ETSI 014 fetch, with a Go `net/http` response-body
  lifecycle error -- the body is read after being closed.

  **Corrected 2026-08-29. This entry used to end: "That is the whole defect, and
  it is upstream in arnika's HTTP client, not in this project's key delivery."
  Both halves of that sentence were wrong.**

  It is two defects, one on each side, and the trigger is ours.

  *Ours.* `KeyPool.run` gated production on `len(self._buf)`, which counts peer
  replicas that `pop_for_enc` may never dispense. A KME whose peer produces
  faster fills with replicas, crosses the watermark on them alone and stops
  producing -- the pool then reads FULL while every `enc_keys` request answers
  503 "key pool empty". Sampled on the public demo over two minutes before the
  fix: alice `rounds_total 7`, `pool_size 64` (capacity), zero rounds per
  minute, against bob's 805 rounds at `pool_size 8`. alice had produced seven
  keys in her entire lifetime and held sixty-four, so at least fifty-seven were
  bob's. Fixed by gating on `dispensable()`.

  *Upstream.* Given that 503, `kmsRequest` in `repositories/kms.go` closes the
  response body inside its retry loop and reads it after the loop; a non-200
  sets no error, so the nil-check falls through. Filed as
  [arnika-project/arnika#43](https://github.com/arnika-project/arnika/issues/43)
  with a minimal Go reproduction and a suggested fix. Still present on upstream
  `main` at `9d44332`, which is also our pin.

  Also corrected: the path. This entry describes BACKUP/`dec_keys`, but the CI
  failure examined on 2026-08-28 is PRIMARY/`enc_keys`
  (`failed to retrieve QKD key from .../api/v1/keys/BOB`). Both route through
  the same `kmsRequest`, so the symptom is broader than recorded.

  And the frequency, **re-measured 2026-08-29 and materially worse than what
  stood here**. This paragraph said "1 failure in the last 20 runs of the
  `ipsec` job" (5% of runs) and `ci.yml` says "1 failure in 45 rotations" (2%
  of rotations). Both are now stale by roughly an order of magnitude.

  Observed across six `ipsec` runs on one branch in a single day:

  | run | rotations | auth failures | rate |
  |---|---|---|---|
  | 33234515173 | -- | 0 | pass |
  | 33235596471 | -- | 0 | pass |
  | 33237084658 | -- | 0 | pass |
  | (superseded) | 9 | **8** | **89%** |
  | (rerun of the above) | -- | 0 | pass |
  | 33238341982 | 13 | **4** | **31%** |

  So **two of six runs failed**, and when a run fails the per-rotation rate is
  31-89%, not 2%. The two failing runs also disagree with each other by a
  factor of three, which is what a race looks like rather than a constant.

  Ruled out as the cause: nothing on that branch touched the lane. The only
  `ci.yml` change was a step added to the `live-stack` job, and `git diff
  --name-only` over the branch returns no file under `nodes/strongswan/`,
  `services/arnika-vici/`, or the `ipsec` job itself. GitHub gives each job its
  own runner, so the added step cannot contend with it either.

  What this means practically: **the 20% ceiling in `ci.yml` is now tripped
  often enough to block merges**, and the honest reading is that the upstream
  `kmsRequest` defect (arnika#43, unfixed at pin `9d44332`) has become more
  frequent rather than that the gate is too tight. Raising the ceiling would
  hide a real regression in the lane's reliability. The gate is doing its job.

  It reproduced on pull requests touching only frontend TypeScript, which is
  consistent with the trigger being a KME that momentarily cannot serve a key
  rather than anything in the change.
  The 20 % threshold is deliberately unchanged: it is catching a real defect.
- **DONE 2026-08-28 — the finite-key analysis is now Lim et al. PRA 89, 022307
  (2014), arXiv:1311.7129.** This entry previously recorded that a paper was
  cited for a formula it does not contain, and proposed either implementing
  that paper's Eq. (32) or downgrading the comment to "generic first-order
  penalty". Neither was done: a web fact-check found three further faults
  beyond the citation, so the formula was replaced outright.
  (a) `sqrt(2/N)*sqrt(log2(2/eps))` is 2.402x a two-sided Hoeffding deviation,
  with `log2` where `ln` belongs. (b) It was channel-independent, so it never
  propagated through the decoy inversion, where near-cancelling differences over
  small denominators amplify the deviation by one to two orders of magnitude —
  the dominant finite-size effect in decoy BB84, entirely absent. (c) It was
  subtracted from a rate rather than producing a key *length*, so it bounded
  nothing in either direction: optimistic on the statistics, pessimistic on the
  rate, and therefore not defensible as conservative.
  Implemented from the paper and cross-checked to 8 significant figures against
  an independent transcription. The zero-crossing moved from 93.3 km to 98.49 km
  at N = 1e9, and the curve now saturates against the asymptotic wall rather
  than gaining ~25 km per decade of N without limit — the old shape would have
  claimed key past 500 km at N = 1e30.
  `tools/precompute_keyrate_table_fallback.py` held a SECOND copy of the same
  wrong formula and wrote it into `config/qkd_keyrate_table.json` as shipped
  data; it now delegates to `_skr.py`, and the table has been regenerated.
