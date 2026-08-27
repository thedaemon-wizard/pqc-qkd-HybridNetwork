# Paper → Code mapping

For each major claim in
`references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf` and
QuLore ([arXiv:2511.22416](https://arxiv.org/abs/2511.22416); CC BY-NC-ND, not redistributed here),
we record (a) where it is implemented and (b) how to reproduce it.

## Phase 9 additions (Quantum-Secure VPN)

| Paper / Standard | Code | Verification |
|---|---|---|
| RFC 9370 (2023) "Multiple Key Exchanges in IKEv2" | `nodes/strongswan/swanctl.conf.tmpl` → `proposals = aes256gcm16-prfsha384-ecp256-ke1_mlkem768` | `docker exec alice-ipsec swanctl --list-sas` shows `KE1_ML_KEM_768` in the established SA. **Superseded spelling:** `ke1_ml_kem_768` appears in earlier drafts and does NOT parse -- `mlkem768` is the only form strongSwan's proposal parser accepts, while `ML_KEM_768` is the long name it prints. |
| RFC 7696 "Cryptographic Algorithm Agility" | **Implemented:** `IKE_PROPOSALS`/`ESP_PROPOSALS` env → `nodes/strongswan/swanctl.conf.tmpl` (KEM changeable without code); per-request `kems`/`sigs` on `POST /api/agility`. **Not implemented:** the `PQC_PROVIDER` env switch this row previously claimed — see the correction in [`phases.md`](phases.md). | `docker exec alice-ipsec swanctl --list-sas` shows the configured KEM; `curl -X POST .../api/agility -d '{"kems":[...]}'` |
| NIST SP 800-131A Rev.3 | [`phases.md` — Cryptographic agility strategy](phases.md#cryptographic-agility-strategy-rfc-7696--nist-sp-800-131a-rev3), which separates the agility this project has from the agility it does not | `VERIFICATION_CHECKLIST.md` 7.1 -- every capability a document claims is grepped for in the code |
| OpenSSL 3.5.0 native PQC (2025-07) | `services/pqc-tls-demo/Dockerfile.openssl35-native` | `openssl s_server -groups X25519MLKEM768` running on Debian trixie |
| Spooren et al. supplementary repo (`aparcar/qkd-pqc-paper-supplementary-files`) | `submodules/qkd-pqc-paper-supplementary/`, analysed via `tools/compare_to_paper.py` | `benchmarks/results/paper_comparison.json`. **Do not read the old "±15 % vs paper 10.27 s @ 10 nodes" as agreement.** `tools/compare_to_paper.py` reads columns 0 and 1 of every CSV it finds, and in `rosenpass-scalability/results/experiment-summary.csv` those are `peer_count` and `avg_cpu_percent` -- there is no handshake-time column in that file at all. The reported `mean: 11.93` is therefore a mean CPU **percentage**, compared against a **time in seconds**; the closeness was a coincidence between two unrelated units. The file's peer counts are 1, 500, 1000, 2500 and 5000, so there is also no 10-node row. And `"ours": {"n": 0}` -- there is no measurement on our side to compare with. |


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
| 4.1 Component Overview | ETSI GS QKD 014 between QKD device and gateway | `services/bb84-kme/app/etsi014.py` (matches `submodules/arnika/repositories/kms.go:43-101`) | `pytest tests/test_etsi014_contract.py` |
| 4.1 Component Overview | Arnika as the QKD↔WireGuard PSK injector | unmodified `submodules/arnika/` (Go binary baked into node image) | `docker logs alice \| grep "PSK configured"` |
| 4.1 Component Overview | Rosenpass E2E PQC handshake (Classic McEliece 460896 + Kyber512; NOT ML-KEM) | `nodes/alice/rosenpass-sidecar.sh` (Rust binary; exits if the keypair is missing, with no fallback) | `docker exec alice ls -l /var/lib/rosenpass/pqc.psk` |
| 3.2 Routing and Composition | Multi-hop trusted-node chain (Alice-Charlie-Bob) | `docker-compose.multihop.yml` (profile `multihop`) | **Implemented.** The relay forms and every hop carries a QKD-derived preshared key; verify with checklist row 3.5, which counts PSK installs rather than ping replies. This entry previously read "Partial, do not cite as verified ... the relay does not form because alice's Rosenpass sidecar peers with bob only", which stopped being true once the sidecar gained `RP_EXTRA_PEERS`. |
| 4.1 Component Overview | Periodic PSK rotation, default 120s | `ARNIKA_INTERVAL` env, default 30s in PoC for demo speed | `wg show wg0` PSK changes within 30s |
| 5 Evaluation, Test 2 -- Long Distance | Setup time dominated by slowest QKD hop, not cumulative | **Not measured.** `benchmarks/handshake_timer.py` samples one container's handshake AGE over time; its only knobs are `--container` and `--duration`, and it emits `epoch,handshake_age_s`. There is no hop or chain-length dimension in the script or its output, so it cannot separate the two hypotheses in the claim. | Nothing to run yet. `benchmarks/results/handshake_age.csv` is absent and `paper_comparison.json` shows `"ours": {"n": 0}`, so `make bench` has never produced a row to compare. Measuring this needs a multi-hop chain and a varying hop count -- see `docker-compose.multihop.yml`. |
| 4.3 Fail-Safe Mechanism (empirical: Test 5 -- Simulated QKD malfunction) | Composability — failure of one layer leaves the other intact | `MODE=AtLeastQkdRequired` falls back to QKD-only if PQC missing (see `main.go:140-196`) | Stop Rosenpass sidecar, observe arnika logs still rotate |

## QuLore (Sanz et al.)

| § | Claim / Component | Implementation status |
|---|---|---|
| III.A | vKMS per-node + central QuSec controller | **Future work** (`docs/roadmap.md` §F). Current PoC uses per-node KME only. |
| III.B | 4 security levels (L1-L4) chosen adaptively | Not implemented in PoC-A. Hybrid is fixed at L3 (HKDF-fused QKD+PQC). |
| IV   | HKDF-SHA256 explicit recipe | We use SHA3-256 (matches arnika); SHA256 variant is a future toggle. |
| V    | ML-KEM-768 + dual-KEM combinations | **Partly.** The IPsec lane negotiates real FIPS 203 ML-KEM-768 (RFC 9370 `KE1_ML_KEM_768`), but that is the IKE key exchange. Rosenpass, which supplies the PQC half of `HKDF(QKD \|\| PQC)`, is **Classic McEliece 460896 + Kyber512** -- a dual-KEM already, but Kyber512 is pre-standardisation Kyber, not ML-KEM. This row previously read "ML-KEM-768 via Rosenpass", which conflated the two. |
