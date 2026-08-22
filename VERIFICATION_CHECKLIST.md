# Verification checklist

What must be checked before a release, and how. Automated items are gated by
[CI](.github/workflows/ci.yml); the browser items are manual because they check
things a headless assertion does not: layout, legibility, and whether a control
does what its label says.

Order: **local build → local browser → PR + CI → demo redeploy → demo browser**.

---

## 1. Build and unit gates (automated)

| # | Check | How | Gate |
|---|---|---|---|
| 1.1 | Python lint clean | `make lint` | CI `python` |
| 1.2 | Unit tests pass | `make test` | CI `python` |
| 1.3 | Frontend typechecks | `npm run typecheck` in `services/webui-frontend` | CI `frontend` |
| 1.4 | Frontend builds | `npx vite build` | CI `frontend` |
| 1.5 | VICI adapter builds against pinned arnika | `sh services/arnika-vici/build.sh submodules/arnika services/arnika-vici /tmp/arnika` | CI `go` |
| 1.6 | VICI adapter tests pass | `go test ./repositories/...` | CI `go` |
| 1.7 | No secrets in history | `gitleaks detect` | CI `secrets` |
| 1.8 | Both node images build | `docker build -f nodes/{strongswan,alice}/Dockerfile .` | CI `images` |
| 1.9 | Key-rate model matches published values | `pytest tests/test_keyrate_golden_vector.py` | CI `keyrate` |
| 1.10 | Browser port matches backend model | `pytest tests/test_keyrate_ports_agree.py` | CI `keyrate` |
| 1.11 | ETSI 014 contract holds | `pytest tests/test_etsi014_contract.py` with a live stack | CI `live-stack` |
| 1.12 | A seeded round is reproducible | `pytest tests/test_bb84_simulator.py::test_seeded_round_is_reproducible` | CI `python` |
| 1.13 | Eve's intercept-resend drives QBER to 0.25 (mean over seeds, not one draw) | `pytest tests/test_bb84_simulator.py` | CI `python` |
| 1.14 | Optimiser SKR agrees with the shared rate model | `pytest tests/test_backend_cross_qber.py` | CI `python` |
| 1.15 | Backend QBER matches the analytical Lo-Ma value | `pytest tests/test_backend_cross_qber.py` | CI `python` |

---

## 2. IPsec lane (manual — needs privileged containers)

`make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.strongswan.yml" --profile ipsec`

| # | Check | Command | Expected |
|---|---|---|---|
| 2.1 | ML-KEM is available to charon | `docker exec alice-ipsec swanctl --list-algs \| grep ML_KEM` | `ML_KEM_768[openssl]` or `[ml]` |
| 2.2 | Connection loads (proposal parses) | `docker exec alice-ipsec swanctl --list-conns` | `loaded connection 'pqcqkd-vpn'` |
| 2.3 | PPK is configured and required | same output | `ppk: ppk-qkd@pqcqkd.local, required` |
| 2.4 | Reauth, not rekey | same output | initiator: `reauthentication every 300s, no rekeying`; responder: no reauthentication |
| 2.5 | Traffic selectors are the real hosts | same output | `10.30.0.20/32` ↔ `10.30.0.21/32` |
| 2.6 | SA establishes with ML-KEM | `docker exec alice-ipsec swanctl --list-sas` | `ESTABLISHED`, proposal contains `ML_KEM_768` |
| 2.7 | IKE_INTERMEDIATE actually runs | `docker logs alice-ipsec \| grep -i intermediate` | at least one exchange |
| 2.8 | **Both peers derive the same PPK** | `docker logs {alice,bob}-ipsec \| grep -cE 'AUTH_FAILED\|no PPK found'` after several rotations | `0` on both. Comparing `--list-conns` cannot show this: it prints the *configured* `ppk_id`, which is static and identical by construction, and the rotating ids are namespaced per peer so they differ by design. Under `ppk_required = yes` a PPK mismatch is `AUTHENTICATION_FAILED`, so a clean reauthentication is the proof. |
| 2.8b | **Exactly one IKE_SA** | `docker exec alice-ipsec swanctl --list-sas \| grep -c ESTABLISHED` after 4+ rotations | `1` (transiently `2` during a make-before-break reauth). Two owners for one SA previously grew this by one per rotation, reaching 140. |
| 2.9 | **KME failure is loud, not silent** | stop `bb84-kme-a`, watch `docker logs alice-ipsec` | explicit error; **no** fallback to random key material |
| 2.10 | No credential leak across rotations | `swanctl --list-conns` / VICI `get-shared` over several rotations | one current id, previous unloaded, never an id-less entry |
| 2.11 | Tunnel carries traffic | `docker exec alice-ipsec ping -c3 10.30.0.21` | replies |

---

## 3. WireGuard lane (manual)

| # | Check | Command | Expected |
|---|---|---|---|
| 3.1 | Smoke test passes | `make smoke` | KME health → ETSI 014 → ping → PSK rotation logged |
| 3.2 | arnika roles do not collide | `docker logs alice \| grep -i primary` | alice and bob take opposite roles (distinct `ARNIKA_ID`) |
| 3.3 | Rosenpass produces a real OSK | `docker logs alice \| grep rosenpass` | genuine exchange, no stub |
| 3.4 | PSK actually rotates | `docker exec alice wg show wg0` twice | preshared key changes |

---

## 4. Browser — every page (manual, Chrome)

Run against the local stack (`http://localhost:5173`) **and** the public demo.

### 4.1 All routes render

| # | Route | Check |
|---|---|---|
| 4.1.1 | `/` | Overview: architecture SVG + container status |
| 4.1.2 | `/e2e` | 4-phase orchestration, client-side |
| 4.1.3 | `/paper-flow` | multi-hop + failure cascade |
| 4.1.4 | `/bb84` | Monte-Carlo BB84, QBER chart |
| 4.1.5 | `/keyflow` | key-derivation Sankey |
| 4.1.6 | `/topology` | force-directed graph |
| 4.1.7 | `/benchmarks` | KPI cards + charts |
| 4.1.8 | `/console` | container log tail |
| 4.1.9 | `/physics` | editable params + key-rate |
| 4.1.10 | `/pqc` | PQC validator, client-side |
| 4.1.11 | `/verify` | agility matrix + cross-checks |
| 4.1.12 | `/hil` | hardware-in-the-loop docs |
| 4.1.13 | `/vpn` | both VPN lanes |

### 4.2 Global assertions, on every page

| # | Check | How |
|---|---|---|
| 4.2.1 | Zero console errors | DevTools console. Only the two React Router v7 future-flag warnings are acceptable. |
| 4.2.2 | No Japanese text | `document.documentElement.innerText.match(/[぀-ヿ㐀-䶿一-鿿]/g)` → `null` |
| 4.2.3 | `<html lang="en">` | view source |
| 4.2.4 | **Every form control is labelled** | For each page: `[...document.querySelectorAll('input,select')].filter(x => !x.getAttribute('aria-label') && !x.labels?.length && !x.closest('label')).length` -> `0`. `/physics` had 15 unlabelled inputs whose parameter name was only adjacent text, so a screen reader announced bare "number" fields on the page that sets the simulation's physics. **Sample only a fully-settled page** -- querying during an SPA route transition reports false positives, which is how three already-correct pages were first misdiagnosed. |
| 4.2.5 | No horizontal overflow | resize to 1280 and 1920 |
| 4.2.6 | SVG connectors meet box edges | endpoints on a border, not a centre (±2.5 px) |
| 4.2.7 | No overlapping SVG text | visual |

### 4.3 Every control

For each page, exercise **every** button, checkbox and select. The inventory
below was taken from the live demo on 2026-08-21 with real navigations; a
`pushState` sweep samples mid-render and under-reports, which produced false
"unlabelled control" findings more than once.

| # | Check | Expected |
|---|---|---|
| 4.3.1 | Each control does what its label says | Exercise it and observe the stated effect. |
| 4.3.2 | Disabled controls render as disabled | `opacity < 1` **and** `cursor: not-allowed`. |
| 4.3.3 | A control that cannot act is disabled, not inert | Compare `button.disabled` against the run state; see 4.4.11 for the measured matrix. |
| 4.3.4 | Every `<select>` option produces a visible change | Set each option in turn and diff the rendered text. |
| 4.3.5 | Errors surface in the UI, not only the console | Force one (stop the backend, then export) and read the toolbar. |
| 4.3.6 | **Control inventory per route** | `/` 16 buttons + 3 selects; `/e2e` 16 + 3 (Run, Pause, Resume, Abort, Reset, Step, modes A/B/C); `/paper-flow` 18 + 3 + hop slider (adds 5 inject buttons and clear, no Abort); `/bb84` 1 checkbox + 1 slider + Plotly modebar only; `/pqc` 1 button + KEM and signature selects; `/physics` 10 buttons + 14 number inputs + Eve checkbox; `/verify` 1; `/benchmarks` and `/console` 7 and 10; `/topology`, `/vpn`, `/keyflow`, `/hil` none. A change here is either a new feature or a regression -- both worth noticing. |
| 4.3.7 | **Export toolbars are only on 5 of 13 routes** | Present on `/`, `/benchmarks`, `/console`, `/e2e`, `/paper-flow`. Absent elsewhere, including `/bb84`, which produces QBER, key-pool and photon-frame data with no way to export any of it. Recorded so the gap is deliberate rather than forgotten. |

### 4.4 E2E orchestration simulator (`/e2e`)

| # | Check | Expected |
|---|---|---|
| 4.4.1 | **Run** | `idle → running` |
| 4.4.2 | **Pause** | `running → paused`, counters freeze, and the tick timer actually stops |
| 4.4.3 | **Resume** | `paused → running`, counters continue from where they stopped |
| 4.4.4 | **Step** | advances exactly one phase (`idle → 1 → 2`); **disabled while running**, enabled when paused. It previously ignored status and advanced the machine underneath the running timer while the badge still read `running` |
| 4.4.5 | **Abort** | stops the run, clears key material, **keeps** counters/history; disabled when idle |
| 4.4.6 | **Reset** | returns to `idle` and clears counters |
| 4.4.7 | Reset then Run | phase timing is correct (the timer was re-seeded, not left running) |
| 4.4.8 | Mode A / B / C | changes which key inputs are used; label updates |
| 4.4.9 | Phase history | 4 rows per cycle; each detail JSON non-empty. Phase 2 carries `key_id`, phase 3 `psk_prefix`/`qkd_bytes`/`pqc_bytes`, phase 4 `packets`/`bytes`/`rate_mbps` |
| 4.4.10 | KPIs | cycles, packets, bytes, throughput all advance |
| 4.4.11 | **Disabled set matches the state** | Read `button.disabled` per state. `idle` -> Pause, Resume, Abort disabled. `running` -> Run, Resume, Step disabled. `paused` -> Pause disabled only. Measured on the demo 2026-08-21; this is what makes 4.3.3 checkable rather than a matter of opinion. |
| 4.4.12 | **Pause really stops the clock** | Note `Cycles`, wait 4 s, read again: unchanged. A paused run that keeps counting is the failure this catches; a paused run that merely stops repainting is not. |
| 4.4.13 | **Failure injection exists on `/e2e` too** | Three buttons (`qkd`, `pqc`, `data`) plus `clear`. Previously only `/paper-flow` had this, though both pages are specified to. |
| 4.4.14 | **Injection outcome depends on the mode** | Not a cascade -- a single tunnel has nothing to cascade through. Mode C survives `qkd` or `pqc` (degrades to the surviving leg, `total_packets` keeps rising, banner says `Degraded:`). Mode A dies on `qkd`, mode B dies on `pqc` (`status: paused`, `total_packets` 0). Mode A ignores `pqc` and mode B ignores `qkd` -- a layer a mode never used must not stop it, or the control is a global kill switch. |
| 4.4.15 | **`data` is fatal in every mode** | AEAD has no second leg. All three modes reach `status: paused` with an error naming AEAD. |
| 4.4.16 | **The banner reads the simulator's verdict, not its own** | `state.failure_is_fatal` is published by `E2ESim`; the page must not recompute it. Check the two cells a mode-based guess gets wrong: mode A + `pqc` and mode B + `qkd` must read "never used this layer; run continues" while the run keeps encrypting. Caught on the deployed demo -- every simulator test passed while the banner said "fatal in mode A" over a healthy run. |

### 4.4b Paper Data Exchange simulator (`/paper-flow`)

The failure-injection feature had no falsifiable row before, which is why a
question about it could not be answered from this checklist.

| # | Check | Expected |
|---|---|---|
| 4.4b.1 | Controls present | Run, Pause, Resume, Reset, **Step**, five inject-failure buttons, clear |
| 4.4b.2 | **Step** | `idle → 1 → 2`; disabled while running, enabled when paused |
| 4.4b.3 | **Inject failure differs per layer** | Cascade stage count is **7 / 6 / 5 / 4 / 2** for qkd / arnika / wireguard / rosenpass / data. A lower layer must cascade through more layers above it (arXiv:2604.05599). Equal counts mean `injectFailure` stopped slicing `CASCADE_STAGES` from the injected layer |
| 4.4b.4 | Banner names the layer and the cascade | e.g. `⚠ qkd failure — 7-stage cascade`. Identical text across layers is the symptom that prompted this row |
| 4.4b.5 | Injecting while stopped says so | banner appends `(armed; press Run)`; a red bar with no motion and no explanation is not acceptable feedback |
| 4.4b.6 | `clear` | removes the banner and empties the cascade timeline |
| 4.4b.7 | Hop slider | `aria-label="Trusted node hop count"`, range 1-8, topology redraws |
| 4.4b.8 | **Logs exports this run** | tooltip reads "Download this run's log (client-side)"; file contains the phase history, **not** backend HTTP request lines |
| 4.4b.9 | **Run log reproduces Table III per phase** | Run, then export Logs and read the per-phase lines: phase 1 `pkts=0 bytes=0`, 2 `pkts=2 bytes=78`, 3 `pkts=3 bytes=398`, 4 `pkts=4 bytes=4772`. Handshake total **9 / 5248**, which is the paper figure. Phase 5 is application data and is deliberately not part of that total. Verified on the demo 2026-08-21. |
| 4.4b.10 | **Step advances exactly one phase** | From `status: paused · phase: idle`, one Step gives `phase: 1` and marks Quantum Plane `active`, and the status stays `paused`. Diff the page text rather than trusting a status regex -- the badge is combined (`status: X · phase: Y`) and a naive match reads the wrong field. |

### 4.5 Export and animation

| # | Check | Expected |
|---|---|---|
| 4.5.1 | PNG | downloads, correct content, **not** all black |
| 4.5.2 | JSON / CSV | both buttons **present on `/e2e`** and download parseable files. The CSV button renders only when the page passes a `csvProvider`; it was absent on `/e2e` for a long time while the docs listed CSV as supported, so check the button exists, not just that the format works somewhere. |
| 4.5.3 | Logs exports THIS run, not a server file | On `/e2e` the button tooltip reads "Download this run's log (client-side)" and the file contains the phase history. A page whose simulation runs in the browser must not offer a server log here: it downloads successfully and contains nothing about the run. |
| 4.5.4 | **Duration select defaults to 10 s** | options 3/5/10/15/20/30/60 |
| 4.5.4b | `/paper-flow` payload is really encrypted | Run, then `atob(<payload b64>).length` = plaintext + **16** (Poly1305 tag). Exactly `64` means the page reverted to `randomBytes(64)` while still titled ChaCha20-Poly1305 -- the panel asserted an AEAD that never ran. Measured 52 B on the live demo. |
| 4.5.4c | **Exports contain the run, not a shell** | After a run on `/e2e`: the CSV header lists one column per detail key (`phase,name,started_at,completed_at,duration_ms,alice_pool,key_id,qkd_key_len,psk_prefix,qkd_bytes,pqc_bytes,packets,bytes,rate_mbps`) and rows carry a real `key_id` and `psk_prefix`; the JSON has non-empty `history` and `engine: client-side`. A non-empty file is not sufficient evidence. |
| 4.5.4d | **Which exports touch the server** | Only `Logs` is a pure client-side blob. JSON/PNG/CSV/WebM/GIF POST to `/api/exports/save` first and fall back to a local blob only on failure, so a static-only deployment silently loses the saved-exports gallery. Verified by wrapping `URL.createObjectURL`: exactly one blob is captured for three export clicks. |
| 4.5.5 | WebM fps select | 12–60, default 25 |
| 4.5.6 | GIF fps select | 2–15, default 4 |
| 4.5.7 | WebM records for the selected duration | file length ≈ selection |
| 4.5.8 | GIF records for the selected duration | frame count ≈ duration × fps |
| 4.5.9 | Export failures are visible | force one; an error appears in the UI |
| 4.5.10 | Saved gallery | lists, downloads and deletes |
| 4.5.11 | **GIF plays back at the recording speed** | Frame delays are the measured gaps between captures, not `1000/fps`. Rendering is not free, so encoding the nominal interval made a 10 s capture play back in appreciably less. `gifFrameDelays` is pure and unit-tested; the sum of delays equals the real capture span. |
| 4.5.12 | **A local-only save says so** | With the backend unreachable the file still downloads and the toolbar shows `downloaded to this device only`. Silence here is what made a static-only deployment look like it had a working gallery. |

### 4.6 Client-side compute (the public demo must not load the server)

| # | Check | How |
|---|---|---|
| 4.6.1 | `/e2e`, `/paper-flow`, `/bb84`, `/physics`, `/pqc` open no WebSocket | DevTools Network → WS empty |
| 4.6.2 | No server call **in the compute path** | Per page during a run, `performance.getEntriesByType('resource')` gains no `/api/` or `/ws` entry -- **measured 0 for `/e2e`, `/paper-flow` and `/bb84`**. Two deliberate exceptions, which are cross-checks and not the computation: `/pqc` computes the round-trip client-side (`PQCValidator.tsx:44-45` calling `lib/sim/pqc`) and *then* posts `/api/pqc/roundtrip` to compare @noble against server liboqs -- that comparison is the page's entire purpose; and `/physics` polls `/api/stats` for display. For those two, assert the client result renders with the backend stopped. An earlier version of this row said simply "no /api entry", which would have failed `/pqc` for behaving correctly. |
| 4.6.3 | BB84 engine badge names the engine | `Worker`, `WebGL2` or `WebGPU`, with a throughput figure. Measured on the live demo: `Worker (CPU) - 107.5M pulses/s`. WebGPU being available in the browser (`'gpu' in navigator` is true) but unused is correct, not a failure: `bb84Sim.ts` only adopts a GPU tier when it benchmarks at least 15% faster than the Worker. |
| 4.6.4 | Recording duration is settable in-page, default 10 s | `document.querySelector('select[aria-label*="duration"]').value` -> `10`, options `[3,5,10,15,20,30,60]`; separate WebM fps (default 25) and GIF fps (default 4) selects. Backed by `DEFAULT_CAPTURE_MS = 10_000` in `lib/exporters.ts`, passed through as `durationSec * 1000` to both encoders -- so the default is one constant, not a literal repeated per call site. |
| 4.6.5 | No WASM / WebNN / WebLLM / ONNX is loaded | Zero occurrences in `services/webui-frontend/src/`. This is a deliberate choice, not an omission: those runtimes target neural inference, where approximate arithmetic and non-deterministic operator scheduling are acceptable, while this needs exact integer arithmetic for ML-KEM and bit-reproducible physics. See the decision record in `docs/roadmap.md`. |
| 4.6.6 | PQC round-trips run in-browser | `/pqc` works with the backend stopped |
| 4.6.7 | PQC sizes are correct | ML-KEM-768: pk 1184 / sk 2400 / ct 1088 / ss 32 B; ML-DSA-65 sig 3309 B |
| 4.6.8 | Tampered signature rejected | `/pqc` shows "Rejects tampered message: pass" |
| 4.6.9 | **The agility matrix spans more than one hardness assumption** | `/pqc` signature picker offers FIPS 204 ML-DSA (module-lattice) AND FIPS 205 SLH-DSA (hash-based), each option labelled with its family. Offering only ML-KEM and ML-DSA is not agility: both are module-lattice, so one structural break takes out every option. |
| 4.6.10 | **FIPS 205 sizes match the standard** | SLH-DSA-SHA2 128s pk 32 / sig 7856; 128f pk 32 / sig 17088; 192s pk 48 / sig 16224; 256s pk 64 / sig 29792. A wrong parameter set still signs and verifies, so a passing round-trip proves nothing about which algorithm you got. |
| 4.6.11 | **The cost of leaving the lattice is visible** | Measured in-browser: ML-DSA-65 ~9 ms, SLH-DSA-SHA2-192s ~2.2 s. Selecting a hash-based scheme pauses the page for one to two seconds; the option label names the family so the pause reads as the tradeoff rather than a hang. |
| 4.6.12 | **Panel headings name the standard from the result** | Select `SLH-DSA-SHA2-192s` on `/pqc` and Run: the heading must read `(FIPS 205)`, not `(FIPS 204)`. It said 204 for every scheme while rendering correct 205 sizes underneath -- the data was right and only the label was wrong, so no test saw it. Same defect shape as 4.4.16. |

### 4.7 Numbers match the model

| # | Check | Expected |
|---|---|---|
| 4.7.1 | `/physics` key rate matches the derivation | Same inputs into [`docs/keyrate.md`](docs/keyrate.md) section 4 give the same rate to 3 significant figures. |
| 4.7.2 | QBER responds to the channel | Raising `link_length_km`, `misalignment_error_ed` or `dark_count_rate_hz` each raises QBER; lowering each lowers it. A figure that does not move is not modelling the channel. |
| 4.7.3 | Rate falls with distance and vanishes | Monotonic decrease over 0-100 km, reaching 0 above roughly 11 % QBER (the Lo-Ma asymptotic bound, `protocol.qber_threshold_abort`). |
| 4.7.4 | `/verify` TNO cross-check agrees | `same_order_of_magnitude: true`. Measured 2026-08-21: closed form 12,333,658 bps against TNO 45,726,822 bps at 10 km -- same order, and the two use independent implementations. |
| 4.7.5 | `/paper-flow` budgets match the paper | Per phase 0/0, 2/78, 3/398, 4/4772; handshake total 9 packets / 5248 bytes. |
| 4.7.6 | `/vpn` shows the **negotiated** proposal | The string comes from `swanctl --list-sas`, not a constant: it names the KEM actually agreed. |
| 4.7.7 | **The Table III match check can fail** | `GET /api/verify/paper-budgets` -> `packets_match` and `bytes_match` compare the phase-table sum against `PAPER_TOTAL_PACKETS`/`PAPER_TOTAL_BYTES`, which are literals transcribed from the paper. They previously compared the sum against a constant defined as that same sum, so they were true by construction. Edit one phase figure and the flag must go false. |
| 4.7.8 | **`/bb84` offline defaults equal `qkd_params.yaml`** | Stop the backend, reload `/bb84`: the simulated link must be the configured one. They had drifted to 25 km and 1e7 against a configured 10 km and 1e9. Pinned by `tests/test_frontend_defaults_match_config.py`. |
| 4.7.9 | **Reported key rate is a rate, not a sifting fraction** | `/verify` `ours_closed_form.skr_bps` must sit far below `pulse_rate_hz / 2`. All three backends once reported the sifting fraction: 500 Mbps against an actual 12.07 Mbps. |

### 4.8 Demo-mode hardening

| # | Check | Expected |
|---|---|---|
| 4.8.1 | `POST /api/stack/*` | `403` |
| 4.8.2 | Rate limit | `429` past the window |
| 4.8.3 | Container controls hidden | no restart buttons on `/` |
| 4.8.4 | Demo matches local | same behaviour on every page |

---

## 5. Code quality

| # | Check |
|---|---|
| 5.1 | No hardcoded physics constants outside `config/qkd_params.yaml` (`pytest tests/test_no_hardcoded_params.py`) |
| 5.2 | No silent fallbacks — a failure must log and surface, never be replaced by plausible-looking data |
| 5.3 | No `\|\| true` masking failures in Makefile, entrypoints or CI |
| 5.4 | Cross-implementation constants are shared, not duplicated |
| 5.5 | New behaviour has a test that fails without the change |
| 5.6 | Randomness is injectable — no module builds its own unseeded generator, or a seeded run is not reproducible |
| 5.7 | Statistical assertions use a mean over seeds, not a single draw against a threshold |
| 5.8 | A quantity computed two ways is cross-checked, not just asserted non-zero |
| 5.9 | Tests are fast enough to actually run — no single test dominates the suite |

---

## 6. Release

| # | Check |
|---|---|
| 6.1 | README pre-release checklist reconciled |
| 6.2 | Only redistributable material under `references/` (see [`docs/references.md`](docs/references.md)) |
| 6.3 | No third-party vendor binaries tracked |
| 6.4 | Private files untracked and unreferenced from any tracked file |
| 6.5 | Submodules pinned to explicit commits |
| 6.6 | `docs/THIRD_PARTY_NOTICES.md` matches the pinned versions |
| 6.7 | Screenshots in `docs/images/screenshots/` refreshed |
| 6.8 | No AI-tooling references in any tracked file or commit trailer |
| 6.9 | No hosting-provider names, hostnames, IPs or credentials in tracked files |
| 6.10 | Pinned upstream facts re-verified against primary sources, with the date recorded |

---

## 7. Documentation

| # | Check | How |
|---|---|---|
| 7.1 | **Documented capabilities exist** | For every env switch, provider selection or cross-check a document claims: grep the code for it and confirm it is read, not just declared. Four claims failed this in one pass -- `PQC_PROVIDER` (display-only const cited as the RFC 7696 evidence), the PQClean byte-equality check (never runs), FIPS 205 (not imported), and a TLS group name absent from the pinned provider. A research repository asserting conformance it does not have is worse than one with stale prose. |
| 7.2 | **Static-hosting claim is accurate** | `docs/deployment-economics.md` page table matches reality: 6 of 13 routes fully self-contained, 7 need the backend. Said "only /verify" for a long time, understating it by seven pages. |
| 7.3 | **`references/` holds only redistributable material** | `git ls-files references/` lists exactly one PDF, arXiv:2604.05599, whose arXiv abstract page states **CC BY 4.0** -- redistribution permitted with attribution, which `docs/references.md` gives. `.gitignore:132` excludes `references/QuLore_*.pdf` because that paper is CC BY-NC-ND, where NoDerivatives and NonCommercial make redistribution from a repository documenting commercial deployment unclear. Check the licence on the arXiv abstract page, not the PDF: this one carries an IEEE copyright line inside it for the conference version while the arXiv posting is CC BY 4.0. |
| 7.4 | No emoji in any documentation file | Arrows and box-drawing glyphs in ASCII diagrams are technical notation, not emoji, and stay. `git ls-files '*.md' \| grep -v submodules \| xargs perl -ne 's/`[^`]*`//g; print "$ARGV:$.\n" if /[\x{1F000}-\x{1FAFF}\x{2600}-\x{27BF}\x{FE0F}]/'` -> no output. Code spans are stripped first because quoting a UI string that contains a glyph is not decoration. |
| 7.5 | README stays a navigational entry point | Detail lives in `docs/` and is linked, not inlined. `wc -l < README.md` -> **376**, and the Table of Contents anchors all resolve to a heading. It was 490 before section 5 moved to `docs/BUILD.md` and section 12 to `docs/LIMITATIONS.md`. |
| 7.6 | Every internal document link resolves | `git ls-files '*.md' \| grep -v submodules` and, for every Markdown link whose target is not `http`, `mailto` or a bare anchor, `test -e` the path relative to the citing file -> no output. Write the example without a literal bracket-paren pair, or the row matches its own check. Anchors are checked by eye: `docs/paper_mapping.md` cited README sections 11.6 and 15.2, neither of which exists, while the file path resolved -- a path check alone would have passed it. |
| 7.7 | No document states as current a design that has been superseded | Historical records say so inline, using the convention in `docs/phases.md`: a blockquote opening `> **Superseded.**`, placed immediately after the stale content, ending in a relative link to what replaced it. `grep -rn '^> \*\*Superseded' *.md docs/*.md` -> 7 markers covering the deleted WebSocket orchestrators and the pre-PPK strongSwan lane. `ARCHITECTURE.md` keeps its phase history in Appendix A for the same reason. |
| 7.8 | Dependency tables match what is actually installed | Version tables in `README.md` and `docs/` against `pip list`, `npm ls --depth=0` and the pinned submodule tags in `.gitmodules`. `docs/THIRD_PARTY_NOTICES.md` must list every submodule that ships in an image, with its licence. |
| 7.9 | Formulas are in MathJax, not ASCII art | `docs/keyrate.md` and `docs/vici-ppk.md` carry the derivations in `$$...$$`. ASCII box-drawing in `README.md` section 2 and `ARCHITECTURE.md` is topology, not mathematics, and stays as it is -- the rule is about equations, not diagrams. |
| 7.10 | No claim that the system silently degrades when the code does not | Where a page needs the backend it must say so on screen rather than render an empty state. `docs/deployment-economics.md` records the per-route behaviour; `/pqc` is the model, stating that the server cross-check was skipped. |
