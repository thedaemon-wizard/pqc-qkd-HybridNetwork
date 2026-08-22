# Roadmap - future research extensions

Actionable work items beyond the current PoC. The code base must remain stable
before starting any of these.

Status is stated per item, and reviewed against the implemented tree rather
than carried forward untouched. Reviewed 2026-08-20.

## Completed since this roadmap was written

These were on the list, or implied by it, and are now done. They are recorded
here so the roadmap does not keep proposing work that already exists.

| Item | Where |
|---|---|
| Crypto-agility matrix across ML-KEM, ML-DSA **and SLH-DSA** parameter sets -- two mathematical families, so a break in module lattices does not take out every option | `/pqc`, running entirely client-side via `@noble/post-quantum`. `/verify` is **not** client-side: it calls `/api/pqc/agility`, `/api/verify/keyrate` and `/api/verify/paper-budgets`, and shows "Backend services unavailable" without them. |
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
| First-order finite-key term only | Not a composable security proof. See [`keyrate.md`](keyrate.md) section 5. |
| Static channel model | Measured field data (arXiv:2608.18869) shows aerial fibre at twice the QBER of buried fibre despite lower loss, with variance tracking wind speed. The model cannot express that. |
| Rotation cadence set by policy, not by link capacity | At the measured 12-22 bit/s a 256-bit key needs 12-20 s to accumulate; `ARNIKA_INTERVAL` should be derived from measured SKR. |
| RFC 9867 unavailable | **No open-source IKEv2 implementation has it** -- strongSwan marks it unsupported in its own features table, and Libreswan HEAD has no reference either, despite Libreswan 5.4 shipping ML-KEM in `IKE_SA_INIT` and `IKE_INTERMEDIATE`. Consuming fresh QKD material therefore needs a full reauthentication per rotation. Not a matter of waiting for one vendor. |
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

## Decision record: client-side compute stack

The public demo must not put simulation load on the server, so every simulation
page computes in the browser. Four runtimes are routinely suggested for that and
none of them is used here. Recording why, so the omission reads as a decision
rather than an oversight.

**What is used.** Pure-TypeScript `@noble/*` for the cryptography, and a
Web Worker for the BB84 Monte-Carlo with an optional WebGL2/WebGPU compute path
for the pulse loop.

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
- **`skr_bps` reported a sifting fraction, not a secret-key rate**, in all
  three backends -- 500 Mbps against an actual 12.07 Mbps, a factor of 41. All
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
- **Multi-hop: three of four layers now work. The fourth is an arnika
  limitation, not a wrapper one.**

  Recorded here twice as "blocked on a new dependency". Both times that was
  wrong, and the corrections are worth keeping:

  * **Rosenpass** was always variadic -- `exchange <OWN> [PEERS]...`, and its
    help says so. Only `rosenpass-sidecar.sh` was single-peer. Fixed with
    `RP_EXTRA_PEERS`; alice now holds `pqc.psk` and `pqc.charlie.psk`.
  * **WireGuard** needed one more `wg set peer`. Fixed with `WG_EXTRA_PEERS`;
    alice carries two peers, both handshaking, ping 0 % loss all three ways.
  * **arnika contained a genuine upstream bug**, found only because the two
    fixes above exposed it. `SetPSK` verified its peer with

        for _, peer := range peers.Peers {
            if peer.PublicKey.String() != r.PeerPublicKey { return ...not found }
        }

    which returns on the first NON-match, so it succeeded only when the
    interface had exactly one peer. With two, alice installed **no** QKD PSK
    while the tunnel came up and passed traffic regardless -- the loss of
    post-quantum protection was completely silent, and `InvalidateTunnel` fails
    the same way, so it could not even fail closed. Patched in
    `nodes/alice/0001-arnika-find-the-peer-among-several.patch`; alice went from
    0 installs and 2 lookup errors to 4 installs and 0 errors.

  What remains: **alice-charlie carries no QKD-derived PSK.** arnika takes one
  `WIREGUARD_PEER_PUBLIC_KEY`, so it manages the bob leg only; measured, 1 of
  alice's 2 peers has a preshared key. A true chain needs a second arnika
  instance per extra neighbour, or multi-peer support upstream. That is an
  arnika feature gap, and it is the first genuinely upstream-shaped item of the
  three.

  A note on how this was nearly missed: after the WireGuard fix, ping succeeded
  0 % loss in all directions and that looked like success. It was not --
  WireGuard works perfectly well with no PSK, so the pings proved connectivity
  and said nothing about protection. Checklist row 2.11 makes exactly this point
  for the IPsec lane. Count PSK installs, not replies.

**Open, unexplained** -- do not close by re-running:

- **The `strongswan-lane` auth-failure count has now fired twice**, both on
  branches touching no lane file: **4 failures in 6 rotations**, then 0 in 6 on
  an immediate re-run, then **4 in 8**. Both nodes, both times, and both times
  exactly four.

  Five observations, per node, all identical across the two nodes in a run:

  | failures | rotations | result |
  |---|---|---|
  | 4 | 6 | fail |
  | 0 | 6 | pass (re-run of the same commit) |
  | 4 | 8 | fail |
  | 0 | 9 | pass |
  | 0 | 5 | pass |

  The count is **bimodal -- 4 or 0, never 1 to 3**. That is the useful clue,
  and it rules out the obvious readings. A per-rotation race would scatter
  (0, 1, 2 ...) and scale with the denominator; it does neither. A fixed
  startup cost would appear in every run; it does not. Something either happens
  once per run and costs exactly four failures, or does not happen at all --
  which points at a startup condition that is itself intermittent, most likely
  the interval during which the bootstrap credential and the first QKD-derived
  key can both answer `PPK_ID`.

  That is a hypothesis, not a finding. It could not be confirmed because the
  job printed only the count and never the matching lines, so a failure left
  nothing to diagnose. The job now dumps the `AUTH_FAILED`, bootstrap-unload,
  orphan-unload and rotation lines when the assertion trips; the next
  occurrence should settle it.

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
