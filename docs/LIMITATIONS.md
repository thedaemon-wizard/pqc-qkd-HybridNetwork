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
- The PoC speaks the **ETSI GS QKD 014 standard interface**, so the interface a vendor's ETSI 014 endpoint exposes is the one arnika already consumes, and the endpoint is selected by the `KMS_URL` environment variable -- see the WebUI "Hardware-In-Loop" page. **Changing that line is not sufficient on its own.** ETSI 014 runs over mutually authenticated TLS, and this repository does not wire it: arnika at the pin (`f4cf9ba`) already reads `CERTIFICATE`, `PRIVATE_KEY` and `CA_CERTIFICATE` (`config/config.go:26-28`, used at `wire_qkd_kms.go:30`), but this repository's compose files and entrypoints pass none of them and mount no certificates. A real device also needs the vendor's SAE IDs. Vendors documenting such an endpoint include ID Quantique (via the **Clarion KX** key-management layer, not the QKD appliance itself), **Toshiba Q-KMS**, and **ThinkQuantum QUKY**. **No hardware has been tested against this PoC.**
  - The product names are the vendors' own: Toshiba Q-KMS, and ThinkQuantum QUKY (QUKY-TX / QUKY-RX). Checked against vendor product pages on 2026-08-22.
- Vendor-specific drivers (USB / serial) and HSM-backed key-management APIs are out of scope.
- **Xanadu's photonic quantum cloud was decommissioned on 2026-01-16** and Strawberry Fields was archived the same day. It was a continuous-variable *quantum computing* service, not a QKD one. Local CV-QKD simulation (GG02) is unaffected.

### 3. Residual limitations
- **Single-host PoC**: all containers run on a single physical host, so a real QKD network's latency, loss and physical isolation are not reproduced.
- **KME-to-KME synchronisation is over HTTP**: in a real deployment both ends derive a symmetric key over a quantum channel plus an authenticated classical channel, but here `bb84-kme-a` ↔ `bb84-kme-b` simply exchange material via an unauthenticated `POST /internal/sync`. Both KMEs sit on `qkd-net` (`internal: true`) and on `mgmt-net` (an ordinary bridge), so that route is reachable from any container on either network and from the Docker host, but not from outside it: no KME port is published.
- **The arnika-to-KME ETSI 014 link has no TLS and no authentication.** The KMEs serve plain HTTP on the internal network; see section 2 for what attaching real hardware needs, and [`roadmap.md`](roadmap.md) for the tracked gap.
- **The post-quantum algorithms differ per layer and per lane.** arnika's own PQC half, on both lanes, is PQC-HPKE: HPKE in Base mode (RFC 9180) with the KEM MLKEM1024-P384 (a hybrid of ML-KEM-1024 and P-384 ECDH, codepoint 0x0051 of draft-ietf-hpke-pq, which is not yet an RFC), HKDF-SHA384 and an export-only AEAD. On the WireGuard lane it keys the `wg0` hop tunnel together with the QKD key, and the `wg1` data tunnel inside it is keyed separately by Rosenpass, whose pinned suite is Classic McEliece 460896 + Kyber512; Kyber512 is the pre-standard Kyber, not FIPS 203.
  On the IPsec lane the IKEv2 key exchange is ML-KEM-768 (RFC 9370, `KE1_ML_KEM_768`), with arnika's HKDF-SHA3-256 over the QKD key and the PQC-HPKE key entering as an RFC 8784 PPK. No Rosenpass runs on that lane. The "PQC Validator" page checks ML-KEM, ML-DSA and SLH-DSA in isolation, spanning two mathematical families (module lattices; FIPS 205 SLH-DSA, hash-based). Conformance is checked two ways: against NIST's own ACVP keyGen vector, and by requiring liboqs and the browser's `@noble` implementation to derive the same ML-KEM shared secret. The byte-equality comparison against **PQClean** is still not performed and will not be -- PQClean was archived on 2026-08-04.
- **arnika's key combiner has two gaps against SP 800-227.** Its HKDF-SHA3-256 over `QKD ‖ PQC` carries no FixedInfo (no domain separator, no protocol or party binding), which arnika#51 did not change, and its inputs are not shown to be approved-KEM-derived: the QKD key is not a KEM output, and the PQC-HPKE key is an HPKE export several derivations downstream of ML-KEM-1024, through a hybrid KEM defined only in an Internet-Draft, which SP 800-227 neither admits nor excludes. The two-step HKDF shape and the nil salt are not gaps. See the appendix of [`vici-ppk.md`](vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner).
- **The arnika pin is an unmerged pull request.** `submodules/arnika` is pinned to `f4cf9ba`, the head of the open arnika#51 (2026-09-24), not to a commit on upstream `main`; it has no upstream review yet and will be re-pinned to the merge commit once #51 merges. Its peer protocol does not interoperate with the previous pin's (the HMAC key now depends on the direction, and PQC-HPKE adds a packet type), so the two nodes of a pair are always updated together.
- **The two nodes of a pair must be recreated together.** The pinned arnika counts its election intervals per process, and under `QkdAndPqcRequired` a BACKUP interval that received no `key_id` ends with a random key. The WireGuard entrypoint starts arnika on a wall-clock interval boundary, which restores the start synchronisation that lane had before release 0.2.0; the IPsec entrypoint deliberately does not, as at v0.1.0, because the before/after measurement compares that lane and both of its arms run the same entrypoint start behaviour (the start offset itself is measured in each arm). Either way a node restarted alone comes back with a different count from its peer's: in every interval where both then elect themselves BACKUP, both ends install random keys, until the pair is recreated. And whatever offset a pair starts with does not stay put: each arnika ticker re-bases after its own processing, so the offset between the two ends wanders by milliseconds per interval. When a BACKUP's boundary lags its PRIMARY's by more than the PRIMARY's KMS fetch time, the PRIMARY's `key_id` can arrive before the BACKUP's boundary and is counted in the BACKUP's previous interval; the BACKUP then fails closed at the end of the current interval if the next interval's `key_id` is not early too, which in practice means at its BACKUP-to-PRIMARY transitions. That is an inference from the code. In one unaligned local run of the IPsec lane, about 6 minutes long, the offset went from about 255 ms to about 217 ms over 12 intervals, and the later node received early `key_id`s in intervals 2 to 8, 10 and 11 and invalidated only at the end of 8 and 11; in three unaligned WireGuard runs, 13 of 21 BACKUP intervals ended that way. Those are observations, not a measurement. All of this is arnika #51's behaviour, to be raised upstream; the mechanism, what the measurement records and the operating rule are in [`BUILD.md` 7.3](BUILD.md#73-starting-arnika-on-the-interval-boundary).
- **Only one end of each Rosenpass pair initiates, and that rests on an internal behaviour.** The node with the lower `wg0` address initiates every exchange and the other only answers, because with two initiators a cold start left the ends on different `wg1` keys for 120 s. That the answering end never initiates is how rosenpass v0.2.3 behaves, not an interface it documents, so a Rosenpass bump has to re-check it. The cost: while the initiating end's Rosenpass is down, the other end's `wg1` key expires and `wg1` fails closed until the initiator is back ([`BUILD.md` 7.2](BUILD.md#72-arnika-and-the-two-wireguard-interfaces)).
- **arnika runs without `CAP_IPC_LOCK`, so its key material may reach swap.** The pinned arnika tries `mlockall` at start-up; without the capability that fails and it logs `process hardening incomplete`. Granting it would lock about 1.2 GB per arnika process (upstream's own measurement, recorded in `hardening/hardening_linux.go`), close to 5 GB for the four arnika processes of the two lanes on one host, so this deployment does not grant it. Core dumps and same-user `/proc` reads are still blocked (`PR_SET_DUMPABLE`, `RLIMIT_CORE`).
- **HKDF-SHA3-256 is the arnika default**; alternative constructions (concatenate-then-HMAC, XOR-only, Cascade KDF, etc.) are out of scope.
- **A new WireGuard PSK takes effect only at WireGuard's next handshake.** arnika overwrites the peer's preshared key and triggers no handshake, so the PSK is mixed in when WireGuard itself rehandshakes (`REKEY_AFTER_TIME`, 120 s while traffic flows). With the default `ARNIKA_INTERVAL=30s`, most installed PSKs are replaced before any handshake uses them.
- **The IPsec lane reauthenticates on every PPK rotation.** RFC 9867, which would let fresh QKD material enter without a full reauthentication, is not available in the pinned strongSwan; see [`roadmap.md`](roadmap.md) and [`vici-ppk.md`](vici-ppk.md).
- **The IPsec lane has an unresolved, CI-only authentication-failure fault**, separate from its millisecond rotation race. Status in [`roadmap.md`](roadmap.md); the investigation is in [`vici-ppk.md`](vici-ppk.md).
- **Two parallel VPN protocol lanes** (Phase 9-A):
  - WireGuard PSK mode (default): the Noise Protocol itself still uses classical primitives (Curve25519 / ChaCha20-Poly1305); arnika layers PSK rotation on the `wg0` hop tunnel, and Rosenpass on the `wg1` data tunnel carried inside it, for additive protection.
  - **strongSwan IPsec/IKEv2 + RFC 9370 hybrid** (recommended for real hardware): `IKE_SA_INIT` carries the classical ECP-256 exchange in its KE payload and *negotiates* ML-KEM-768 as Additional Key Exchange 1 (`KE1_ML_KEM_768`); the ML-KEM exchange itself then runs in a following `IKE_INTERMEDIATE` (RFC 9242), and both shared secrets are mixed into the IKE keying material. RFC 9370 Sec. 2.2.1 requires this placement: additional key exchanges "MUST take place in a series of IKE_INTERMEDIATE exchanges following the IKE_SA_INIT exchange". It matters here because `IKE_SA_INIT` is unencrypted and cannot be fragmented by RFC 7383, while an ML-KEM-768 key share is 1184/1088 bytes; see [`vici-ppk.md`](vici-ppk.md).
- **No FIPS or Common Criteria certification**: this is a research PoC, not for production deployment.
- **Regulation and export control**: re-distributing cryptographic software may be covered by ECCN 5D002 or similar — check your jurisdiction before redistribution.

---
