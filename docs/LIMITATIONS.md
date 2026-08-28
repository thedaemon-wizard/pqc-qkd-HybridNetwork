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
  - `qkdnetsim_proxy` — fetches keys from `qkdnetsim-kme`, a second and
    independently written ETSI GS QKD 014 server, to cross-check the REST
    contract. That server is `kme_facade.py`, a Flask app; it is **not** the
    NS-3 C++ KMS, and nothing compares key material between the two -- both
    draw from a CSPRNG, so agreement on bytes would be impossible rather than
    merely unverified
- All parameters are **scientifically grounded** — `config/qkd_keyrate_table.json` is precomputed offline by [`tools/precompute_keyrate_table_fallback.py`](../tools/precompute_keyrate_table_fallback.py) from Lo-Ma-Chen (PRL 94, 230504, 2005) and the Lim et al. (PRA 89, 022307, 2014, arXiv:1311.7129) finite-key bound. This line previously credited "the openQKDsecurity Winick SDP" as well. No SDP ran: the file's own `provenance` field names the Python script, its `formulas` field names only those two references, and the MATLAB producer those sites pointed at (`tools/precompute_keyrate_table.m`) has never existed in this repository. openQKDsecurity is vendored as a submodule and has produced nothing that ships.
- Device-specific non-idealities such as **temperature drift, bandpass filtering, and wavelength-dependent quantum efficiency** are still not modelled.

### 12.2 Hardware connectivity
- Because we speak the **ETSI GS QKD 014 standard interface**, a platform that publishes an ETSI 014 REST endpoint can be substituted by **changing a single `KMS_URL` line** — see the WebUI "Hardware-In-Loop" page. Vendors documenting such an endpoint include ID Quantique (via the **Clarion KX** key-management layer, not the QKD appliance itself), **Toshiba Q-KMS**, and **ThinkQuantum QUKY**. **No hardware has been tested against this PoC.**
  - This list previously named "Toshiba MUSE" and "Thinkquantum TQ-KME". Neither product exists under those names; the vendors' own documentation says Q-KMS and QUKY (QUKY-TX / QUKY-RX) respectively. Checked against vendor product pages on 2026-08-22.
- Vendor-specific drivers (USB / serial) and HSM-backed key-management APIs are out of scope.
- **Xanadu's photonic quantum cloud was decommissioned on 2026-01-16** and Strawberry Fields was archived the same day. It was a continuous-variable *quantum computing* service, not a QKD one — this entry previously called it "CV-QKD", which it never was. Local CV-QKD simulation (GG02) is unaffected.

### 12.3 Residual limitations
- **Single-host PoC**: all containers run on a single physical host, so a real QKD network's latency, loss and physical isolation are not reproduced.
- **KME-to-KME synchronisation is over HTTP**: in a real deployment both ends derive a symmetric key over a quantum channel plus an authenticated classical channel, but here `bb84-kme-a` ↔ `bb84-kme-b` simply exchange material via `POST /internal/sync` (isolated by `qkd-net` with `internal: true`).
- **The PQC focus is ML-KEM-768**; other algorithms can be tried from the "PQC Validator" page, which now spans two mathematical families (FIPS 204 ML-DSA, module-lattice; FIPS 205 SLH-DSA, hash-based). Conformance is checked two ways: against NIST's own ACVP keyGen vector, and by requiring liboqs and the browser's `@noble` implementation to derive the same ML-KEM shared secret. The byte-equality comparison against **PQClean** is still not performed and will not be -- PQClean was archived on 2026-08-04.
- **HKDF-SHA3-256 is the arnika default**; alternative constructions (concatenate-then-HMAC, XOR-only, Cascade KDF, etc.) are out of scope.
- **Two parallel VPN protocol lanes** (Phase 9-A):
  - WireGuard PSK mode (default): the Noise Protocol itself still uses classical primitives (Curve25519 / ChaCha20-Poly1305); arnika layers PSK rotation on top for additive protection.
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (recommended for real hardware): `IKE_SA_INIT` carries the classical ECP-256 exchange in its KE payload and *negotiates* ML-KEM-768 as Additional Key Exchange 1 (`KE1_ML_KEM_768`); the ML-KEM exchange itself then runs in a following `IKE_INTERMEDIATE` (RFC 9242), and both shared secrets are mixed into the IKE keying material. This line previously read "ML-KEM-768 is exchanged directly inside the IKE_SA_INIT KE1 payload", which RFC 9370 Sec. 2.2.1 rules out in as many words: additional key exchanges "MUST take place in a series of IKE_INTERMEDIATE exchanges following the IKE_SA_INIT exchange". The rest of the repository already had it right -- `nodes/strongswan/swanctl.conf.tmpl` and `docs/vici-ppk.md` describe the correct placement, and the latter explains why it matters here: `IKE_SA_INIT` is unencrypted and cannot be fragmented by RFC 7383, while an ML-KEM-768 key share is 1184/1088 bytes.
- **No FIPS or Common Criteria certification**: this is a research PoC, not for production deployment.
- **Regulation and export control**: re-distributing cryptographic software may be covered by ECCN 5D002 or similar — check your jurisdiction before redistribution.

---
