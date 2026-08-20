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
| Crypto-agility matrix across ML-KEM and ML-DSA parameter sets | `/pqc` and `/verify`, running client-side via `@noble/post-quantum` |
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
