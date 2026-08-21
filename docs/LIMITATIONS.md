# Limitations

Extracted from the README. Kept as its own document because an honest account
of what a research PoC does *not* do is worth more than a footnote, and
because it overlaps with the carried-forward gaps in
[`roadmap.md`](roadmap.md) -- read both.

When citing or releasing the PoC, **please always disclose the limitations below.**

### 12.1 QKD physical simulation
- **Reinforced from seven complementary backends**:
  - `qutip` — lightweight, educational, photon-level
  - `simqn` — Cascade error correction + Toeplitz privacy amplification + fibre attenuation (`submodules/SimQN`, 2026-05-25 active)
  - `sequence` — the SeQUeNCe physical-layer model (`submodules/SeQUeNCe`, 2026-05-12 active, Argonne National Lab)
  - `cvqkd` — Strawberry Fields GG02 continuous-variable QKD (`submodules/strawberryfields`)
  - `composite_sim_to_net` — SimQN physical layer + qkdnetsim NS-3 v3.46 network layer
  - `tno_keyrate` — TNO-Quantum's independently developed decoy-state BB84/BBM92
    key-rate engine (`submodules/tno-qkd-key-rate`, Apache-2.0), used to
    cross-check this project's own rate model against a third-party one
  - `qkdnetsim_proxy` — fetches keys from the NS-3 reference KME's own C++
    ETSI GS QKD 014 implementation, for cross-validating the REST contract
- All parameters are **scientifically grounded** — `config/qkd_keyrate_table.json` is precomputed offline from the openQKDsecurity Winick SDP and the arXiv:2511.21253 closed-form formula.
- Device-specific non-idealities such as **temperature drift, bandpass filtering, and wavelength-dependent quantum efficiency** are still not modelled.

### 12.2 Hardware connectivity
- Because we speak the **ETSI GS QKD 014 standard interface**, commercial QKD devices (ID Quantique Cerberis, Toshiba MUSE, Thinkquantum TQ-KME, etc.) can be plugged in by **changing a single `KMS_URL` line** — see the WebUI "Hardware-In-Loop" page for the HIL mode.
- Vendor-specific drivers (USB / serial) and HSM-backed key-management APIs are out of scope.
- **Xanadu's cloud CV-QKD service was decommissioned in 2026-01**, but local CV-QKD simulation remains available.

### 12.3 Residual limitations
- **Single-host PoC**: all containers run on a single physical host, so a real QKD network's latency, loss and physical isolation are not reproduced.
- **KME-to-KME synchronisation is over HTTP**: in a real deployment both ends derive a symmetric key over a quantum channel plus an authenticated classical channel, but here `bb84-kme-a` ↔ `bb84-kme-b` simply exchange material via `POST /internal/sync` (isolated by `qkd-net` with `internal: true`).
- **The PQC focus is ML-KEM-768**; other algorithms can be tried from the "PQC Validator" page. The byte-equality cross-check against PQClean is **not performed**: `services/pqc-validator/` looks for `test/test_<algo>` binaries that the image never builds, so every response reports `pqclean_test_present: false`. Conformance therefore rests on liboqs alone, which is a weaker claim than an independent second implementation.
- **HKDF-SHA3-256 is the arnika default**; alternative constructions (concatenate-then-HMAC, XOR-only, Cascade KDF, etc.) are out of scope.
- **Two parallel VPN protocol lanes** (Phase 9-A):
  - WireGuard PSK mode (default): the Noise Protocol itself still uses classical primitives (Curve25519 / ChaCha20-Poly1305); arnika layers PSK rotation on top for additive protection.
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (recommended for real hardware): ML-KEM-768 is exchanged directly inside the IKE_SA_INIT KE1 payload and combined with classical ECDH to strengthen forward secrecy.
- **No FIPS or Common Criteria certification**: this is a research PoC, not for production deployment.
- **Regulation and export control**: re-distributing cryptographic software may be covered by ECCN 5D002 or similar — check your jurisdiction before redistribution.

---
