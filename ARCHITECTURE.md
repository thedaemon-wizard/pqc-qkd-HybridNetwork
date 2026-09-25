# Architecture

## 1. Layered model (matches `references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf`)

```
+---------------------------------------------------------------------+
| Layer 3 — End-to-End PQC                                           |
| Rosenpass sidecar in each node                                   |
| Output: /var/lib/rosenpass/pqc.psk (32B, refreshed periodically) |
+---------------------------------------------------------------------+
| Layer 2 — Transport orchestration                                  |
| arnika (Go, unmodified from submodules/arnika/)               |
| - ETSI 014 client (plain HTTP; mTLS not implemented)             |
| - reads pqc.psk file                                             |
| - HKDF-SHA3-256(qkd || pqc) -> 32B PSK                           |
| - wgctrl netlink call -> writes PSK to wg0 peer entry            |
+---------------------------------------------------------------------+
| Layer 1 — Hop encryption                                           |
| WireGuard wg0 between alice and bob (or alice-charlie-bob)       |
| ChaCha20-Poly1305 + Noise + PSK                                  |
| PSK written by arnika every `ARNIKA_INTERVAL` (30s default);     |
| WireGuard mixes it in at its next handshake (section 3)          |
+---------------------------------------------------------------------+
```

## 2. Container topology

| Container | Compose file (profile) | Image source | Networks | Privileges |
|---|---|---|---|---|
| `bb84-kme-a` | `docker-compose.yml` | `services/bb84-kme/` | qkd-net, mgmt-net | none |
| `bb84-kme-b` | `docker-compose.yml` | `services/bb84-kme/` (same image) | qkd-net, mgmt-net | none |
| `alice` | `docker-compose.yml` | `nodes/alice/Dockerfile` | qkd-net, wan-net | NET_ADMIN, SYS_MODULE, `/dev/net/tun` |
| `bob` | `docker-compose.yml` | `nodes/alice/Dockerfile` (same image) | qkd-net, wan-net | NET_ADMIN, SYS_MODULE, `/dev/net/tun` |
| `webui-backend` | `docker-compose.yml` | `services/webui-backend/` | mgmt-net, qkd-net | docker.sock read-only |
| `webui-frontend` | `docker-compose.yml` | `services/webui-frontend/` | mgmt-net | none |
| `pqc-validator` | `docker-compose.yml` | `services/pqc-validator/Dockerfile` | mgmt-net, qkd-net | none; no published port |
| `alice-ipsec` | `docker-compose.strongswan.yml` (`ipsec`) | `nodes/strongswan/Dockerfile` | qkd-net, wan-net | NET_ADMIN, SYS_MODULE |
| `bob-ipsec` | `docker-compose.strongswan.yml` (`ipsec`) | `nodes/strongswan/Dockerfile` (same image) | qkd-net, wan-net | NET_ADMIN, SYS_MODULE |
| `charlie` | `docker-compose.multihop.yml` (`multihop`) | `nodes/alice/Dockerfile` (same image) | qkd-net, wan-net | NET_ADMIN, SYS_MODULE, `/dev/net/tun` |
| `qkdnetsim-kme` | `docker-compose.qkdnetsim.yml` (`crossvalidate`) | `services/qkdnetsim-kme/Dockerfile` | qkd-net, mgmt-net | none; no published port |
| `caddy` | `deploy/docker-compose.cloud.yml` | upstream `caddy:2-alpine` | mgmt-net | publishes 80 and 443 |

Only the first seven start with a plain `docker compose up`. The rest come from
an overlay and, where shown, its profile.

Each KME serves two key-delivery interfaces over one key pool: ETSI GS QKD 014
(`/api/v1/keys/...`, what arnika uses) and ETSI GS QKD 004 V2.1.1
(`/etsi004/v2.1.1/...`, this project's HTTP binding, off by default; see
[`docs/etsi004-binding.md`](docs/etsi004-binding.md)). Neither is published to
the host.

Networks:
- `qkd-net` — `internal: true`. KME ↔ arnika, KME-KME key sync, and the 004 stream exchange (`/internal/etsi004/...`). No host bridge.
- `wan-net` — simulated public Internet. WireGuard and IKEv2 endpoints.
- `mgmt-net` — WebUI plane. Exposes 5173 and 8000 to host.

## 3. Data flow (one PSK rotation on the WireGuard lane)

```
T+0   bb84-kme-a runs a key-production round with the configured simulator
      backend (`simulator.backend` in config/qkd_params.yaml; simqn by default)
T+0.1 reconciliation produces a 256-bit secret key, base64-encoded
T+0.1 KME-a stores key by UUID and POSTs /internal/sync to KME-b
T+0.2 the PRIMARY arnika for this interval (re-elected every interval: bit 0
      of the first byte of HMAC-SHA256(ARNIKA_PSK, interval) XOR ARNIKA_ID,
      `config.go` IsPrimary) polls
      /api/v1/keys/<peer SAE>/enc_keys?number=1&size=256
T+0.2 it receives {keys: [{key_ID, key}]} and sends key_ID to the peer's
      :9999 over UDP, AES-256-GCM encrypted and HMAC-SHA256 signed with
      ARNIKA_PSK, with a timestamp window against replay
T+0.3 the BACKUP arnika receives key_ID, calls .../dec_keys?key_ID=...
T+0.3 Both sides now hold the SAME 256-bit QKD key
T+0.3 Both read /var/lib/rosenpass/pqc.psk (independently produced by Rosenpass)
T+0.3 Both compute HKDF-SHA3-256(qkd || pqc) -> 32B PSK
T+0.3 Both write it as the wg0 peer's preshared key via netlink
later The new PSK takes effect at WireGuard's NEXT handshake. arnika only
      overwrites the peer entry; it triggers no handshake. The entrypoint sets
      persistent-keepalive 25, so traffic always flows and the initiator
      re-handshakes every REKEY_AFTER_TIME = 120 s. With ARNIKA_INTERVAL=30s,
      roughly three of every four PSKs are replaced before any handshake uses
      them; each handshake uses the PSK installed most recently before it.
```

## 4. The IPsec lane

The strongSwan lane (`docker-compose.strongswan.yml`, profile `ipsec`) is a
second consumer of the same key sources, not a second output of the WireGuard
lane's arnika:

- `alice-ipsec` and `bob-ipsec` run **their own** arnika instances
  (`ARNIKA_ID` 11 and 12, UDP `:9998`) against the same KMEs, and read the PQC
  half from the same Rosenpass output: they mount the `pqc-psk-alice` and
  `pqc-psk-bob` volumes that alice's and bob's sidecars write.
- Their arnika is built with the VICI key writer
  (`services/arnika-vici/`, `-tags strongswan_vici`) instead of the netlink
  one. It hands the HKDF output to charon over the VICI socket as an RFC 8784
  Post-quantum Preshared Key (`load-shared`, type `ppk`), not as an IKEv2 PSK:
  a PSK only authenticates, while a PPK is mixed into `SK_d`, `SK_pi` and
  `SK_pr`.
- A PPK applies to the initial IKE SA only, so each rotation is consumed by a
  full reauthentication, which the initiator (`VICI_IKE_ROLE`) requests over
  VICI after loading the new key. `ppk_required = yes` on both ends makes a
  missing or mismatched PPK an authentication failure rather than a silent
  fallback to `NO_PPK_AUTH`.
- The key exchange itself is RFC 9370 hybrid IKEv2: ECP-256 plus ML-KEM-768
  (`ke1_mlkem768`).

The mechanism, the rotation sequence and the open issues are in
[`docs/vici-ppk.md`](docs/vici-ppk.md).

## 5. Critical reused arnika code paths

These are the points we depend on; changing them in upstream arnika would require
contract updates here. Line numbers are at the pinned submodule commit.

| Symbol | File:Lines | Why we depend |
|---|---|---|
| `setPSK()` | `submodules/arnika/main.go:30-88` | Drives the rotation; logs we grep in smoke tests |
| `HTTPKMSRepository.GetNewKey()` | `submodules/arnika/repositories/kms.go:94-96` | Defines `enc_keys?number=1&size=256` URL |
| `HTTPKMSRepository.GetKeyByID()` | `submodules/arnika/repositories/kms.go:98-104` | Defines `dec_keys?key_ID=...` URL (`:102`) |
| `type kmsKey struct` | `submodules/arnika/repositories/kms.go:43-46` | JSON field names `key_ID` + `key` — exactly what our Python KME emits |
| `DeriveKey()` | `submodules/arnika/kdf/kdf.go:17-39` | HKDF-SHA3-256 contract visualised in the Sankey/Manim |
| `IsPrimary()` | `submodules/arnika/config/config.go:56-71` | Per-interval PRIMARY/BACKUP election; why the two `ARNIKA_ID`s must differ in parity |
| Operational modes | `submodules/arnika/config/config.go:34` | 4 modes drive WebUI ControlPanel choices |

## 6. Why this matches the paper

| Paper claim | Implementation correspondence |
|---|---|
| WireGuard PSK rotated periodically per hop | `ARNIKA_INTERVAL` (default 30s in PoC, 120s in paper) |
| ETSI GS QKD 014 between KME and Arnika | `services/bb84-kme/app/etsi014.py` mounts `/api/v1/keys/{SAE}/...`, which is the `KMS_URL` base arnika is configured with; arnika appends `/enc_keys?number=1&size=256` (`kms.go:95`) or `/dec_keys?key_ID=...` (`kms.go:102`) and issues the request at `kms.go:121` (`r.conn.Get(r.baseURL + path)`) |
| PQC E2E via Rosenpass | `nodes/alice/rosenpass-sidecar.sh` produces pqc.psk; arnika fuses it via HKDF (`kdf/kdf.go`) |
| Layered composability (compromise of one layer ≠ catastrophe) | Three Docker networks isolate planes; mode `QkdAndPqcRequired` enforces both layers |
| Setup time scales with slowest QKD hop, not cumulative | **Not measured.** `benchmarks/handshake_timer.py` samples ONE container's handshake age over time (`--container`, `--duration`; output `epoch,handshake_age_s`). It varies no chain length and has no hop dimension, so nothing in it could distinguish scaling-with-slowest-hop from scaling-cumulatively. No handshake-age series has been captured, so `tools/compare_to_paper.py` reports this project's side as `"ours": {"n": 0}` with a note saying why. |
| Forward secrecy at both QKD and PQC layers | Independent rotation: BB84 producer triggers QKD refresh, Rosenpass sidecar triggers PQC refresh |

## 7. Repository layout

The main tracked entries, from `git ls-files` and `.gitmodules`.

```
pqc-qkd-HybridNetwork/
├── README.md                          # Entry point and documentation index
├── ARCHITECTURE.md                    # This file
├── VERIFICATION_CHECKLIST.md          # Manual and CI-backed verification rows
├── LICENSE, NOTICE
├── docker-compose.yml                 # Default topology (7 services)
├── docker-compose.strongswan.yml      # IPsec lane (profile ipsec)
├── docker-compose.multihop.yml        # Adds the Charlie relay (profile multihop)
├── docker-compose.qkdnetsim.yml       # Second ETSI 014 server (profile crossvalidate)
├── .env.example                       # Sample environment for a local stack
├── Makefile                           # build / up / smoke / bench / lint / test
├── .github/workflows/ci.yml           # CI
├── references/                        # Reference papers (only where the licence permits)
├── submodules/                        # Git submodules, pinned and unmodified
│   ├── arnika/                        # Go; built into the node images
│   ├── rosenpass/                     # PQC handshake daemon, built into the node image
│   ├── strongswan/                    # IKEv2 daemon, built into the IPsec image
│   ├── wgephemeralpeer/               # Mullvad ephemeral-peer reference (not built)
│   ├── liboqs/                        # NIST PQC library for pqc-validator and pqc-tls-demo
│   ├── oqs-provider/                  # OpenSSL provider for the pqc-tls-demo agility lane
│   ├── SimQN/                         # BB84 simulator backend
│   ├── SeQUeNCe/                      # Photonic discrete-event simulator backend
│   ├── strawberryfields/              # CV-QKD (GG02) backend
│   ├── tno-qkd-key-rate/              # TNO-Quantum decoy-state key-rate engine (cross-check)
│   ├── qkdnetsim/                     # NS-3 qkdnetsim; compiled by qkdnetsim-kme, not run
│   ├── openQKDsecurity/               # MATLAB SDP toolkit (vendored, not used)
│   ├── qkd_kme_server/                # Rust ETSI 014 KME (vendored, not built)
│   └── qkd-pqc-paper-supplementary/   # Spooren et al. containerlab supplementary files
├── config/
│   ├── qkd_params.yaml                # Single source of truth (hot-reloaded)
│   └── qkd_keyrate_table.json         # Pre-computed SKR table (Lo-Ma 2005 + Lim 2014)
├── services/
│   ├── bb84-kme/                      # Python KME: pluggable QKD backends, ETSI 014 REST,
│   │   │                              #   ETSI 004 V2.1.1 binding (off by default)
│   │   └── app/backends/              # qutip / simqn / sequence / cvqkd / composite / qkdnetsim_proxy / tno
│   ├── webui-backend/                 # FastAPI API behind the dashboard
│   ├── webui-frontend/                # React/Vite dashboard, 14 routes incl. /e2e,
│   │                                  #   /paper-flow and the /protocol-lab simulation
│   ├── pqc-validator/                 # liboqs; @noble-vs-liboqs ML-KEM interop
│   ├── pqc-tls-demo/                  # Two PQC TLS image builds (not compose services)
│   ├── arnika-vici/                   # strongSwan VICI key writer for arnika (RFC 8784 PPK)
│   └── qkdnetsim-kme/                 # 2nd ETSI 014 server (Flask; image builds NS-3, does not run it)
├── nodes/
│   ├── alice/                         # WireGuard node image; bob and charlie reuse it
│   └── strongswan/                    # IPsec node image (alice-ipsec, bob-ipsec)
├── deploy/                            # Single-host cloud and demo overlays, Caddy, deploy scripts
├── scripts/                           # Release gates and external audits
├── tools/                             # Precompute and paper-comparison scripts (Python)
├── pki/                               # mTLS cert generation (`make pki`; nothing consumes the output yet)
├── animations/                        # Manim scenes (.py)
├── benchmarks/                        # Latency / throughput scripts
├── tests/                             # pytest contract, unit and repository-guard tests
└── docs/                              # keyrate, vici-ppk, references, roadmap,
                                       #   phases, paper_mapping, THIRD_PARTY_NOTICES, ...
```

---

## Appendix A. Phase history

How the system arrived at this shape, phase by phase, is kept in
[`docs/phases.md`](docs/phases.md); sections 1-7 above describe what runs today.
