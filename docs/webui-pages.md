# WebUI pages

The thirteen routes the dashboard serves, what each one computes in the
browser, and what it needs the backend for.

Moved out of `README.md` section 7 on 2026-08-29. The list is a page
inventory, consulted when you want to know what a route does; the README
should say how to open the UI and get out of the way.

Which routes survive without a backend, and what each one costs to host, is a
different question -- see [`deployment-economics.md`](deployment-economics.md).

---

## Pages

1. **Overview** (`/`) — Layered architecture SVG + live container status badges
2. **Quantum-Secure E2E** (`/e2e`) — **client-side** 4-phase orchestration (Quantum Plane → QKD Key IDs → PQC Handshake → Data Exchange) with **real in-browser HKDF-SHA3-256 + ChaCha20-Poly1305** (`@noble`), over the arnika architecture diagram, Run/Pause/Resume/Reset/Step + Mode A/B/C
3. **Paper Data Exchange** (`/paper-flow`) — **client-side** multi-hop trusted-node Data Exchange (Spooren et al. arXiv:2604.05599): swimlane sequence, hop-count slider (1–8), layer-aware failure-cascade timeline, ChaCha20-Poly1305 payload
4. **BB84 Live** (`/bb84`) — **client-side** Monte-Carlo photon simulation in a **Web Worker** (~70–100M pulses/s; optional WebGPU), real-time QBER chart, key-pool size, photon-frame table, **Eve toggle** + intercept-probability slider, live engine badge
5. **Key Flow** (`/keyflow`) — Plotly Sankey of QKD raw → sifted → reconciled + Rosenpass → HKDF → WireGuard PSK
6. **Topology** (`/topology`) — D3-force graph of alice, bob and the two KMEs. Charlie is **not** shown: `/api/topology` returns a fixed four-node graph with no multihop branch.
7. **Benchmarks** (`/benchmarks`) — Round latency, QBER history, KPI cards (accepted/aborted/avg ms)
8. **Console** (`/console`) — Live log tail of any container (alice / bob / KMEs)
9. **Physics Params** (`/physics`) — **Editable** parameter inputs (Apply/Reset). `config/qkd_params.yaml` provides the defaults (best-effort synced to the KMEs); a **client-side** live key-rate (closed-form Lo-Ma) + **client-side** μ/ν optimiser recompute in-browser as you edit, plus the backend selector (incl. `tno`)
10. **PQC Validator** (`/pqc`) — client-side ML-KEM / ML-DSA / SLH-DSA via @noble, cross-checked against liboqs by `POST /api/interop/mlkem`
11. **Verification** (`/verify`) — Research-implementation evidence: crypto-agility matrix across **two mathematical families** (ML-KEM 512/768/1024 and ML-DSA 44/65/87 on module lattices, SLH-DSA SHA2-128s/192s/256s hash-based), key-rate cross-check (our closed-form vs the independent **TNO-Quantum** engine), and arXiv:2604.05599 packet-budget match
12. **Hardware-In-Loop** (`/hil`) — Checklist for wiring real ETSI 014 KMS hardware (mTLS)
13. **VPN Protocols** (`/vpn`) — WireGuard + strongSwan IPsec/IKEv2 (RFC 9370 ML-KEM-768 hybrid) status

Most pages provide per-page export buttons below the description — **high-DPI PNG (2×)**, JSON, CSV, **WebM (HQ)** + **full-resolution GIF** animation, and logs; artefacts are stored on the backend and re-downloadable via the "Saved exports" picker.

---

## Demo mode

**Public-demo profile (`DEMO_MODE=1`).** For an unattended, multi-user public
demo set `DEMO_MODE=1` on `webui-backend`. The demo is **functionally
equivalent to full mode except the one genuinely dangerous operation** --
**container lifecycle control** (`/api/stack/*`), which could take the shared
demo offline and stays **403** (its restart buttons are hidden) -- plus a
per-IP rate limit (`DEMO_RATE_MAX` / `DEMO_RATE_WINDOW_S`, 429) for abuse
protection. **Backend switching, parameter overrides, and server-side export
saves are all allowed** (reversible / capacity-bounded by `EXPORT_MAX_FILES`
+ `EXPORT_MAX_BYTES` / rate-limited). Local full-stack and the `deploy/` cloud
real-WG stack run with `DEMO_MODE` unset (unchanged).

> Note: The WebUI Backend mounts `/var/run/docker.sock:ro` to query container
> state. This is acceptable for a single-host PoC but should not be exposed in
> production.
