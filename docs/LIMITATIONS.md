# Limitations

What this research PoC does *not* do. Kept as its own document because an
honest account of that is worth more than a footnote. Each entry is stated
here once; where a limitation has a detailed home elsewhere, the entry links
to it rather than repeating it. Planned work and closed gaps are tracked in
[`roadmap.md`](roadmap.md).

When citing or releasing the PoC, **please always disclose the limitations below.**

### 1. QKD physical simulation
- **Reinforced from seven complementary backends**:
  - `qutip` — lightweight, educational, photon-level
  - `simqn` — SimQN quantum channel, fibre attenuation and sifting (`submodules/SimQN`, 2026-05-25 active). SimQN's own BB84 post-processing (Cascade and Toeplitz over its simulated classical channel) is bypassed; the reason is in the docstring of `_run_one_round_sync` in `services/bb84-kme/app/backends/simqn_backend.py`. Post-processing is this project's `reconciliation.py` instead: a heuristic entropy margin and a Toeplitz hash, with **no Cascade** error correction ([`keyrate.md`](keyrate.md) section 7).
  - `sequence` — the SeQUeNCe physical-layer model (`submodules/SeQUeNCe`, 2026-05-12 active, Argonne National Lab)
  - `cvqkd` — Strawberry Fields GG02 continuous-variable QKD (`submodules/strawberryfields`)
  - `composite_sim_to_net` — SimQN physical layer feeding that same second
    ETSI 014 server over REST. **No NS-3 runs.** The image compiles NS-3 v3.46 and
    qkdnetsim and copies the binaries into its runtime stage, but the
    entrypoint is the Flask app named below, which fills a key buffer from a
    CSPRNG at the rate SimQN computes. What this backend adds over `simqn`
    alone is a second implementation of the REST contract, not a simulated
    network layer
  - `tno_keyrate` — TNO-Quantum's independently developed decoy-state BB84/BBM92
    key-rate engine (`submodules/tno-qkd-key-rate`, Apache-2.0), used to
    cross-check this project's own rate model against a third-party one
  - `qkdnetsim_proxy` — fetches keys from `qkdnetsim-kme`, a second and
    independently written ETSI GS QKD 014 server. It is a second
    implementation of the REST contract, not a cross-check that runs: the
    container exists only in the `crossvalidate` overlay
    (`docker-compose.qkdnetsim.yml`), which publishes no host port and which
    neither CI nor the Makefile starts, and no test runs against it -- CI's
    `live-stack` job drives `tests/test_etsi014_contract.py` against `bb84-kme`
    only. That server is `kme_facade.py`, a Flask app serving the ETSI 014
    GET forms, a rate push from `composite_sim_to_net` and a health check; it
    is **not** the NS-3 C++ KMS, and nothing compares key material between the
    two -- both draw from a CSPRNG, so agreement on bytes would be impossible
    rather than merely unverified
- All parameters are **scientifically grounded** — `config/qkd_keyrate_table.json` is precomputed offline by [`tools/precompute_keyrate_table_fallback.py`](../tools/precompute_keyrate_table_fallback.py) from Lo-Ma-Chen (PRL 94, 230504, 2005) and the Lim et al. (PRA 89, 022307, 2014, arXiv:1311.7129) finite-key bound. No numerical (SDP) key-rate solver is involved: the file's own `provenance` field names the Python script, and its `formulas` field names only those two references. openQKDsecurity is vendored as a submodule and has produced nothing that ships.
- Device-specific non-idealities such as **temperature drift, bandpass filtering, and wavelength-dependent quantum efficiency** are still not modelled.

### 2. Hardware connectivity
- The PoC speaks the **ETSI GS QKD 014 standard interface**, so the interface a vendor's ETSI 014 endpoint exposes is the one arnika already consumes, and the endpoint is selected by the `KMS_URL` environment variable -- see the WebUI "Hardware-In-Loop" page. **Changing that line is not sufficient on its own.** ETSI 014 runs over mutually authenticated TLS, and this repository does not wire it: arnika at the pin (`3a8cc13`) already reads `CERTIFICATE`, `PRIVATE_KEY` and `CA_CERTIFICATE` (`config/config.go:21-23`, `keyreader.go:10`), but this repository's compose files and entrypoints pass none of them and mount no certificates. A real device also needs the vendor's SAE IDs. Vendors documenting such an endpoint include ID Quantique (via the **Clarion KX** key-management layer, not the QKD appliance itself), **Toshiba Q-KMS**, and **ThinkQuantum QUKY**. **No hardware has been tested against this PoC.**
  - The product names are the vendors' own: Toshiba Q-KMS, and ThinkQuantum QUKY (QUKY-TX / QUKY-RX). Checked against vendor product pages on 2026-08-22.
- Vendor-specific drivers (USB / serial) and HSM-backed key-management APIs are out of scope.
- **Xanadu's photonic quantum cloud was decommissioned on 2026-01-16** and Strawberry Fields was archived the same day. It was a continuous-variable *quantum computing* service, not a QKD one. Local CV-QKD simulation (GG02) is unaffected.

### 3. Residual limitations
- **Single-host PoC**: all containers run on a single physical host, so a real QKD network's latency, loss and physical isolation are not reproduced.
- **KME-to-KME synchronisation is over HTTP**: in a real deployment both ends derive a symmetric key over a quantum channel plus an authenticated classical channel, but here `bb84-kme-a` ↔ `bb84-kme-b` simply exchange material via an unauthenticated `POST /internal/sync`. Both KMEs sit on `qkd-net` (`internal: true`) and on `mgmt-net` (an ordinary bridge), so that route is reachable from any container on either network and from the Docker host, but not from outside it: no KME port is published.
- **The arnika-to-KME ETSI 014 link has no TLS and no authentication.** The KMEs serve plain HTTP on the internal network; see section 2 for what attaching real hardware needs, and [`roadmap.md`](roadmap.md) for the tracked gap.
- **The post-quantum algorithm differs per lane.** On the WireGuard lane the PQC half that arnika feeds into HKDF comes from Rosenpass, whose pinned suite is Classic McEliece 460896 + Kyber512. Kyber512 is the pre-standard Kyber, not FIPS 203.
  On the IPsec lane the IKEv2 key exchange is ML-KEM-768 (RFC 9370, `KE1_ML_KEM_768`), with the QKD-derived material entering as an RFC 8784 PPK. The "PQC Validator" page checks ML-KEM, ML-DSA and SLH-DSA in isolation, spanning two mathematical families (module lattices; FIPS 205 SLH-DSA, hash-based). Conformance is checked two ways: against NIST's own ACVP keyGen vector, and by requiring liboqs and the browser's `@noble` implementation to derive the same ML-KEM shared secret. The byte-equality comparison against **PQClean** is still not performed and will not be -- PQClean was archived on 2026-08-04.
- **arnika's key combiner has two gaps against SP 800-227.** Its HKDF-SHA3-256 over `QKD ‖ PQC` carries no FixedInfo (no domain separator, no protocol or party binding), and its inputs are not approved-KEM-derived: the QKD key is not a KEM output, and Rosenpass's suite is not an approved one. The two-step HKDF shape and the nil salt are not gaps. See the appendix of [`vici-ppk.md`](vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner).
- **HKDF-SHA3-256 is the arnika default**; alternative constructions (concatenate-then-HMAC, XOR-only, Cascade KDF, etc.) are out of scope.
- **A new WireGuard PSK takes effect only at WireGuard's next handshake.** arnika overwrites the peer's preshared key and triggers no handshake, so the PSK is mixed in when WireGuard itself rehandshakes (`REKEY_AFTER_TIME`, 120 s while traffic flows). With the default `ARNIKA_INTERVAL=30s`, most installed PSKs are replaced before any handshake uses them.
- **The IPsec lane reauthenticates on every PPK rotation.** RFC 9867, which would let fresh QKD material enter without a full reauthentication, is not available in the pinned strongSwan; see [`roadmap.md`](roadmap.md) and [`vici-ppk.md`](vici-ppk.md).
- **The IPsec lane has an unresolved, CI-only authentication-failure fault**, separate from its millisecond rotation race. Status in [`roadmap.md`](roadmap.md); the investigation is in [`vici-ppk.md`](vici-ppk.md).
- **Two parallel VPN protocol lanes** (Phase 9-A):
  - WireGuard PSK mode (default): the Noise Protocol itself still uses classical primitives (Curve25519 / ChaCha20-Poly1305); arnika layers PSK rotation on top for additive protection.
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (recommended for real hardware): `IKE_SA_INIT` carries the classical ECP-256 exchange in its KE payload and *negotiates* ML-KEM-768 as Additional Key Exchange 1 (`KE1_ML_KEM_768`); the ML-KEM exchange itself then runs in a following `IKE_INTERMEDIATE` (RFC 9242), and both shared secrets are mixed into the IKE keying material. RFC 9370 Sec. 2.2.1 requires this placement: additional key exchanges "MUST take place in a series of IKE_INTERMEDIATE exchanges following the IKE_SA_INIT exchange". It matters here because `IKE_SA_INIT` is unencrypted and cannot be fragmented by RFC 7383, while an ML-KEM-768 key share is 1184/1088 bytes; see [`vici-ppk.md`](vici-ppk.md).
- **No FIPS or Common Criteria certification**: this is a research PoC, not for production deployment.
- **Regulation and export control**: re-distributing cryptographic software may be covered by ECCN 5D002 or similar — check your jurisdiction before redistribution.

---
