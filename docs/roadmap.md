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
| Crypto-agility matrix across ML-KEM and ML-DSA parameter sets | `/pqc`, running entirely client-side via `@noble/post-quantum`. `/verify` is **not** client-side: it calls `/api/pqc/agility`, `/api/verify/keyrate` and `/api/verify/paper-budgets`, and shows "Backend services unavailable" without them. |
| Independent key-rate cross-check | TNO-Quantum backend, plus a golden vector pinned to Ma et al. 2005 in `tests/test_keyrate_golden_vector.py` |
| CI enforcement of the ETSI 014 contract | `.github/workflows/ci.yml`, job `live-stack` |
| A written key-rate derivation | [`keyrate.md`](keyrate.md) |
| Secret scanning in CI | `.github/workflows/ci.yml`, job `secrets` (was listed as "recommended" for months) |
| Reproducible seeded simulation runs | `reconcile()` now takes an injectable RNG |

## Known gaps, carried forward

Recorded rather than scheduled. Each is a real limitation of the current
implementation, not a speculative feature.

| Gap | Consequence |
|---|---|
| No real error correction | `reconciliation.py` hashes Alice's bits and applies a heuristic entropy margin. `f_EC` is an assumed constant, and no leakage is measured. |
| First-order finite-key term only | Not a composable security proof. See [`keyrate.md`](keyrate.md) section 5. |
| Static channel model | Measured field data (arXiv:2608.18869) shows aerial fibre at twice the QBER of buried fibre despite lower loss, with variance tracking wind speed. The model cannot express that. |
| Rotation cadence set by policy, not by link capacity | At the measured 12-22 bit/s a 256-bit key needs 12-20 s to accumulate; `ARNIKA_INTERVAL` should be derived from measured SKR. |
| RFC 9867 unavailable | strongSwan 6.0.7 does not implement it, so consuming fresh QKD material needs a full reauthentication per rotation. |
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
for the pulse loop. The ladder degrades in that order, and every rung produces
identical results because the physics is seeded through `pure-rand`.

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
  one IKE_SA, and rotate. One authentication failure per ~9 rotations remains
  and is the documented sub-millisecond race in [`vici-ppk.md`](vici-ppk.md),
  not a regression.
- **Dead backend removed.** `e2e_orchestrator.py` and `paper_flow.py` are gone
  along with ~200 lines of unreachable routes; `main.py` 842 -> 653. The paper
  budgets moved to `paper_budgets.py` and are now pinned by a test.
- **rosenpass** 2024 pin -> v0.2.3, which forced `rust:1.83` -> `rust:1.90`
  because a transitive dependency declares edition 2024.
- **README** 490 -> 376 lines; build detail and limitations split out.
- **Formulas** all render on GitHub -- `\boxed{}` and `aligned` are not in its
  MathJax subset and were showing as raw source.
- **Two shell scripts were unrunnable** (CRLF), including the repository's own
  secret scanner. Fixed by normalisation; `.gitattributes` prevents recurrence.

### Known gaps, carried forward

- **Exports round-trip through the backend.** `saveToBackendAndDownload` POSTs
  every JSON/PNG/CSV/GIF/WebM to `/api/exports/save` before handing it over,
  falling back to a local blob only on failure. A static-only deployment
  therefore loses the saved-exports gallery silently. See
  [`deployment-economics.md`](deployment-economics.md).
- **GIF playback is faster than real time.** Frame delays are written as the
  nominal interval while the capture loop sleeps *after* a synchronous
  serialise-and-encode, so real elapsed time exceeds the request.
- **`/bb84`'s photon-frame table is not the run** on a GPU tier:
  `cpuSampleFrames` regenerates frames with `Math.random()` independently of
  the pass that produced the QBER.
- **Hardcoding.** The QBER threshold line is the literal `0.11` rather than the
  editable `qber_threshold_abort`; the key-pool model is duplicated verbatim
  across three engines.
- **PQClean cross-check is not performed** -- the test binaries are never
  built. The scope note in `services/pqc-validator/Dockerfile` says so.
- **`PQC_PROVIDER` is not implemented.** Withdrawn from the documentation
  rather than faked; wiring the two TLS lanes into compose behind a real switch
  is the remaining work for that RFC 7696 claim.
