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
| Spooren et al. supplementary repo (`aparcar/qkd-pqc-paper-supplementary-files`) | `submodules/qkd-pqc-paper-supplementary/`, analysed via `tools/compare_to_paper.py` | `benchmarks/results/paper_comparison.json` ±15 % vs paper 10.27 s @ 10 nodes |


## PQC-Enhanced QKD Networks (Spooren et al.)

| § | Claim / Component | Implementation | Verification |
|---|---|---|---|
| II.A | KMS-free layered overlay (no centralised KMS) | docker-compose 3-network split; per-node `bb84-kme-*` instead of central KMS | `make ps` shows no central KMS container; `qkd-net` is `internal: true` |
| II.B | ETSI GS QKD 014 between QKD device and gateway | `services/bb84-kme/app/etsi014.py` (matches `submodules/arnika/repositories/kms.go:43-101`) | `pytest tests/test_etsi014_contract.py` |
| II.C | Arnika as the QKD↔WireGuard PSK injector | unmodified `submodules/arnika/` (Go binary baked into node image) | `docker logs alice \| grep "PSK configured"` |
| II.D | Rosenpass E2E PQC handshake (Classic McEliece + Kyber/ML-KEM) | `nodes/alice/rosenpass-sidecar.sh` (Rust binary; exits if the keypair is missing, with no fallback) | `docker exec alice ls -l /var/lib/rosenpass/pqc.psk` |
| III   | Multi-hop trusted-node chain (Alice-Charlie-Bob) | `docker-compose.multihop.yml` (profile `multihop`) | **Partial, do not cite as verified.** `charlie` builds and starts and swaps public keys with alice; the relay does not form because alice's Rosenpass sidecar peers with bob only. See the multi-hop row in the README's status table. |
| IV.A | Periodic PSK rotation, default 120s | `ARNIKA_INTERVAL` env, default 30s in PoC for demo speed | `wg show wg0` PSK changes within 30s |
| IV.B | Setup time dominated by slowest QKD hop, not cumulative | `benchmarks/handshake_timer.py` | `make bench` |
| V    | Composability — failure of one layer leaves the other intact | `MODE=AtLeastQkdRequired` falls back to QKD-only if PQC missing (see `main.go:140-196`) | Stop Rosenpass sidecar, observe arnika logs still rotate |

## QuLore (Sanz et al.)

| § | Claim / Component | Implementation status |
|---|---|---|
| III.A | vKMS per-node + central QuSec controller | **Future work** (`docs/roadmap.md` §F). Current PoC uses per-node KME only. |
| III.B | 4 security levels (L1-L4) chosen adaptively | Not implemented in PoC-A. Hybrid is fixed at L3 (HKDF-fused QKD+PQC). |
| IV   | HKDF-SHA256 explicit recipe | We use SHA3-256 (matches arnika); SHA256 variant is a future toggle. |
| V    | ML-KEM-768 + dual-KEM combinations | ML-KEM-768 via Rosenpass; dual-KEM (e.g. ML-KEM + Classic McEliece) is roadmap. |
