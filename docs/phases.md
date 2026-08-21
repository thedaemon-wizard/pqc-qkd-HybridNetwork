# Implementation phases

The phase-by-phase record of how this PoC was built, extracted from the README
so that document stays a navigational entry point rather than a changelog.

Each section states what was added, which files carry it, and how it was
verified at the time. Where a later change has superseded something recorded
here, the superseding note says so inline.

See also:

- [`../README.md`](../README.md) - overview, quickstart and configuration
- [`../VERIFICATION_CHECKLIST.md`](../VERIFICATION_CHECKLIST.md) - what must be
  checked before a release
- [`keyrate.md`](keyrate.md) - the key-rate model
- [`vici-ppk.md`](vici-ppk.md) - the IPsec key-delivery design

---

## 11.5 Phase 8 — Multi-backend QKD simulation & parameter optimisation

Phase 8 addresses the §12 "QKD is only physically simulated" limitation by adding 4 additional
2026-active OSS backends and a science-grounded parameter pipeline.

### Design principle — no hardcoded numbers
Every numeric tunable lives in `config/qkd_params.yaml`. The Python source under
`services/bb84-kme/app/backends/` is guarded by `tests/test_no_hardcoded_params.py`
which walks the AST and rejects magic floats / ints (allow-list only for unit
conversions, π/2 etc., and explicitly documented CV-QKD defaults).

### Parameter source priority
```
1. WebUI live slider (PhysicsParams page)        →
2. config/qkd_params.yaml (hot-reloaded via watchdog) →
3. config/qkd_keyrate_table.json (pre-computed, openQKDsecurity SDP +
                                  arXiv:2511.21253 closed-form)
4. scikit-optimize gp_minimize (Bayesian Optimization on closed-form SKR)
```

### Backend selection
Set via `SIMULATOR_BACKEND` env or `simulator.backend` YAML key, or switch the
**runtime** backend live from the WebUI "Physics Params" page's selector (which
reflects the actual running backend from `/api/stats`). This controls the
bb84-kme physics backend used by the full-stack real KME; the Physics page's
key-rate panel is computed **client-side** and is backend-independent. The
selector is **enabled in `DEMO_MODE`** too — switching the shared backend is
reversible and rate-limited, so it's safe on a public host (its effect is visible
on the Benchmarks page).

| Backend | Source | Purpose |
|---|---|---|
| `qutip` | built-in | Lightweight teaching demo |
| `simqn` | `submodules/SimQN` | Realistic Cascade + Toeplitz PA + fiber loss |
| `sequence` | `submodules/SeQUeNCe` | Photonic noise (depolarizing + measurement error) |
| `cvqkd` | `submodules/strawberryfields` | GG02 continuous-variable QKD |
| `tno` | `submodules/tno-qkd-key-rate` | TNO-Quantum decoy-state BB84/BBM92 key-rate (Apache-2.0) |
| `qkdnetsim_proxy` | `services/qkdnetsim-kme` | ETSI 014 reference (NS-3 v3.46) |
| `composite_sim_to_net` | SimQN + qkdnetsim | Physical layer feeds network layer |

### Parameter optimisation
The bb84-kme **backend** optimiser (scikit-optimize `gp_minimize`, Bayesian) is
available via the CLI / API:
```bash
source .venv/bin/activate
python -c "
from app import config_loader; config_loader.reload()
from app.optimizer import optimize_from_yaml
print(optimize_from_yaml())
"
```
The WebUI **Physics Params** page's "Optimize μ / ν" button runs a fast
**client-side** μ/ν grid search over the closed-form Lo-Ma SKR (no backend call).

### Verification (host venv)
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install fastapi 'uvicorn[standard]' pydantic httpx 'numpy<2.3' qutip pyyaml \
            prometheus-client scikit-optimize pandas 'Cython<3.0' pytest
pip install -e submodules/SimQN
QKD_PARAMS_FILE=config/qkd_params.yaml \
  python -m pytest tests/test_no_hardcoded_params.py \
                    tests/test_backend_cross_qber.py \
                    tests/test_bb84_simulator.py -v
# Expected: 7 passed
```

### Pre-computed key-rate table
```bash
source .venv/bin/activate
python tools/precompute_keyrate_table_fallback.py
# wrote 1170 rows to config/qkd_keyrate_table.json
```

The table is committed to git so users without MATLAB get production defaults.

---

## 11.6 Phase 9 — Real Quantum-Secure VPN extensions

Phase 9 takes the PoC from "research demo" toward "real quantum-safe VPN stack" by
adding parallel VPN protocols, a documented crypto-agility strategy, paper-baseline
comparison, and end-to-end browser verification.

### VPN protocol lanes (WireGuard + strongSwan IPsec/IKEv2)

| Lane | Tunnel impl | Key exchange | PSK injection path |
|---|---|---|---|
| `wireguard` (Phase 0-7 default) | kernel module `wg` | Curve25519/ChaCha20-Poly1305 + Noise + PSK | `arnika` → `wgctrl` netlink |
| `strongswan` (Phase 9-A) | `charon` daemon | **RFC 9370** hybrid (ECP-256 + KE1=ml_kem_768) | `arnika-vici-bridge.sh` → `swanctl --load-creds` |

> **Superseded.** This lane was rebuilt on RFC 8784 PPK with a native Go VICI
> client. The proposal keyword above (`ke1_ml_kem_768`) does not parse; the
> correct spelling is `ke1_mlkem768`. The shell bridge has been deleted. See
> [`vici-ppk.md`](vici-ppk.md) for the current design and why the original was
> wrong at the mechanism level, not merely in its implementation.

Bring up either lane (or both):

```bash
make up                                   # WireGuard (default profile)
make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.strongswan.yml" \
   --profile ipsec                        # IPsec/IKEv2 (RFC 9370) lane
```

Verify RFC 9370 hybrid handshake:

```bash
docker exec alice-ipsec swanctl --list-sas | grep -E "ESTABLISHED|ML_KEM"
docker exec alice-ipsec tcpdump -i eth0 -nn udp port 500 -c 4
```

### Cryptographic agility strategy (RFC 7696 / NIST SP 800-131A Rev.3)

The PoC ships **two parallel PQC stacks** so users can choose between maximum
algorithm coverage and FIPS-stable production:

| Lane | Image | Algorithm space | Use case |
|---|---|---|---|
| `oqs-provider` (default) | `services/pqc-tls-demo/Dockerfile.oqs-provider` | ML-KEM, ML-DSA, **SLH-DSA, Falcon, HQC, Classic McEliece**, future NIST round 4 | Research, experiments, algorithm agility |
| `openssl35-native` | `services/pqc-tls-demo/Dockerfile.openssl35-native` | **NIST standards only** (FIPS 203/204) | Production, FIPS compliance |

```bash
make pqc-tls-demo-both                    # Start both lanes side-by-side
# Test:
openssl s_client -tls1_3 -groups X25519MLKEM768 -connect tls35:4433
openssl s_client -tls1_3 -groups X25519MLKEM768 -provider oqsprovider \
                 -connect tls-oqs:4433
```

> **Correction.** Earlier revisions of this section stated that a `PQC_PROVIDER`
> env selects which of these two lanes the WebUI "PQC Validator" page targets.
> **No such switch exists.** `PQC_PROVIDER` is a display-only constant in
> `services/webui-frontend/src/lib/sim/pqc.ts` recording the provenance of
> `@noble/post-quantum`; it is read once for a label and never selects anything.
> Neither TLS image is instantiated by any compose file, so there is no running
> lane to target. The claim is withdrawn rather than papered over, because RFC
> 7696 conformance was being asserted on the strength of it.
>
> What crypto agility this project actually has:
>
> * **IKEv2 proposals are env-driven and real** — `IKE_PROPOSALS` /
>   `ESP_PROPOSALS` in `docker-compose.strongswan.yml` are substituted into
>   `nodes/strongswan/swanctl.conf.tmpl`, so the KEM can be changed without
>   touching code. This is the strongest agility story in the repository.
> * **Algorithm choice is per-request on the validator** — `POST /api/agility`
>   accepts `kems`/`sigs` lists and `POST /api/roundtrip` accepts `algo`
>   (`services/pqc-validator/app/main.py`).
> * **The two TLS images are build artefacts**, reachable only through
>   `make pqc-tls-demo-both`. Wiring them into compose and behind a real switch
>   is tracked in [`roadmap.md`](roadmap.md).

### Paper baseline comparison (`tools/compare_to_paper.py`)

`submodules/qkd-pqc-paper-supplementary/` (added in Phase 9-B) contains the raw
experimental data from Spooren et al. (arXiv:2604.05599). Run:

```bash
source .venv/bin/activate
python tools/compare_to_paper.py
cat benchmarks/results/paper_comparison.json | head -n 30
```

Sample output (after `make bench`): rosenpass-scalability experiment-summary.csv
mean handshake time is within ±15 % of the paper's 10.27 s @ 10 nodes.

### End-to-end browser verification (13 pages)

| # | Path | Page |
|---|---|---|
| 1 | `/` | Overview (architecture SVG + live container status) |
| 2 | `/e2e` | Quantum-Secure E2E — **client-side** 4-phase orchestration (real @noble HKDF-SHA3 + ChaCha20) |
| 3 | `/paper-flow` | Paper Data Exchange — **client-side** multi-hop + failure cascade (arXiv:2604.05599) |
| 4 | `/bb84` | BB84 Live — **client-side** Monte-Carlo (Web Worker/WebGPU), QBER chart, Eve toggle, photon frames |
| 5 | `/keyflow` | Hybrid Key Derivation Sankey |
| 6 | `/topology` | D3-force network graph |
| 7 | `/benchmarks` | KPI cards + latency/QBER charts |
| 8 | `/console` | Container log tail |
| 9 | `/physics` | PhysicsParams — editable params + **client-side** key-rate & μ/ν optimiser (closed-form Lo-Ma) |
| 10 | `/pqc` | PQC Validator (liboqs vs PQClean) |
| 11 | `/verify` | Implementation Verification (crypto-agility matrix + TNO key-rate cross-check + paper budgets) |
| 12 | `/hil` | Hardware-In-The-Loop bridge instructions |
| 13 | `/vpn` | VPN Protocols (WireGuard ⟷ strongSwan) |

Verified in a browser: all 13 React Router paths render their correct headings,
the four simulation pages run client-side (no `/ws/*`), and console errors = 0.
- 0 console errors (only React Router v7 future-flag warnings, which are benign)
- `/api/*` proxy targets backend; pages with API dependencies show "Loading…" gracefully

---

## 11.7 Phase 10 — Quantum-Secure E2E live simulation page

Phase 10 adds a single **Quantum-Secure E2E** page (route `/e2e`, sidebar starred entry)
that drives an actual background simulation from Alice to Bob across the full 4-phase
Data Exchange depicted in the reference architecture image, with live buttons.

### What runs in the background

A coroutine-based state machine
(since deleted; now `services/webui-frontend/src/lib/sim/e2eSim.ts`) cycles through four phases:

| Phase | Name | What actually happens |
|---|---|---|
| **1** | Quantum Plane | Poll `bb84-kme-a` `/api/v1/keys/ALICE/status` until SimQN backend produces a key |
| **2** | QKD Key IDs (ETSI 014) | `GET /enc_keys` from KME-A, mirror retrieval via `GET /dec_keys?key_ID=…` at KME-B (matches `submodules/arnika/repositories/kms.go:43-101`) |
| **3** | PQC Handshake (HKDF-SHA3) | `HKDF-SHA3-256(qkd ‖ random_pqc, salt="pqcqkd-e2e", info=mode)` → 32 B PSK |
| **4** | Data Exchange (ChaCha20-Poly1305) | Encrypt 64 ping-sized payloads per cycle, count bytes and packets |

Verified: 5 seconds @ default settings produces **~60 cycles, ~3 900 packets, ~280 KB
encrypted**, with rotating QKD key IDs and per-cycle PSK derivation.

### What the UI shows

`services/webui-frontend/src/pages/QuantumSecureE2E.tsx` renders, top-to-bottom:

1. **SVG architecture diagram** faithful to the reference image — Site A / Site B,
   ARNIKA (orange) · ROSENPASS (pink) · WIREGUARD (purple), KMS keystores
   (ETSI 014, green) at each edge. Active phase highlights the relevant elements
   with a coloured glow.
2. **Mode buttons A / B / C** — `A · QKD-only`, `B · PQC-only`, `C · Hybrid (QKD ‖ PQC)`.
3. **Control buttons** — `▶ Run` / `⏸ Pause` / `▶ Resume` / `⏹ Reset` / `⏭ Step` +
   live status badge.
4. **Phase progress strip** — 4 boxes turning red-active or green-done as the
   state machine progresses.
5. **KPI cards** — Completed cycles, packets encrypted, bytes encrypted, throughput Mbps.
6. **Latest derived material** — most recent QKD `key_ID` and HKDF PSK prefix.
7. **Phase history table** — last 8 phase entries with detail JSON.

State streams live over WebSocket (`/ws/e2e`) at ~4 Hz.

> **Superseded.** The `/e2e` and `/paper-flow` pages moved to client-side
> simulation (`services/webui-frontend/src/lib/sim/e2eSim.ts` and
> `paperSim.ts`); the frontend opens no WebSocket at all. The backend
> orchestrators and the REST/WebSocket surface described above have been
> deleted. The paper budgets survive in
> `services/webui-backend/app/paper_budgets.py`, which is what
> `/api/verify/paper-budgets` now reads.


### REST + WebSocket surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/e2e/state` | GET | Current snapshot (status, phase, mode, cycles, history…) |
| `/api/e2e/start` | POST | Kick the orchestrator into `running` |
| `/api/e2e/pause` | POST | Freeze the state machine (counter halts) |
| `/api/e2e/resume` | POST | Resume from `paused` |
| `/api/e2e/reset` | POST | Clear cycles/packets/history back to `idle` |
| `/api/e2e/step` | POST | Single-step one cycle even while paused |
| `/api/e2e/mode` | POST | Set mode A / B / C |
| `/ws/e2e` | WS | Live snapshot pushed on every state transition |

### Browser verification (Chrome)

Verified end-to-end against the live Docker stack (bb84-kme-a/b + webui-backend +
webui-frontend, all healthy):

- `Pause` → counter froze at cycles=1489 across 3 seconds
- `Resume` → counter advanced 1489 → 1517
- `Reset` → counter → 0 (idle state)
- `Mode A` / `Mode B` / `Mode C` → backend `mode_label` updated to "QKD-only" /
  "PQC-only" / "Hybrid (QKD ‖ PQC)" respectively
- WebSocket delivered 3 snapshots in 250 ms intervals with phase transitions visible
- **0 console errors** (only React Router v7 future-flag warnings, benign)
- Idle / running / paused states reviewed on screen (captures not committed)

### Layout v2 (Phase 11)

The initial SVG (880×280, ~30 elements) was rewritten to **1240×620 with 145 SVG
elements** so the on-screen architecture is now 1:1 faithful to the reference image:

- Three dashed boundary boxes — VPN scope (red), Secure Application Entity (purple,
  per site), Quantum Key Distribution Infrastructure (blue, far left + right)
- Top key-colour legend with A/B/C key icons, mirrored on Site A and Site B
- KMS Keystore [ETSI 014] + QKD sub-box + ETSI Interface "E" badge per side
- Centre "VPN" lock icon between sites
- Three separated bottom rows: **PQC KEY exchange** (Rosenpass A⇄B), **QKD key_ID
  exchange** (ETSI 014), and **Quantum Channel** (BB84 photonic) — each on its own
  y-band, no overlapping labels
- Bottom-left legend explaining A = QKD Mode / B = PQC Mode / C = Hybrid /
  E = ETSI Interface

A new submodule **`mullvad/wgephemeralpeer`** (2026-05-08 active, GPL-3.0) is added
as a reference for the alternative "PQC-only PSK rotation" approach used in
production by Mullvad VPN; see [`docs/IMAGE1_VPN_SCOPE.md`](IMAGE1_VPN_SCOPE.md)
for a head-to-head comparison with arnika.

Screenshots were reviewed for this layout but not committed. These specific captures were never committed; the files in `docs/images/screenshots/` are listed in the repository. Kept as a record of what was checked at the time, not as a pointer to an artefact.

---

## 11.8 Phase 12 — Logger / shared UI / per-page exports

Three improvements that make the PoC easier to operate, inspect, and reproduce:

### 12-A: Rotating file logger

All Python services (webui-backend, bb84-kme-a, bb84-kme-b, pqc-validator) now log
through `services/<svc>/app/logging_setup.py`. Output is duplicated to:

- stdout — keeps `docker logs <svc>` behaviour intact
- **`/var/log/pqcqkd/<svc>.log`** — `RotatingFileHandler`, 10 MB × 5 backups, mounted
  as the shared `pqcqkd-logs` volume

Two REST endpoints expose the files to the browser:

```bash
curl http://localhost:5173/api/logs/files
# {"files":[{"name":"alice.log","size":863,...},
#           {"name":"bob.log","size":742,...},
#           {"name":"webui-backend.log","size":388,...}]}

curl http://localhost:5173/api/logs/download/alice?lines=200
# (downloads the last 200 lines of /var/log/pqcqkd/alice.log)
```

Also: `make tail-logs` follows the live rotation inside the container.

### 12-B: Shared React components

Seven reusable building blocks live under
`services/webui-frontend/src/components/` so individual pages stop re-implementing
their own button / panel / row / badge / KPI:

| Component | Purpose |
|---|---|
| `PageHeader` | `<h2>` + lead `<p>` + right-aligned `ExportToolbar` slot |
| `Panel` | Card with optional left-border accent colour |
| `Row` | Aligned key/value display |
| `Badge` | Coloured status pill (`running`, `paused`, `healthy`, ...) |
| `Button` | Variant-aware button (`primary`/`secondary`/`danger`/`success`/`warn`/`ghost`) |
| `KPI` | Dashboard number tile |
| `ExportToolbar` | The download buttons described below |

Dark theme tokens are centralised in `services/webui-frontend/src/lib/commonStyles.ts`.

The `Quantum-Secure E2E` page (Phase 11 SVG) is **unchanged** in layout; only the
heading and the toolbar are added on top.

### 12-C: Per-page export toolbar

A new `<ExportToolbar>` ships on every refactored page. Each button is opt-in: the
page only declares the providers it can supply.

| Button | Action |
|---|---|
| **Logs** | Download `/api/logs/download/<service>` as `.log` |
| **PNG** | High-DPI (2×) PNG — SVG diagrams via XMLSerializer→Canvas at 2× scale; other pages via `html-to-image` `pixelRatio: 2` |
| **JSON** | Serialise the page's snapshot from `jsonProvider()` |
| **CSV** | Serialise tabular data from `csvProvider()` |
| **WebM (HQ)** | High-quality animation — records for a user-selected duration (default 10 s) via `MediaRecorder` + `canvas.captureStream` (VP9/VP8 WebM, no 256-colour limit) |
| **GIF** | Animated GIF (universally compatible) — full-resolution frames. Now encoded with `modern-gif`; `gifshot` was replaced after it went unmaintained. |

All downloads are produced client-side (`Blob` + `URL.createObjectURL`), with a
best-effort backend save for re-download; **no server-side generation is required**.

### Browser verification

- `/e2e` export toolbar exposes `["Logs","PNG","JSON","WebM (HQ)","GIF","Saved"]`;
  verified PNG = 2480×1200 (2×), GIF = 1240×600 (full-res), WebM = valid VP9 video
- Pressing Logs produces a `text/plain` blob of 388 B (matches the file size on disk)
- Pressing JSON produces an `application/json` blob of 308 B
- `/api/logs/files` returns the three rotating log files actually written under
  `/var/log/pqcqkd/` (verified inside the container)
- **0 console errors**
- Toolbar layout reviewed on screen; the capture was not committed

---

## 11.9 Phase 14 — Paper Data Exchange page + /e2e SVG polish + Rust ETSI 014 KME

Phase 14 introduces a brand-new page that implements the *paper-faithful* Data
Exchange (vs the single-tunnel concept on `/e2e`), polishes the existing E2E
SVG layout, and adds a third independent ETSI 014 KME (Rust) as 2026-active
OSS reference.

### A new page: `/paper-flow` — Paper Data Exchange

Route: `/paper-flow` (sidebar entry "Paper Data Exchange " right after the
existing "Quantum-Secure E2E "). The page is intentionally distinct from
`/e2e`:

| | `/e2e` (image 1) | `/paper-flow` (image 2 + arXiv:2604.05599) |
|---|---|---|
| Source figure | `arnika-project/arnika` single-tunnel diagram | **Multi-hop trusted-node diagram** (End Node Alice \| Trusted Node × N \| End Node Bob) |
| Focus | key fusion in one Site A ↔ Site B tunnel | **5-phase daisy chain** with paper-quoted packet budgets |
| Failure model | Eve attack on BB84 | **240-720 s layer cascade** per §VI |
| Data Exchange | conceptual ChaCha20 over derived PSK | live `ChaCha20-Poly1305` payload per cycle, packet/byte counters track paper §IV-B Table III |

Backend orchestrator (deleted; now `services/webui-frontend/src/lib/sim/paperSim.ts`):
- 5-phase state machine: **Quantum Plane → Arnika QKD key_ID → WG hop handshake → Rosenpass PQC handshake → Final data tunnel**
- Paper budgets embedded as the source of truth (`PHASE_BUDGETS` constant):
  Phase 2 = 2 pkt / 78 B; Phase 3 = 3 pkt / 398 B; Phase 4 = 4 pkt / 4772 B;
  **total handshake = 9 pkt / 5248 B**
- Failure cascade scheduler with 7 stages (0/180/240/360/420/540/720 s)
- WebSocket `/ws/paper-flow` at ~4 Hz

> **Superseded.** The `/e2e` and `/paper-flow` pages moved to client-side
> simulation (`services/webui-frontend/src/lib/sim/e2eSim.ts` and
> `paperSim.ts`); the frontend opens no WebSocket at all. The backend
> orchestrators and the REST/WebSocket surface described above have been
> deleted. The paper budgets survive in
> `services/webui-backend/app/paper_budgets.py`, which is what
> `/api/verify/paper-budgets` now reads.

- REST: `/api/paper-flow/{state,start,pause,resume,reset,config,inject-failure,clear-failure}`

Frontend (`services/webui-frontend/src/pages/PaperDataExchange.tsx`):
- `MultiHopTopologySvg` — image-2 faithful 3-column-or-more SVG (Alice \|
  TN×N \| Bob), hop slider 1 → 8, per-phase glow highlighting
- `PhaseSequenceSvg` — 5-lane swimlane with time axis 0..540 s, byte-proportional bars
- `PacketFlowTable` — Phase × (packets, bytes, period, grace, status)
- `FailureCascadeTimeline` — 7-event timeline with a moving head; events flip
  red as wall-clock crosses them
- 5 KPI cards (paper packets, paper bytes, mean 10-hop setup, live cycles,
  live bytes)
- Layer-failure injection buttons: `qkd / arnika / wireguard / rosenpass /
  data + clear`
- `ExportToolbar` (Phase 13) wired with `pngTargetSelector="#paper-flow-topology-svg"`

### `/e2e` SVG polish (Phase 11 v2 unchanged in spirit)

Four coordinate fixes to remove subtle text-to-box collisions. Element count
145 and viewBox `1240×620` are preserved:

| Element | Before | After |
|---|---|---|
| KMS→ARNIKA `QKD KEY` label | y=232 (collided with ARNIKA tag y=238) | **y=208** (clear above box) |
| ARNIKA→KMS `key_ID` label | y=278 (10 px below box) | **y=288** (20 px below box) |
| Center `VPN tunnel (ChaCha20-Poly1305)` label | y=206 (touching WIREGUARD title y=220) | **y=174** (just under Site A/B headings) |
| HKDF SHA3 badge inside ARNIKA | x=244 (mid-box, over title text) | **x=222** (top-left corner of box) |

Browser verification confirmed the four labels render at the new
coordinates: `QKD KEY y=[208,208], key_ID y=[288,288], VPN tunnel y=174`.

### A third ETSI 014 KME (Rust, 2026-04-01 active)

`submodules/qkd_kme_server` is now part of the repo —
[`thomasarmel/qkd_kme_server`](https://github.com/thomasarmel/qkd_kme_server)
with its most recent commit on **2026-04-01**, Rust + ETSI GS QKD 014 v1.1.1
compliant. Together with our existing Python `bb84-kme` (Phase 1) and NS-3
C++ `qkdnetsim-kme` (Phase 9), this gives **three independent ETSI 014
implementations** for cross-validation:

| Implementation | Language | Phase | Last commit |
|---|---|---|---|
| `services/bb84-kme` (this repo) | Python + SimQN | 1 | live |
| `services/qkdnetsim-kme` (NS-3 contrib) | C++ | 9 | 2026-05-03 |
| `submodules/qkd_kme_server` | Rust | 14 | **2026-04-01** |

Note: `pq-wireguard` (Kudelski Security) was previously listed as a
candidate but was **archived on 2024-09-03** ("not actively maintained
anymore"), so it has been excluded; only the verifiably 2026-active option
above was added.

### Browser verification (Chrome)

- 12 sidebar nav links including the new "Paper Data Exchange "
- `#paper-flow-topology-svg` viewBox `0 0 1060 720`, 160 elements
- `#paper-flow-sequence-svg` 91 elements
- Hop slider 1 → 8 renders 3 → 10 columns
  ("End Node Alice + Trusted Node 1..N + End Node Bob")
- Inject `qkd` failure → 7 cascade events scheduled
  (t=0/180/240/360/420/540/720 s)
- Backend orchestrator: 389 live cycles after ~1.3 s with
  `paper_packets=9 / paper_bytes=5248` (paper-quoted values)
- **0 console errors**

---

