# Implementation phases

The phase-by-phase record of how this PoC was built. This is the one home for
project history; other documents link here rather than repeating it.

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

## Phase 8 — Multi-backend QKD simulation & parameter optimisation

Phase 8 addresses the "QKD is only physically simulated" limitation
([`LIMITATIONS.md`](LIMITATIONS.md)) by adding 4 additional 2026-active OSS
backends and a science-grounded parameter pipeline.

### Design principle — no hardcoded numbers
Every numeric tunable lives in `config/qkd_params.yaml`. The Python source under
`services/bb84-kme/app/backends/` is guarded by `tests/test_no_hardcoded_params.py`
which walks the AST and rejects magic floats / ints (allow-list only for unit
conversions, π/2 etc., and explicitly documented CV-QKD defaults).

### Parameter source priority
```
1. WebUI live slider (PhysicsParams page)        →
2. config/qkd_params.yaml (hot-reloaded: 1 s mtime poll) →
3. config/qkd_keyrate_table.json (pre-computed by
                                  tools/precompute_keyrate_table_fallback.py:
                                  Lo-Ma-Chen PRL 94, 230504 + Lim PRA 89, 022307
                                  closed-form. NOT an SDP -- see LIMITATIONS)
4. scikit-optimize gp_minimize (Bayesian Optimization on closed-form SKR)
```

### Backend selection
Set via `SIMULATOR_BACKEND` env or `simulator.backend` YAML key, or switch the
**runtime** backend live from the WebUI "Physics Params" page's selector (which
reflects the actual running backend from `/api/stats`). This controls the
bb84-kme physics backend used by the full-stack real KME; the Physics page's
key-rate panel is computed **client-side** and is backend-independent. The
selector reaches the KMEs only where `ENABLE_LIVE_PARAM_OVERRIDES` is on, which
it is not by default: the backend is process-global state that every visitor
and both live VPN lanes share, so on a public host one visitor's switch would
be everyone's. With it off, `POST /api/sim/backend` answers 403 and the page
disables the selector and says why. See
[`webui-pages.md`](webui-pages.md#server-side-switches). That the switch is
reversible and rate-limited does not prevent the conflict.

| Backend | Source | Purpose |
|---|---|---|
| `qutip` | built-in | Lightweight teaching demo |
| `simqn` | `submodules/SimQN` | SimQN quantum channel, fibre loss and sifting; post-processing by `reconciliation.py` (heuristic entropy margin + Toeplitz hash; **no Cascade** -- SimQN's own post-processing is bypassed) |
| `sequence` | `submodules/SeQUeNCe` | Photonic noise (depolarizing + measurement error) |
| `cvqkd` | `submodules/strawberryfields` | GG02 continuous-variable QKD |
| `tno` | `submodules/tno-qkd-key-rate` | TNO-Quantum decoy-state BB84/BBM92 key-rate (Apache-2.0) |
| `qkdnetsim_proxy` | `services/qkdnetsim-kme` | 2nd ETSI 014 server. **Flask, not NS-3** -- the image compiles NS-3 v3.46 but the entrypoint never runs it |
| `composite_sim_to_net` | SimQN + that same server | SimQN's rate feeds a REST key buffer. **No network layer is simulated** |

Each backend is one module under `services/bb84-kme/app/backends/`
(`qutip_backend.py`, `simqn_backend.py`, `sequence_backend.py`,
`cvqkd_backend.py`, `qkdnetsim_proxy.py`, `composite_sim_to_net.py`,
`tno_backend.py`) implementing `base.py::KeyProducer`. The parameter pipeline
around them:

- `config_loader.py` polls the YAML's mtime once a second (`start_watchdog`, a
  thread rather than the `watchdog` package) and calls its subscribers with the
  effective parameters on every reload.
- `_skr.py` holds the Lo-Ma 2005 asymptotic decoy bound and the Lim et al.
  PRA 89, 022307 (2014) finite-key length ([`keyrate.md`](keyrate.md)).
- `optimizer.py` runs `skopt.gp_minimize` over $`(\mu, \nu_1, \nu_2)`$,
  maximising the closed-form finite-key rate from `_skr.py`. $`p_z`$ is in the
  search space, but the objective ignores it (the rate model has no $`p_z`$
  dependence), so the $`p_z`$ it returns is reported, not optimised.

The pipeline Phase 8 put in place, drawn with the current key-rate model:

```
                ┌─────────────────────────────────────────────────────────┐
                │ WebUI (9 pages) Overview / BB84 / KeyFlow / Topology   │
                │   Benchmarks / Console / PhysicsParams / PQCValidator   │
                │   Hardware-In-Loop                                       │
                └──────────────┬──────────────────────────────────────────┘
                               │  REST (JSON)
                ┌──────────────▼──────────────────────────────────────────┐
                │  webui-backend (FastAPI)                               │
                │   /api/sim/params, /api/sim/backend                     │
                │   /api/pqc/algorithms, /api/pqc/roundtrip               │
                └──┬─────────────────────────────────────────────┬────────┘
                   │                                             │
                ┌──▼──────────────────────────────┐         ┌────▼────────┐
                │  bb84-kme (per SAE)             │         │ pqc-validator│
                │                                  │         │ liboqs checks│
                │  KeyProducer ABC                 │         │ (KEM / SIG)  │
                │  ┌──────┬─────┬────────┬───────┐│         └──────────────┘
                │  │qutip │simqn│sequence│cvqkd  ││
                │  └──────┴─────┴────────┴───────┘│
                │  + composite_sim_to_net          │
                │  + qkdnetsim_proxy               │
                │  + tno                           │
                │                                  │
                │  config/qkd_params.yaml          │
                │   (hot-reload, 1 s mtime poll)   │
                │                                  │
                │  optimizer.py                    │
                │   scikit-optimize gp_minimize    │
                │   ↔ closed-form Lo-Ma 2005       │
                │   ↔ Lim 2014 finite-key          │
                └────────┬───────────────────────┬─┘
                         │                       │ bb84-kme is the client:
                         │ ETSI 014              │ qkdnetsim_proxy pulls
                         │ (arnika pulls keys)   │ GET .../enc_keys;
                         │                       │ composite_sim_to_net also
                         │                       │ POSTs /internal/set_rate
                         ▼                       ▼
                ┌────────────────┐      ┌────────────────────┐
                │ arnika (Go)    │      │ qkdnetsim-kme      │
                │ HKDF-SHA3-256  │      │ Flask ETSI 014 srv │
                │ → WG PSK       │      │ (facade, not NS-3) │
                └────────────────┘      └────────────────────┘
```

### Parameter optimisation
The bb84-kme **backend** optimiser (scikit-optimize `gp_minimize`, Bayesian) is
available from the command line; it has no HTTP route:
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

Installed in the same order, and against the same pins, as
`services/bb84-kme/Dockerfile`, so the venv matches the image and CI rather
than a range of its own. `test_no_hardcoded_params.py` is the AST guard
against magic numbers in the backends, `test_backend_cross_qber.py` keeps every
backend's QBER under the threshold, and `test_bb84_simulator.py` checks the
QuTiP simulator's Eve and no-Eve QBER bands.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r services/bb84-kme/requirements.txt pytest
pip install -c services/bb84-kme/constraints.txt pandas 'Cython<3.0'
pip install -c services/bb84-kme/constraints.txt -e submodules/SimQN
QKD_PARAMS_FILE=config/qkd_params.yaml \
  python -m pytest tests/test_no_hardcoded_params.py \
                    tests/test_backend_cross_qber.py \
                    tests/test_bb84_simulator.py -v
```

Every test should pass except one that skips, and says so, when SimQN is not
importable -- which is what happens if the editable install above failed. No
count is pinned here, because a pinned count drifts from the suite. Measured
2026-09-25 in a venv without SimQN: 10 passed, 1 skipped.

### Pre-computed key-rate table
```bash
source .venv/bin/activate
python tools/precompute_keyrate_table_fallback.py
# wrote 1170 rows to config/qkd_keyrate_table.json
```

The table is committed to git, so the shipped configuration has production defaults without re-running this script; regenerate it whenever the physical parameters change.

---

## Phase 9 — Real Quantum-Secure VPN extensions

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
make up        # WireGuard (default profile)
make up-ipsec  # IPsec/IKEv2 (RFC 9370) lane

# Not `make up COMPOSE_FILES=... --profile ipsec`: `--profile` is a docker
# compose flag, not a make flag, so make exits with "unrecognized option
# '--profile'" before running any recipe. `up-ipsec` passes it to compose in
# the right place.
```

Verify RFC 9370 hybrid handshake:

```bash
docker exec alice-ipsec swanctl --list-sas | grep -E "ESTABLISHED|ML_KEM"
docker exec alice-ipsec tcpdump -i eth0 -nn udp port 500 -c 4
```

### Cryptographic agility strategy (Phase 9-C, RFC 7696)

NIST SP 800-131A Rev. 3 is an initial public draft that has not gone final
([`references.md`](references.md)), so it is not a conformance target here.

The PoC carries **two PQC TLS images**, both build artefacts that no compose
file runs. Both are on `debian:trixie-slim`, whose OpenSSL is 3.5 (OpenSSL
3.5.0 was released 2025-04-08 with ML-KEM, ML-DSA and SLH-DSA in its default
provider), and both serve an RSA-2048 certificate, so only the key exchange of
a handshake is post-quantum:

| Image | Algorithm space | Use |
|---|---|---|
| `services/pqc-tls-demo/Dockerfile.oqs-provider` | OpenSSL 3.5 plus the pinned oqs-provider (`5fd81fb`), for TLS groups OpenSSL does not ship, such as `p384_mlkem768` and FrodoKEM; the build negotiates each of its groups before the image is accepted. The pinned provider exposes **no HQC group** (upstream re-enabled HQC after the pin) and **no Classic McEliece group** | Research. The pin predates four merged upstream fixes to key handling (a heap overflow, a double free, a use-after-free and missing length checks; listed in the Dockerfile header), so the lane is for a local handshake only |
| `services/pqc-tls-demo/Dockerfile.openssl35-native` | OpenSSL 3.5's own groups, the three ML-KEM hybrids of RFC 10024 (`X25519MLKEM768`, `SecP256r1MLKEM768`, `SecP384r1MLKEM1024`) | Research. These are OpenSSL's default-provider implementations, **not a FIPS-validated module**, and no FIPS provider is configured |

```bash
make pqc-tls-demo-both    # Builds both images; it starts nothing
```

There is no compose service for either image, so there is no `tls35` or
`tls-oqs` host to connect to.

> **Correction.** Earlier revisions of this section stated that a `PQC_PROVIDER`
> env selects which of these two lanes the WebUI "PQC Validator" page targets.
> **No such switch exists.** `PQC_PROVIDER` is a display-only constant in
> `services/webui-frontend/src/lib/sim/pqc.ts` recording the provenance of
> `@noble/post-quantum`; it labels the page and its exports and never selects anything.
> Neither TLS image is instantiated by any compose file, so there is no running
> lane to target. The claim is withdrawn rather than papered over, because RFC
> 7696 conformance was being asserted on the strength of it.
>
> What crypto agility this project actually has:
>
> * **IKEv2 proposals are env-driven and real** — `IKE_PROPOSALS` /
>   `ESP_PROPOSALS` in `docker-compose.strongswan.yml` are substituted into
>   `nodes/strongswan/swanctl.conf.tmpl`, so the KEM can be changed without
>   touching code. That is **parameter agility within one family**: the
>   post-quantum key exchanges the pinned strongSwan parses are `mlkem512`,
>   `mlkem768` and `mlkem1024`, all module-lattice. The lane's only
>   non-lattice input is the RFC 8784 PPK.
> * **The agility matrix runs a default set** — `POST /api/pqc/agility` on the
>   backend with an empty body, which is what `/verify` sends, runs ML-KEM
>   512/768/1024 and HQC-1/3/5, and ML-DSA 44/65/87 and SLH-DSA
>   SHA2-128s/128f/192s/256s, through liboqs; each half spans two families.
>   The validator's own routes (`/api/agility`, `/api/roundtrip`,
>   `services/pqc-validator/app/main.py`) take algorithm names, but the
>   validator publishes no port and is reached only through the backend.
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

**What the output does NOT say.** This paragraph used to read: *"Sample output
(after `make bench`): rosenpass-scalability experiment-summary.csv mean
handshake time is within ±15 % of the paper's 10.27 s @ 10 nodes."* Three
things are wrong with that, and they compound:

1. `tools/compare_to_paper.py` reads columns 0 and 1 of every CSV it finds. In
   `rosenpass-scalability/results/experiment-summary.csv` those columns are
   `peer_count` and `avg_cpu_percent`. **That file has no handshake-time column
   at all.** The reported `mean: 11.93` is a mean CPU *percentage*, compared
   against a *time in seconds*. Reproduce it: the column holds
   0.01, 3.19, 6.17, 15.56, 34.72, whose mean is exactly 11.93 and whose
   standard deviation is the 12.5236783733... the JSON prints.
2. The file's peer counts are 1, 500, 1000, 2500 and 5000. There is no 10-node
   row to compare against.
3. The tool's output (`paper_comparison.json`, gitignored and regenerated by
   the command above) records `"ours": {"n": 0}` -- our side of the
   comparison is empty, because `benchmarks/results/handshake_age.csv` has
   never been produced.

So the "±15 % agreement" was a numerical coincidence between two quantities in
different units, at a scale that is not in the data, against a measurement that
does not exist. `make bench` still runs and the JSON is still a useful index of
what the supplementary repository contains; it is not a validation.

### End-to-end browser verification (13 pages)

A dated record of the thirteen routes that existed when this check was last
written; `/protocol-lab` was added as route 14 on 2026-09-25 and is covered in
the 2026-09-25 section below. The current page inventory is
[`webui-pages.md`](webui-pages.md).

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
| 10 | `/pqc` | PQC Validator (@noble in-browser, liboqs interop cross-check) |
| 11 | `/verify` | Implementation Verification (crypto-agility matrix + TNO key-rate cross-check + paper budgets) |
| 12 | `/hil` | Hardware-In-The-Loop bridge instructions |
| 13 | `/vpn` | VPN Protocols (WireGuard ⟷ strongSwan) |

Verified in a browser: all 13 React Router paths render their correct headings,
the four simulation pages run client-side (no `/ws/*`), and console errors = 0.
- 0 console errors (only React Router v7 future-flag warnings, which are benign)
- `/api/*` proxy targets backend; pages with API dependencies show "Loading…" gracefully

The two lanes and the backend in front of them, as Phase 9 arranged them:

```
                ┌─────────────────────────────────────────────────────────┐
                │ WebUI 10 pages (Phase 9-WebUI)                          │
                │  Overview / BB84 / KeyFlow / Topology / Benchmarks      │
                │  Console / PhysicsParams / PQCValidator / HIL / VPN     │
                └──────────────┬──────────────────────────────────────────┘
                               │
                ┌──────────────▼──────────────────────────────────────────┐
                │  webui-backend (FastAPI)                                │
                │   /api/vpn/protocols      — both lanes' live status     │
                │   /api/vpn/ppk-rotations  — PPK rotation counts         │
                │   /api/pqc/{algorithms,roundtrip}                       │
                └──┬───────────────────────────────────────────────┬──────┘
                   │                                               │
        ┌──────────▼──────────┐                       ┌────────────▼─────────┐
        │ alice + bob (WG)    │                       │ alice-ipsec +        │
        │  arnika → wgctrl    │                       │ bob-ipsec (strongSwan)│
        │  Curve25519+Noise   │                       │ RFC 9370 hybrid IKE  │
        │  + PSK rotation     │                       │ ECP-256 + ML-KEM-768 │
        │  every 30 s         │                       │ + vici PPK injection │
        └──────────┬──────────┘                       └─────────┬────────────┘
                   │                                            │
                   └────────────── arnika HKDF(QKD‖PQC) ────────┘
                                              │
                ┌─────────────────────────────▼─────────────────────────────┐
                │ Phase 8: 7 QKD backends + paper supplementary             │
                │ ┌──────┬─────┬────────┬───────┬──────────┬──────────┬───┐│
                │ │qutip │simqn│sequence│cvqkd  │qkdnetsim │composite │tno││
                │ └──────┴─────┴────────┴───────┴──────────┴──────────┴───┘│
                │ precompute_keyrate_table_fallback.py (offline SKR table) │
                │ aparcar/qkd-pqc-paper-supplementary (Phase 9-B baseline) │
                └───────────────────────────────────────────────────────────┘
```

---

## Phase 10 — Quantum-Secure E2E live simulation page

Phase 10 adds a single **Quantum-Secure E2E** page (route `/e2e`, sidebar starred entry)
that drove a background simulation from Alice to Bob across the full 4-phase
Data Exchange depicted in the reference architecture image, with live buttons.

### What ran in the background (Phase 10; since deleted)

A coroutine-based backend state machine cycled through four phases. The table
records what it did then. Its client-side replacement,
`services/webui-frontend/src/lib/sim/e2eSim.ts`, does none of the network
steps below: it uses random surrogate keys, and a run makes no HTTP request
(exports aside) -- see
[`IMAGE1_VPN_SCOPE.md`](IMAGE1_VPN_SCOPE.md).

| Phase | Name | What the deleted orchestrator did |
|---|---|---|
| **1** | Quantum Plane | Poll `bb84-kme-a` `/api/v1/keys/ALICE/status` until SimQN backend produces a key |
| **2** | QKD Key IDs (ETSI 014) | `GET /enc_keys` from KME-A, mirror retrieval via `GET /dec_keys?key_ID=…` at KME-B (matched `submodules/arnika/repositories/kms.go:43-102` at the pin of the time; `repositories/kms/kms.go` since arnika #51) |
| **3** | PQC Handshake (HKDF-SHA3) | `HKDF-SHA3-256(qkd ‖ random_pqc, salt="pqcqkd-e2e", info=mode)` → 32 B PSK |
| **4** | Data Exchange (ChaCha20-Poly1305) | Encrypt 64 ping-sized payloads per cycle, count bytes and packets |

The mode set which phases ran: `A` ("QKD-only") skipped the PQC secret in
phase 3, `B` ("PQC-only") skipped the QKD key in phase 2, and `C`
("Hybrid (QKD ‖ PQC)", the default) used both.

Verified: 5 seconds @ default settings produces **~60 cycles, ~3 900 packets, ~280 KB
encrypted**, with rotating QKD key IDs and per-cycle PSK derivation.

### What the UI shows

`services/webui-frontend/src/pages/QuantumSecureE2E.tsx` renders, top-to-bottom:

1. **SVG architecture diagram** faithful to the reference image — Site A / Site B,
   ARNIKA (orange) · ROSENPASS (pink) · WIREGUARD (purple), KMS keystores
   (ETSI 014, green) at each edge. Active phase highlights the relevant elements
   with a coloured glow.
2. **Mode buttons A / B / C** — `A · QKD-only`, `B · PQC-only`, `C · Hybrid (QKD ‖ PQC)`.
3. **Control buttons** — Run / Pause / Resume / Reset / Step +
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
> orchestrators, and every route in the "REST + WebSocket surface" table
> that follows this note, have been deleted -- that table is a record of a
> surface the backend no longer serves, not a list of live endpoints. The
> paper budgets survive in
> `services/webui-backend/app/paper_budgets.py`, which is what
> `/api/verify/paper-budgets` now reads.


### REST + WebSocket surface (deleted -- historical record)

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

The initial SVG (880×280, ~30 elements) was rewritten to **1240×600 with 145 SVG
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

Screenshots were reviewed for this layout but not committed, and none are in the repository. Kept as a record of what was checked at the time, not as a pointer to an artefact.

---

## Phase 12 — Logger / shared UI / per-page exports

Three improvements that make the PoC easier to operate, inspect, and reproduce:

### 12-A: Rotating file logger

webui-backend and the two KMEs (bb84-kme-a, bb84-kme-b) log through
`services/<svc>/app/logging_setup.py`, calling `configure(<svc>)` at startup.
`pqc-validator` has no such module and logs to stdout only. Output is
duplicated to:

- stdout — keeps `docker logs <svc>` behaviour intact
- **`/var/log/pqcqkd/<svc>.log`** — `RotatingFileHandler`, 10 MB × 5 backups, mounted
  as the shared `pqcqkd-logs` volume

Two REST endpoints, backed by `list_log_files()` and `read_tail()`, expose the
files to the browser:

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

Seven reusable building blocks were added under
`services/webui-frontend/src/components/` so individual pages stop re-implementing
their own button / panel / row / badge / KPI (`Badge` and `Row` have since been
removed from that directory):

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
| **Logs** | Save the page's client-side run log (`logProvider`) as `.log`; on `/` and `/benchmarks`, which pass `logService` instead, download the server log from `/api/logs/download/<service>` |
| **PNG** | High-DPI (2×) PNG — SVG diagrams via XMLSerializer→Canvas at 2× scale; other pages via `html-to-image` `pixelRatio: 2` |
| **JSON** | Serialise the page's snapshot from `jsonProvider()` |
| **CSV** | Serialise tabular data from `csvProvider()` |
| **WebM (HQ)** | High-quality animation — records for a user-selected duration (default 10 s) via `MediaRecorder` + `canvas.captureStream` (VP9/VP8 WebM, no 256-colour limit) |
| **GIF** | Animated GIF (universally compatible) — full-resolution frames. Now encoded with `modern-gif`; `gifshot` was replaced after it went unmaintained. |

Every download except that server log is produced client-side (`Blob` +
`URL.createObjectURL`); **no server-side generation is required**. A copy is
saved to the backend, where the Saved-exports picker can list it for
re-download, only when the visitor ticks "copy to shared gallery", which is
off by default.
`lib/exporters.ts` loads `html-to-image` and the GIF encoder only when an export
needs them.

### Browser verification

- At Phase 12 the `/e2e` export toolbar exposed Logs, PNG, JSON, WebM (HQ), GIF
  and the Saved-exports picker; verified PNG = 2480×1200 (2×), GIF = 1240×600
  (full-res), WebM = valid VP9 video
- Pressing Logs then downloaded the server log: a `text/plain` blob of 388 B
  (matches the file size on disk). `/e2e` now passes `logProvider`, so its Logs
  button saves the client-side run log instead
- Pressing JSON produces an `application/json` blob of 308 B
- `/api/logs/files` returns the three rotating log files actually written under
  `/var/log/pqcqkd/` (verified inside the container)
- **0 console errors**
- Toolbar layout reviewed on screen; the capture was not committed

---

## Phase 14 — Paper Data Exchange page + /e2e SVG polish + Rust ETSI 014 KME

Phase 14 introduces a brand-new page that implements the *paper-faithful* Data
Exchange (vs the single-tunnel concept on `/e2e`), polishes the existing E2E
SVG layout, and adds a third independent ETSI 014 KME (Rust) as 2026-active
OSS reference.

### A new page: `/paper-flow` — Paper Data Exchange

Route: `/paper-flow` (sidebar entry "Paper Data Exchange " right after the
existing "Quantum-Secure E2E "). The page is intentionally distinct from
`/e2e`; [`IMAGE2_MULTIHOP.md`](IMAGE2_MULTIHOP.md) maps its figure to the
code:

| | `/e2e` (image 1) | `/paper-flow` (image 2 + arXiv:2604.05599) |
|---|---|---|
| Source figure | `arnika-project/arnika` single-tunnel diagram | **Multi-hop trusted-node diagram** (End Node Alice \| Trusted Node × N \| End Node Bob) |
| Focus | key fusion in one Site A ↔ Site B tunnel | **5-phase daisy chain** with paper-quoted packet budgets |
| Failure model | Eve attack on BB84 | **240-720 s layer cascade** per 4.3 Fail-Safe Mechanism (empirical: Test 5) |
| Data Exchange | conceptual ChaCha20 over derived PSK | live `ChaCha20-Poly1305` payload per cycle, packet/byte counters track paper, Evaluation Test 1, Table 1 |

Backend orchestrator (deleted; now `services/webui-frontend/src/lib/sim/paperSim.ts`):
- 5-phase state machine: **Quantum Plane → Arnika QKD key_ID → WG hop handshake → Rosenpass PQC handshake → Final data tunnel**
- Paper budgets embedded as the source of truth (`PHASE_BUDGETS` constant):
  Phase 2 = 2 pkt / 78 B; Phase 3 = 3 pkt / 398 B; Phase 4 = 4 pkt / 4772 B;
  **total handshake = 9 pkt / 5248 B**
- Failure cascade scheduler with 7 stages (0/180/240/360/420/540/720 s)
- WebSocket `/ws/paper-flow` at ~4 Hz
- REST: `/api/paper-flow/{state,start,pause,resume,reset,config,inject-failure,clear-failure}`

> **Superseded.** The `/e2e` and `/paper-flow` pages moved to client-side
> simulation (`services/webui-frontend/src/lib/sim/e2eSim.ts` and
> `paperSim.ts`); the frontend opens no WebSocket at all. The backend
> orchestrators and every REST/WebSocket route listed above -- the
> `/ws/paper-flow` and `/api/paper-flow/*` bullets included -- have been
> deleted. The paper budgets survive in
> `services/webui-backend/app/paper_budgets.py`, which is what
> `/api/verify/paper-budgets` now reads.

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
145 and viewBox `1240×600` are preserved (`GEO` in `QuantumSecureE2E.tsx` has
`W: 1240, H: 600`; its `divider: 620` is the centre line's x coordinate, not a
height):

| Element | Before | After |
|---|---|---|
| KMS→ARNIKA `QKD KEY` label | y=232 (collided with ARNIKA tag y=238) | **y=208** (clear above box) |
| ARNIKA→KMS `key_ID` label | y=278 (10 px below box) | **y=288** (20 px below box) |
| Center `VPN tunnel (ChaCha20-Poly1305)` label | y=206 (touching WIREGUARD title y=220) | **y=174** (just under Site A/B headings) |
| HKDF SHA3 badge inside ARNIKA | x=244 (mid-box, over title text) | **x=222** (top-left corner of box) |

Browser verification confirmed the four labels render at the new
coordinates: `QKD KEY y=[208,208], key_ID y=[288,288], VPN tunnel y=174`.

### Rust ETSI 014 KME (vendored, not built)

`submodules/qkd_kme_server` is now part of the repo —
[`thomasarmel/qkd_kme_server`](https://github.com/thomasarmel/qkd_kme_server)
with its most recent commit on **2026-04-01**, Rust + ETSI GS QKD 014 v1.1.1
compliant.

At most **two** ETSI 014 servers run in this repository, not three.
`services/qkdnetsim-kme` is `kme_facade.py`, a Flask app minting
`secrets.token_bytes`; no NS-3 binary is invoked. It is a genuine second
implementation of the REST contract -- it is just Python, and it is not NS-3
-- and it runs only under the `crossvalidate` overlay, which neither CI nor the
Makefile starts and which publishes no host port. The Rust server is vendored
and not yet wired into any compose profile.

| Implementation | Language | Phase | Runs here? |
|---|---|---|---|
| `services/bb84-kme` (this repo) | Python + SimQN | 1 | yes |
| `services/qkdnetsim-kme` (`kme_facade.py`) | Python (Flask) | 9 | only under the `crossvalidate` overlay -- a facade over the contract, NOT the NS-3 C++ KMS |
| `submodules/qkd_kme_server` | Rust | 14 | no -- vendored, in no compose profile |

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


## 2026-09-25 — Log redaction, Protocol Lab, ETSI GS QKD 004 on the KME

One batch (PR #130, `d3d2e74`), deployed the same day, then a follow-up for
three defects the browser pass found.

### What went in

- **`/api/logs` stops serving key material.** The pinned arnika prints
  `Arnika PSK: <value>` at startup; the route returned container logs
  unredacted and with no cap on `tail`. It now redacts secret lines and caps
  `tail` at 2000. `ARNIKA_PSK` was rotated at deploy, since redaction does not
  un-serve what was already served.
- **Dependencies**: fastapi 0.141.1 / starlette 1.7.0, liboqs-python
  0.16.0.1, plotly.js 4.1.1 (send-to-cloud off), react-router-dom 6.30.6,
  vite 6.4.3. nginx serves `index.html` `no-cache` and hashed assets
  immutable.
- **`/protocol-lab`** (route 14), a client-side simulation over five published
  networks, and the **ETSI GS QKD 004 V2.1.1 endpoint** in `bb84-kme` over this
  project's own HTTP binding, off by default -- see
  [`etsi004-binding.md`](etsi004-binding.md).
- `.dockerignore` for every build context: a host `__pycache__` had put
  bytecode older than its source into the KME image.

### Deploy (2026-09-25)

- The four rebuilt images passed their build-time checks
  (`web stack OK: starlette 1.7.0`, `etsi004 spec V2.1.1 22 transitions`,
  `liboqs 0.16.0 / liboqs-python 0.16.0.1`).
- `ARNIKA_PSK` was rotated, and both lanes re-established on the new value:
  `PSK configured` on alice (PRIMARY) and bob (BACKUP), and the IPsec lane
  `.../KE1_ML_KEM_768/PPK` with `ppk_required` and `ppk_used` on both ends and
  paired SPIs.

### Browser verification (Chrome, deployed build)

- The loaded bundle was the local build's; `index.html` is served `no-cache`
  and hashed assets `public, max-age=31536000, immutable`.
- **14/14 routes** render with no error boundary and no failure banner;
  control inventory in checklist row 4.6.18b.
- `GET /api/logs/alice?tail=200000` -> **422**; `?tail=2000` -> 200 with
  `Arnika PSK: (redacted)` on alice, bob, alice-ipsec and bob-ipsec; the
  download route carries no PSK line.
- `/vpn`: established, `/PPK`, ESP counters **non-zero without a manual
  ping** (336 B / 4 pkt, later 168 B / 2 pkt after a reauthentication
  installed a new CHILD_SA) -- the new healthcheck ping. The lane
  reauthenticates on every PPK rotation and does not rekey, which is the
  distinction RFC 8784 and checklist row 2.4 depend on.
- `/protocol-lab`: Run / Pause / Resume / Step (from idle and paused) / Reset
  change the state as labelled; failing CAPE-TREL moves the TREL-CAPE demand to
  two hops via ENGI with one route change; all five presets and the SECOQC
  replay load; Logs, PNG, JSON, CSV and WebM export valid files.
- `/e2e` and `/paper-flow`: same controls; `/e2e` Abort shows
  `status: idle (aborted)`.

### Found by the browser pass, fixed in the follow-up

- **Every exported GIF had zero frames.** 801 bytes -- header, colour table,
  loop extension, no image. modern-gif's `encode({frames})` does not await
  frames given as URLs, and every frame here is a data URL. `encodeGifFrames`
  now awaits each one; a local build exported 13 frames for 3 s at 4 fps.
  This predates the batch (modern-gif 2.1.0 on both sides of it) and no
  earlier check had parsed the file.
- **A page opened in a background tab never loaded.** `usePoll` skipped its
  first call while the tab was hidden, so `/physics` sat on
  `Loading parameters...`. It now always loads once on mount.
- **`Requests ok / failed` read `0 / 0` in stores accounting**, where requests
  are not counted at all. It now says `not counted (stores accounting)`.

---

## 2026-09-26 — Public-demo hardening and a full audit pass

A read-only audit of every document, page, pinned dependency and cited source
found 329 defects (32 HIGH). This batch corrects most of them, starting with
the ones a visitor to the public demo could exploit; the rest are in the
dated deferred table in [`roadmap.md`](roadmap.md).

### What went in

- **Live KME overrides are opt-in.** Any anonymous visitor could change the
  simulator backend and the parameter set of both KMEs, which feed both live VPN
  lanes. `POST /api/sim/params`, `/api/sim/params/reset` and `/api/sim/backend`
  now answer 403 unless `ENABLE_LIVE_PARAM_OVERRIDES` is true (default false;
  a route dependency, so a bodyless POST is refused the same way).
  `/physics` applies edits to an in-browser model and says so. A switch to a
  backend that needs `qkdnetsim-kme` is refused with 503 when that service is
  not deployed, instead of starving both KMEs.
- **Docker-backed routes take an allow-list.** `/api/logs/{name}` serves the
  six containers `/console` shows and `/api/wg/{node}` the two WireGuard nodes;
  anything else is 404 before Docker is asked.
- **`/api/pqc/agility` is bounded** to the validator's own algorithm lists
  (422 otherwise). The matrix now spans two KEM families (ML-KEM, HQC) and two
  signature families (ML-DSA, SLH-DSA); every signature row reports whether a
  tampered message is rejected, and `/verify` requires it.
- **Exports are local first**; a copy to the shared gallery is opt-in, and the
  store is bounded per file, by count and in total.
- **`/paper-flow` follows the paper.** The failure cascade follows Test 5 (nine
  stages), every grace window is the 60 s of 4.3 (two read 180 s), and the page
  names the paper's stages (1)-(4) beside its own five phases -- the paper does
  not use the word "phase".
- **`/physics` field reference** compares the measured QBERs with the
  finite-key model's tolerance at the shipped block size and at a large block,
  not with a different closed form.
- **Dependencies**: `react-router-dom` 7.18.4 (retires two moderate advisories
  that affect all of v6), the archived and unused PQClean submodule removed,
  the unusable boringtun overlay removed, the oqs-provider TLS image fixed (it
  never contained `oqsprovider.so`). CI actions moved to their current majors
  and `runs-on` is pinned to `ubuntu-24.04`.
- **`qkdnetsim-kme` builds again.** Its NS-3 compile had stopped at
  `'FILLEDCURVE' is not a member of 'ns3::Gnuplot2dDataset'`: qkdnetsim's own
  installation steps patch NS-3's gnuplot module first, and the Dockerfile did
  not. Built and started by hand on 2026-09-26; CI still does not build this
  image, which only the `crossvalidate` overlay uses.
- **Published-text scan**: commit messages and pull-request text are checked
  with the same matchers as the tree, private names by digest only.
- **Documents**: `ARCHITECTURE.md`'s phase history moved here; corrections to
  the threat model, notices, references and limitations; the checklist is 290
  rows.

### Deploy (2026-09-26)

The pull-request branch was deployed before merging, so the deployed build
could be measured and the results recorded in the same change. The rebuilt
images were `webui-frontend`, `webui-backend`, `bb84-kme` (both KMEs),
`pqc-validator` and the two WireGuard nodes; Caddy was restarted to read the
new Caddyfile. No `ARNIKA_PSK` rotation was needed: nothing in this batch
exposed it.

The ten minutes after the KME restart showed four authentication failures per
end on the IPsec lane (20 rotations, 16 applied). A restarted KME's pool starts
empty, which would leave a key id handed over just before the restart
unresolvable; that is the likely cause, not a measured one. The next window
had 20 rotations, 20 applied and none failed.

### Browser verification (deployed build)

Every row the checklist marked pending on the deployed build is now measured
and dated 2026-09-26 in place: all 14 routes (0 unlabelled controls, 0 Japanese
text), the Protocol Lab rows 4.4c.1-16, the 10 s WebM and GIF exports on
`/e2e`, `/paper-flow` and `/protocol-lab` (rows 4.5.7 and 4.5.8), the rate
limiter (121 x 403, then 19 x 429), log redaction and the allow-lists, and the
cache headers. `/physics` applied an edit in the browser with no request to the
server, and its backend buttons were disabled with the reason. `/verify` passed
13 of 13 liboqs rows, every signature row with the tampered message rejected.

Three things the pass found were corrected in the same change: the HQC rows'
hardness assumption read `not recorded`, Thuringia's keystore hop was called
`not a QKD link` in the model column, and the `/vpn` WireGuard card still named
boringtun.

---

## 2026-09-26 — arnika #51 adopted and the WireGuard lane layered as in the paper (release 0.2.0)

The first change after the `v0.1.0` tag, to be released as 0.2.0 (see
[`../CHANGELOG.md`](../CHANGELOG.md)); the `v0.2.0` tag and its date are set
after the merge. It moves `submodules/arnika` from
`3a8cc13` to `f4cf9ba`, the head of the open, unmerged arnika PR #51 (dated
2026-09-24), because that PR removes the file handover this project's PQC half
depended on (`PQC_PSK_FILE`) and replaces it with PQC-HPKE, a key agreement
between the arnika peers themselves. The pin is re-pinned to the merge commit
once #51 merges ([`roadmap.md`](roadmap.md), "Follow-ups from adopting arnika
#51").

### What went in

- **PQC-HPKE on every arnika instance.** HPKE in Base mode (RFC 9180) with the
  KEM MLKEM1024-P384 (a hybrid of ML-KEM-1024 and P-384 ECDH, codepoint 0x0051
  of draft-ietf-hpke-pq, not yet an RFC), HKDF-SHA384 and an export-only AEAD,
  run over the UDP socket the two peers already share. Every instance -- alice
  and bob, alice-ipsec and bob-ipsec, and charlie in the multi-hop overlay --
  runs `PQC_ENABLED=true` with `QkdAndPqcRequired` and the unchanged 30 s
  interval, and both peers of each pair use the same values. `PQC_PSK_FILE` and
  the `pqc-psk-*` volumes are gone. The entrypoints refuse an `ARNIKA_PSK`
  shorter than 32 bytes or equal to the `.env.example` placeholder, and arnika
  logs at `info`. `CAP_IPC_LOCK` is not granted
  ([`LIMITATIONS.md`](LIMITATIONS.md)).
- **The WireGuard lane follows the paper's layering** (arXiv:2604.05599, 4.2).
  Each of alice and bob runs `wg0`, the hop tunnel keyed by arnika with
  HKDF-SHA3-256 over the QKD key and the PQC-HPKE key, and `wg1`, the
  end-to-end data tunnel (`10.0.1.1`/`10.0.1.2` by default), whose peer
  endpoint is the other node's `wg0` address. Rosenpass (Classic McEliece
  460896 + Kyber512) exchanges between the two `wg0` addresses on UDP 9997,
  the lower address initiating and the other only answering, and writes
  `wg1`'s preshared key through its own WireGuard output; it no longer feeds
  arnika. Every `wg0` and `wg1` peer starts with a random placeholder PSK, so
  a completed handshake, not a `preshared key` line, is the evidence that a
  daemon keyed it. The multi-hop overlay's charlie leg gets both layers too.
  `GET /api/wg/{node}` reports `wg0` as before and `wg1` under `data_tunnel`,
  each with a `psk_source`.
- **Start alignment, WireGuard lane only.** The WireGuard entrypoint starts
  arnika at the next wall-clock multiple of `ARNIKA_INTERVAL`, so the two
  processes of a pair start counting their intervals in step, as they did
  while arnika waited for the first Rosenpass key. Without it, in three
  short local WireGuard runs, the later-started node failed closed at the end
  of 13 of its 21 BACKUP intervals (an observation, not a measurement). The
  IPsec entrypoint deliberately starts arnika as at v0.1.0, because the
  before/after measurement compares that lane and both arms run the same
  entrypoint start behaviour; the start offset itself is measured in each
  arm. The two nodes of a pair are recreated together, and the alignment
  holds only at the start: the offset between the two tickers drifts
  afterwards (in one unaligned local IPsec run of about 6 minutes, from
  about 255 ms to about 217 ms over 12 intervals). From reading the code, a
  BACKUP whose boundary lags the PRIMARY's by more than the PRIMARY's KMS
  fetch time can count an early `key_id` in its previous interval, and it
  then fails closed at the end of the current interval unless the next
  `key_id` is early too, in practice where it goes from BACKUP to PRIMARY; in
  that run the later node received early `key_id`s in intervals 2 to 8, 10
  and 11 and invalidated only at 8 and 11. That is an inference and one short run, not a measurement
  ([`BUILD.md`](BUILD.md#73-starting-arnika-on-the-interval-boundary)). It is
  not a mitigation of the IPsec lane's PPK ordering race.
- **The IPsec lane runs without Rosenpass.** Its PPK is arnika's
  HKDF-SHA3-256 over the QKD key and the PQC-HPKE key, in IKEv2 with
  ML-KEM-768 (RFC 9370) as before. The VICI adapter moved to upstream's
  one-method key-writer port (`SetPSK(psk []byte) error`) as the package
  `repositories/swanvici`, wired by `wire_strongswan_vici.go`; the text of its
  log lines is unchanged, which the WebUI's rotation counter depends on.
- **Documents.** Every statement about the live lanes; the SP 800-227 analysis
  of the new PQC input, which is not called approved
  ([`vici-ppk.md`](vici-ppk.md#appendix-sp-800-227-and-this-projects-key-combiner));
  what commit `3e02741` is expected to do to the IPsec lane's rotation race,
  from reading the code; strongSwan 6.1.0 recorded as a security floor
  (CVE-2026-78133); ANSSI's IPsec sheet (ANSSI-FT-117) added to the threat
  model's survey; RFC 9881, the revised Weis preprint, draft-ietf-tls-mlkem-11
  and the D6.1 site distance brought up to date; `CITATION.cff` and
  `CHANGELOG.md` added. The paper content (`/paper-flow`,
  [`IMAGE2_MULTIHOP.md`](IMAGE2_MULTIHOP.md)) is unchanged.

### Not established by this change

- **Nothing here says `3e02741` fixes the intermittent PPK mismatch.** Reading
  the code, it is expected to move the exposed intervals from alice-PRIMARY to
  alice-BACKUP; that is unmeasured. A 168-hour before/after measurement is
  planned
  ([`vici-ppk.md`](vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race)).
- The builds, the live lanes on the new pin and the measurement are recorded
  in their own dated entries when they run, not here.

---

## 2026-09-26 — Responsive shell: the WebUI on a phone (release 0.2.0)

Also part of the unreleased 0.2.0 (see [`../CHANGELOG.md`](../CHANGELOG.md)).
Until this change the shell kept its 220 px sidebar at every width, so on a
phone each page was laid out in what the sidebar left.

### Measured before

On the build before this change, at a 375 x 812 viewport (2026-09-26, method
under "Verification" below): `<main>` was 155 px wide and 13 of the 14 routes
scrolled sideways, by 48 px (`/keyflow`) to 394 px (`/physics`); only
`/topology` fit. `/vpn` also squeezed ten text elements into columns narrower
than 24 px, one or two characters per line. At 768 and 1280 px no route
overflowed, with `<main>` 548 and 1060 px wide.

### What went in

- **One breakpoint.** `NARROW_LAYOUT_MAX_PX = 767` in
  `services/webui-frontend/src/lib/layout.ts` is the widest viewport, in CSS
  px, that gets the collapsed layout, so a 768 px tablet keeps the sidebar,
  which measured overflow-free. `NARROW_LAYOUT_QUERY` is built from it, and
  pages read it only through `useNarrowLayout()`: `src/lib/layout.test.ts`
  fails if any other source file calls `matchMedia` or writes a width media
  query, so no page can carry a second breakpoint a few pixels away from this
  one.
- **What collapses at 767 px and below.**
  - The sidebar becomes a top bar with a button named **Menu**
    (`aria-expanded`, `aria-controls="site-nav"`) that shows or hides a panel
    holding the same 14 links and the same attribution. Opening it moves focus
    to the first link; Escape closes it and returns focus to the button; a
    press outside it closes it; following a link closes it and leaves focus on
    `<main>`. Crossing the breakpoint with focus on a shell control moves focus
    to that control's counterpart in the other layout. The dismissal and focus
    rules are in `src/lib/disclosure.ts`.
  - `<main>` gets a 16 px gutter (`NARROW_MAIN_PADDING`) instead of its 2rem
    side padding.
  - Panel grids go to one column (`narrowColumns`, a `minmax(0, 1fr)` track
    that may shrink below its content's width), and a key/value row on `/vpn`
    or `/e2e` may put its value on the line below its label.
  - A wide table, a `<pre>` or the Key Flow Sankey scrolls inside its own box.
    The Sankey, the wide tables and one `/vpn` `<pre>` sit in a `ScrollRegion`
    (next item); the other `<pre>` blocks scroll inside themselves. The
    Topology graph is cropped to its drawing.
- **A box that scrolls sideways is a named Tab stop, at any width.**
  `ScrollRegion` (`src/components/ScrollRegion.tsx`) follows its content, not
  the viewport. While the content is wider than the box by more than
  `SUBPIXEL_OVERFLOW_PX` (1 CSS px of rounding), the box is `role="region"`
  with `tabIndex={0}` and its required `aria-label`, so the keyboard can reach
  it and the arrow keys scroll it. While the content fits, it is a plain div
  and adds no Tab stop. A `ResizeObserver` on the box and its first element
  child, and a `MutationObserver` on the box's own child list (not its
  subtree), make the decision again when either changes. The attributes take
  no space, so adding or removing them does not change the widths the
  decision is made from. From 768 px up the `/vpn` notes `<pre>` scrolls
  itself and takes the same attributes through the same hook
  (`useScrollsSideways`), and so does the `/keyflow` `kdf.go` snippet, a
  `<pre>` whose 448 px longest line scrolls in its box at 320 to 414 px. Below 768 px a visible line under the Key Flow chart
  says that it scrolls sideways, and the region points to it with
  `aria-describedby`. At every width the chart's own div clips what Plotly
  draws (`overflow-x: clip`), so a hover label near the chart's right edge
  cannot make the box scroll. If a box has keyboard focus when its content
  stops being wider, for example because the window widened, its Tab stop is
  removed while it is focused, and the browser decides where focus goes
  (Chrome puts it on `<body>`).
- **Two deliberate changes at 768 px and up.** Everything else either switches
  on `useNarrowLayout()` or does not change the layout from 768 px up. These
  two are fixes that show there, and both leave 1280 px as it was:
  - **The saved-exports list is kept on screen at 768 px**
    (`SavedExportsPicker`). Opened on `/pqc`, it hung right-aligned under its
    button and started 16 px left of the viewport, where no scrolling reaches;
    it now spans 16 to 394 px. At 1280 px, where it already fitted, it spans
    436 to 814 px before and after.
  - **The `/e2e` controls row wraps at 768 px.** With a run in progress the
    row did not fit on one line: its status badge ended at 814 px and the page
    scrolled sideways by 46 px. It now measures 0. At 1024 and 1280 px the
    page measured 0 during a run before and after.

  The `ScrollRegion` rule also applies from 768 px up, but it changes the Tab
  order and the accessibility tree, not the layout: a box whose content is
  wider than it there carries a role, a Tab stop and a name. With idle data
  that is the `/protocol-lab` links table and the `/vpn` notes at 768 px, and
  none at 1280 px; the `/e2e` step history becomes one while a run is going
  (under "Verification").

### Verification (local stack, 2026-09-26)

The figures here and under "Measured before" come from scripts that drive
headless Chrome 152 over the DevTools protocol against a local stack. For each
route at each emulated device width, with mobile emulation below 768 px, it
loads the route, waits for it to settle and compares
`document.documentElement.scrollWidth` with the emulated device width. It
compares with the device width and not with `innerWidth`, because under mobile
emulation the layout viewport grows to the content's width: before this change
`/` gave an `innerWidth` of 650 at a 375 px device width, equal to its
`scrollWidth`, so `scrollWidth > innerWidth` was false on a page that scrolled
by 275 px. It also counts text squeezed to one or two characters per line and
controls without an accessible name. The scripts are scratch tools and are not
in the repository; checklist row 4.2.8b of
[`../VERIFICATION_CHECKLIST.md`](../VERIFICATION_CHECKLIST.md) is the manual
equivalent. Unless a bullet says otherwise, the backend was idle: no `/e2e` run
was going.

- **0 px of sideways scroll on all 14 routes at nine widths**: 320, 375, 414,
  600, 700, 767, 768, 1024 and 1280 px, 126 route-widths, with no text one or
  two characters per line and no control without an accessible name. Also 0
  on all 14 at 375 px with the menu open, and at 380 px. From 320 to 767 px
  the Menu button shows and `<main>` is as wide as the viewport; at 768, 1024
  and 1280 px the 220 px sidebar shows and `<main>` is 548, 804 and 1060 px.
  This sweep ran before the `ScrollRegion` rule above took its final form.
  That last change touched only the seven routes that use it (`/`, `/keyflow`,
  `/vpn`, `/verify`, `/protocol-lab`, `/paper-flow` and `/e2e`). After it,
  those seven measured 0 px again at 320, 375, 768 and 1280 px, with no
  squeezed text and no unnamed control, and with `<main>` 320, 375, 548 and
  1060 px wide.
- **Menu, at 375 x 812**: opening it showed the 14 links with focus on
  Overview, Escape put focus back on the button, and a tap on a menu link and
  Enter on one both left focus on `<main>`. The open panel filled the viewport
  below the bar (756 px), so the press outside it was tried at 430 x 932, where
  it ended at 852.5 px and a press in the 79.5 px below it closed it. Crossing
  from 1280 to 375 px with focus on the sidebar's `/verify` link left focus on
  the Menu button, and crossing back from the menu's `/hil` link left it on the
  sidebar's `/hil` link. At 768 and 1280 px the shell grid was `220px 548px`
  and `220px 1060px`, with no Menu button.
- **`ScrollRegion`, one box on each of the seven routes** (figures are the
  box's `scrollWidth`/`clientWidth` in px). On every route and at every width
  measured, a box was a named region with `tabindex="0"` exactly when its
  content was more than 1 px wider than it. At 375 x 812 the regions were
  `/keyflow` (800/343), `/vpn` (574/313) and `/protocol-lab` (800/318); `/`
  (343/343), `/e2e` (317/317), `/paper-flow` (318/318) and `/verify`
  (318/318) fit and were plain divs. At 320 x 568 `/paper-flow` (280/263) and
  `/verify` (315/263) were regions too, and `/` (288/288) and `/e2e`
  (262/262) were plain. At 768 px the regions were `/protocol-lab` (490/459)
  and the `/vpn` `<pre>` (570/454), and at 1280 px there were none. Tab from
  the page reached each region and showed its focus ring, and focusing it
  moved or resized no element in `<main>`. No box changed its attributes over
  4 s while the page polled. At 320 and 375 px the `/keyflow` region's
  description was the visible line `Scroll sideways to see the whole flow.`.
- **The decision follows a resize both ways.** One page resized through 375,
  768, 1280, 768, 320, 1280 and 375 px read: on `/keyflow` region, plain,
  plain, plain, region, plain, region; on `/protocol-lab` and `/vpn` region,
  region, plain, region, region, plain, region; on `/verify` plain except at
  320 px.
- **Hovering the Key Flow chart changes nothing.** Pointer sweeps of 800, 384
  and 272 moves over the chart at 1280, 768 and 375 px changed the box's
  attributes 0 times, and its `scrollWidth` stayed 996, 484 and 800 px.
- **With an `/e2e` run going**, the step-history table held 8 rows and was
  505.7 px wide. Its box became a region at 320, 375, 768 and 800 px (boxes of
  262, 317, 458 and 490 px) and stayed plain at 816 px, where the box is
  506 px. At all five widths it was plain before the run. Tab from the top of
  the page reached it, and ArrowRight scrolled it, by 40 px, or by 16 px at
  800 px, which is all the overflow there is.
- **From 768 px up, compared with the build before** (both served locally, at
  768 and 1280 px, on the seven routes). Every heading, table, `<pre>`,
  top-level `<svg>`, canvas, button, input, select and bordered box outside
  Plotly's plot area and toolbar had the same position and size, except on
  `/e2e` at 768 px: the controls row (the deliberate change above) made that
  page 20 px taller and moved what is below it down. Screenshots taken in one
  5200 px tall viewport were pixel-identical on `/keyflow`, `/verify` and
  `/paper-flow` at both widths and on `/` at 1280 px. On `/vpn` and
  `/protocol-lab` at both widths, and on `/` at 768 px, they differed, while
  every element box matched.
- **Key/value rows** (checklist row 4.8.9): no value that starts on its label's
  line abutted it, on `/`, `/vpn`, `/e2e` or `/protocol-lab` at 320, 375, 768
  or 1280 px.
- `npx vitest run src/lib/layout.test.ts src/lib/disclosure.test.ts
  src/pages/theLayoutDoesNotScrollSideways.test.ts OnAPhone FitsAPhone
  NarrowScreen OwnBox StayOnScreen WhileItScrolls` -> 19 files, 291 tests
  pass. They read source and rendered markup and do not measure geometry.
  `src/components/scrollRegionIsReachableWhileItScrolls.test.ts` drives the
  decision with fake observers, and checks that each of the seven
  `<ScrollRegion>` uses has a non-empty label.

### Not established by this change

- The element-by-element comparison with the build before covered the seven
  routes that use `ScrollRegion`, at 768 and 1280 px only. On the other seven
  routes, and at the widths between, this compared sideways scroll and
  `<main>`'s width, not the position of every element. It did not look inside
  Plotly's plot area or inside an SVG drawing.
- What the differing pixels show, on `/vpn` and `/protocol-lab` at 768 and
  1280 px and on `/` at 768 px. Their element boxes matched, and these pages
  draw live values, but this did not tell a changed value apart from a changed
  rendering.
- Data other than an idle backend and one `/e2e` run, such as error states or
  an empty backend.
- Any browser other than headless Chrome 152 with mobile emulation: no Safari,
  no Firefox and no real touch device. The menu was opened by scripted input.
- What a screen reader announces. Region names and the Key Flow description
  were read from the DOM, not heard.
- Nothing here was measured on the deployed demo; it is a local build.

---
