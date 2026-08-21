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
| 4.2.4 | No horizontal overflow | resize to 1280 and 1920 |
| 4.2.5 | SVG connectors meet box edges | endpoints on a border, not a centre (±2.5 px) |
| 4.2.6 | No overlapping SVG text | visual |

### 4.3 Every control

For each page, exercise **every** button, checkbox and select:

| # | Check |
|---|---|
| 4.3.1 | Each control does what its label says |
| 4.3.2 | Disabled controls render as disabled — `opacity < 1` **and** `cursor: not-allowed` |
| 4.3.3 | A control that cannot act is disabled rather than silently doing nothing |
| 4.3.4 | Every `<select>` option produces a visible change |
| 4.3.5 | Errors are shown in the UI, not only in the console |

### 4.4 E2E orchestration simulator (`/e2e`)

| # | Check | Expected |
|---|---|---|
| 4.4.1 | **Run** | `idle → running` |
| 4.4.2 | **Pause** | `running → paused`, counters freeze, and the tick timer actually stops |
| 4.4.3 | **Resume** | `paused → running`, counters continue from where they stopped |
| 4.4.4 | **Step** | advances exactly one phase; disabled while running |
| 4.4.5 | **Abort** | stops the run, clears key material, **keeps** counters/history; disabled when idle |
| 4.4.6 | **Reset** | returns to `idle` and clears counters |
| 4.4.7 | Reset then Run | phase timing is correct (the timer was re-seeded, not left running) |
| 4.4.8 | Mode A / B / C | changes which key inputs are used; label updates |
| 4.4.9 | Phase history | records phase, name, duration, detail |
| 4.4.10 | KPIs | cycles, packets, bytes, throughput all advance |

### 4.5 Export and animation

| # | Check | Expected |
|---|---|---|
| 4.5.1 | PNG | downloads, correct content, **not** all black |
| 4.5.2 | JSON / CSV | both buttons **present on `/e2e`** and download parseable files. The CSV button renders only when the page passes a `csvProvider`; it was absent on `/e2e` for a long time while the docs listed CSV as supported, so check the button exists, not just that the format works somewhere. |
| 4.5.3 | Logs exports THIS run, not a server file | On `/e2e` the button tooltip reads "Download this run's log (client-side)" and the file contains the phase history. A page whose simulation runs in the browser must not offer a server log here: it downloads successfully and contains nothing about the run. |
| 4.5.4 | **Duration select defaults to 10 s** | options 3/5/10/15/20/30/60 |
| 4.5.4b | `/paper-flow` payload is really encrypted | Run, then `atob(<payload b64>).length` = plaintext + **16** (Poly1305 tag). Exactly `64` means the page reverted to `randomBytes(64)` while still titled ChaCha20-Poly1305 -- the panel asserted an AEAD that never ran. Measured 52 B on the live demo. |
| 4.5.5 | WebM fps select | 12–60, default 25 |
| 4.5.6 | GIF fps select | 2–15, default 4 |
| 4.5.7 | WebM records for the selected duration | file length ≈ selection |
| 4.5.8 | GIF records for the selected duration | frame count ≈ duration × fps |
| 4.5.9 | Export failures are visible | force one; an error appears in the UI |
| 4.5.10 | Saved gallery | lists, downloads and deletes |

### 4.6 Client-side compute (the public demo must not load the server)

| # | Check | How |
|---|---|---|
| 4.6.1 | `/e2e`, `/paper-flow`, `/bb84`, `/physics`, `/pqc` open no WebSocket | DevTools Network → WS empty |
| 4.6.2 | No server call **in the compute path** | During a run: `performance.getEntriesByType('resource')` gains no `/api/` or `/ws` entry. Deliberately broader than "no `/api/sim/*`": `/pqc` probes `/api/pqc/algorithms` and `/physics` polls `/api/stats`, so naming one prefix would pass a page that still computed server-side. |
| 4.6.3 | BB84 engine badge names the engine | `Worker`, `WebGL2` or `WebGPU` |
| 4.6.4 | PQC round-trips run in-browser | `/pqc` works with the backend stopped |
| 4.6.5 | PQC sizes are correct | ML-KEM-768: pk 1184 / sk 2400 / ct 1088 / ss 32 B; ML-DSA-65 sig 3309 B |
| 4.6.6 | Tampered signature rejected | `/pqc` shows "Rejects tampered message: pass" |

### 4.7 Numbers match the model

| # | Check |
|---|---|
| 4.7.1 | `/physics` key rate matches [`docs/keyrate.md`](docs/keyrate.md) for the same inputs |
| 4.7.2 | QBER responds correctly to link length, `e_d` and dark-count rate |
| 4.7.3 | Rate falls monotonically with distance and reaches 0 above ~11 % QBER |
| 4.7.4 | `/verify` TNO cross-check agrees with the closed-form rate |
| 4.7.5 | `/paper-flow` packet/byte budgets match the cited paper table |
| 4.7.6 | `/vpn` shows the **negotiated** proposal, not a placeholder |

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

| # | Check |
|---|---|
| 7.1 | No emoji in any documentation file. Arrows and box-drawing glyphs in ASCII diagrams are technical notation, not emoji, and stay. |
| 7.2 | README stays a navigational entry point; detail lives in `docs/` and is linked, not inlined |
| 7.3 | Every internal document link resolves |
| 7.4 | No document states as current a design that has been superseded; historical records say so inline |
| 7.5 | Dependency tables match what is actually installed |
| 7.6 | Formulas are in MathJax, not ASCII art |
| 7.7 | No claim that the system silently degrades when the code does not |
