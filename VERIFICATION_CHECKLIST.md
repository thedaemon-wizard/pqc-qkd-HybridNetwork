# Verification checklist

What must be checked before a release, and how. Automated items are gated by
[CI](.github/workflows/ci.yml); the browser items are manual because they check
things a headless assertion does not: layout, legibility, and whether a control
does what its label says.

Order: **local build → local browser → PR + CI → demo redeploy → demo browser**.

## Where the work is

188 rows, of which **30 are machine-checked and 158 are not**. Worth knowing
before planning a release, because the manual share is not evenly spread:

| § | Section | Rows | Automated | Manual |
|---|---|---|---|---|
| 1 | Build and unit gates | 16 | **16** | 0 |
| 2 | IPsec lane | 14 | 1 | 13 |
| 3 | WireGuard lane | 5 | 1 | 4 |
| 4 | Browser, every page | **111** | 2 | **109** |
| 5 | Code quality | 12 | 4 | 8 |
| 6 | Release | 19 | 5 | 14 |
| 7 | Documentation | 11 | 1 | 10 |

Section 4 is 61 % of the checklist and almost entirely manual. That is partly
irreducible -- layout, legibility and whether a control does what its label
says are not headless assertions -- but it is also where the least automation
has been attempted, so it is the first place to look for rows worth converting.

Section 2 reads as manual and is not: the `ipsec` CI job asserts 2.6, 2.7, 2.8,
2.8b, 2.11, 2.12 and 2.13 on every pull request. Treat a green run as those
rows executed rather than merely intended.

Everything CI can check, in one command:

```bash
.venv/bin/python -m pytest tests/ -q --ignore=tests/test_etsi014_contract.py \
  && .venv/bin/ruff check services/ tests/ tools/ benchmarks/ \
  && bash scripts/check_env_example.sh \
  && (cd services/webui-frontend && npm run typecheck && npx vitest run && npx vite build)
```

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
| 1.16 | **ETSI 014 roundtrip waits for the sync, it does not guess** | `tests/test_etsi014_contract.py` polls `dec_keys` to a 15 s deadline instead of `time.sleep(0.5)`. Propagation is asynchronous -- `KeyPool._sync_to_peer` POSTs to the neighbour and its HTTP client alone allows **2.0 s**, four times the old wait -- so a slow sync failed with `404 unknown key_ID` while nothing was wrong. Seen in CI on a branch touching only a script, a test exemption and a checklist row. The poll still fails on a genuinely unknown key: it returns 404 at the deadline rather than hanging or passing. | CI `live-stack` |

---

## 2. IPsec lane (needs privileged containers)

`make up COMPOSE_FILES="-f docker-compose.yml -f docker-compose.strongswan.yml" --profile ipsec`

Most of this section is **not** manual: the CI job `strongswan-lane` brings both
nodes up on every pull request and asserts 2.6, 2.7, 2.8, 2.8b, 2.11, 2.12 and
2.13 automatically. Treat a green run as those rows having been executed, not
merely intended.

The rows are still written as commands because the public demo does **not** run
this lane -- it needs `NET_ADMIN`, and the cloud profile brings up the WireGuard
nodes (`alice`, `bob`) with the WebUI instead. Running these against the demo
host will find no `alice-ipsec` container, which is expected rather than a
failure.

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
| 2.11 | **Traffic actually traverses ESP** | `docker exec alice-ipsec ping -c3 10.30.0.21`, then `docker exec alice-ipsec swanctl --list-sas \| grep -m1 'out '` | a non-zero byte count, e.g. `out c0ffee42, 252 bytes`. Ping replies alone are NOT sufficient: a tunnel that is up but installs no ESP counters is passing traffic in the clear past the policy, and it answers pings exactly the same way. CI asserts the byte count, and this row previously did not. |
| 2.12 | **Rotation actually happens, more than once** | Over a 240 s window: `docker logs alice-ipsec \| grep -c 'PPK rotated'` -> at least 2. A lane that establishes once and never rotates satisfies every row above while the QKD material is never consumed, which is the entire point of the integration. |
| 2.13 | **Auth failures stay in race territory, not systematic** | `authfail * 5 <= rotations`. Rotating a PPK under a stable `PPK_ID` cannot be atomic across two hosts, so zero is the wrong assertion and would make the guard flake -- measured 1 failure in 45 rotations, self-correcting. What must fail is SYSTEMATIC mismatch, two credentials answering one `PPK_ID`: that measured 4 in 9 before the bootstrap credential was retired. The 20% ceiling separates a race from a coin flip. **Know the operating point before reading that as generous:** the job's window is `sleep 240` and both nodes report **6** rotations, so the ceiling is `floor(6/5) = 1` failure per run, not nine. A run on 2026-08-22 reported 4 failures in 6 rotations on both nodes and then 0 in 6 on an immediate re-run of the same commit with no lane file changed -- outside race territory and unexplained, so treat a repeat as signal rather than re-running until green. See `docs/vici-ppk.md`. |

---

## 3. WireGuard lane (manual)

| # | Check | Command | Expected |
|---|---|---|---|
| 3.1 | Smoke test passes | `make smoke` | KME health → ETSI 014 → ping → PSK rotation logged |
| 3.2 | arnika roles do not collide | `docker logs alice \| grep -i primary` | alice and bob take opposite roles (distinct `ARNIKA_ID`) |
| 3.3 | Rosenpass produces a real OSK | `docker logs alice \| grep rosenpass` | genuine exchange, no stub |
| 3.4 | PSK actually rotates | `docker exec alice wg show wg0` twice | preshared key changes |
| 3.5 | **Multi-hop: count PSK installs, not ping replies** | `docker compose -f docker-compose.yml -f docker-compose.multihop.yml --profile multihop up -d alice bob charlie bb84-kme-a bb84-kme-b`, wait ~90 s, then per node `docker logs <n> \| grep -c 'PSK configured on WireGuard interface'` and `\| grep -c 'not found on interface'`. Expect alice **2 peers, 2 of 2 with a preshared key, 0 errors**, and `docker logs alice \| grep -c 'starting arnika'` -> **2** (one instance per neighbour; arnika manages a single `WIREGUARD_PEER_PUBLIC_KEY`). **Ping is not the check.** WireGuard works fine with no preshared key, so 0 %% loss in all three directions proves connectivity and says nothing about protection -- that is how a silent loss of the QKD PSK was nearly signed off. Confirm with `docker exec alice wg show wg0 \| grep -c 'preshared key'` -> **2**. And rebuild before measuring: `docker compose up -d` reuses the existing image, which once produced a whole round of "the second instance never started". |

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
| 4.4.17 | **Pause freezes the clock, on both simulators** | Run to a cycle count, press Pause, wait 5 s, read the count again -- it must be identical. Verified on the deployed build 2026-08-22: `/e2e` held at 1 across 5 s, `/paper-flow` held at 2 across 4.5 s. A Pause that only stops repainting looks the same until you compare counts either side of a wait. |
| 4.4.18 | **Step advances without resuming** | From `paused`, press Step three times: the phase advances and a cycle completes, but `status` stays `paused`. Then wait 3-4 s and read again -- the count must be UNCHANGED. Verified: `/e2e` 1 -> 2 then unchanged over 3.5 s; `/paper-flow` unchanged over 4 s. This is the property that broke before -- `step()` ignored `status` and advanced a paused run. |
| 4.4.19 | **Resume returns to free-running** | After the Step sequence, Resume must restore `status: running` and the cycle count must climb again. Verified: `/e2e` reached running, `/paper-flow` 2 -> 3 within 4 s. |
| 4.4.20 | **All four export types produce real content, both simulators** | Run first, then Logs / JSON / PNG / CSV. Verified 2026-08-22 on the deployed build. `/e2e` (`e2e-architecture`): log 1124 B, JSON 2136 B, CSV 857 B / 14 columns / 7 phase rows, PNG 323330 B. `/paper-flow` (`paper-data-exchange`): JSON 3844 B, CSV 394 B / 6 columns / 6 rows, PNG 323117 B. Note the export stem is `paper-data-exchange`, not `paper-flow`. |
| 4.4.21 | **The PNG is a PNG** | Check the first four bytes are `89 50 4E 47`, not just that a file arrived. A failed render saved under a `.png` name is a plausible failure that a size check alone would pass. Both simulators verified. |
| 4.4.22 | **Exported JSON carries live run state, not a template** | `/e2e` JSON must contain `failure_is_fatal`, `mode_label` and a non-zero `completed_cycles`; `/paper-flow` JSON must contain `hop_count`, `cycles_succeeded` and `bytes_total`. A snapshot serialised before the run would have the keys and zero everywhere. |

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
| 4.5.4c | **Exports contain the run, not a shell** | After a run on `/e2e`: the CSV header lists one column per detail key (`phase,name,started_at,completed_at,ui_dwell_ms,nominal_dwell_ms,alice_pool,key_id,qkd_key_len,psk_prefix,qkd_bytes,pqc_bytes,packets,bytes,rate_mbps`) and rows carry a real `key_id` and `psk_prefix`; the JSON has non-empty `history` and `engine: client-side`. A non-empty file is not sufficient evidence. |
| 4.5.4d | **Which exports touch the server** | Only `Logs` is a pure client-side blob. JSON/PNG/CSV/WebM/GIF POST to `/api/exports/save` first and fall back to a local blob only on failure, so a static-only deployment silently loses the saved-exports gallery. Verified by wrapping `URL.createObjectURL`: exactly one blob is captured for three export clicks. |
| 4.5.4f | **The timing column is not read as a measurement** | The CSV must export `ui_dwell_ms` beside `nominal_dwell_ms`, never a bare `duration_ms`. The value is the animation dwell, not protocol timing, and the browser distorts it: Chrome clamps `setInterval` to about 1 Hz in a hidden tab. Reproduce with `document.visibilityState` and a timed interval on the deployed demo -- observed `hidden`, 935 ms per requested 100 ms, and phases logging 999 ms against a 450 ms nominal. `npx vitest run src/lib/sim/dwellIsNotAMeasurement.test.ts` pins that the two pages keep DIFFERENT nominals (450 on `/e2e`, 350 on `/paper-flow`); a single shared constant would export 450 for a page that dwells 350. |
| 4.5.4g | **The Run hint only appears where Run exists** | `.venv/bin/python -m pytest tests/test_toolbar_hint_matches_the_page.py` -> passes. `ExportToolbar` ended both animation tooltips with "Press Run first." unconditionally; nine pages mount it and only `/e2e` and `/paper-flow` have a Run button, so seven pages told the reader to press a control that is not there -- `/bb84` animates continuously and has no start at all. Pages opt in with `hasRunControl`, and the test fails both ways: a Run page that does not opt in, and a Run-less page that does. |
| 4.5.5 | WebM fps select | 12–60, default 25 |
| 4.5.6 | GIF fps select | 2–15, default 4 |
| 4.5.7 | WebM records for the selected duration | file length ≈ selection |
| 4.5.8 | GIF records for the selected duration | frame count ≈ duration × fps |
| 4.5.9 | Export failures are visible | force one; an error appears in the UI |
| 4.5.10 | Saved gallery | lists, downloads and deletes |
| 4.5.11 | **GIF plays back at the recording speed** | Frame delays are the measured gaps between captures, not `1000/fps`. Rendering is not free, so encoding the nominal interval made a 10 s capture play back in appreciably less. `gifFrameDelays` is pure and unit-tested; the sum of delays equals the real capture span. |
| 4.5.12 | **A local-only save says so** | With the backend unreachable the file still downloads and the toolbar shows `downloaded to this device only`. Silence here is what made a static-only deployment look like it had a working gallery. |
| 4.5.13 | **No server compute during a client-side run** | On `/bb84`, wrap `window.fetch` and `XMLHttpRequest.prototype.open`, let the simulation run, then assert zero `/api/` or `/ws/` calls. Measured on the demo: **0 network calls in 6 s at 59.9M pulses/s**. |
| 4.5.14 | **The compute engine is chosen by measurement, not assumed** | DevTools console on `/bb84` shows one line, e.g. `[bb84] WebGPU 34M/s <= Worker 62M/s -- keeping Worker`. The ladder benchmarks WebGPU then WebGL2 against the CPU Worker and adopts a tier only if it wins, so "Worker (CPU)" on a WebGPU-capable browser is a recorded decision rather than a silent fallback. A `console.warn` naming init/bench failure is the case to investigate. |

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
| 4.6.13 | **The liboqs cross-check compares secrets, not byte counts** | On `/pqc` with the backend up, "Shared secrets agree" must pass: the browser generates an ML-KEM key with @noble, liboqs encapsulates to it in C, the browser decapsulates and the SHA-256 digests match. The panel previously compared only `ss_len`/`ct_len` -- an implementation returning 1088 zero bytes would have passed. The length row is kept and labelled weak. |
| 4.6.14 | **No endpoint claims a check it does not perform** | `/api/kat` reports `is_known_answer_test: false` and `cross_checked: false`, and no longer returns `pqclean_test_present`. It accepted a seed and used it only for `len(seed)`. Building PQClean is not the remedy: archived 2026-08-04, its notice redirects to mlkem-native / mldsa-native / slhdsa-c. |
| 4.6.15 | **ML-KEM has a known-answer test that is not self-referential** | Seed `0x01`x64 into FIPS 203 KeyGen_internal. Encapsulation-key SHA-256 must be `871c0a93…` (512), `e68d6085…` (768), `05227acb…` (1024). These were derived INDEPENDENTLY by liboqs (C) and @noble (JS) and agreed byte for byte; a vector recorded from one implementation would only prove it equals itself. Both halves are pinned, so drift in either breaks one. |
| 4.6.16 | **The authoritative vector is NIST's, not ours** | ML-KEM-768 `d`=`e582b7d7…`, `z`=`1cdacb87…` from NIST ACVP `ML-KEM-keyGen-FIPS203` tgId 2 tcId 26, pinned at commit `15c0f3de…`. Encapsulation key SHA-256 must be `4158f6af…` in BOTH liboqs and @noble. Cross-implementation agreement catches disagreement; only NIST's vector catches both being wrong the same way. Reversing the `d`/`z` order must FAIL -- the 64-byte packing is convention, not spec. |
| 4.6.17 | **Every page that produces evidence can export it** | Systematic sweep of all 13 routes, 2026-08-22: export toolbars on the **nine** data pages -- `/`, `/e2e`, `/paper-flow`, `/bb84`, `/pqc`, `/physics`, `/verify`, `/benchmarks`, `/console`. The **four** display-only prose pages -- `/topology`, `/vpn`, `/keyflow`, `/hil` -- correctly have none. 9 + 4 = 13; an earlier version of this row listed 8 + 4 and silently dropped `/physics`, which does have a toolbar. Check the arithmetic, not just the lists. `/verify` in particular is headed "Implementation Verification" and previously offered no way to export the verification -- a reviewer had to screenshot the table. |
| 4.6.18 | **Full-route control inventory** | All 13 routes, via the app's own navigation with 2.8 s settle: **zero unlabelled inputs and zero Japanese text on every route**. `Animation duration (seconds)` present with 7 options defaulting to 10 on every page carrying a toolbar. `/pqc` signature picker offers 7 algorithms across two families. `/physics` exposes 14 numeric inputs plus 1 checkbox, all labelled. |
| 4.6.19 | **`/physics` exports the parameters AND the rate they imply** | Export toolbar present; the JSON carries `parameters` (all editable paths, config default vs effective, which are overridden) and `derived` (`eta_total`, `Y0`, `qber`, `skr_per_pulse`, `skr_bps`). Inputs alone would be half the evidence -- the page's claim is that a given channel yields a given rate, and both sides are needed to reproduce it. Derived values are computed client-side from the same closed form the page displays, so export and screen cannot disagree. |
| 4.6.20 | **One bundled parameter set; engines derive, never restate** | `BUNDLED_PARAMS` in `lib/sim/keyrate.ts` is the only literal, checked against `config/qkd_params.yaml` by `tests/test_frontend_defaults_match_config.py`. `bb84Sim.ts` and `bb84.worker.ts` must call `bundledChannel()`, not carry their own eta/Y0. They previously held `{etaTotal: 0.02, Y0: 1e-5}` -- a channel 6.3x more lossy with 100x the dark-count yield than the configured one, and the worker starts before `/api/sim/params` arrives, so those were the values the first rounds were drawn from. eta_total and Y0 are DERIVED quantities; writing them as literals is what let them drift. |

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

| # | Check | How |
|---|---|---|
| 5.1 | No hardcoded physics constants outside `config/qkd_params.yaml` | `pytest tests/test_no_hardcoded_params.py tests/test_frontend_defaults_match_config.py`. The second one exists because the first covered `backends/` only, and the frontend had drifted to 25 km against a configured 10. |
| 5.2 | No silent fallbacks | A failure must log and surface, never be replaced by plausible-looking data. `grep -rnE 'catch\s*(\([^)]*\))?\s*\{\s*\}' services/webui-frontend/src` -> every hit must carry a comment saying why swallowing is right. Four exist, all offline-fallback paths on pages that must work without a backend. |
| 5.3 | No `\|\| true` masking failures | `grep -rn '\|\| true' --include='*.sh' --include='*.yml' --include=Makefile .` -> every hit on a `grep -c` where no-match is a legitimate zero, or a backgrounded server start. Never on a build, lint or test step. |
| 5.4 | Cross-implementation constants are shared, not duplicated | `pytest tests/test_paper_constants_agree_across_ports.py tests/test_keyrate_ports_agree.py`, plus `bundledDefaults.test.ts`. Three separate cases have been found and fixed: the key-pool model in three engines, the BB84 channel in three files, and the paper setup times in two ports. |
| 5.5 | New behaviour has a test that fails without the change | Verified by mutation, not by inspection: revert the change and confirm the new test fails. Recorded in the PR body for each. A test written after the fact that passes on the old code is decoration. |
| 5.6 | Randomness is injectable | No module builds a generator a caller cannot override. `grep -rn 'default_rng()' services/ \| grep -vE 'rng or \|rng is not None else '` -> empty. Note the filter: a bare `grep default_rng()` returns 13 hits and all are FINE -- `rng = rng or np.random.default_rng()` is the injectable pattern, and the backends seed from `cfg.rng_seed`. Writing the naive grep as the expectation here was wrong, and checking it is what caught that. |
| 5.7 | Statistical assertions use a mean over seeds | A single draw against a threshold flakes or, worse, passes on a broken model that happens to land inside the band. See the intercept-resend QBER test, which asserts a range over 4000 sampled frames. |
| 5.8 | A quantity computed two ways is cross-checked | Not just asserted non-zero. `/verify` compares the closed-form SKR against TNO; `/pqc` makes liboqs and `@noble` agree on a shared secret. Asserting non-zero is what let `skr_bps` report a sifting fraction for months. |
| 5.9 | Tests are fast enough to actually run | `pytest tests/ --durations=5` and `npx vitest run`. Host suite ~3 s, frontend ~2 s. The SLH-DSA cases are the slowest at 1-2 s each and are computed once in a `beforeAll` rather than per assertion. |
| 5.10 | **Every compose env var is read by something** | `.venv/bin/python -m pytest tests/test_compose_env_is_read_by_something.py` -> passes. Seven `BB84_*` vars and `ETSI_MTLS_ENABLED` were set in compose, listed in `.env.example` and documented in the README with a "source of truth" column naming a Python file -- and read by no Python file at all. `config_loader.py` declares `config/qkd_params.yaml` the single source, so they were a second config surface wired on the outside and connected to nothing. Parse the YAML, do NOT regex the lines: a draft matched `build.args` too and reported `USE_BORINGTUN` as an env var. Skips must name an external consumer (OpenMP, OpenBLAS, wg-quick); an undocumented skip is the hole. |
| 5.11 | **The userspace WireGuard fallback exists** | `docker run --rm --entrypoint wireguard-go pqcqkd/node-alice:local --version` -> `wireguard-go v0.0.20220316`. It must live at `/usr/bin/wireguard-go`, which is what `wg-quick` uses by default (`${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}`), so no override is needed and `docker-compose.boringtun.yml` is redundant. Until 2026-08 nothing provided one and that overlay named a `boringtun` binary the image lacked, so the documented recovery path could not work. Do NOT conclude a package is absent from `apt-cache policy` showing `Installed: (none)` -- that is the local system; read the `Candidate:` line. Concluding otherwise is what made this look like it needed a vendored submodule. |
| 5.12 | **A backend that fails to install fails the build** | `docker build -f services/bb84-kme/Dockerfile .` -> the step prints `backend modules importable: ['qns', 'sequence', 'strawberryfields', 'tno.quantum.communication.qkd_key_rate']`. The four editable installs were chained `pip install ... \|\| echo "...failed; will use volume mount" && \\`, which cannot fail a build -- `A \|\| B && C` runs C either way -- so a broken simulator produced a green image that degraded to a logged warning at runtime. Verify the guard bites by pointing one install at a non-existent path; the build must exit non-zero. IMPORT the modules, do not probe names: SimQN provides `qns` and TNO provides `tno.quantum.communication.qkd_key_rate`, and guessing either reports a confident false absence (both mistakes were made while writing this row). |

---

## 6. Release

| # | Check | How |
|---|---|---|
| 6.1 | README pre-release checklist reconciled | Every unchecked box in the README's pre-release list either done or deleted. A checklist that carries permanently-unticked items stops being read. |
| 6.2 | Only redistributable material under `references/` | `git ls-files references/` -> exactly one PDF, arXiv:2604.05599, CC BY 4.0 per its arXiv abstract page. `.gitignore:132` excludes the CC BY-NC-ND QuLore paper. Check the licence on the abstract page, not inside the PDF -- this one carries an IEEE line for the conference version while the arXiv posting is CC BY. |
| 6.3 | No third-party vendor binaries tracked | `git ls-files \| grep -iE '\\.(so\|dll\|dylib\|a\|jar\|whl)$'` -> empty. |
| 6.4 | **Private working files stay untracked AND unnamed** | For every pattern `p` in `.git/info/exclude`: `git ls-files \| grep -F "$p"` -> empty, and `git grep -lF -- "$p"` -> empty. Run it as a loop over that file; **do not write the patterns into this document.** Naming them here IS the disclosure this row exists to prevent, and the previous version did exactly that -- it spelled out two private filenames while asserting "a reference from a tracked file discloses the name", and its own `grep ... -> empty` was false, returning this checklist. Note the protection is `.git/info/exclude`, which is local to one clone and does NOT travel: a fresh clone has no such rule, so `git add -A` there would stage those files. |
| 6.4b | **Private files have a safe harbour that travels** | `.venv/bin/python -m pytest tests/test_private_files_have_a_safe_harbour.py` -> passes. Protection used to be `.git/info/exclude`, which is per-clone and is NOT committed: simulated a clean clone with only the repository's `.gitignore` and `git add -A` staged the operator's private files. The tracked rule is a generic `/private/` directory -- generic deliberately, because naming the files in `.gitignore` would disclose them, the mistake row 6.4 made. The test cannot verify the operator has moved anything into it without knowing the names, so that step stays manual. |
| 6.5 | Submodules pinned to explicit commits | `git submodule status` -> every line carries a 40-char SHA. A `-` prefix means merely NOT CHECKED OUT here and is normal (12 of 15 in a typical working copy); it is `+` that matters, meaning the checkout has drifted from the recorded commit. Run `git submodule update --init --recursive` before reading this as a fresh-clone check. |
| 6.6 | `docs/THIRD_PARTY_NOTICES.md` matches the pinned versions | Human read of the licence and activity columns. The VERSION claims are machine-checked by 6.6b; everything else here -- licence names, "active", push dates -- is not, and saying so is more useful than implying it is. |
| 6.6b | **Every row states its pinned commit, and states it correctly** | `.venv/bin/python -m pytest tests/test_notices_match_the_pins.py` -> passes, with **15 of 15** submodule rows checked. The earlier version of this test checked **3 of 15**: it only matched a **bolded** `vX.Y.Z`, and it resolved tags in the LOCAL clone then skipped when none were found -- and 12 of 15 clones here are shallow with zero tags. Every row later found wrong was in the unchecked 12. Confirm coverage with `-rs`: skips must all read "row makes no bolded tag claim", never "cannot reach". The primary assertion is now the backticked pinned SHA against `git ls-tree HEAD`, which needs no network and works for untagged pins; a bolded tag is additionally resolved via `git ls-remote --tags`. |
| 6.6c | **Scope the version regex to the Activity column** | Do NOT widen it to the whole row. A draft that scanned the entire line read `GPL-3.0` out of the LICENCE column as version "3.0" and failed `wgephemeralpeer` for a defect that did not exist. Equally, only a bolded version ADJACENT TO "pinned" is an equality claim: the `oqs-provider` row legitimately bolds **0.15.0** and **0.16.0** while discussing the liboqs pairing, and neither is its own pin. The match is case-insensitive because the `liboqs` row capitalises "Pinned to tag **0.16.0**", and a case-sensitive draft silently skipped it. |
| 6.7 | Screenshots in `docs/images/screenshots/` refreshed | Guarded by `test_verification_checklist_is_citable.py::test_every_screenshot_a_document_names_actually_exists`, which fails on any `docs/images/screenshots/*.png` named in prose but absent. |
| 6.8 | No AI-tooling references in any tracked file or commit trailer | CI job `secrets`, plus `git log --format='%an%n%b' \| grep -ciE 'claude\|anthropic\|co-authored'` -> 0. |
| 6.8b | **The multihop overlay is covered by the env check** | `bash scripts/check_env_example.sh` -> the second group lists `docker-compose.multihop.yml`. It was checked by nothing, which is how `charlie` shipped without the `ARNIKA_ID` and `ARNIKA_PSK` its own entrypoint refuses to start without. Verify the guard bites: change charlie's `ARNIKA_PSK` to a name absent from `.env.example` and the script must error. Do not write a `${VAR:?...}` example into a compose COMMENT -- the extractor reads it as a real mandatory variable, which this row's first draft did. |
| 6.8c | **Multi-hop is described as partial, not implemented** | `docker compose -f docker-compose.yml -f docker-compose.multihop.yml --profile multihop up -d alice bob charlie bb84-kme-a bb84-kme-b`, wait ~2 min. Expect: all three Up, `docker exec charlie ls /shared` shows six files (alice/bob/charlie x wg+rp), and charlie's log reaches "peer WireGuard public key". Expect ALSO that it then fails: no PQC OSK, and arnika exits on the missing `pqc.psk`. Cause is architectural -- `nodes/alice/rosenpass-sidecar.sh` takes one `RP_PEER_HOST`, so alice peers with bob only and charlie's handshake to `alice:9997` is never accepted. Any document calling this row "Implemented" or the ping "Replies via charlie" is wrong. |
| 6.9 | No hosting-provider names, hostnames, IPs or credentials in tracked files | `git ls-files \| xargs grep -lniE 'ssh_info\|<demo-host>'` -> empty; gitleaks runs in CI. |
| 6.9b | **Every published formula typesets** | `cd services/webui-frontend && npx vitest run src/lib/docsLatex.test.ts` -> passes. Renders every formula in `git ls-files '*.md'` through KaTeX in strict mode. Two equations in `docs/keyrate.md` -- the QBER (Eq. 11) and the GLLP key rate (Eq. 12), the two the golden vector is derived from -- were not valid LaTeX. Do NOT substitute a brace-counting check: in both, braces balanced AND `\left`/`\right` balanced, across the wrong groups, so counting passed them. |
| 6.9c | **Display maths uses a fenced ```` ```math ```` block, inline maths needing escapes uses ``$`...`$``** | Same test; the "GitHub delivers the formula unchanged" block. GitHub applies CommonMark backslash-escape removal to `$...$` and `$$...$$` content **before** MathJax sees it: `\;`->`;`, `\,`->`,`, `\{`->`{` (so `\left\{` becomes the parse error `\left{`), `\_`->`_` (a literal underscore silently becomes a subscript), `\%`->`%` (starts a comment and eats the rest of the line). 17 expressions across three files were affected, and correct LaTeX alone did not fix them. Verify against GitHub itself, not by inspection: `gh api -X POST /markdown -f mode=gfm -f text='$$a \|; b$$'` and check what comes back inside `<math-renderer>`. The fenced and code-span forms come back verbatim. |
| 6.10 | Pinned upstream facts re-verified against primary sources, with the date recorded | Each claim in `docs/references.md` carries the date it was checked. Undated claims age silently -- the NCSC citation pointed at a URL that had begun redirecting. |
| 6.11 | **Publication constraints are executed, not swept by hand** | `.venv/bin/python -m pytest tests/test_repo_is_publication_ready.py` -> passes. Four properties that had been re-verified manually more than once are now guards: no Japanese in tracked files, no emoji in documentation, no AI-tooling attribution, no non-private IP address. The Japanese rule is **exactly one** occurrence and it must be row 4.2.2 -- that row has to quote the Unicode ranges to specify the browser check, so a plain zero-tolerance rule fails on it and deleting the row would remove the check. All four verified to fail when violated. Formula rendering is NOT here: it needs GitHub's renderer and lives in the frontend suite where KaTeX already is. |
| 6.12 | **The GitHub-side surface is audited, not just the tree** | `bash scripts/audit_github_surface.sh` -> `ok: GitHub surface is clean`. CI's `secrets` job and `scripts/secret_scan.sh` see tracked files and commit messages. Neither can see **pull-request titles and bodies, the contributor list, or the collaborator list** -- that is GitHub state, not repository state, and it is where an attribution appears with no commit recording it. The script also checks commit AUTHORSHIP, which a message-only scan passes even when the author is a tool. Measured 2026-08-22: 50 PRs / 0 matches, one contributor, one collaborator, 170 commits / 0 matches, 0 `Co-authored-by` trailers. |

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
| 7.11 | **"PSK" is qualified wherever both lanes are visible** | `.venv/bin/python -m pytest tests/test_psk_is_qualified_where_it_is_ambiguous.py` -> passes. The word means opposite things here: the **IKEv2** PSK enters only the `AUTH` payload and carries no confidentiality (which is why the IPsec lane needs RFC 8784's PPK), while **WireGuard's** preshared key is mixed into the Noise_IKpsk2 chaining key and does contribute to the transport keys -- mechanically the PPK's analogue. `/e2e`, `/paper-flow` and `/vpn` model the WireGuard lane and must say so; unqualified, a reader arriving from `docs/vici-ppk.md` concludes those pages demonstrate the weaker construction. Reported by a reader, not caught by any check, which is why the wording is now pinned. |
