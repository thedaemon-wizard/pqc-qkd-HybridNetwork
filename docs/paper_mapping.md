# Paper → Code mapping

For each major claim in
`references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf` and
QuLore ([arXiv:2511.22416](https://arxiv.org/abs/2511.22416); CC BY-NC-ND, not redistributed here),
we record (a) where it is implemented and (b) how to reproduce it.

## Phase 9 additions (Quantum-Secure VPN)

| Paper / Standard | Code | Verification |
|---|---|---|
| RFC 9370 (2023) "Multiple Key Exchanges in IKEv2" | `nodes/strongswan/swanctl.conf.tmpl` → `proposals = aes256gcm16-prfsha384-ecp256-ke1_mlkem768` | `docker exec alice-ipsec swanctl --list-sas` shows `KE1_ML_KEM_768` in the established SA. **Superseded spelling:** `ke1_ml_kem_768` appears in earlier drafts and does NOT parse -- `mlkem768` is the only form strongSwan's proposal parser accepts, while `ML_KEM_768` is the long name it prints. |
| RFC 7696 "Cryptographic Algorithm Agility" | **Implemented:** `IKE_PROPOSALS`/`ESP_PROPOSALS` env → `nodes/strongswan/swanctl.conf.tmpl`, so the IKE KEM changes without code -- but only among the ML-KEM parameter sets the pinned strongSwan parses (`mlkem512`/`mlkem768`/`mlkem1024`), which is parameter agility within one family; the agility matrix on `/verify` (`POST /api/pqc/agility`), whose KEM half (ML-KEM, HQC) and signature half (ML-DSA, SLH-DSA) each span two families. **Not implemented:** a `PQC_PROVIDER` env switch between the two TLS images; no such switch exists -- see [`phases.md`](phases.md), Phase 9. | `docker exec alice-ipsec swanctl --list-sas` shows the configured KEM; `curl -X POST http://localhost:8000/api/pqc/agility` with no body (the backend; `/api/agility` is the validator's internal route, which compose does not publish) returns the default matrix |
| OpenSSL 3.5.0 native PQC (released 2025-04-08) | `services/pqc-tls-demo/Dockerfile.openssl35-native` | `make pqc-tls-demo-both` builds the image on Debian trixie (OpenSSL 3.5); no compose service runs it, and it is not a FIPS-validated module |
| Spooren et al. supplementary repo (`aparcar/qkd-pqc-paper-supplementary-files`) | `submodules/qkd-pqc-paper-supplementary/`, analysed via `tools/compare_to_paper.py` | **Not a validation.** The tool's output compares a CPU percentage with a time in seconds and has no measurement on our side; see [`phases.md`](phases.md), "Paper baseline comparison", which is where that is set out. |


## PQC-Enhanced QKD Networks (Spooren et al.)

> **These rows used to carry Roman-numeral section numbers. The paper has
> none.** Its headings are Arabic and named -- 1 Introduction,
> 2 System and Threat Model, 3 Design (3.1 Layering Principle, 3.2 Routing and
> Composition), 4 Implementation (4.1 Component Overview, 4.2 Integration
> Workflow, 4.3 Fail-Safe Mechanism), 5 Evaluation (Tests 1-5), 6 Security
> Evaluation, 7 Discussion, 8 Conclusion. `pdftotext -layout` over the
> redistributed PDF returns **zero** matches for a Roman-numeral heading.
>
> So every citation here pointed at a numbering scheme that does not exist, and
> a reader following one would find nothing. Each has been retargeted by
> locating the cited CLAIM in the PDF by line number and reading which section
> contains it. A straight Roman-to-Arabic transliteration would have been
> wrong in at least two places:
>
> * the 240-720 s failure cascade sits at PDF lines 442-443, between 4.3
>   Fail-Safe Mechanism (line 429) and 5 Evaluation (line 493). It was cited
>   as the sixth section; section 6 is Security Evaluation and contains no
>   timing at all.
> * the default 120 s rotation interval sits at line 412, inside 4.1 Component
>   Overview -- not 4.3, which transliterating its old number would give.
>
> Names are cited beside the numbers because the arXiv and IEEE QCNC versions
> may number differently; the names are what a reader can search for. The
> QuLore table below keeps its Roman numerals deliberately: that paper is
> CC BY-NC-ND and is NOT redistributed here, so its numbering cannot be checked
> against a local copy and must not be "corrected" on a guess.

| Paper section | Claim / Component | Implementation | Verification |
|---|---|---|---|
| 3.1 Layering Principle (also 1.2 Contributions) | KMS-free layered overlay (no centralised KMS) | docker-compose 3-network split; per-node `bb84-kme-*` instead of central KMS | `make ps` shows no central KMS container; `qkd-net` is `internal: true` |
| 4.1 Component Overview | ETSI GS QKD 014 between QKD device and gateway | `services/bb84-kme/app/etsi014.py` (matches `submodules/arnika/repositories/kms/kms.go:43-102`) | `pytest tests/test_etsi014_contract.py` |
| 4.1 Component Overview | Arnika as the QKD↔WireGuard PSK injector | `submodules/arnika/` at `f4cf9ba`, the head of the open upstream PR #51, not modified here (Go binary baked into node image). It injects into the hop tunnel `wg0`, as the paper's arnika does, but its key is HKDF-SHA3-256 over the QKD key and its own PQC-HPKE key, where the paper's is the QKD key alone | `docker logs alice \| grep "PSK configured"` |
| 4.1 Component Overview, 4.2 Integration Workflow | Rosenpass E2E PQC handshake (Classic McEliece 460896 + Kyber512; NOT ML-KEM), routed through the QKD-secured hop tunnel, its key injected into the final data tunnel | Rosenpass in `alice` and `bob` (Rust binary): the exchange runs between the two `wg0` addresses on UDP 9997, so it travels inside `wg0`. The node with the lower `wg0` address initiates every exchange and the other only answers (`nodes/alice/entrypoint.sh`, `rp_peer_entry`). Rosenpass writes the preshared key of `wg1`, whose peer endpoint is the other node's `wg0` address, through its own WireGuard output. Since 2026-09-26; before that Rosenpass wrote a file that arnika mixed into `wg0`'s key, and no separate data tunnel existed | `docker exec alice wg show wg1 endpoints` prints bob's `wg0` address as `wg1`'s endpoint. That Rosenpass keyed `wg1` shows as a completed handshake, not as a preshared-key line: every peer starts with a random placeholder PSK that only its own node knows, so `docker exec alice wg show wg1 latest-handshakes` must be recent and `docker exec alice ping -c3 10.0.1.2` must answer over `wg1`. `docker logs alice 2>&1 \| grep -c 'Exchanged key with peer'` rises by one per exchange, about every 130 s |
| 3.2 Routing and Composition | Multi-hop trusted-node chain (Alice-Charlie-Bob) | `docker-compose.multihop.yml` (profile `multihop`). **Implemented.** The relay forms, and the charlie leg has both layers, like the bob leg: a `wg0` hop tunnel keyed by its own arnika pair (charlie's instance and alice's second one), which agrees its own PQC-HPKE key, and a `wg1` leg keyed by Rosenpass inside that `wg0` (`WG1_CHARLIE_IP`, `WG1_LISTEN_PORT_CHARLIE`; alice initiates, as the lower `wg0` address). Both legs terminate at alice, so the relay holds both legs' hop keys, as a trusted node does, and also each leg's `wg1` key. **That differs from the paper**, whose end-to-end tunnel does not terminate at the trusted node: there the relay forwards it without holding its key. A bob-charlie `wg1` across alice is not built | Checklist row 3.5, per leg. The evidence that a leg is keyed is a completed handshake on its `wg0` and `wg1` peers (a recent `wg show <iface> latest-handshakes` and a ping that answers over the interface), not a `preshared key` line: every peer starts with a random placeholder PSK that only its own node knows |
| 4.1 Component Overview | Periodic PSK rotation, default 120s | `ARNIKA_INTERVAL` env, default 30s in PoC for demo speed | `wg show wg0 dump \| tail -n +2 \| cut -f2 \| sha256sum` changes within 30s. Not plain `wg show wg0`: it prints `preshared key: (hidden)`, never the value, so it cannot show a rotation. The change alone does not show that arnika's key is the one in use, because an invalidation also writes a (random) key: `docker exec alice wg show wg0 latest-handshakes` must stay recent and `docker exec alice ping -c3 10.0.0.2` must answer. |
| 5 Evaluation, Test 2 -- Long Distance | Setup time dominated by slowest QKD hop, not cumulative | **Not measured.** `benchmarks/handshake_timer.py` samples one container's handshake AGE over time; its only knobs are `--container` and `--duration`, and it emits `epoch,handshake_age_s`. There is no hop or chain-length dimension in the script or its output, so it cannot separate the two hypotheses in the claim. | Nothing to run yet. `benchmarks/results/handshake_age.csv` is absent and `paper_comparison.json` shows `"ours": {"n": 0}`, so `make bench` has never produced a row to compare. Measuring this needs a multi-hop chain and a varying hop count -- see `docker-compose.multihop.yml`. |
| 4.3 Fail-Safe Mechanism (empirical: Test 5 -- Simulated QKD malfunction) | Composability — failure of one layer leaves the other intact | Between the two tunnels the independence holds **one way only**. A Rosenpass failure leaves `wg0`'s arnika rotation intact: when `rosenpass` exits, the sidecar installs a random PSK on every `wg1` peer, so `wg1` fails closed, and starts Rosenpass again (`nodes/alice/rosenpass-sidecar.sh`). A `wg0` failure stops `wg1` as well, because both `wg1`'s packets and the Rosenpass exchange travel inside `wg0`. Within arnika, `MODE` decides: `AtLeastQkdRequired` falls back to the QKD key alone when no PQC-HPKE key is available (`buildPSK`, `main.go:68-123`; the mode predicates are `config/config.go:53-55` and `:93-95`), while the deployed `QkdAndPqcRequired` installs a random key instead, as 4.3's injected random keys do | Stop the `rosenpass` process in `alice`. The image has no procps, so no `pkill` or `ps`: either find it through `/proc` inside the container, `docker exec alice bash -c 'for p in /proc/[0-9]*; do [[ $(cat $p/comm 2>/dev/null) == rosenpass ]] && kill ${p#/proc/}; done'`, or run `sudo kill <PID>` on the host with the host PID that `docker top alice` lists for `rosenpass`. Then check that arnika still logs `PSK configured on WireGuard interface` for `wg0`, that `docker logs alice 2>&1 \| grep 'installing a random wg1 PSK'` shows the sidecar's fail-closed write and restart, and that `wg1` completes no handshake until the restarted Rosenpass has exchanged a key again. Not run on the current pin |

## QuLore (Sanz et al.)

| § | Claim / Component | Implementation status |
|---|---|---|
| III.A | vKMS per-node + central QuSec controller | **Future work** (`docs/roadmap.md` §F). Current PoC uses per-node KME only. |
| III.B | 4 security levels (L1-L4) chosen adaptively | Not implemented in PoC-A. Hybrid is fixed at L3 (HKDF-fused QKD+PQC). |
| IV   | HKDF-SHA256 explicit recipe | We use SHA3-256 (matches arnika); SHA256 variant is a future toggle. |
| V    | ML-KEM-768 + dual-KEM combinations | **Partly.** The IPsec lane negotiates real FIPS 203 ML-KEM-768 (RFC 9370 `KE1_ML_KEM_768`), but that is the IKE key exchange. The PQC half of arnika's `HKDF(QKD \|\| PQC)` is PQC-HPKE with the KEM MLKEM1024-P384: FIPS 203 ML-KEM-1024 paired with P-384 ECDH, a post-quantum/traditional hybrid rather than a dual-KEM. Rosenpass, which keys the `wg1` data tunnel, is **Classic McEliece 460896 + Kyber512** -- a dual-KEM, but Kyber512 is pre-standardisation Kyber, not ML-KEM. |
