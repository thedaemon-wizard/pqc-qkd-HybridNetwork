# Paper → Code mapping

For each major claim in
`references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf` and
`references/QuLore_An_Adaptive_Security_Framework...pdf`,
we record (a) where it is implemented and (b) how to reproduce it.

## Phase 9 additions (Quantum-Secure VPN)

| Paper / Standard | Code | Verification |
|---|---|---|
| RFC 9370 (2023) "Multiple Key Exchanges in IKEv2" | `nodes/strongswan/swanctl.conf.tmpl` → `proposals = aes256gcm16-sha256-prfsha256-ecp256-ke1_ml_kem_768` | `docker exec alice-ipsec swanctl --list-sas` shows `ml_kem_768` in established SA |
| RFC 7696 "Cryptographic Algorithm Agility" | `services/pqc-tls-demo/Dockerfile.oqs-provider` + `.openssl35-native` (two PQC providers, `PQC_PROVIDER` env switch) | `make pqc-tls-demo-both` + `openssl s_client -groups X25519MLKEM768` |
| NIST SP 800-131A Rev.3 | crypto agility lane documented in README §11.6 / §15.2 | — |
| OpenSSL 3.5.0 native PQC (2025-07) | `services/pqc-tls-demo/Dockerfile.openssl35-native` | `openssl s_server -groups X25519MLKEM768` running on Debian trixie |
| Spooren et al. supplementary repo (`aparcar/qkd-pqc-paper-supplementary-files`) | `submodules/qkd-pqc-paper-supplementary/`, analysed via `tools/compare_to_paper.py` | `benchmarks/results/paper_comparison.json` ±15 % vs paper 10.27 s @ 10 nodes |


## PQC-Enhanced QKD Networks (Spooren et al.)

| § | Claim / Component | Implementation | Verification |
|---|---|---|---|
| II.A | KMS-free layered overlay (no centralised KMS) | docker-compose 3-network split; per-node `bb84-kme-*` instead of central KMS | `make ps` shows no central KMS container; `qkd-net` is `internal: true` |
| II.B | ETSI GS QKD 014 between QKD device and gateway | `services/bb84-kme/app/etsi014.py` (matches `submodules/arnika-vq/kms/kms.go:69-176`) | `pytest tests/test_etsi014_contract.py` |
| II.C | Arnika as the QKD↔WireGuard PSK injector | unmodified `submodules/arnika-vq/` (Go binary baked into node image) | `docker logs alice \| grep "PSK configured"` |
| II.D | Rosenpass E2E PQC handshake (Classic McEliece + Kyber/ML-KEM) | `nodes/alice/rosenpass-sidecar.sh` (Rust binary or urandom fallback) | `docker exec alice ls -l /var/lib/rosenpass/pqc.psk` |
| III   | Multi-hop trusted-node chain (Alice—Charlie—Bob) | `docker-compose.multihop.yml` (profile `multihop`) | `make up-multihop && docker exec alice ping 10.0.0.2` |
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
