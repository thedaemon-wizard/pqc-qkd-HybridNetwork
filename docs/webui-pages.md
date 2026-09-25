# WebUI pages

The fourteen routes the dashboard serves, what each one computes in the
browser, and what it needs the backend for.

Which routes survive without a backend, and what each one costs to host, is a
different question -- see [`deployment-economics.md`](deployment-economics.md).

---

## Pages

1. **Overview** (`/`) — Layered architecture SVG + live container status badges. Its Logs export is the rotating `webui-backend` server log from `GET /api/logs/download/webui-backend?lines=1000` (Logs export only)
2. **Quantum-Secure E2E** (`/e2e`) — **client-side** 4-step orchestration (Quantum Plane → QKD Key IDs → PQC Handshake → Data Exchange) with **real in-browser HKDF-SHA3-256 + ChaCha20-Poly1305** (`@noble`) over random surrogate keys, drawn over the arnika architecture diagram, Run/Pause/Resume/Reset/Step + Mode A/B/C. See [`IMAGE1_VPN_SCOPE.md`](IMAGE1_VPN_SCOPE.md) for what each element does and does not stand for
3. **Paper Data Exchange** (`/paper-flow`) — **client-side** multi-hop trusted-node Data Exchange (Spooren et al. arXiv:2604.05599): swimlane sequence, hop-count slider (1–8), layer-aware failure-cascade timeline, ChaCha20-Poly1305 payload
4. **BB84 Live** (`/bb84`) — **client-side** Monte-Carlo photon simulation in a **Web Worker**, with optional **WASM (Rust, 907 B)**, **WebGL2** and **WebGPU** tiers -- each benchmarked against the Worker for one round and adopted only if it wins, so the badge names the engine that actually ran. Throughput depends on the visitor's device: one run on the public demo kept the Worker at 62M pulses/s over WebGPU at 34M/s. Real-time QBER chart, key-pool size, photon-frame table, **Eve toggle** + intercept-probability slider, live engine badge
5. **Key Flow** (`/keyflow`) — Plotly Sankey of QKD raw → sifted → reconciled + Rosenpass → HKDF → WireGuard PSK
6. **Topology** (`/topology`) — D3-force graph of alice, bob and the two KMEs. Charlie is **not** shown: `/api/topology` returns a fixed four-node graph with no multihop branch.
7. **Benchmarks** (`/benchmarks`) — Round latency, QBER history, KPI cards (accepted/aborted/avg ms). Its Logs export is `alice.log`, the rotating log that `bb84-kme-a` writes (its `SAE_ID` is `ALICE`), from `GET /api/logs/download/alice?lines=1000` (Logs export only)
8. **Console** (`/console`) — Live log tail of one of six containers: `alice`, `bob`, `bb84-kme-a`, `bb84-kme-b`, `alice-ipsec` and `bob-ipsec`. `GET /api/logs/{name}` accepts only those names and answers 404 for any other before Docker is touched; secret lines are redacted
9. **Physics Params** (`/physics`) — Editable parameter inputs with a **client-side** key rate and **client-side** μ/ν optimiser that recompute in the browser as you edit. The rate shown is the closed-form **asymptotic** Lo-Ma two-decoy bound; the KMEs and `/protocol-lab` use the Lim et al. finite-key rate, which is lower -- see [`keyrate.md`](keyrate.md). `config/qkd_params.yaml` provides the defaults, with bundled defaults when no backend answers. Whether Apply, Reset and the backend selector (incl. `tno`) reach the KMEs depends on `ENABLE_LIVE_PARAM_OVERRIDES`; see [Server-side switches](#server-side-switches). The two backends that forward to `qkdnetsim-kme` (`qkdnetsim_proxy`, `composite_sim_to_net`) are offered only while `/api/stack` reports that container running, since it exists only in the `crossvalidate` overlay. Below the form, a read-only **field reference** panel shows the measured link values of arXiv:2608.18869v2 with the source's digits beside what this project's model gives at the same loss -- its rate under the shipped configuration, and its QBER tolerance at the shipped block size $`N = 10^9`$ and at $`N = 10^{18}`$ (`LARGE_BLOCK_N` in `lib/sim/protocolLab/rates.ts`, the model's large-block tolerance) -- and states that the paper's BBM92 system is a different protocol from the model's decoy-state BB84
10. **PQC Validator** (`/pqc`) — client-side ML-KEM / ML-DSA / SLH-DSA via @noble. The ML-KEM half is cross-checked against liboqs when the backend answers: `POST /api/pqc/interop` has liboqs encapsulate to a key the browser generated, and the browser must derive the same shared secret (`/api/interop/mlkem` is the pqc-validator's internal route behind it); `POST /api/pqc/roundtrip` adds liboqs's own round trip. The signatures are checked in the browser only; the liboqs signature check is on `/verify`
11. **Verification** (`/verify`) — Research-implementation evidence: a crypto-agility matrix run through liboqs by `POST /api/pqc/agility` (the pqc-validator's internal `/api/agility` behind it), spanning **two mathematical families on each side** -- KEMs ML-KEM 512/768/1024 (module lattice) and HQC-1/3/5 (code-based), signatures ML-DSA 44/65/87 (module lattice) and SLH-DSA SHA2-128s/128f/192s/256s (hash-based). Each signature row carries `verified` and `rejects_tampered`: liboqs signs, verifies the genuine message, and must reject a tampered one, and the row passes only if both hold. The same page can run the matrix in the browser and compare the two halves. Also a key-rate cross-check (our closed-form vs the independent **TNO-Quantum** engine) and the arXiv:2604.05599 packet-budget match
12. **Hardware-In-Loop** (`/hil`) — Checklist for wiring real ETSI 014 KMS hardware (mTLS not yet implemented; see [`LIMITATIONS.md`](LIMITATIONS.md))
13. **VPN Protocols** (`/vpn`) — WireGuard + strongSwan IPsec/IKEv2 status, parsed live from both IPsec nodes: the negotiated proposal (RFC 9370 ML-KEM-768), per-SA RFC 8784 PPK use (`/PPK`), whether a PPK is required and used on both ends, whether the ESP SPIs pair across the ends, and ESP byte/packet counters per CHILD_SA (alice's view on the page; both nodes in the JSON export and `GET /api/vpn/protocols`), plus each IPsec node's PPK rotation count over the last 10 minutes from `GET /api/vpn/ppk-rotations`
14. **Protocol Lab** (`/protocol-lab`) — **client-side simulation**, labelled as such before anything runs: trusted-node key relay and re-routing over five published QKD networks (Cambridge 2019, SECOQC Vienna 2008, Tokyo 2010, MadQCI 2024, and the Thuringia medical-data chain of arXiv:2608.18869), with this stack's ETSI GS QKD 014 message shapes per hop and a simulated ETSI GS QKD 004 V2.1.1 stream end to end. Three cited scenarios replay the sources' own re-routing runs and state where the replay differs. Every reported number keeps the source's digits and reference; this project's key-rate model appears in the link table only

Thirteen of the fourteen pages carry an export toolbar (all but `/hil`) -- **high-DPI PNG (2×)**, JSON, CSV, **WebM (HQ)** + **full-resolution GIF** animation where the page animates, and logs. Every file except the server-log download on `/` and `/benchmarks` is built in the browser and downloaded from memory; on those two pages the Logs button fetches a server log through `GET /api/logs/download/<service>` instead. A copy goes to the backend only when the visitor ticks "copy to shared gallery" (off by default), which is what lets the "Saved exports" picker list it again.

---

## Server-side switches

Environment variables on `webui-backend` that decide what a visitor can change
on the server. The boolean ones accept `1`, `true`, `yes` or `on`, case
insensitive; anything else, including unset, is off. `GET /api/config` reports
each one, so a deployment's posture can be checked from outside without
attempting the call it guards.

| Variable | Default | Effect | Reported in `/api/config` as |
|---|---|---|---|
| `ENABLE_LIVE_PARAM_OVERRIDES` | off | When off, `POST /api/sim/params`, `POST /api/sim/params/reset` and `POST /api/sim/backend` answer **403**. `GET` routes are unaffected. | `live_param_overrides` |
| `ENABLE_CONTAINER_CONTROL` | off | When off, `POST /api/stack/{action}/{name}` answers **403** and the Overview hides its restart buttons. `DEMO_MODE` vetoes it: both set means off. | `container_control` |
| `DEMO_MODE` | off | Removes capability rather than adding protection: it vetoes container control, and `deploy/docker-compose.demo.yml` pairs it with a sim-only profile that runs no privileged node and mounts no Docker socket. It does not switch the rate limit. | `demo_mode` |
| `DEMO_RATE_MAX` / `DEMO_RATE_WINDOW_S` | 120 per 60 s | A token bucket on every mutating request (POST, PUT, PATCH, DELETE), **always on** whatever `DEMO_MODE` says; an empty bucket answers **429**. | `rate_limit` |
| `EXPORT_MAX_FILES` / `EXPORT_MAX_BYTES` / `EXPORT_MAX_TOTAL_BYTES` | 100 files / 25 MiB each / 512 MiB in total | Bounds the saved-exports store, oldest file removed first; a single file over the per-file limit, or over the total if that is smaller, answers **413**. | -- |

**Why live overrides are off by default.** The simulator parameters and the
selected backend live in each KME process and are shared by everyone: one
visitor's Apply changes what every other visitor sees, and what both live VPN
lanes draw their QKD keys from, with the last write winning. On a public host
that is a conflict between visitors, not a feature. Turn it on for a
single-user or local stack.

**What `/physics` does when they are off.** The page already computes the key
rate and the μ/ν optimiser in the browser, so Apply and Reset change only the
in-browser model, and the page says so plainly. The backend-switch buttons
are disabled with the same explanation. Nothing on the KMEs changes.

Local full-stack and the `deploy/` cloud real-WireGuard stack run with
`DEMO_MODE` unset.

> Note: in the full profile `webui-backend` mounts `/var/run/docker.sock:ro` to
> enumerate containers and read their logs. This is acceptable for a
> single-host PoC but should not be exposed in production; removing it is on
> the [`roadmap.md`](roadmap.md).
