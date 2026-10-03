# Build details

Host prerequisites, per-service builds, deployment entry points, the dev
environment and the configuration variables. The README keeps a pointer here.

See also [`../deploy/README.md`](../deploy/README.md) for deploying to a host,
and [`deployment-economics.md`](deployment-economics.md) for what each option
costs and which pages survive it.

### 5.1 Host prerequisites (AlmaLinux 9.7)

`docker-ce` and `docker-compose-plugin` come from Docker's own repository, not
from EPEL, so it is added first:

```bash
sudo dnf install -y epel-release dnf-plugins-core
sudo dnf config-manager --set-enabled crb
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
# WireGuard ships in AlmaLinux 9.7's mainline kernel — only the userspace
# tools are needed; ELRepo's kmod-wireguard is NOT required.
sudo dnf install -y wireguard-tools gcc cmake ninja-build git \
                    python3.12 python3.12-devel openssl-devel libsodium-devel \
                    docker-ce docker-compose-plugin nodejs
sudo modprobe wireguard
echo wireguard | sudo tee /etc/modules-load.d/wireguard.conf
sudo systemctl enable --now docker
sudo usermod -aG docker $USER && newgrp docker
```

This is the development host. The deployment scripts in `deploy/` assume a
different one; see 5.5.

### 5.2 liboqs + oqs-provider (host install, optional)

For the `services/pqc-tls-demo/` sanity check only; the main hybrid pipeline does NOT
require liboqs on the host (Rosenpass is bundled in the node image, and arnika's
PQC-HPKE key agreement is the Go standard library's `crypto/hpke`).

```bash
make build-liboqs
make build-oqs-provider
make pqc-list    # should show ML-KEM-768 etc.
```

### 5.3 WireGuard kernel module fallback

If `modprobe wireguard` fails on your host, **the stack still works and you
need to do nothing.** The node image installs `wireguard-go`, and
`nodes/alice/entrypoint.sh` uses it when the kernel interface cannot be
created:

```sh
if ! ip link add dev "$WG_IFACE" type wireguard 2>/dev/null; then
    userspace="${WG_QUICK_USERSPACE_IMPLEMENTATION:-wireguard-go}"
    "$userspace" "$WG_IFACE"
fi
```

Nothing in this repository invokes `wg-quick`; the fallback is the entrypoint's
own. Confirm the binary is present with:

```bash
docker run --rm --entrypoint wireguard-go pqcqkd/node-alice:local --version
```

No override is needed. `WG_QUICK_USERSPACE_IMPLEMENTATION` can only select a
userspace implementation the image actually contains, and the image ships
`wireguard-go` alone; naming anything else makes the entrypoint exit on a host
without the kernel module, which is exactly the host the fallback is for.

### 5.4 Multi-hop (Alice—Charlie—Bob)

```bash
make up-multihop
```

This launches the `charlie` relay (compose profile `multihop`).

### 5.5 Cloud deployment (single host + TLS)

The scripts in [`deploy/`](../deploy/) target **Ubuntu 22.04 or 24.04** on a
KVM VPS, and both should be treated as Ubuntu-only: they install packages with
`apt-get` and manage the firewall with `ufw`. On a host without `apt-get` they
fail differently. `deploy.sh` runs under `set -euo pipefail`, and its bare
`apt-get update -y` stops the script at the WireGuard step. `deploy-demo.sh`
writes its `apt-get` line as `... || true`, so it carries on and builds. Both
skip the firewall step with a one-line log when `ufw` is absent, so a host that
gets past them can be left with no firewall rules from the script.
To run the full real-WireGuard stack on a supported host behind automatic
HTTPS:

```bash
cp deploy/.env.example .env       # set PUBLIC_HOST + ACME_EMAIL
sudo bash deploy/deploy.sh        # Docker + WireGuard module + UFW + build & up
# or manually:
docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
```

A Caddy reverse proxy is the only public service (80/443, auto Let's Encrypt);
the KME/backend and WireGuard nodes stay on the internal networks. The
privileged WG nodes need a real kernel (fine on a KVM VPS, not on managed PaaS).
See [`deploy/README.md`](../deploy/README.md). Per-dependency licence terms are
in [`docs/THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

### 5.6 Public-demo profile — client-side simulation (near-zero backend load)

The **Quantum-Secure E2E**, **Paper Data Exchange**, **Physics Params** and
**BB84 Live** pages run their simulation **entirely client-side** in the browser
— real HKDF-SHA3-256 + ChaCha20-Poly1305 via [`@noble`](https://github.com/paulmillr/noble-hashes),
the closed-form Lo-Ma key-rate ported to TypeScript, and a **Web Worker**
Monte-Carlo for BB84 (throughput depends on the visitor's device). Optional
WASM, WebGL2 and **WebGPU** tiers are each benchmarked against the Worker and
adopted only when at least 15 % faster (`UPGRADE_MARGIN` in
`services/webui-frontend/src/lib/sim/bb84Sim.ts`); otherwise the Worker keeps
running. No `/ws/*` sockets are opened for these pages, so each visitor runs an
independent sim on their own device and a public multi-user demo puts ~no load
on the server.

```bash
# Sim-only public-demo profile (DEMO_MODE=1, no privileged WG nodes / docker.sock):
docker compose -f docker-compose.yml -f deploy/docker-compose.demo.yml \
  up -d --build bb84-kme-a bb84-kme-b pqc-validator webui-backend webui-frontend
```

What the backend then allows is set by the switches in section 7.1, not by
`DEMO_MODE` alone: the per-IP rate limit on mutating requests (`POST`, `PUT`,
`PATCH`, `DELETE`) is always on, container control is off (`DEMO_MODE` vetoes
it even where `ENABLE_CONTAINER_CONTROL` is set), and live parameter overrides
are off unless `ENABLE_LIVE_PARAM_OVERRIDES` is set, which the demo overlay
does not do. Which pages need the backend at all, and which degrade to
bundled defaults without it, is tabulated once, in
[`deployment-economics.md`](deployment-economics.md).

---

## 6. Dev Environment

Tested on:
- **OS**: AlmaLinux 9.7
- **CPU**: Intel i5-13600K (14C/20T)
- **RAM**: 128 GB DDR5 5200
- **GPU**: NVIDIA RTX 6000 PRO Blackwell 96GB (CUDA 13.0)
  — *GPU is optional*; the BB84 simulator is CPU-bound by design for portability.
  Future Shor-attack-simulator (roadmap A) will leverage CUDA-Q + cuQuantum.
- **Python**: 3.12 in a `.venv` for host-side scripts (tests, benchmarks, manim)
- **Docker**: 24+ with Compose v2
- **WireGuard**: in-tree kernel module (AlmaLinux 9.7 mainline); only
  `wireguard-tools` userspace is installed. Without the module, see 5.3.

Host-side Python venv. The first install line is what CI's `python` job
installs, so `make test` (which runs `pytest tests/` with the venv's
interpreter) has the same imports as CI; the second is optional and only for
the animations and plots:

```bash
python3.12 -m venv .venv
.venv/bin/pip install ruff pytest pytest-asyncio httpx \
    -r services/bb84-kme/requirements.txt \
    -r services/webui-backend/requirements.txt
.venv/bin/pip install manim matplotlib     # optional: animations/, benchmarks/plot_results.py
```

Run helper scripts with the venv's interpreter, either through their `make`
targets or directly as `.venv/bin/python tools/<script>.py`. Their
`#!/usr/bin/env python3` shebang resolves to whatever `python3` is first on the
`PATH`, which on AlmaLinux 9 is the system Python 3.9, not the venv's 3.12.

---

## 7. Configuration

Deployment variables live in `.env` (copy from `.env.example`;
`scripts/check_env_example.sh` checks it covers every mandatory variable).
Compose reads `.env` only to fill in the `${VAR}` references of the compose
files, so a variable reaches a container only where a compose file forwards
it. Every variable in this table is referenced by a compose file.

| Variable | Default | Purpose | Source of truth |
|---|---|---|---|
| `ARNIKA_MODE` | `QkdAndPqcRequired` | One of 4 modes: `QkdAndPqcRequired` / `AtLeastQkdRequired` / `AtLeastPqcRequired` / `EitherQkdOrPqcRequired`. Both peers of a pair must use the same one; `QkdAndPqcRequired` installs a random key when either half is missing | `submodules/arnika/config/config.go` |
| `ARNIKA_INTERVAL` | `30s` | PSK rotation period. arnika's own default is `10s`, and upstream recommends aligning with WireGuard's 120 s rekey; on the WireGuard lane that rekey bounds the key epoch whatever this is set to ([`threat-model.md` §2.1](threat-model.md)). The WireGuard entrypoint also reads it, to start arnika on an interval boundary (7.3), so it must be a Go duration in whole hours, minutes and seconds (`30s`, `2m`, `1m30s`, `1h`). That entrypoint refuses anything else, including `500ms` or `1.5s`, which arnika itself accepts but a whole-second boundary cannot honour | `submodules/arnika/config/config.go` |
| `ARNIKA_ID_*` | `1` / `2` (`4` for charlie) | Per-node ID in the primary election; peers must differ in **parity** | `.env.example` |
| `ARNIKA_PSK` | none | Keys the arnika peer channel (including the PQC-HPKE frames) and the election; must be identical on both peers, at least 32 bytes, and not the `.env.example` placeholder, or the node entrypoints refuse to start. Generate it with `openssl rand -base64 32` | `.env.example` |
| `KMS_HTTP_TIMEOUT` | `10s` | ETSI 014 HTTP timeout | arnika config |
| `WEBUI_BACKEND_PORT` | `8000` | Backend port (host) | docker-compose |
| `WEBUI_FRONTEND_PORT` | `5173` | Frontend nginx port (host) | docker-compose |
| `ENABLE_LIVE_PARAM_OVERRIDES` | `false` | Lets `POST /api/sim/params`, `POST /api/sim/params/reset` and `POST /api/sim/backend` change the running simulator. Off, they return 403 and `/physics` applies edits to the in-browser model only; `GET /api/config` reports it as `live_param_overrides` | `services/webui-backend/app/main.py`, forwarded by `docker-compose.yml` |

**Numeric BB84 tunables are not environment variables.** They come from
`config/qkd_params.yaml`, which `services/bb84-kme/app/config_loader.py`
declares the single source of truth, and which
`tests/test_no_hardcoded_params.py` and
`tests/test_frontend_defaults_match_config.py` enforce. An earlier version of
this table listed seven `BB84_*` variables and an `ETSI_MTLS_ENABLED`, each
naming a Python file as its source of truth; no Python file read any of them.

### 7.1 Backend variables that `.env` does not reach

`services/webui-backend/app/main.py` reads the variables below from its own
environment, but `docker-compose.yml` sets only `KME_A_URL`, `KME_B_URL`,
`PQC_VALIDATOR_URL`, `LOG_LEVEL`, `ARNIKA_INTERVAL` and
`ENABLE_LIVE_PARAM_OVERRIDES` on `webui-backend`. Of these, only
`ARNIKA_INTERVAL` and `ENABLE_LIVE_PARAM_OVERRIDES` come from `.env`; the rest
are fixed service URLs and `LOG_LEVEL=INFO`. **Setting any of the variables
below in `.env` has no effect.** Set them in the `environment:` block of
`webui-backend` in a compose override, as the two overlays in `deploy/` do
(with fixed values, not `${VAR}` references).

| Variable | Default in code | Purpose | Set by |
|---|---|---|---|
| `ENABLE_CONTAINER_CONTROL` | off | Enables `/api/stack/*` container start/stop/restart through the mounted Docker socket. Opt-in, and vetoed by `DEMO_MODE` | no compose file; opting in takes an override |
| `DEMO_MODE` | off | Removes capability for a shared public host: vetoes container control. The demo overlay also runs no privileged WireGuard nodes and mounts no Docker socket. It does not switch the rate limit on or off | `deploy/docker-compose.demo.yml` (`"1"`) |
| `DEMO_RATE_MAX` / `DEMO_RATE_WINDOW_S` | `120` / `60` s | Per-IP token bucket on every `POST`, `PUT`, `PATCH` and `DELETE`; over budget, 429. Always on, whatever `DEMO_MODE` says; the names are kept for compatibility | `deploy/docker-compose.demo.yml`, at the code defaults |
| `EXPORT_MAX_BYTES` | 25 MiB | Largest single file `POST /api/exports/save` accepts (413 above it, or above `EXPORT_MAX_TOTAL_BYTES` if that is smaller) | both `deploy/` overlays, at the code default |
| `EXPORT_MAX_FILES` | `100` | Files kept in the server-side export store; the oldest are deleted first | both `deploy/` overlays, at the code default |
| `EXPORT_MAX_TOTAL_BYTES` | 512 MiB | Total size of the export store; the oldest files are deleted first | no compose file |
| `STATS_TTL_S` | `1.0` s | Cache lifetime of `GET /api/stats`, which `/benchmarks` polls once a second, so any number of viewers costs one KME sample per second | no compose file |
| `PQC_AGILITY_ERROR_TTL_S` | `10.0` s | How long a failed validator call behind `POST /api/pqc/agility` is cached, so an unreachable validator does not cost every viewer a full timeout. A successful matrix is cached for `PQC_AGILITY_TTL_S`, default `300.0` s | no compose file |

The remaining cache and size knobs follow the same pattern and have their
defaults beside the line that reads them in `main.py`: `STACK_TTL_S`,
`LOGS_TTL_S`, `LOGS_MAX_TAIL`, `KEYRATE_TTL_S`, `VPN_SAMPLE_TTL_S`,
`VPN_ROTATION_TTL_S`, `VPN_ROTATION_WINDOW_MAX_S`, `WG_SHOW_TTL_S` (the
per-node cache of `GET /api/wg/{node}`, 5 s by default) and `EXPORT_DIR`.

The three boolean switches (`ENABLE_LIVE_PARAM_OVERRIDES`,
`ENABLE_CONTAINER_CONTROL`, `DEMO_MODE`) accept `1`, `true`, `yes` or `on`
(any case) as on; anything else, including unset, is off.

### 7.2 arnika and the two WireGuard interfaces

Set in the environment of the node containers (`alice` and `bob`, and
`charlie` in the multi-hop overlay; for arnika also `alice-ipsec` and
`bob-ipsec`). The addresses and ports below are the defaults; `wg1`'s endpoint
is always the peer's `wg0` address, so `wg1` traffic travels inside `wg0`.

| Variable | Default | Purpose | Source of truth |
|---|---|---|---|
| `PQC_ENABLED` | `true` on every arnika instance | Turns on arnika's PQC-HPKE key agreement with its peer (HPKE, RFC 9180, with MLKEM1024-P384). arnika treats any value other than the exact string `true` as off, and a PQC-requiring `MODE` then refuses to start. Both peers must match | `submodules/arnika/config/config.go` |
| `PQC_ROUND_INTERVAL`, `PQC_ROUND_TIMEOUT`, `PQC_MAX_KEY_AGE` | arnika's: the rotation interval, a quarter of it, and twice the round interval (30 s, 7.5 s and 60 s at `ARNIKA_INTERVAL=30s`) | Cadence and staleness of the PQC-HPKE rounds; this repository relies on the defaults. `PQC_ROUND_INTERVAL` must match on both peers | `submodules/arnika/config/config.go` |
| `LOG_LEVEL` (arnika) | `info` | arnika logs through `log/slog`; the VICI adapter's `PPK rotated` lines are emitted at INFO, so `warn` or `error` would hide the rotations the WebUI counts | `submodules/arnika/logging.go` |
| `WG1_ALICE_IP` / `WG1_BOB_IP` | `10.0.1.1` / `10.0.1.2` (`/24`) | Addresses of the `wg1` data tunnel. `wg0` keeps `10.0.0.1` and `10.0.0.2` | `docker-compose.yml`, read by `nodes/alice/entrypoint.sh` |
| `WG1_LISTEN_PORT_ALICE` / `WG1_LISTEN_PORT_BOB` | `51830` / `51831` | `wg1`'s UDP ports, reached through `wg0` | `docker-compose.yml`, read by `nodes/alice/entrypoint.sh` |
| `WG1_CHARLIE_IP` / `WG1_LISTEN_PORT_CHARLIE` | `10.0.1.3` (`/24`) / `51832` | charlie's `wg1` address and port in the multi-hop overlay. alice lists charlie in `WG1_EXTRA_PEERS` and reaches this port at charlie's `wg0` address, so the charlie leg's `wg1` runs inside that leg's `wg0`, keyed by alice's and charlie's Rosenpass | `docker-compose.multihop.yml`, read by `nodes/alice/entrypoint.sh` |
| `RP_LISTEN_PORT` | `9997` | Rosenpass's UDP port, bound on the node's `wg0` address, so the exchange runs through the hop tunnel. Of each pair, only the node with the lower `wg0` address initiates, to the peer's `wg0` address on this port; the other end only answers, to the address the initiator's packets come from (`rp_peer_entry` in `nodes/alice/entrypoint.sh`). With both ends initiating, every cold start measured locally left the two ends on different `wg1` keys for 120 s. The answering end never initiating is a property of the pinned rosenpass v0.2.3, not a documented interface, so a Rosenpass bump has to re-check it | `docker-compose.yml`, read by `nodes/alice/entrypoint.sh` |

`PQC_PSK_FILE`, through which arnika read Rosenpass's output file until
release 0.2.0, is gone: the pinned arnika ignores it, and no compose file or
entrypoint sets it.

### 7.3 Starting arnika on the interval boundary

Only the WireGuard lane does this. `nodes/alice/entrypoint.sh` waits once,
before it starts any of its arnika instances (one per `wg0` neighbour), until
the next wall-clock multiple of `ARNIKA_INTERVAL`. With both containers of a
pair past that point within the same interval, the two arnika tickers fire
within milliseconds of each other. `nodes/strongswan/entrypoint.sh` starts the
IPsec lane's arnika without that wait, on purpose.

**Why the WireGuard lane waits.** Because of two properties of the pinned
arnika (`f4cf9ba`). Each process counts intervals from its own start
(`main.go:327-333`), and the role election is an HMAC of that count. And under
`QkdAndPqcRequired` a BACKUP whose interval ends with no `key_id` from its
peer logs `no key_id from the peer` and installs a random key
(`main.go:409-418`), where the previous pin kept the superseded key installed
and logged nothing. Until release 0.2.0 the WireGuard entrypoint started
arnika only once Rosenpass's first key existed, which happened on both nodes
almost at once, so the two processes started together as a side effect. From
0.2.0 on arnika no longer waits for Rosenpass, and the offset between two
container starts became the offset between two interval counters. In short
local runs without the alignment, the later-started node repeatedly logged
`no key_id from the peer` and invalidated its tunnel at the end of a BACKUP
interval, leaving the two ends on different keys for about 0.4 to 0.9 s each
time: at the end of 13 of its 21 BACKUP intervals over three WireGuard runs,
and twice in the one IPsec run described below. That is an observation, not a
measurement. The wait restores the start synchronisation the old start order
gave on this lane, which is not the lane the before/after measurement
compares.

**Why the IPsec lane does not.** Its entrypoint starts arnika as soon as the
connection is loaded, as at v0.1.0, when the lane's two nodes were never
aligned: compose started them together, about 30 ms apart on the public demo
host. The 168-hour before/after measurement compares this lane
([`vici-ppk.md`](vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race)),
as a pure port plus a measurement with any mitigation left for later, so both
arms run the same entrypoint start behaviour. The start offset itself is not
assumed equal between the arms: arm B, at the new pin, also drops the IPsec
nodes' `depends_on` on the WireGuard nodes, which changes the order in which
compose starts them, so the offset is measured in each arm (below). Whatever
the new fail-closed path for an interval without a `key_id` does under that
offset is a finding to measure, not something to hide with a start change
made in one arm only.

**Alignment fixes the offset only at the start.** Each arnika ticker re-bases
after its own processing: the loop resets it at its top (`main.go:331`),
after the previous tick and whatever the end of that interval did, so each
node's boundaries move later by its own processing time, and the offset
between the two ends of a pair wanders by milliseconds per interval. The
offset matters because of when the PRIMARY sends its `key_id`: at the next
whole second after its own boundary plus its KMS fetch (`main.go:348-351`),
and only once it has built its PSK (`main.go:369`). For each tick, let
$`d`$ be the BACKUP's boundary minus the PRIMARY's, and $`t_{\mathrm{KMS}}`$
the PRIMARY's KMS fetch time. For $`d`$ below about a second, the chance that
the PRIMARY's `key_id` reaches the BACKUP before the BACKUP's own boundary
("early") is roughly $`\min(1, \max(0, d - t_{\mathrm{KMS}}) / 1\,\mathrm{s})`$,
if over a long run the fraction of a second at which the fetch ends is spread
evenly; the send also waits for the PSK build, which lowers it a little. An early `key_id` is
counted in the BACKUP's previous interval. The BACKUP fails closed at the end
of the current interval only if the next interval's `key_id` is not early
too, which in practice means at its BACKUP-to-PRIMARY transitions: while it
stays BACKUP, the next early `key_id` fills the interval the previous one
left empty. All of this is an inference from the code, not a measurement. It
concerns both lanes: the IPsec lane from its start offset on, and the
WireGuard lane once drift has moved its offset past the fetch time.

The one local observation of it is an unaligned run of the IPsec lane on
2026-09-26, about 6 minutes long, with bob's arnika started about 0.25 s
after alice's. Each node's boundary moved by 0 to 12 ms per interval, and the
offset between the two went from about 255 ms to about 217 ms over 12
intervals. bob received early `key_id`s in intervals 2 to 8, 10 and 11, and
invalidated only at the end of intervals 8 and 11, each followed by an
interval in which bob was PRIMARY. One short run: an observation, not a
measurement.

Two more cases that neither lane's start timing covers:

- **A node restarted on its own.** Its count starts again at 0 while its
  peer's has kept running (on the WireGuard lane it starts on a boundary
  again, but that does not help). The election hashes the count, so the two
  ends then elect the same role in about half of the intervals, and in each
  interval where both come out BACKUP both ends fail closed.
- **A straddled boundary, on the WireGuard lane only.** If the two containers
  of a pair reach the alignment on either side of a boundary, they start one
  or more intervals apart, with the same result as a restart; two containers
  that arrive $`s`$ seconds apart do so with a probability of about $`s / T`$
  for an interval of $`T`$ seconds.

Both are inferences from the code, not measurements. This is arnika #51's
behaviour rather than this deployment's, and it is to be raised on #51
together with a measurement ([`roadmap.md`](roadmap.md), "Follow-ups from
adopting arnika #51"). Neither lane's start timing is a mitigation of the
IPsec lane's PPK ordering race, and nothing claimed about that race depends on
it
([`vici-ppk.md`](vici-ppk.md#2026-09-26-arnika-51-head-what-changes-for-the-rotation-race)).

**What the measurement records.** A boundary is the line each arnika logs as
an interval starts: `waiting for a key_id from the peer` on a BACKUP, and
`requesting a new QKD key` on a PRIMARY, whose interval number comes from the
`serving this interval` line after its KMS fetch (at the pinned commit). For
the IPsec pair, `scripts/ppk_race_report.py` reads the two nodes' logs and
prints, beside the `no key_id from the peer` invalidations: the offset
between the two ends' boundaries (its size, trend and change from tick to
tick), each PRIMARY's KMS fetch time, the ticks whose interval numbers differ
(the restart or straddle case) or whose two ends hold the same role, and how
many `key_id`s arrived before the receiver's own boundary. For equal time
segments of the window it puts the early `key_id`s and the BACKUP intervals
that ended in that invalidation beside the median offset, and its JSON
output also keeps these tick by tick, so that the inference above can be
checked against numbers. The report's offset is signed, bob's boundary minus
alice's, so $`d`$ above is that offset in ticks where alice is PRIMARY and
its negative in ticks where bob is. The report covers the IPsec pair only. No
tool records the WireGuard lane's boundaries yet: there the same lines, with
their `interval=N`, are compared by hand between the two nodes' logs.

**Operating rule: the two nodes of a pair are always recreated together**,
in one `docker compose up -d --force-recreate` naming both (`alice` and
`bob`, or `alice-ipsec` and `bob-ipsec`), never one alone.
