# Architecture

## 1. Layered model (matches `references/PQC-Enhanced_QKD_Networks_A_Layered_Approach.pdf`)

```
+---------------------------------------------------------------------+
| Layer 3 — End-to-end PQC and the data tunnel                        |
| Rosenpass in alice and bob; its exchange runs between the two wg0   |
| addresses (UDP 9997), so it travels inside the hop tunnel; the      |
| lower wg0 address initiates, the other end only answers             |
| Output: the preshared key of wg1, written by Rosenpass itself       |
| wg1 (alice 10.0.1.1, bob 10.0.1.2) has the peer's wg0 address as    |
| its endpoint, so every wg1 packet is carried inside wg0             |
+---------------------------------------------------------------------+
| Layer 2 — Transport orchestration                                   |
| arnika (Go; submodules/arnika, the head of open upstream PR #51)    |
| - ETSI 014 client (plain HTTP; mTLS not implemented)                |
| - PQC-HPKE round with its peer over arnika's own UDP socket:        |
|   HPKE Base mode (RFC 9180), MLKEM1024-P384, HKDF-SHA384            |
| - HKDF-SHA3-256(qkd || pqc) -> 32B PSK                              |
| - wgctrl netlink call -> writes PSK to wg0 peer entry               |
+---------------------------------------------------------------------+
| Layer 1 — Hop encryption                                            |
| WireGuard wg0 between alice and bob (or alice-charlie-bob)          |
| ChaCha20-Poly1305 + Noise + PSK                                     |
| PSK written by arnika every `ARNIKA_INTERVAL` (30s default);        |
| WireGuard mixes it in at its next handshake (section 3)             |
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
- `wan-net` — simulated public Internet. The `wg0` and IKEv2 endpoints. `wg1` and the Rosenpass exchange run between the two `wg0` IPs (the lower one initiates each Rosenpass exchange, the other answers), so on `wan-net` they appear only as `wg0` traffic.
- `mgmt-net` — WebUI plane. Exposes 5173 and 8000 to host.

## 3. Data flow (one PSK rotation on the WireGuard lane)

```
start every wg0 and wg1 peer is created with a random placeholder PSK that
      only its own node knows, so no handshake completes on either
      interface until arnika (wg0) or Rosenpass (wg1) has installed the same
      key on both ends; the WireGuard entrypoint starts arnika at the next
      wall-clock multiple of ARNIKA_INTERVAL, so the two processes' interval
      counters start ticking together (below the diagram)
each  the two arnika peers run one PQC-HPKE round on their existing UDP
round socket, every PQC_ROUND_INTERVAL (arnika's default is the rotation
      interval, 30 s here): the round's initiator sends a fresh
      MLKEM1024-P384 public key, the responder encapsulates and both export
      32 bytes; confirmation tags go both ways, and each side publishes the
      round's key only once the peer's tag matches
T+0   bb84-kme-a runs a key-production round with the configured simulator
      backend (`simulator.backend` in config/qkd_params.yaml; simqn by default)
T+0.1 reconciliation produces a 256-bit secret key, base64-encoded
T+0.1 KME-a stores key by UUID and POSTs /internal/sync to KME-b
T+0.2 the PRIMARY arnika for this interval (re-elected every interval: bit 0
      of the first byte of HMAC-SHA256(ARNIKA_PSK, interval) XOR ARNIKA_ID,
      `config.go` IsPrimary) polls
      /api/v1/keys/<peer SAE>/enc_keys?number=1&size=256
T+0.2 it receives {keys: [{key_ID, key}]}, builds its PSK =
      HKDF-SHA3-256(qkd || latest published PQC-HPKE key), and sends key_ID
      to the peer's :9999 over UDP, AES-256-GCM encrypted and HMAC-SHA256
      signed under keys derived from ARNIKA_PSK (the HMAC key also from the
      sender's ARNIKA_ID parity), with a timestamp window against replay
T+0.3 the BACKUP arnika receives key_ID, calls .../dec_keys?key_ID=...,
      builds the same PSK, writes it as the wg0 peer's preshared key via
      netlink, and only then ACKs
T+0.3 the PRIMARY writes its PSK only after that ACK. In QkdAndPqcRequired a
      missing ACK, a missing key_id or a missing PQC key installs a random
      PSK instead, so a failed rotation invalidates wg0 rather than extending
      the previous key
later The new PSK takes effect at WireGuard's NEXT handshake. arnika only
      overwrites the peer entry; it triggers no handshake. The entrypoint sets
      persistent-keepalive 25, so traffic always flows and the initiator
      re-handshakes every REKEY_AFTER_TIME = 120 s. With ARNIKA_INTERVAL=30s,
      roughly three of every four PSKs are replaced before any handshake uses
      them; each handshake uses the PSK installed most recently before it.
apart Rosenpass in alice and bob exchanges keys between the wg0 addresses
      (UDP 9997), inside wg0, on its own schedule: the lower wg0 address
      initiates every exchange, about every 130 s, and the other end only
      answers. Each new key becomes wg1's preshared key; arnika never sees it
```

Two properties of the pinned arnika, both from reading its code and neither
measured here: both peers read "the latest published" PQC-HPKE key when they
build their PSK -- the PRIMARY before it sends the key_ID, the BACKUP after
its `dec_keys` request -- so a round that publishes between the two reads
gives them different PSKs until the next rekey (upstream's `docs/pqc-hpke.md` states
this read gap as an open design question); and because the BACKUP installs
before it ACKs and the PRIMARY after, the two nodes no longer install at the
same moment. What the second means for the IPsec lane is in
[`docs/vici-ppk.md`](docs/vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race).

The interval number that elects PRIMARY and BACKUP is counted by each arnika
process from its own start, and since #51 a BACKUP whose interval ends
without a `key_id` fails closed. When the BACKUP's boundary lags the
PRIMARY's by more than the PRIMARY's KMS fetch time, the PRIMARY's `key_id`
can arrive before the BACKUP's boundary ("early") and is then counted in the
BACKUP's previous interval. The BACKUP fails closed at the end of the current
interval only if the next interval's `key_id` is not early too, which in
practice means at its BACKUP-to-PRIMARY transitions. That is an inference
from the code. In short local runs without alignment the later-started node
did this at the end of 13 of its 21 BACKUP intervals over three WireGuard
runs, and in one IPsec run of about 6 minutes it received early `key_id`s
in nine intervals and invalidated at two of them, each before an interval in
which it was PRIMARY (observations, not a measurement). So the WireGuard
entrypoint holds arnika back to the next wall-clock multiple of the interval,
which restores the start synchronisation that lane had while arnika waited
for the first Rosenpass key. The IPsec entrypoint deliberately does not: the
before/after measurement compares that lane, so its two arms run the same
entrypoint start behaviour, and the start offset itself is measured in each
arm. The alignment holds only at the start, since each ticker re-bases after
its own processing and the offset between the two ends wanders by
milliseconds per interval (in that IPsec run, from about 255 ms to about
217 ms over 12 intervals). The two nodes of a pair are always recreated
together: after one node restarts alone the two counters differ, and the
elections stop being complementary
([`docs/BUILD.md`](docs/BUILD.md#73-starting-arnika-on-the-interval-boundary)).

## 4. The IPsec lane

The strongSwan lane (`docker-compose.strongswan.yml`, profile `ipsec`) is a
second consumer of the same KMEs, not a second output of the WireGuard lane's
arnika:

- `alice-ipsec` and `bob-ipsec` run **their own** arnika instances
  (`ARNIKA_ID` 11 and 12, UDP `:9998`) against the same KMEs, and agree their
  own PQC-HPKE keys over that socket. Nothing on this lane reads Rosenpass
  output, and no Rosenpass runs in these containers.
- Their arnika is built with the VICI key writer
  (`services/arnika-vici/`, package `repositories/swanvici`, wired by
  `wire_strongswan_vici.go` under `-tags strongswan_vici`) instead of the
  netlink one. It implements upstream's one-method key-writer port,
  `SetPSK(psk []byte) error`; invalidation and the write lock live in
  arnika's `KeyWriterService`. It hands the HKDF output to charon over the
  VICI socket as an RFC 8784
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
contract updates here. Line numbers are at the pinned submodule commit,
`f4cf9ba` (the head of open PR #51).

| Symbol | File:Lines | Why we depend |
|---|---|---|
| `setPSK()`, `buildPSK()`, `writePSK()` | `submodules/arnika/main.go:62-65`, `:68-123`, `:126-141` | Drive the rotation; `writePSK` logs `msg="PSK configured on WireGuard interface"` (`:138`), the line the smoke tests grep |
| `kms.Repository.GetNewKey()` | `submodules/arnika/repositories/kms/kms.go:94-96` | Defines `enc_keys?number=1&size=256` URL |
| `kms.Repository.GetKeyByID()` | `submodules/arnika/repositories/kms/kms.go:98-104` | Defines `dec_keys?key_ID=...` URL (`:102`) |
| `type kmsKey struct` | `submodules/arnika/repositories/kms/kms.go:43-46` | JSON field names `key_ID` + `key` — exactly what our Python KME emits |
| `DeriveKey()` | `submodules/arnika/kdf/kdf.go:17-39` | HKDF-SHA3-256 contract visualised in the Sankey/Manim; byte-identical to the previous pin `3a8cc13` |
| `pqcSuite()` | `submodules/arnika/repositories/pqchpke/pqchpke.go:222-224` | The PQC half: MLKEM1024-P384, HKDF-SHA384, export-only |
| `keyWriterRepository` | `submodules/arnika/services/keywriter.go:23-25` | The one-method port (`SetPSK(psk []byte) error`) the VICI adapter implements |
| `RunKeyIDWorker()` | `submodules/arnika/transport/server.go:361-377` | The BACKUP installs its key before it ACKs; the PRIMARY writes after the ACK (`main.go:369-394`) |
| `IsPrimary()` | `submodules/arnika/config/config.go:102-113` | Per-interval PRIMARY/BACKUP election; why the two `ARNIKA_ID`s must differ in parity (since #51 the parity also picks each direction's HMAC key) |
| Operational modes | `submodules/arnika/config/config.go:42`, validated at `:280-283` | 4 modes drive WebUI ControlPanel choices; both peers must use the same one |

## 6. Why this matches the paper

| Paper claim | Implementation correspondence |
|---|---|
| WireGuard PSK rotated periodically per hop | `ARNIKA_INTERVAL` (default 30s in PoC, 120s in paper) |
| ETSI GS QKD 014 between KME and Arnika | `services/bb84-kme/app/etsi014.py` mounts `/api/v1/keys/{SAE}/...`, which is the `KMS_URL` base arnika is configured with; arnika appends `/enc_keys?number=1&size=256` (`repositories/kms/kms.go:95`) or `/dec_keys?key_ID=...` (`kms.go:102`) and issues the request at `kms.go:121` (`r.conn.Get(r.baseURL + path)`) |
| PQC E2E via Rosenpass, carried over the QKD-secured hop tunnel (4.2) | Rosenpass in alice and bob exchanges between the two `wg0` addresses, the lower address initiating and the other answering, and writes the preshared key of `wg1`, the end-to-end data tunnel whose packets travel inside `wg0`. It does not feed arnika: arnika's PQC half is its own PQC-HPKE round, fused with the QKD key via HKDF (`kdf/kdf.go`) into `wg0`'s key, which the paper's hop key does not include |
| Layered composability (compromise of one layer ≠ catastrophe) | Three Docker networks isolate planes; data in `wg1` is encrypted under `wg1`'s session keys, which mix in Rosenpass's key, and then again under `wg0`'s, which mix in arnika's; mode `QkdAndPqcRequired` makes `wg0` require both the QKD and the PQC-HPKE key |
| Setup time scales with slowest QKD hop, not cumulative | **Not measured.** `benchmarks/handshake_timer.py` samples ONE container's handshake age over time (`--container`, `--duration`; output `epoch,handshake_age_s`). It varies no chain length and has no hop dimension, so nothing in it could distinguish scaling-with-slowest-hop from scaling-cumulatively. No handshake-age series has been captured, so `tools/compare_to_paper.py` reports this project's side as `"ours": {"n": 0}` with a note saying why. |
| Forward secrecy at both QKD and PQC layers | Independent rotation: the BB84 producer triggers the QKD refresh, each PQC-HPKE round uses a fresh key pair, and Rosenpass renews `wg1`'s key on its own schedule |

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
│   ├── arnika/                        # Go; built into the node images (head of open PR #51)
│   ├── rosenpass/                     # PQC handshake daemon keying wg1, built into the node image
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
