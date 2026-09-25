# Cloud deployment (`deploy/`)

Artifacts to run the **full real-WireGuard stack** (all 7 services, including
the privileged `alice`/`bob` WireGuard nodes) on a single public host with
automatic TLS.

**Host requirement: Ubuntu 22.04 or 24.04 on a KVM virtual machine with
root.** Treat both scripts as Ubuntu-only: they install packages with
`apt-get` and manage the firewall with `ufw`. On a host without `apt-get` they
fail differently. `deploy.sh` runs under `set -euo pipefail`, so its bare
`apt-get update -y` stops it at the WireGuard step; `deploy-demo.sh` writes its
`apt-get` line as `... || true` and carries on. Both skip the firewall step
with a one-line log when `ufw` is absent. The runtime switches the backend
reads (`DEMO_MODE`, `ENABLE_LIVE_PARAM_OVERRIDES`, the rate limit and the
export-store bounds), and which of them `.env` can set, are in
[`../docs/BUILD.md` section 7](../docs/BUILD.md#7-configuration).

| File | Purpose |
|---|---|
| `docker-compose.cloud.yml` | Overlay: adds a Caddy reverse proxy (the only public service, 80/443), restart policies and a bound on the server-side export store. Use with the base compose. |
| `docker-compose.demo.yml` | **Public-demo profile** (sim-only): `DEMO_MODE=1` (container control vetoed), no privileged WG nodes and no `docker.sock` mount. The E2E / Paper / Physics / BB84 pages run **client-side** (browser JS + Web Worker/WebGPU, real `@noble` crypto); live parameter overrides stay off, as on every host that does not set `ENABLE_LIVE_PARAM_OVERRIDES=true`. |
| `Caddyfile` | Caddy config: auto-HTTPS for `$PUBLIC_HOST`, proxies to `webui-frontend`. |
| `deploy.sh` | Bootstrap for the **FULL** real-WireGuard stack (Docker, WG module, IP forwarding, UFW, **swap**, build & up). Heavy: needs **≥4 GB RAM / ~15 GB disk** + a real kernel. |
| `deploy-demo.sh` | Bootstrap for the **lighter public-demo** profile (sim-only, no privileged WG nodes). Recommended for a public demo. |
| `lib.sh` | Routines both scripts share: the `--pull` update and the UFW rules. |
| `caddy.d/` | Host-owned Caddy site drop-ins (`*.caddy`, gitignored), imported by the `Caddyfile`. Extra sites on the same host go here, never into the tracked `Caddyfile`. |
| `.env.example` | Copy to repo-root `.env`; set `PUBLIC_HOST`, `ACME_EMAIL`, backend profile, ports. |

## Note: Which deploy do I want? (read this first)

- **`deploy/deploy.sh` — FULL real-WireGuard stack.** Builds liboqs + **rosenpass (Rust)** +
  **strongSwan** from source for the privileged `alice`/`bob` nodes. **Requires a real kernel and
  ≥4 GB RAM (8 GB to build everything on-box) + ~15 GB free disk.** On a smaller box the first build
  is OOM-killed / fills the disk, so a container such as `bb84-kme` ends up with a broken image and
  **"fails to start"** — which then aborts everything that depends on it
  (`Error dependency bb84-kme-a failed to start`). To reduce this risk `deploy.sh` adds a 4 GB
  swapfile when the host has under 4 GB of RAM and less than about 2 GB of swap.
- **`deploy/deploy-demo.sh` — public DEMO (recommended).** No privileged WG nodes, no rosenpass/
  strongSwan build. The four simulation pages run **client-side**, so the backend is tiny (just
  `webui-backend` in `DEMO_MODE` + `bb84-kme` + `pqc-validator` for `/verify`). Runs on a small box.

```sh
cp deploy/.env.example .env   # set PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy-demo.sh
```

**Leanest (near-$0):** build the frontend
(`cd services/webui-frontend && npm ci && npx vite build`) and serve `dist/` statically.
Some pages then work unchanged, some fall back to bundled defaults, and some
need the backend; which is which, page by page, is kept in one place:
[`../docs/deployment-economics.md`](../docs/deployment-economics.md), with the
current hosting costs.

### Troubleshooting "Error dependency bb84-kme-a failed to start"
`bb84-kme-b` (and `alice`/`bob`) only report this because they **depend on `bb84-kme-a`** — the real
failure is that **`bb84-kme-a` itself did not come up**. Two distinct causes, in likelihood order:

1. **A QKD-backend submodule was empty when the image was built, or the configured backend fails at runtime.**
   The KME default backend is **`simqn`** in `config/qkd_params.yaml`, but **this deploy overrides it to `cvqkd`** in `deploy/.env.example` (`SIMULATOR_BACKEND`), and the env var wins (`docker-compose.yml` reads `${SIMULATOR_BACKEND:-}`). Diagnose against the backend actually configured.
   The bb84-kme image installs SimQN / SeQUeNCe / Strawberry Fields / TNO from `submodules/` at build
   time, and each install must succeed: an empty submodule (clone failed, or cloned without
   `--recurse-submodules`) fails the **build**, with pip's error, rather than producing an image
   without that backend. `deploy.sh` and `deploy-demo.sh` run
   `git submodule update --init --force --recursive` on all four before building and stop the deploy
   if that fails.

   | `SIMULATOR_BACKEND` | Submodule it needs |
   |---|---|
   | `cvqkd` (the deploy default) | `submodules/strawberryfields` |
   | `simqn` (the config default) | `submodules/SimQN` |
   | `sequence` | `submodules/SeQUeNCe` |
   | `tno` | `submodules/tno-qkd-key-rate` |
   | `qutip` | none |

   - **(a) Populate the submodule and rebuild.** For the deploy default:
     ```sh
     git submodule update --init --force --recursive submodules/strawberryfields
     ls submodules/strawberryfields/setup.py        # must exist
     docker compose ... up -d --build --force-recreate bb84-kme-a bb84-kme-b
     ```
   - **(b) Run on the built-in `qutip` backend.** If the image built but the configured backend fails
     when the KME starts, `qutip` (in `requirements.txt`, no submodule) always constructs. Set the
     override and recreate the KMEs:
     ```sh
     SIMULATOR_BACKEND=qutip docker compose -f docker-compose.yml \
       -f deploy/docker-compose.cloud.yml up -d --force-recreate bb84-kme-a bb84-kme-b
     ```
     The Physics page's backend selector reaches the live KMEs only where
     `ENABLE_LIVE_PARAM_OVERRIDES=true`, which `deploy/.env.example` keeps false.
   - **(c) Runtime fallback.** With no override, `KeyPool.__init__` degrades a backend whose
     constructor raises to `qutip` and logs an error naming it, so the KME does not die on boot.
     (a)/(b) are preferred because they make the choice explicit rather than silent.
2. **Build OOM / out-of-disk (only on a genuinely small box).** A box with ≥4 GB RAM + ~15 GB disk is
   not affected; `deploy.sh` also auto-adds swap. Irrelevant on a larger host.

Diagnose the actual error (don't guess):
```sh
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml build bb84-kme-a   # real build error
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml logs bb84-kme-a    # real runtime error
free -m && df -h /                                                                        # rule out RAM/disk
```

## Quick start (VPS)

```sh
git clone --recurse-submodules <repo> pqc-qkd-hybrid
cd pqc-qkd-hybrid
cp deploy/.env.example .env      # edit PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy.sh
```

Then add a DNS **A record** for `PUBLIC_HOST` → the VPS public IP. Caddy
obtains a Let's Encrypt certificate automatically and serves the WebUI at
`https://$PUBLIC_HOST`.

## Redeploying an existing host

The quick start above is a **first-time** install. To update a host that is
already running, use `--pull`:

```sh
cd ~/pqc-qkd-hybrid
sudo bash deploy/deploy-demo.sh --pull      # simulation-only demo
sudo bash deploy/deploy.sh --pull --ipsec   # full stack, with the IPsec lane
```

Both scripts share the routine in `deploy/lib.sh`; `--ipsec` adds
`docker-compose.strongswan.yml` with the `ipsec` profile.

`--pull` fetches `origin/main`, fast-forwards, re-syncs submodules, then
rebuilds and restarts. Without the flag the script builds whatever is already
in the working tree, which is what you want when you have applied a local
hotfix and do not want it discarded.

Deliberate properties, because this runs as root on a live host:

- **Opt-in.** Updating is never implicit. `.env` and any local change live in
  the working tree, and moving `HEAD` underneath them silently is how a
  redeploy becomes an outage.
- **Preserves local modifications.** They are reported, not treated as a
  blocker. `git merge --ff-only` already refuses precisely when it matters --
  when the incoming commits would overwrite a locally-modified file -- and it
  names those files exactly. Blocking on *any* dirty file instead was tried and
  removed: a host with any deliberate local edit could then not be updated by
  the script at all, which pushes the operator into running git by hand -- less
  safe than the script. Host-specific Caddy sites no longer need such an edit;
  they belong in `deploy/caddy.d/`, which is gitignored.
- **Fast-forward only.** A merge or rebase could conflict and leave the tree
  half-updated with nobody at the keyboard.
- **Prints the range.** The commits between the old and new `HEAD` are logged,
  so what actually shipped is in the deploy output.

Override the branch with `DEPLOY_BRANCH=dev sudo -E bash deploy/deploy-demo.sh --pull`.

To confirm the update landed, check that the served bundle hash changed:

```sh
curl -s https://$PUBLIC_HOST/ | grep -o '/assets/index-[^."]*'
```

## The firewall step

Both scripts **add** UFW rules for the SSH port(s) `sshd -T` reports, 80/tcp,
443/tcp and 443/udp, and keep every other rule. They used to run `ufw --force
reset` first, which deleted whatever else the host had -- another site's
ports, or SSH on a non-standard port -- on every redeploy. The default-deny
policy is set only when UFW was inactive, i.e. when the script is the one
turning the firewall on. `SKIP_UFW=1` leaves the firewall untouched.

## Why a virtual machine (not managed PaaS)

The real WireGuard end-to-end tunnel needs the `wireguard` kernel module and
privileged containers (`NET_ADMIN`/`SYS_MODULE`, `/dev/net/tun`). A KVM
virtual machine with root provides this; a managed container platform that
runs unprivileged containers on a shared kernel cannot.

## Local smoke test (through Caddy, plain HTTP)

```sh
PUBLIC_HOST=":80" ACME_EMAIL="" \
  docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
# WebUI now reachable via the proxy at http://localhost/
```

> Per-dependency licence terms are in
> [`../docs/THIRD_PARTY_NOTICES.md`](../docs/THIRD_PARTY_NOTICES.md).
