# Deployment economics

What it costs to host this demo, and which pages survive each option.

The simulation work in this project runs in the browser, so the interesting
question is not "how big a server" but "how little server". This document
answers that with the page-by-page reality rather than a slogan.

Reviewed 2026-08-21.

---

## 1. Which pages actually need a backend

Measured by reading every page's fetch calls, including the ones routed through
`services/webui-frontend/src/api.ts`. This table is the thing to keep accurate;
an earlier claim that a static deployment "disables only `/verify`" was wrong by
seven pages.

| Route | Backend calls | Static-only behaviour |
|---|---|---|
| `/e2e` | none | **Fully works.** Real HKDF-SHA3-256 and ChaCha20-Poly1305 in-browser |
| `/paper-flow` | none | **Fully works.** Includes the AEAD payload and failure cascade |
| `/keyflow` | none | **Fully works** (static diagram) |
| `/hil` | none | **Fully works** (static) |
| `/bb84` | `GET /api/sim/params` once at mount | **Works**, falls back to bundled defaults |
| `/pqc` | `GET /api/pqc/algorithms`, `POST /api/pqc/roundtrip` | **Works client-side**; the server cross-check is skipped and the UI says so |
| `/` | `GET /api/stack` (3 s poll) | Degrades: container status is empty |
| `/benchmarks` | `GET /api/stats` (1 s poll) | Degrades: no live statistics |
| `/console` | `GET /api/logs/<name>` (1.5 s poll) | Degrades: no container logs |
| `/topology` | `GET /api/topology` | Degrades: no graph data |
| `/vpn` | `GET /api/vpn/protocols` (3 s poll) | Degrades: no lane status |
| `/physics` | 5 endpoints, incl. 5 s poll | Degrades: stuck on "Loading parameters…" |
| `/verify` | `/api/pqc/agility`, `/api/verify/keyrate`, `/api/verify/paper-budgets` | Degrades: no verification evidence |

**Six of thirteen routes are fully self-contained. Seven need the backend.**

The four pages that carry the project's actual argument — the E2E hybrid
exchange, the paper reproduction, BB84 and the PQC validator — are all in the
first group. That is what makes a near-zero-cost deployment worth considering.

---

## 2. Options

### A. Static only

Build `services/webui-frontend` and serve `dist/`:

```sh
cd services/webui-frontend && npm ci && npx vite build
```

Cost is effectively zero. Cloudflare Pages is the notable option here because,
as of 2026, its free tier is the only one among the major static hosts that
does **not** meter bandwidth and charges no egress — which suits a demo whose
compute happens on the visitor's machine and whose only server cost is shipping
a bundle. GitHub Pages and Netlify are equivalent in function with metered
bandwidth.

Requires SPA fallback (rewrite unknown paths to `index.html`); the router uses
real paths, not hashes. Without it, deep links such as `/paper-flow` return 404
on reload.

Loses the seven backend pages above.

### B. Static edge plus a small backend

Serve `dist/` from a static host and run only `webui-backend` (plus
`bb84-kme-a/b` and `pqc-validator` if `/verify` matters) on a small VPS,
pointing the frontend's `/api` at it via CORS or a proxy.

This keeps all thirteen pages and moves the bandwidth — the part that scales
with visitors — off the metered host. A single-region VPS cannot match a
300-plus-location edge for static delivery, so paying a VPS to serve bundles is
the wrong way round; paying it to serve the handful of API calls is not.

### C. Everything on one VPS

What the public demo runs. Simplest to reason about, one machine, one TLS
certificate. Reasonable while the demo is small; the cost grows with traffic
because the bundle is served from it.

**It is the FULL stack, not the sim-only demo profile.** This section used to
say it was "what `deploy/deploy-demo.sh` does today" and sized it accordingly.
Measured against the running host: `/api/config` reports `demo_mode: false`, and
`/api/stack` enumerates ten containers including both privileged WireGuard nodes
(`alice`, `bob`) and both strongSwan nodes (`alice-ipsec`, `bob-ipsec`).

Requirements are therefore the full-stack ones from
[`../deploy/README.md`](../deploy/README.md): **≥4 GB RAM** (8 GB to build
everything on-box) and **~15 GB free disk**, because `pqc-validator` builds
liboqs and `bb84-kme` builds Python wheels. On a smaller box the first build is
OOM-killed or fills the disk, leaving a broken image.

The figures previously given here — 2 GB RAM and 8 GB disk — were attributed to
`deploy/README.md`, which contains neither. They are `deploy/deploy-demo.sh`'s
demo-profile numbers, so this section sized the deployed system at roughly half
its documented requirement while citing a file that says otherwise.

**One consequence worth stating.** The full profile mounts the Docker socket
into `webui-backend`, which is reachable from an unauthenticated HTTP surface.
Container *control* is disabled on the public host — `/api/config` reports
`container_control: false` and `POST /api/stack/{action}/{name}` answers 403 —
but container *enumeration* is not; `/api/stack` is the command used above.
That is a deliberate choice for a demo whose purpose is to show the lanes
running, and not a default to carry into a deployment where the host matters.

---

## 3. Recommendation

**B**, unless `/verify` and the live container views are unnecessary, in which
case **A** costs nothing.

The reasoning is not about price alone. The pages that demonstrate the
cryptography need no server, so serving them from an edge is both cheaper and
faster. The pages that need a server are operational views — container status,
logs, live statistics — which are interesting to an operator and largely
uninteresting to a visitor evaluating the research.

Splitting on that line means visitor traffic never touches the VPS, and the VPS
can be sized for one user rather than for the internet.

---

## 4. What must not be assumed

- **The client-side pages are genuinely client-side.** Verified by recording the
  resource timeline during a run on `/e2e` and `/paper-flow`: zero `/api` and
  zero WebSocket requests. `VERIFICATION_CHECKLIST.md` item 4.6.2 asserts this
  with a command, so it stays true.
- **Exports currently round-trip through the backend.** `saveToBackendAndDownload`
  in `services/webui-frontend/src/lib/exporters.ts` POSTs each artefact to
  `/api/exports/save` before handing it to the user, falling back to a local
  blob only on failure. On a static-only deployment every export takes the
  fallback path. That works, but it means option A silently loses the saved-
  exports gallery, and the code should arguably not assume a backend at all.
- **`DEMO_MODE` matters if a backend is public.** It disables container control
  and rate-limits POSTs. See `deploy/docker-compose.demo.yml`.
