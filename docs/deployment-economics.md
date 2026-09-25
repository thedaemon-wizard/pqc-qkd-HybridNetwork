# Deployment economics

What it costs to host this demo, and which pages survive each option.

The simulation work in this project runs in the browser, so the interesting
question is not "how big a server" but "how little server". This document
answers that with the page-by-page reality rather than a slogan.

Reviewed 2026-09-25: the route table below was re-read against every page's
fetch calls on that date.

---

## 1. Which pages actually need a backend

Measured by reading every page's fetch calls, including the ones routed through
`services/webui-frontend/src/api.ts`. This table is the one place that
records it; other documents link here. An earlier claim that a static
deployment "disables only `/verify`" was wrong by five pages: six routes need
the backend, not one.

| Route | Backend calls | Static-only behaviour |
|---|---|---|
| `/e2e` | none during a run (exports aside) | **Fully works.** Real HKDF-SHA3-256 and ChaCha20-Poly1305 in-browser |
| `/paper-flow` | none during a run (exports aside) | **Fully works.** Includes the AEAD payload and failure cascade |
| `/keyflow` | none (exports aside) | **Fully works** (static diagram) |
| `/hil` | none | **Fully works** (static) |
| `/protocol-lab` | none during a run (exports aside) | **Fully works.** Relay, re-routing and the ETSI 014 / 004 timeline are simulated in the browser from published data |
| `/bb84` | `GET /api/sim/params` once at mount | **Works**, falls back to bundled defaults |
| `/pqc` | `GET /api/pqc/algorithms`, `POST /api/pqc/roundtrip`, `POST /api/pqc/interop` | **Works client-side**; the liboqs cross-checks are skipped and the UI says so |
| `/physics` | `GET /api/sim/params/editable`, `GET /api/stats` and `GET /api/sim/params` (5 s poll), `GET /api/stack` (5 s poll, so the two backends that forward to `qkdnetsim-kme` are offered only while it runs), `GET /api/config`; `POST /api/sim/params`, `POST /api/sim/params/reset` and `POST /api/sim/backend` only where live overrides are enabled | **Works**: the form falls back to bundled defaults, and the key rate and optimiser run in the browser. Apply and Reset change only the in-browser model, as they do on any backend with live overrides off; the backend selector is disabled. See [`webui-pages.md`](webui-pages.md#server-side-switches) |
| `/` | `GET /api/stack` (3 s poll), `GET /api/config`; `GET /api/logs/download/webui-backend?lines=1000` (Logs export only) | Degrades: container status is empty, and the Logs export fails |
| `/benchmarks` | `GET /api/stats` (1 s poll); `GET /api/logs/download/alice?lines=1000` (Logs export only) | Degrades: no live statistics, and the Logs export fails |
| `/console` | `GET /api/logs/<name>` (1.5 s poll) | Degrades: no container logs |
| `/topology` | `GET /api/topology` | Degrades: no graph data |
| `/vpn` | `GET /api/vpn/protocols` (5 s poll, served from a 5 s server-side sample cache), `GET /api/vpn/ppk-rotations?window_s=600` (30 s poll) | Degrades: no lane status and no rotation counts |
| `/verify` | `POST /api/pqc/agility`, `GET /api/verify/keyrate`, `GET /api/verify/paper-budgets` | Degrades: no server evidence; the browser half of the agility cross-check still runs |

**Five routes need no backend call besides the optional export copy below.
Three more work without one, on bundled defaults or without their server
cross-check. Six need the backend for their content.**

Thirteen of the fourteen pages carry an export toolbar (all but `/hil`). Every
file except the server-log download on `/` and `/benchmarks` is built in the
browser and delivered from memory. On those two pages the Logs button fetches
the tail of a server-side log (`webui-backend.log`, and the `alice.log` that
`bb84-kme-a` writes) through `GET /api/logs/download/<service>`, so it is the
one export that needs the backend. The toolbar sends `POST /api/exports/save`
only when the visitor ticks "copy to shared gallery", which is off by default,
and `GET /api/exports/list` only when the Saved-exports picker is opened.
Neither is needed for the export itself.

The four pages that carry the project's actual argument — the E2E hybrid
exchange, the paper reproduction, BB84 and the PQC validator — all work
without a backend. That is what makes a near-zero-cost deployment worth
considering.

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

Loses the six backend pages above.

### B. Static edge plus a small backend

Serve `dist/` from a static host and run only `webui-backend` (plus
`bb84-kme-a/b` and `pqc-validator` if `/verify` matters) on a small VPS,
pointing the frontend's `/api` at it via CORS or a proxy.

This keeps all fourteen pages and moves the bandwidth — the part that scales
with visitors — off the metered host. A single-region VPS cannot match a
300-plus-location edge for static delivery, so paying a VPS to serve bundles is
the wrong way round; paying it to serve the handful of API calls is not.

### C. Everything on one VPS

The full stack on one machine: simplest to reason about, one TLS certificate.
Reasonable while the demo is small; the cost grows with traffic because the
bundle is served from it.

**This is the full stack, not the sim-only demo profile**, and it has to be
sized as one. The requirements are the full-stack ones from
[`../deploy/README.md`](../deploy/README.md): **≥4 GB RAM** (8 GB to build
everything on-box) and **~15 GB free disk**, because `pqc-validator` builds
liboqs and `bb84-kme` builds Python wheels. On a smaller box the first build is
OOM-killed or fills the disk, leaving a broken image. The 2 GB RAM and 8 GB
disk that apply to the sim-only demo profile are `deploy/deploy-demo.sh`'s
figures, not these.

**One consequence worth stating.** The full profile mounts the Docker socket
read-only into `webui-backend`, which serves an unauthenticated HTTP API, so
that `/api/stack` can enumerate containers and `/api/logs` can read them.
Container *control* is off unless explicitly enabled
([`webui-pages.md`](webui-pages.md#server-side-switches)); container
*enumeration* is not. That suits a demo whose purpose is to show the lanes
running, and is not a default to carry into a deployment where the host
matters. Removing the socket from the internet-facing process is on the
[`roadmap.md`](roadmap.md) list of deferred items.

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
- **Exports download from memory first.** `services/webui-frontend/src/lib/exporters.ts`
  hands the file to the browser, and posts a copy to `/api/exports/save` only
  when the visitor asked for one; that copy only feeds the Saved-exports
  picker, which a static-only deployment lacks. The exception is the Logs
  button on `/` and `/benchmarks`, whose file is a server log and so comes
  from `GET /api/logs/download/<service>`.
- **The server-side switches matter if a backend is public.** Live parameter
  overrides and container control are both off by default, and the rate limit
  is always on; what each switch does is in
  [`webui-pages.md`](webui-pages.md#server-side-switches).
