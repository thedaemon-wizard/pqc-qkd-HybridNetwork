"""WebUI Backend — FastAPI orchestrator.

Endpoints:
    GET  /api/health
    GET  /api/stack          : container status (alice/bob/bb84-kme-*)
    GET  /api/stats          : aggregated KME + arnika stats
    GET  /api/logs/{name}    : last N log lines from a container
    GET  /api/wg/{node}      : redacted `wg show wg0` for the node. NOT `dump`:
                               that form emits the interface private key and the
                               preshared key in plaintext. See WG_SHOW_CMD.
    POST /api/stack/{action}/{name} : start|stop|restart a service
                             ^^^^^^^ the {name} segment is not optional. Omitting
                             it here is what made scripts/verify-demo-hardening.sh
                             probe a route that does not exist and pass on the 404.
    GET  /api/topology       : graph nodes/edges for D3

    This module serves no bench route, and never has. The ping benchmark is
    `benchmarks/ping_loop.sh` (run by `make bench`), a shell script that does
    `docker exec alice ping` and writes benchmarks/results/ping_*.log; nothing
    ever wrapped it in a handler. The index above advertised such a route from
    the initial commit, and it answered 404 on the live demo the whole time.
"""
from __future__ import annotations

import os
import re
import time
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

try:
    import docker
    _docker_available = True
except ImportError:
    _docker_available = False

from . import logging_setup, paper_budgets

log = logging_setup.configure("webui-backend")

KME_A_URL = os.environ.get("KME_A_URL", "http://bb84-kme-a:8080")
KME_B_URL = os.environ.get("KME_B_URL", "http://bb84-kme-b:8080")
PQC_VALIDATOR_URL = os.environ.get("PQC_VALIDATOR_URL", "http://pqc-validator:8090")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=4.0)
    if _docker_available:
        try:
            app.state.docker = docker.from_env()
        except Exception as e:
            log.warning("docker SDK init failed: %s", e)
            app.state.docker = None
    else:
        app.state.docker = None

    # The /e2e and /paper-flow orchestrators used to start here. Both pages
    # moved to client-side simulation, nothing has called their endpoints
    # since, and the only thing still reading them was the static budget dict
    # now in `paper_budgets`. Two background tasks per process, for nothing.

    yield
    await app.state.http.aclose()


app = FastAPI(title="PQC-QKD WebUI Backend", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------- Public-demo hardening (DEMO_MODE) -----------------------
def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")

# When DEMO_MODE is on (public multi-user host) the demo is functionally
# EQUIVALENT to full mode EXCEPT the one genuinely dangerous operation —
# container lifecycle control (/api/stack/*), which could take the shared demo
# offline — and a per-IP token-bucket rate-limit on POSTs (abuse protection).
# Backend switching, parameter overrides and (bounded) server-side export saves
# are all ALLOWED: they are reversible / capacity-bounded / rate-limited and
# cannot damage the shared host. Local full-stack and the cloud real-WG deploy
# run with DEMO_MODE OFF (unchanged behaviour).
DEMO_MODE = _truthy(os.environ.get("DEMO_MODE"))
DEMO_RATE_MAX = int(os.environ.get("DEMO_RATE_MAX", "120"))        # tokens / window
DEMO_RATE_WINDOW_S = float(os.environ.get("DEMO_RATE_WINDOW_S", "60"))
_rate_state: dict[str, tuple[float, float]] = {}                   # ip -> (tokens, ts)

# Container lifecycle control is OPT-IN, not opt-out.
#
# This endpoint can start/stop/restart containers through a mounted
# /var/run/docker.sock, so on a reachable host it is a privilege-escalation
# path, not merely a way to take the demo offline. It used to be enabled by
# default and disabled only when DEMO_MODE was set — meaning a deployment that
# simply forgot the flag exposed it to the internet. That is exactly what
# happened to the public demo: it answered `demo_mode: false` while running the
# full profile with docker.sock mounted.
#
# Inverting the default changes the failure mode: a missing or misspelled
# variable now yields a SAFE deployment (403) rather than an exposed one.
# Enabling it is a deliberate act, and DEMO_MODE additionally vetoes it so the
# two cannot be switched on together by accident.
CONTAINER_CONTROL_ENABLED = (
    _truthy(os.environ.get("ENABLE_CONTAINER_CONTROL")) and not DEMO_MODE
)


@app.middleware("http")
async def demo_rate_limit(request, call_next):
    """Per-IP token-bucket on POST requests. ALWAYS ON.

    This was gated on DEMO_MODE. The public demo runs with DEMO_MODE unset --
    `GET /api/config` returns `{"demo_mode": false, "rate_limit": null}` -- so
    on the one host that faces the internet, the limiter was inert.

    That is backwards. DEMO_MODE exists to REMOVE capability (container
    control, privileged nodes); it is not a statement that a host is exposed.
    A rate limit is cheap on a private host and essential on a public one, and
    tying it to a variable that is off in production means the protection is
    absent exactly where it is needed.

    Measured before this change: `POST /api/sim/optimize` (now deleted) cost
    14.6 s of server CPU per unauthenticated request with no throttle at all.

    The name is kept because DEMO_RATE_MAX / DEMO_RATE_WINDOW_S are the
    documented env vars and renaming them would break deployments for nothing.

    The method set is every mutating verb, not just POST. Ungating DEMO_MODE
    closed one hole and left another: `DELETE /api/exports/{filename}` is the
    project's only non-POST mutating route, and it sat outside the limiter
    before and after that change. Measured on the public host: thirty
    consecutive unauthenticated deletes, thirty 200s, no throttle.

    PUT and PATCH are included although no route uses them today, so that
    adding one is not silently adding an unthrottled mutation.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        tokens, last = _rate_state.get(ip, (float(DEMO_RATE_MAX), now))
        tokens = min(DEMO_RATE_MAX,
                     tokens + (now - last) * (DEMO_RATE_MAX / DEMO_RATE_WINDOW_S))
        if tokens < 1.0:
            _rate_state[ip] = (tokens, now)
            return JSONResponse(
                {"detail": "rate limit exceeded"}, status_code=429)
        _rate_state[ip] = (tokens - 1.0, now)
    return await call_next(request)


# ----------------------- Health / Stack -----------------------
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "demo_mode": DEMO_MODE}


@app.get("/api/config")
async def config() -> dict[str, Any]:
    """Runtime flags the frontend uses to adapt the UI (e.g. hide controls).

    `container_control` is reported explicitly so the deployment's posture can
    be checked from outside without attempting the dangerous call itself --
    see scripts/verify-demo-hardening.sh.
    """
    return {
        "demo_mode": DEMO_MODE,
        "container_control": CONTAINER_CONTROL_ENABLED,
        # Reported unconditionally, because the limiter now runs
        # unconditionally. This was `... if DEMO_MODE else None`, which paired
        # with the old DEMO_MODE-gated middleware -- both off together, so the
        # field was at least honest. Leaving it gated after making the limiter
        # always-on would have made /api/config report "no rate limit" on a
        # host that has one, which is the shape of claim this project keeps
        # removing. scripts/verify-demo-hardening.sh reads this field.
        "rate_limit": {"max": DEMO_RATE_MAX, "window_s": DEMO_RATE_WINDOW_S},
    }


# Services that exist only in a compose OVERLAY behind a profile, mapped to the
# profile that enables them. Absent is the correct state for these whenever the
# profile is not active, and the base `docker-compose.yml` does not define them
# at all -- so on a healthy default stack three of the ten rows below are
# absent BY DESIGN.
#
# Without this table `/api/stack` reported `absent` for "you did not start the
# crossvalidate overlay" and for "bb84-kme-a died" using the same word, and the
# Overview page painted both the same grey. Three rows therefore read as
# failures on a stack with nothing wrong with it, which is exactly the
# absence-rendered-as-a-measurement defect this project treats as a bug
# everywhere else.
#
# Derived from the compose files rather than asserted here; the values are
# checked against them by tests/test_optional_services_are_labelled.py, so this
# dict cannot drift from `profiles:` without the build noticing.
PROFILE_GATED: dict[str, tuple[str, str]] = {
    "qkdnetsim-kme": ("crossvalidate", "docker-compose.qkdnetsim.yml"),
    "alice-ipsec": ("ipsec", "docker-compose.strongswan.yml"),
    "bob-ipsec": ("ipsec", "docker-compose.strongswan.yml"),
}


@app.get("/api/stack")
async def stack() -> list[dict[str, Any]]:
    """Container status for the main services.

    `absent` means the container is not present. For a profile-gated service
    that is the expected state unless its overlay was started, so those rows
    carry `optional: true` plus the profile and compose file that would create
    them. A consumer that ignores the flag renders exactly what it did before.
    """
    names = ["alice", "bob", "bb84-kme-a", "bb84-kme-b", "webui-backend",
             "webui-frontend", "pqc-validator", "alice-ipsec", "bob-ipsec",
             "qkdnetsim-kme"]

    def gating(n: str) -> dict[str, Any]:
        """Why this row may legitimately be absent. Empty for required ones."""
        if n not in PROFILE_GATED:
            return {}
        profile, compose = PROFILE_GATED[n]
        return {
            "optional": True,
            "profile": profile,
            "compose_file": compose,
            "note": (
                f"not in the default stack: defined only in {compose} behind "
                f"`profiles: [\"{profile}\"]`. Absent here means the overlay "
                f"was not started, not that anything failed."
            ),
        }

    out: list[dict[str, Any]] = []
    cli = app.state.docker
    if cli is None:
        # `unknown`, not `absent`: we could not look. Keep the gating metadata
        # so the page can still explain the optional rows.
        return [{"name": n, "status": "unknown", **gating(n)} for n in names]
    for n in names:
        try:
            c = cli.containers.get(n)
        except Exception:
            # The container genuinely is not there. This is the only path that
            # may say "absent".
            out.append({"name": n, "status": "absent", **gating(n)})
            continue

        # Reading the image is a SEPARATE failure from the container being
        # absent, and it used to be inside the same try. `c.image` raises
        # ImageNotFound whenever the image the container runs has lost its
        # tag -- which happens routinely: rebuilding `pqcqkd/node-alice:local`
        # leaves every other container still running the previous, now
        # dangling, image ID.
        #
        # Measured on the deployed host: after rebuilding alice, `bob` was
        # `Up 4 days` and rotating keys normally, `containers.get("bob")`
        # returned status=running, and `bob.image` raised
        # `ImageNotFound: 404 ... /images/1a2e95e58251`. The Overview page
        # showed bob as ABSENT for a container that was working.
        #
        # A cosmetic field must not be able to erase an observed status.
        image = ""
        try:
            tags = c.image.tags
            image = tags[0] if tags else ""
        except Exception:
            # Untagged is a real, reportable state -- not an empty string,
            # which would read as "no image information available".
            image = "<untagged>"

        out.append({
            "name": n,
            "status": c.status,
            "image": image,
            "started_at": c.attrs.get("State", {}).get("StartedAt"),
            **gating(n),
        })
    return out


# ----------------------- Stats -----------------------
@app.get("/api/stats")
async def stats():
    async with httpx.AsyncClient(timeout=2.0) as client:
        results: dict[str, Any] = {}
        for label, url in (("alice", KME_A_URL), ("bob", KME_B_URL)):
            try:
                r = await client.get(f"{url}/sim/stats")
                results[label] = r.json()
            except Exception as e:
                results[label] = {"error": str(e)}
        return results


# ----------------------- Phase 12-A: file-backed log endpoints -----------------------
# Registered BEFORE the dynamic /api/logs/{name} route so "files" and
# "download/<svc>" are matched literally first.
@app.get("/api/logs/files")
async def list_log_files() -> dict[str, list]:
    """List every *.log* file present in the shared LOG_DIR volume."""
    return {"files": logging_setup.list_log_files()}


@app.get("/api/logs/download/{service}")
async def download_log(service: str, lines: int = 1000):
    """Return the last `lines` lines of <service>.log as a text/plain download.

    404 when the file is absent, rather than 200 with a comment standing in for
    it. The previous form returned

        # log file <service>.log not found

    under a Content-Disposition header, so asking for a log that does not exist
    produced a *successful* download of a one-line file that looked like a log.
    `/console` did exactly that for both KME containers, and no caller could
    distinguish "no such log" from "the service has been quiet".
    """
    safe = service.replace("/", "_").replace("..", "_")
    known = {f["name"] for f in logging_setup.list_log_files()}
    if f"{safe}.log" not in known:
        raise HTTPException(
            status_code=404,
            detail=f"no log file {safe}.log; available: {sorted(known)}",
        )
    return PlainTextResponse(
        logging_setup.read_tail(safe, lines=int(lines)),
        headers={"Content-Disposition": f'attachment; filename="{safe}.log"'},
    )


# ----------------------- Phase 13: Backend-stored exports -----------------------
# Persist artefacts (PNG, JSON, CSV, GIF, log) into a shared volume, then offer
# them for download via a stable URL. Lets users save/share simulation outputs
# beyond a single browser session.
EXPORT_DIR = os.environ.get("EXPORT_DIR", "/var/lib/pqcqkd-exports")
EXPORT_MAX_BYTES = int(os.environ.get("EXPORT_MAX_BYTES", 50 * 1024 * 1024))
EXPORT_MAX_FILES = int(os.environ.get("EXPORT_MAX_FILES", 200))


def _ensure_export_dir():
    from pathlib import Path
    d = Path(EXPORT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _gc_export_dir() -> None:
    """Keep only the most recent EXPORT_MAX_FILES files (oldest deleted first)."""
    from pathlib import Path
    d = Path(EXPORT_DIR)
    if not d.exists():
        return
    files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[EXPORT_MAX_FILES:]:
        try: old.unlink()
        except Exception: pass


@app.post("/api/exports/save")
async def export_save(req: dict):
    """Body: {name: str, ext: str, content_b64: str}
    Saves <timestamp>-<safe_name>.<ext> into EXPORT_DIR.  Returns the URL.
    Allowed in DEMO_MODE: the store is capacity-bounded (EXPORT_MAX_FILES FIFO +
    EXPORT_MAX_BYTES/file — tightened via env in the demo profile), names are
    sanitised (no path traversal), and POSTs are per-IP rate-limited."""
    import base64
    import re
    import time
    raw_name = str(req.get("name", "export"))
    ext = str(req.get("ext", "bin")).lstrip(".").lower()
    content_b64 = req.get("content_b64")
    if not content_b64:
        raise HTTPException(400, "content_b64 required")
    try:
        data = base64.b64decode(content_b64, validate=False)
    except Exception as e:
        raise HTTPException(400, f"invalid base64: {e}")
    if len(data) > EXPORT_MAX_BYTES:
        raise HTTPException(413, f"payload {len(data)} > limit {EXPORT_MAX_BYTES}")

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name)[:80] or "export"
    safe_ext = re.sub(r"[^A-Za-z0-9]+", "", ext)[:8] or "bin"
    ts = time.strftime("%Y%m%d-%H%M%S")
    filename = f"{ts}-{safe_name}.{safe_ext}"

    d = _ensure_export_dir()
    (d / filename).write_bytes(data)
    _gc_export_dir()

    log.info("export saved name=%s ext=%s bytes=%d", safe_name, safe_ext, len(data))
    return {
        "ok": True,
        "filename": filename,
        "size": len(data),
        "url": f"/api/exports/download/{filename}",
    }


@app.get("/api/exports/list")
async def export_list():
    from pathlib import Path
    d = Path(EXPORT_DIR)
    if not d.exists():
        return {"exports": []}
    out: list[dict] = []
    for p in sorted(d.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime,
                        "url": f"/api/exports/download/{p.name}"})
        except FileNotFoundError:
            continue
    return {"exports": out}


@app.get("/api/exports/download/{filename}")
async def export_download(filename: str):
    import re
    from pathlib import Path

    from fastapi.responses import FileResponse
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]
    if safe != filename or ".." in safe:
        raise HTTPException(400, "invalid filename")
    p = Path(EXPORT_DIR) / safe
    if not p.exists():
        raise HTTPException(404, "not found")
    ct_map = {".png": "image/png", ".gif": "image/gif",
              ".json": "application/json", ".csv": "text/csv",
              ".log": "text/plain", ".txt": "text/plain"}
    return FileResponse(p, media_type=ct_map.get(p.suffix.lower(),
                                                  "application/octet-stream"),
                        filename=safe)


@app.delete("/api/exports/{filename}")
async def export_delete(filename: str):
    import re
    from pathlib import Path
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)[:120]
    if safe != filename or ".." in safe:
        raise HTTPException(400, "invalid filename")
    p = Path(EXPORT_DIR) / safe
    if p.exists():
        p.unlink()
    return {"ok": True}


# ----------------------- Logs (Docker stdout, dynamic by container name) -----------------------
@app.get("/api/logs/{name}")
async def logs(name: str, tail: int = 200) -> dict[str, str]:
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(name)
        data = c.logs(tail=tail).decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(404, str(e))
    return {"name": name, "log": data}


# ----------------------- WireGuard show -----------------------
# `wg show <if> dump` PRINTS SECRETS. From wg(8): the first line is
# "private-key, public-key, listen-port, fwmark" tab-separated, and each peer
# line is "public-key, preshared-key, endpoint, allowed-ips, latest-handshake,
# rx, tx, keepalive". Fields 1 and 2 respectively are the interface private key
# and the preshared key, both in plaintext base64.
#
# This route served that verbatim, unauthenticated, with no DEMO_MODE gate. A
# 2026-08-27 GET of the public demo's /api/wg/alice returned alice's wg0 private
# key and the live preshared key -- and on this stack the preshared key is the
# arnika HKDF(QKD || PQC) output, i.e. the entire product of the key path the
# project exists to demonstrate. Nothing in the frontend has ever called this
# route, so the exposure carried no compensating benefit.
#
# The non-dump form is what wireguard-tools redacts for you: it prints
# "private key: (hidden)" and "preshared key: (hidden)". Use it. Then redact
# again on the way out, so that editing one word of the command back is not by
# itself sufficient to leak. See tests/test_wg_endpoint_redacts_secrets.py.
WG_SHOW_CMD = "wg show wg0"

_WG_SECRET_LINE = re.compile(r"^(\s*(?:private key|preshared key)\s*:).*$", re.M | re.I)


def _redact_wg(text: str) -> str:
    """Remove key material from `wg show` output, failing closed.

    Two layers, because what is being guarded is a one-word edit:

      1. any `private key:` / `preshared key:` value becomes `(hidden)`, which
         is what the non-dump form prints anyway -- so this is a no-op on
         correct input and a rescue on incorrect input;
      2. if the text looks like `dump` output at all, the whole body is
         withheld rather than field-edited. The dump format is positional, and
         a redactor that miscounts columns leaks instead of over-redacting;
         refusing is the only safe response to a shape we did not ask for.
    """
    if "\t" in text and "interface:" not in text:
        return (
            "[withheld] this looks like `wg show ... dump`, whose first field is "
            "the interface private key and whose second per-peer field is the "
            "preshared key. This endpoint serves only the redacted `wg show` "
            f"form; see WG_SHOW_CMD ({WG_SHOW_CMD!r})."
        )
    return _WG_SECRET_LINE.sub(r"\1 (hidden)", text)


@app.get("/api/wg/{node}")
async def wg_show(node: str):
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    try:
        c = cli.containers.get(node)
        rc, out = c.exec_run(WG_SHOW_CMD)
        text = out.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(404, str(e))
    return {"node": node, "rc": rc, "output": _redact_wg(text)}


# The Eve-control, E2E-orchestrator, Paper-Data-Exchange and WebSocket fan-out
# routes were removed here. Every one of them was fully routed and unreachable:
# the frontend has contained no `new WebSocket(...)` since the simulation pages
# moved client-side, and nothing in the repository -- no page, test, Makefile
# target or CI job -- referenced /api/e2e/*, /api/paper-flow/*, /ws/e2e,
# /ws/paper-flow, /ws/frames, /api/sim/eve or /api/sim/rotate.
#
# The Eve and frames routes were thin proxies to services/bb84-kme, which still
# serves them directly; only the unused pass-through is gone.
#
# See docs/phases.md for the superseded design.


# ----------------------- Stack control -----------------------
@app.post("/api/stack/{action}/{name}")
async def stack_action(action: str, name: str):
    # Opt-in, so that forgetting a flag fails closed rather than open.
    if not CONTAINER_CONTROL_ENABLED:
        raise HTTPException(
            403,
            "container control is disabled; set ENABLE_CONTAINER_CONTROL=1 "
            "(and do not set DEMO_MODE) on a trusted host to enable it",
        )
    cli = app.state.docker
    if cli is None:
        raise HTTPException(503, "docker not available")
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(400, "action must be start|stop|restart")
    try:
        c = cli.containers.get(name)
        getattr(c, action)()
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": True, "action": action, "name": name}


# ----------------------- Physics params (proxy to KME A) -----------------------
@app.get("/api/sim/params")
async def sim_params_proxy():
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(f"{KME_A_URL}/sim/params")
        return r.json()


# ----------------------- Simulator control fan-out -----------------------
# These three endpoints POST to BOTH KMEs. Each used to wrap the call in
# `try/except Exception` that logged and continued, then `return {"ok": True}`
# unconditionally -- so with neither KME reachable the caller got HTTP 200 and
# `{"ok": true}`, and /physics printed "Reverted to config/qkd_params.yaml
# defaults." having changed nothing anywhere.
#
# Same family as the restart button that always 403'd: an action that reports
# success it did not have. There the promise was discarded; here the success was
# fabricated one layer earlier.
#
# `ok` now means EVERY peer was reached and answered. `nodes` says which did, so
# a half-applied override -- alice updated, bob not -- is visible rather than
# indistinguishable from both succeeding. That asymmetry matters here: the two
# KMEs must agree on the physics or the key rates they report diverge for a
# reason nobody can see.
def _fanout_result(outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the response, and say plainly which peers answered.

    A peer is `ok` only if the POST completed AND the KME did not answer 4xx/5xx.
    """
    reached = [n for n, o in outcomes.items() if o["ok"]]
    return {
        "ok": len(reached) == len(outcomes),
        "reached": len(reached),
        "of": len(outcomes),
        # Bodies are dropped here: `nodes` answers "did this peer apply it",
        # and the applied values are returned once, under `kme`.
        "nodes": {n: {k: v for k, v in o.items() if k != "body"}
                  for n, o in outcomes.items()},
    }


async def _post_both(client: httpx.AsyncClient, path: str,
                     json: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """POST `path` to both KMEs, recording each outcome instead of discarding it."""
    outcomes: dict[str, dict[str, Any]] = {}
    for name, url in (("alice", KME_A_URL), ("bob", KME_B_URL)):
        try:
            r = await client.post(f"{url}{path}", json=json) if json is not None \
                else await client.post(f"{url}{path}")
            if r.status_code >= 400:
                outcomes[name] = {"ok": False, "status": r.status_code,
                                  "error": r.text[:200], "body": None}
            else:
                # Body captured HERE. A first draft of this had the caller POST
                # a second time to read it, which applies the override twice --
                # a fix that introduces a worse bug than the one it closes.
                try:
                    body = r.json()
                except Exception:
                    body = None
                outcomes[name] = {"ok": True, "status": r.status_code, "body": body}
        except Exception as e:
            # Logged AND reported. Logging alone is what made this invisible:
            # the operator never sees the backend's log.
            log.warning("%s on %s failed: %s", path, url, e)
            outcomes[name] = {"ok": False, "status": None,
                              "error": str(e)[:200], "body": None}
    return outcomes


@app.post("/api/sim/backend")
async def sim_backend_proxy(req: dict[str, Any]):
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/backend", req)
    _invalidate_keyrate_cache()
    return _fanout_result(outcomes)


@app.get("/api/sim/params/editable")
async def sim_params_editable_proxy():
    """Editable parameter descriptors + current effective values (from KME A)."""
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(f"{KME_A_URL}/sim/params/editable")
        return r.json()


@app.post("/api/sim/params")
async def sim_params_set_proxy(req: dict[str, Any]):
    """Apply UI parameter overrides to BOTH KMEs (in-memory; config is default)."""
    last: dict[str, Any] | None = None
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/params", req)
        # A 4xx from a KME is a rejected override -- a validation error the user
        # must see, not a peer being down -- so it still raises rather than
        # being folded into the per-node report.
        for name, o in outcomes.items():
            if o["status"] is not None and o["status"] >= 400:
                raise HTTPException(o["status"], f"{name}: {o['error']}")
        # The applied values, from whichever peer answered -- read from the
        # response already captured, not by POSTing again.
        last = next((o["body"] for o in outcomes.values() if o["ok"] and o["body"]),
                    None)
    _invalidate_keyrate_cache()
    return {**_fanout_result(outcomes), "kme": last}


@app.post("/api/sim/params/reset")
async def sim_params_reset_proxy():
    """Drop UI overrides on both KMEs — revert to config defaults."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        outcomes = await _post_both(client, "/sim/params/reset")
    _invalidate_keyrate_cache()
    return _fanout_result(outcomes)


# `POST /api/sim/optimize` was here. Deleted, not disabled.
#
# It proxied the KME's Bayesian optimiser (skopt gp_minimize, 50 evaluations).
# Measured against the live public demo: 14.6 s of server CPU per request,
# unauthenticated, and the per-IP limiter above was inert because the host runs
# with DEMO_MODE unset. Nothing called it -- a repo-wide grep found only the two
# route definitions and two ARCHITECTURE.md diagram lines -- and /physics does
# its mu/nu optimisation as a client-side grid search (PhysicsParams.tsx).
#
# So: a dead endpoint that was also the cheapest way to exhaust the box.
@app.get("/api/pqc/algorithms")
async def pqc_algos():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{PQC_VALIDATOR_URL}/api/algorithms")
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


@app.post("/api/pqc/interop")
async def pqc_interop_proxy(req: dict[str, Any]):
    """Proxy the liboqs-vs-browser ML-KEM interoperability check.

    The browser cannot reach pqc-validator directly, and this is the one call
    on the /pqc page that constitutes an actual cross-check rather than a
    comparison of byte counts.
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/interop/mlkem", json=req)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"pqc-validator unavailable: {e}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()


@app.post("/api/pqc/roundtrip")
async def pqc_roundtrip(req: dict[str, Any]):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/roundtrip", json=req)
            return r.json()
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


# Two endpoints that are PURE FUNCTIONS of things that rarely change, and were
# recomputed from scratch on every page load.
#
# Measured against the live demo 2026-08-28:
#
#     POST /api/pqc/agility    4.0 s      -- 3 ML-KEM + 3 ML-DSA + 3 SLH-DSA
#                                            keygen/sign/verify in liboqs
#     GET  /api/verify/keyrate 1.1 s      -- closed form (microseconds) plus a
#                                            scipy optimise in the TNO engine
#
# /verify fetches both on mount, so every visitor cost ~5 s of server CPU
# before seeing anything. The agility matrix does not depend on the request at
# all -- it runs a fixed algorithm list -- and the key-rate cross-check depends
# only on config, which POST /api/sim/params changes.
#
# CACHED RATHER THAN MOVED TO THE BROWSER, deliberately. `lib/sim/pqc.ts`
# already has an `agilityMatrix()` that computes the same thing with
# @noble/post-quantum, and it is never called. Wiring it in would be the bigger
# saving -- and would make the panel title ("Crypto-Agility Matrix (liboqs ...)")
# and the citable export line ("# Crypto-agility matrix (liboqs)") FALSE, because
# the numbers would then come from a different library. Provenance is the point
# of that page. A cache buys most of the time back and costs no honesty.
#
# Failures are cached too, briefly: an unreachable validator should not mean a
# 20-second httpx timeout per viewer.
PQC_AGILITY_TTL_S = float(os.environ.get("PQC_AGILITY_TTL_S", "300.0"))
KEYRATE_TTL_S = float(os.environ.get("KEYRATE_TTL_S", "10.0"))
_pure_cache: dict[str, dict[str, Any]] = {}


def _cached(key: str, ttl: float):
    hit = _pure_cache.get(key)
    if hit is not None and (time.monotonic() - hit["at"]) < ttl:
        return hit["value"], hit["at"]
    return None, None


def _store(key: str, value: Any) -> Any:
    _pure_cache[key] = {"at": time.monotonic(), "value": value}
    return value


def _invalidate_keyrate_cache() -> None:
    """Drop the key-rate cache whenever the KME's effective config changes.

    A bare TTL would make VERIFICATION_CHECKLIST.md row 4.7.10 racy: it tells
    the reader to POST a new link length and reload /verify, and within the
    window they would read the previous distance's verdict and conclude the
    endpoint is broken. Explicit invalidation keeps the checklist executable as
    written.

    Called from the three proxies that mutate KME state -- backend swap,
    parameter override, override reset. Defined here rather than beside them so
    it sits with the cache it clears; Python resolves the global at call time,
    so the ordering is irrelevant at runtime.
    """
    _pure_cache.pop("keyrate", None)


@app.post("/api/pqc/agility")
async def pqc_agility(req: dict[str, Any] | None = None):
    """Crypto-agility matrix (ML-KEM, ML-DSA and SLH-DSA across levels).

    Cached: the validator runs a FIXED algorithm list, so the response is the
    same for every caller and every request body.
    """
    # Only the default (bodyless) call is cacheable -- a caller who supplies an
    # explicit algorithm list is asking for something else.
    cacheable = not req
    if cacheable:
        value, at = _cached("agility", PQC_AGILITY_TTL_S)
        if value is not None:
            return {**value, "cached": True,
                    "cache_age_s": round(time.monotonic() - at, 3)}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(f"{PQC_VALIDATOR_URL}/api/agility", json=req or {})
            out = r.json()
            if cacheable:
                _store("agility", out)
            return {**out, "cached": False} if isinstance(out, dict) else out
    except Exception as e:
        raise HTTPException(503, f"pqc-validator unavailable: {e}")


# ----------------------- Implementation verification -----------------------
@app.get("/api/verify/keyrate")
async def verify_keyrate():
    """TNO-vs-closed-form key-rate cross-check (from KME A).

    Cached for a short TTL. It is a pure function of the KME's effective
    config, which only POST /api/sim/params changes -- and the TTL is short
    enough (10 s) that an operator editing a parameter sees the new figure
    within one poll rather than having to know a cache exists.
    """
    value, at = _cached("keyrate", KEYRATE_TTL_S)
    if value is not None:
        return {**value, "cached": True,
                "cache_age_s": round(time.monotonic() - at, 3)}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{KME_A_URL}/sim/keyrate/crosscheck")
            out = r.json()
            if isinstance(out, dict):
                _store("keyrate", out)
                return {**out, "cached": False}
            return out
    except Exception as e:
        raise HTTPException(503, f"kme unavailable: {e}")


@app.get("/api/verify/paper-budgets")
async def verify_paper_budgets():
    """Paper packet-budget match (arXiv:2604.05599 Table 1).

    Reads the literature values directly from `paper_budgets`. It used to reach
    into a running paper-flow orchestrator for the same static dict, which meant
    a dead 400-line module had to keep booting with the application, and a 503
    here whenever it had not started yet.
    """
    budgets = paper_budgets.as_dict()
    phases = budgets["phases"]
    total_pkts = sum(int(p.get("packets", 0)) for p in phases)
    total_bytes = sum(int(p.get("bytes", 0)) for p in phases)
    # Compared against the separately transcribed paper totals, NOT against
    # `total_handshake_*`, which is the sum of these very phases. That earlier
    # comparison was a sum against itself -- always true, whatever the paper
    # says -- and /verify displayed it as evidence.
    return {
        "phases": phases,
        "computed_total_packets": total_pkts,
        "computed_total_bytes": total_bytes,
        "paper_total_packets": budgets["paper_total_packets"],
        "paper_total_bytes": budgets["paper_total_bytes"],
        "packets_match": total_pkts == budgets["paper_total_packets"],
        "bytes_match": total_bytes == budgets["paper_total_bytes"],
        "reference": "Spooren et al. arXiv:2604.05599 Evaluation Test 1, Table 1",
    }


# ----------------------- VPN Protocols (Phase 9-A) -----------------------
# Both lanes answer with the SAME key set in every state -- success, error and
# absent -- so a consumer never has to branch on which shape it received. The
# templates below are the single definition of those key sets; every return
# path starts from one of them rather than restating the keys, which is what
# let the WireGuard branch drift to a two-key dict on its default path while a
# comment on the IPsec branch claimed the invariant held for both.
def _wg_unknown(status: str) -> dict[str, Any]:
    """The WireGuard lane's key set, with nothing measured.

    `proposal` is None and stays None. WireGuard negotiates no cipher suite --
    ChaCha20-Poly1305 and Noise_IKpsk2 are fixed by the protocol, and `wg show`
    reports neither -- so any string here would be a constant this file made up.
    It used to hold "ChaCha20-Poly1305 + Noise + PSK". Moving that constant
    server-side would only have changed which file states it as though measured.
    `peers_with_psk` replaces it with something actually observable.
    """
    return {
        "name": "wireguard",
        "status": status,
        "active_sa": None,
        "proposal": None,
        "last_handshake": None,
        "last_handshake_s": None,
        "peers": None,
        "peers_with_psk": None,
    }


def _ipsec_unknown(status: str) -> dict[str, Any]:
    """The IPsec lane's key set, with nothing measured."""
    return {
        "name": "ipsec",
        "status": status,
        "active_sa": None,
        "proposal": None,
        "last_handshake": None,
        "pq_key_exchange": None,
        "ppk_used": None,
        "ppk_id": None,
        "ppk_required": None,
        "child_sas": None,
    }


# One CHILD_SA block from `swanctl --list-sas`, at four spaces of indent:
#
#     in  cb1df209,      0 bytes,     0 packets
#     out c15c9a27,   1680 bytes,    20 packets,     3s ago
#
# Format from swanctl/commands/list_sas.c:194-224 -- the SPI may carry a
# "/<cpi>" suffix and an optional " (mark .../if-id ...)" group before the
# comma, and an optional ", %5ss ago" after the packet count. Counters are
# printed with `%6s` / `%5s` of a plain integer, so the whitespace is variable
# and there are no thousands separators.
_CHILD_DIR_RE = re.compile(
    r"^\s{4}(in|out)\s+([0-9a-fA-F]+)(?:/\S+)?(?:\s+\([^)]*\))?,"
    r"\s*(\d+)\s+bytes,\s*(\d+)\s+packets",
)
# The CHILD_SA header, at two spaces:
#     tunnel: #6261, reqid 1, INSTALLED, TUNNEL-in-UDP, ESP:AES_GCM_16-256
_CHILD_HEAD_RE = re.compile(
    r"^\s{2}(\S+):\s*#(\d+),\s*reqid\s+(\d+),\s*([A-Z-]+)"
    r"(?:,\s*([^,]+?))?(?:,\s*ESP:(\S+))?\s*$",
)
# An IKE_SA header sits at column 0, which is what ends a CHILD_SA block.
_IKE_HEAD_RE = re.compile(r"^\S")


def _parse_child_sas(sas: str) -> list[dict[str, Any]]:
    """CHILD_SA byte/packet counters and SPIs, as a line-scanning state machine.

    NOT two `findall`s over the whole text. During a rekey window `--list-sas`
    prints two `tunnel:` blocks under one IKE_SA, and pairing the Nth `in` line
    with the Nth `out` line across the whole document silently mixes the old
    SA's inbound counters with the new SA's outbound ones. Scanning line by line
    and closing a block when the indent drops is the only form that stays
    correct while a rekey is in flight -- which is exactly when someone is
    looking.

    An absent direction is None, never 0. charon omits the line it has nothing
    for, and "no outbound line" must not read as "zero bytes sent".
    """
    children: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None

    def _close() -> None:
        nonlocal cur
        if cur is not None:
            children.append(cur)
            cur = None

    for line in sas.splitlines():
        head = _CHILD_HEAD_RE.match(line)
        if head:
            _close()
            cur = {
                "name": head.group(1),
                "unique_id": int(head.group(2)),
                "reqid": int(head.group(3)),
                "state": head.group(4),
                "mode": head.group(5),
                "esp_proposal": head.group(6),
                "in": None,
                "out": None,
            }
            continue
        if _IKE_HEAD_RE.match(line):
            # Back at column 0: a new IKE_SA, so the previous child is complete.
            _close()
            continue
        if cur is None:
            continue
        d = _CHILD_DIR_RE.match(line)
        if d:
            cur[d.group(1)] = {
                "spi": d.group(2),
                "bytes": int(d.group(3)),
                "packets": int(d.group(4)),
            }
    _close()
    return children


def _sample_ipsec(cli, container: str) -> dict[str, Any]:
    """One node's IPsec view. Two `docker exec`s; never raises."""
    try:
        c = cli.containers.get(container)
        rc_sas, sas = c.exec_run("swanctl --list-sas")
        rc_conns, conns = c.exec_run("swanctl --list-conns")
        # Check the exit codes. swanctl writes its error text to the same
        # stream as its output, and that text is non-empty, so passing a
        # failed invocation into the parser makes `sas.strip()` truthy and
        # reports status "running" for a charon that is dead. That is the
        # precise "healthy while doing nothing" mode this lane exists to
        # eliminate, reproduced in the status API.
        if rc_sas != 0 or rc_conns != 0:
            detail = (sas if rc_sas != 0 else conns).decode("utf-8", errors="replace")
            log.warning(
                "swanctl failed in %s (list-sas rc=%s, list-conns rc=%s): %s",
                container, rc_sas, rc_conns, detail.strip()[:200],
            )
            # Same keys as the success path, so a consumer never has to branch
            # on which shape it received. Seeded from the template rather than
            # restated, so the two cannot drift apart -- which is how the
            # WireGuard branch ended up with a two-key default while a comment
            # claimed the invariant held for both.
            #
            # active_sa is None, not 0: swanctl did not answer, so "we looked
            # and there are none" is not something we know.
            return _ipsec_unknown("error")
        return _parse_ipsec_sas(
            sas.decode("utf-8", errors="replace"),
            conns.decode("utf-8", errors="replace"),
        )
    except Exception as e:
        log.warning("ipsec status unavailable for %s: %s", container, e)
        return _ipsec_unknown("absent")


def _both_ends(alice: dict[str, Any], bob: dict[str, Any]) -> dict[str, Any]:
    """Aggregate the two nodes' views into facts that need BOTH to be known.

    Computed server-side, not in the browser, for a specific reason: `null &&
    true` is falsy in JavaScript, so a client-side `a.ppk_used && b.ppk_used`
    would render "not in use" for "one end did not answer". Here the three
    outcomes stay distinct -- True, False, and None for "could not tell".
    """
    def _both(key: str) -> bool | None:
        a, b = alice.get(key), bob.get(key)
        if a is None or b is None:
            return None
        return bool(a) and bool(b)

    # alice's outbound SPI must be bob's inbound one, and vice versa. This is
    # the only field here that could not be faked by one end alone: an SPI is
    # chosen by the receiver and echoed by the sender, so a match proves the
    # two containers are describing the same pair of ESP SAs rather than two
    # unrelated tunnels that both happen to be up.
    def _spis(node: dict[str, Any]) -> tuple[set[str], set[str]] | None:
        kids = node.get("child_sas")
        if not kids:
            return None
        return (
            {k["in"]["spi"] for k in kids if k.get("in")},
            {k["out"]["spi"] for k in kids if k.get("out")},
        )

    a_spis, b_spis = _spis(alice), _spis(bob)
    if a_spis is None or b_spis is None or not (a_spis[0] or a_spis[1]):
        spi_paired: bool | None = None
    else:
        spi_paired = bool(a_spis[1] & b_spis[0]) and bool(a_spis[0] & b_spis[1])

    return {
        # Deliberately NEW names, not a redefinition of the flat `ppk_required`.
        # A shape change fails loudly; a meaning change fails silently -- a
        # cached frontend would render alice-only data under a both-ends label
        # and nothing would break.
        "ppk_required_both_ends": _both("ppk_required"),
        "ppk_used_both_ends": _both("ppk_used"),
        "pq_key_exchange_both_ends": _both("pq_key_exchange"),
        "spi_paired": spi_paired,
    }


# Sampling `/api/vpn/protocols` costs five `docker exec`s (wg show, and
# list-sas + list-conns on each of the two IPsec nodes). The page polls every
# 3 s per viewer, so on a public host that is five execs per viewer per poll.
# A short TTL collapses concurrent viewers onto one sample without introducing
# a background task -- main.py deliberately has none.
#
# Failure shapes are cached too. Caching only successes would make a broken
# lane the expensive case, which is precisely when the host is least able to
# absorb it.
VPN_SAMPLE_TTL_S = float(os.environ.get("VPN_SAMPLE_TTL_S", "2.0"))
_vpn_sample: dict[str, Any] = {}


@app.get("/api/vpn/protocols")
def vpn_protocols():
    """Live status of both VPN lanes, from both ends of the IPsec one.

    A plain `def`, not `async def`. Every call inside is a blocking
    `exec_run`; under `async def` those five round trips run ON the event loop
    and stall every other request for their duration. FastAPI dispatches a sync
    handler to its threadpool instead.
    """
    now = time.monotonic()
    cached = _vpn_sample.get("v")
    if cached is not None and (now - cached["at"]) < VPN_SAMPLE_TTL_S:
        return cached["value"]

    cli = app.state.docker
    wg_status: dict[str, Any] = _wg_unknown("absent")
    alice_ipsec: dict[str, Any] = _ipsec_unknown("absent")
    bob_ipsec: dict[str, Any] = _ipsec_unknown("absent")

    if cli is not None:
        try:
            c = cli.containers.get("alice")
            rc, out = c.exec_run("wg show wg0")
            wg_text = out.decode("utf-8", errors="replace")
            if rc != 0:
                # Previously a non-zero rc degraded to status "running", which
                # VpnProtocols.tsx renders GREEN -- so a lane whose `wg show`
                # failed outright looked healthy. The IPsec branch has said
                # "error" for this case since it was written; this one matches.
                log.warning(
                    "wg show failed in alice (rc=%s): %s", rc, wg_text.strip()[:200],
                )
                wg_status = _wg_unknown("error")
            else:
                wg_status = _parse_wg(wg_text)
        except Exception as e:
            # The IPsec branch logs; this one used to swallow silently, so a
            # WireGuard lane that was never reachable looked identical to one
            # that was simply absent.
            log.warning("wireguard status unavailable: %s", e)

        alice_ipsec = _sample_ipsec(cli, "alice-ipsec")
        bob_ipsec = _sample_ipsec(cli, "bob-ipsec")

    value = {
        "wireguard": wg_status,
        # The flat IPsec fields keep meaning exactly what they meant before:
        # alice's view. Adding `nodes` and the *_both_ends aggregates alongside
        # them is additive; redefining these would have been a silent change.
        "ipsec": {
            **alice_ipsec,
            "nodes": {"alice": alice_ipsec, "bob": bob_ipsec},
            **_both_ends(alice_ipsec, bob_ipsec),
        },
        # So a reader can tell a fresh sample from a cached one rather than
        # inferring it from how fast the numbers move.
        "observed_at": time.time(),
        "cache_ttl_s": VPN_SAMPLE_TTL_S,
    }
    _vpn_sample["v"] = {"at": now, "value": value}
    return value


# Rotations get their own endpoint, at their own cadence.
#
# VERIFICATION_CHECKLIST row 2.14 is a ten-minute procedure, not a snapshot.
# Folding it into /api/vpn/protocols would mean reading two containers' whole
# log streams every 3 s per viewer -- server compute the public demo is
# supposed to avoid, and orders of magnitude more expensive than the five
# `exec_run`s above.
_ROTATION_RE = re.compile(r"PPK rotated \(id=(\S+?) ")
ROTATION_WINDOW_MAX_S = int(os.environ.get("VPN_ROTATION_WINDOW_MAX_S", "3600"))
ROTATION_TTL_S = float(os.environ.get("VPN_ROTATION_TTL_S", "15.0"))
_rotation_sample: dict[int, Any] = {}


def _count_rotations(cli, container: str, window_s: int) -> dict[str, Any]:
    """Count 'PPK rotated' lines in a container's recent log.

    Counts only. The log lines themselves are never returned: they carry
    credential ids and peer identities, and this endpoint is public.

    `count: None` plus an `error` string when we could not look. Zero rotations
    and "could not look" must never be the same value -- a stalled arnika and
    an unreachable container are different faults and the first is the one row
    2.14 exists to catch.
    """
    try:
        c = cli.containers.get(container)
        raw = c.logs(since=int(time.time()) - window_s, stdout=True, stderr=True)
        text = raw.decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("could not read %s logs: %s", container, e)
        return {"count": None, "distinct_ids": None, "error": str(e)[:200]}
    ids = _ROTATION_RE.findall(text)
    return {
        "count": len(ids),
        # A rotation that reinstalls the SAME credential id is not a rotation.
        # Reporting both makes that visible instead of inflating the count.
        "distinct_ids": len(set(ids)),
        "error": None,
    }


@app.get("/api/vpn/ppk-rotations")
def vpn_ppk_rotations(window_s: int = 600):
    """How many PPK rotations each IPsec node logged in the last `window_s`.

    Bounded and cached: an unbounded window would read the entire log stream of
    two containers on every request.
    """
    window_s = max(30, min(int(window_s), ROTATION_WINDOW_MAX_S))
    now = time.monotonic()
    cached = _rotation_sample.get(window_s)
    if cached is not None and (now - cached["at"]) < ROTATION_TTL_S:
        return cached["value"]

    cli = app.state.docker
    if cli is None:
        nodes = {n: {"count": None, "distinct_ids": None, "error": "docker not available"}
                 for n in ("alice-ipsec", "bob-ipsec")}
    else:
        nodes = {n: _count_rotations(cli, n, window_s)
                 for n in ("alice-ipsec", "bob-ipsec")}

    value = {
        "window_s": window_s,
        "nodes": nodes,
        "observed_at": time.time(),
        "cache_ttl_s": ROTATION_TTL_S,
        # What this endpoint does NOT establish, said here rather than left for
        # a reader to assume. Row 2.14 also asserts "concurrency 1 across 20
        # samples"; proving that needs a sampler running between requests, and
        # main.py deliberately runs no background tasks (see `lifespan`). A
        # single instantaneous `active_sa` from /api/vpn/protocols is the most
        # this API can honestly offer.
        "note": (
            "Counts log lines in a window. It does not establish that SA "
            "concurrency stayed at 1 throughout -- that needs repeated sampling, "
            "which this server does not do. Read active_sa from "
            "/api/vpn/protocols for an instantaneous value."
        ),
    }
    _rotation_sample[window_s] = {"at": now, "value": value}
    return value


# `wg show wg0` renders one block per peer, e.g.
#   interface: wg0
#     public key: <base64>
#     private key: (hidden)
#     listening port: 51820
#
#   peer: <base64>
#     preshared key: (hidden)
#     endpoint: 10.30.0.11:51821
#     allowed ips: 10.0.0.2/32
#     latest handshake: 1 minute, 32 seconds ago
#     transfer: 726.21 KiB received, 980.89 KiB sent
#
# Two of those lines are CONDITIONAL, which is what makes them worth reading.
# From wireguard-tools src/show.c:
#   * `preshared key:` prints only when `peer->flags & WGPEER_HAS_PRESHARED_KEY`,
#     so its presence is direct evidence that arnika installed the QKD-derived
#     key on that peer. It is the one observable security fact this lane has,
#     and it is what replaces the invented `proposal` constant.
#   * `latest handshake:` prints only when the handshake time is non-zero.
_WG_PEER_RE = re.compile(r"^peer:\s*\S+", re.M)
_WG_PSK_RE = re.compile(r"^\s+preshared key:", re.M)
_WG_HANDSHAKE_RE = re.compile(r"^\s+latest handshake:\s*(.+?)\s*$", re.M)

# The handshake value comes from show.c's ago(), which has exactly three shapes:
#   "Now"
#   "(System clock wound backward; connection problems may ensue.)"
#   "<pretty_time> ago"
# and pretty_time() OMITS zero components:
#
#   if (years)  ... if (days) ... if (hours) ... if (minutes) ... if (seconds)
#
# so "2 days, 5 seconds ago" is a legal rendering and a positional parse would
# read the 5 as minutes. Match unit names, never positions. Units are singular
# at 1 and plural otherwise, hence the optional s.
_WG_AGO_COMPONENT_RE = re.compile(r"(\d+)\s+(year|day|hour|minute|second)s?\b")
# Same arithmetic show.c uses: a year is 365 * 24 * 60 * 60, not a calendar year.
_WG_UNIT_SECONDS = {
    "second": 1, "minute": 60, "hour": 3600, "day": 86400, "year": 365 * 86400,
}


def _wg_handshake_seconds(raw: str) -> int | None:
    """Age in seconds from one `latest handshake:` value, or None if unreadable.

    None means "we could not read it", never "0 seconds". show.c renders a
    zero-second age as the literal "Now", so 0 is a real measurement and has to
    stay distinguishable from a parse failure -- including for the
    clock-wound-backward case, where the age is genuinely unknown rather than
    small.
    """
    value = raw.strip()
    if value == "Now":
        return 0
    if "wound backward" in value:
        return None
    components = _WG_AGO_COMPONENT_RE.findall(value)
    if not components:
        return None
    return sum(int(n) * _WG_UNIT_SECONDS[unit] for n, unit in components)


def _parse_wg(text: str) -> dict[str, Any]:
    """Derive WireGuard lane status from real `wg show` output.

    Every field is measured or None. The version this replaced reported
    `proposal` as the literal "ChaCha20-Poly1305 + Noise + PSK" and
    `last_handshake` as the literal "via wg show" -- a description of where a
    value would come from, shipped as the value -- and both went out over the
    public API. See `_wg_unknown` for why `proposal` is None permanently.

    `active_sa` counts peers that have completed a handshake, matching what the
    field means on the IPsec side (established SAs) rather than the previous
    `1 if "latest handshake" in text else 0`, which could not exceed 1 and
    ignored the exit code entirely.
    """
    peers = len(_WG_PEER_RE.findall(text))
    if peers == 0:
        # `wg show` succeeded but the interface has no peers -- the tunnel
        # cannot be established, and saying "running" would overstate it.
        return {**_wg_unknown("running"), "peers": 0, "peers_with_psk": 0,
                "active_sa": 0}

    handshakes = [_wg_handshake_seconds(m) for m in _WG_HANDSHAKE_RE.findall(text)]
    readable = [s for s in handshakes if s is not None]
    # Freshest peer, which is what a single "last handshake" figure can honestly
    # mean when there is more than one peer.
    age = min(readable) if readable else None

    return {
        "name": "wireguard",
        "status": "established" if handshakes else "running",
        "active_sa": len(handshakes),
        "proposal": None,
        "last_handshake": f"{age}s ago" if age is not None else None,
        "last_handshake_s": age,
        "peers": peers,
        "peers_with_psk": len(_WG_PSK_RE.findall(text)),
    }


# `swanctl --list-sas` renders an established IKE_SA as e.g.
#   pqcqkd-vpn: #1, ESTABLISHED, IKEv2, 8f3a...:c1d2...
#     local  'alice@pqcqkd.local' @ 10.30.0.20[500]
#     ...
#     AES_GCM_16-256/PRF_HMAC_SHA2_384/ECP_256/ML_KEM_768
#     established 12s ago, reauth in 18s
_SA_PROPOSAL_RE = re.compile(r"^\s{2,}([A-Z0-9_]+(?:-[0-9]+)?(?:/[A-Z0-9_]+)+)\s*$", re.M)
_SA_ESTABLISHED_RE = re.compile(r"established (\d+)([smh]) ago", re.M)
# `swanctl --list-conns` renders a PPK-enabled connection as:
#     ppk: ppk-qkd@pqcqkd.local, required
_CONN_PPK_RE = re.compile(r"^\s*ppk:\s*(\S+?),\s*(required|optional)\s*$", re.M)


def _parse_ipsec_sas(sas: str, conns: str) -> dict[str, Any]:
    """Derive IPsec lane status from real swanctl output.

    Every field is parsed from the daemon. An earlier version returned a
    hardcoded proposal string, so the UI kept advertising RFC 9370 ML-KEM even
    when charon had negotiated something else -- or, as it turned out, when
    charon was not running at all.

    Note the two mechanisms are reported separately and must not be conflated:
      * RFC 9370 (ML-KEM in the proposal) strengthens the key EXCHANGE.
      * RFC 8784 (PPK) mixes the QKD key into SK_d/SK_pi/SK_pr.
    Seeing ML_KEM in the proposal says nothing about whether the PPK is in use.
    """
    established = sas.count("ESTABLISHED")
    status = "established" if established else ("running" if sas.strip() else "absent")

    proposals = _SA_PROPOSAL_RE.findall(sas)
    # The IKE_SA proposal is the first algorithm line; CHILD_SA lines follow.
    proposal = proposals[0] if proposals else None

    age = _SA_ESTABLISHED_RE.search(sas)
    ppk = _CONN_PPK_RE.search(conns)

    # Seeded from the shared template so the success and error paths cannot
    # drift to different key sets; see _ipsec_unknown.
    return {
        **_ipsec_unknown(status),
        "active_sa": established,
        # None rather than a plausible-looking constant, so the UI can tell
        # "not negotiated yet" apart from "negotiated X".
        "proposal": proposal,
        "last_handshake": f"{age.group(1)}{age.group(2)} ago" if age else None,
        # RFC 9370: an additional ML-KEM key exchange was negotiated.
        #
        # Tri-state, deliberately. This was `"ML_KEM" in (proposal or "") or None`,
        # which yields True or None and NEVER False -- so "we read the proposal
        # and there is no ML-KEM in it" was indistinguishable from "we never
        # got a proposal". Both rendered as an em dash, so nothing on screen
        # could contradict it either.
        "pq_key_exchange": ("ML_KEM" in proposal) if proposal else None,
        # RFC 8784: whether the PPK was actually USED for this IKE_SA.
        #
        # This comment used to read: "charon does not report per-SA PPK use over
        # VICI, so this is honestly labelled as configuration, not as proof of
        # use." That is wrong, and the evidence was already in the output this
        # function is given. strongSwan 6.0.7, three files:
        #
        #   sa/ike_sa.h:258      /** A Postquantum Preshared Key was used when
        #                            this IKE_SA was created */
        #                        COND_PPK = (1<<13),
        #   vici/vici_query.c:640   add_condition(b, ike_sa, "ppk", COND_PPK);
        #   swanctl/list_sas.c:322  if (streq(ike->get(ike, "ppk"), "yes"))
        #                               printf("/PPK");
        #
        # and the condition is set in ikev2/tasks/ike_auth.c:1187, inside
        # apply_ppk(), only AFTER derive_ike_keys_ppk() has succeeded -- i.e.
        # only once the PPK has actually been mixed into SK_d/SK_pi/SK_pr.
        #
        # So the trailing "/PPK" on the proposal line is per-SA proof of use.
        # We were fetching --list-sas already and discarding the answer, while
        # reading --list-conns for a weaker one.
        "ppk_used": ("/PPK" in proposal) if proposal else None,
        # ...and this stays what it always was: CONFIGURATION, from
        # --list-conns. Kept separate rather than merged, because "the operator
        # required a PPK" and "charon mixed one in" fail independently -- a
        # required PPK that never arrives is exactly the case worth seeing.
        "ppk_id": ppk.group(1) if ppk else None,
        "ppk_required": (ppk.group(2) == "required") if ppk else None,
        # ESP counters and SPIs, per CHILD_SA. `swanctl --list-sas` has always
        # carried these; nothing parsed them, so VERIFICATION_CHECKLIST rows
        # 2.3 and 2.11 could only be executed over SSH.
        "child_sas": _parse_child_sas(sas),
    }


# ----------------------- Topology -----------------------
@app.get("/api/topology")
async def topology():
    """Static four-node graph: alice, bob and the two KMEs.

    The previous docstring said "in multihop mode include charlie", which no
    code does -- there is no multihop branch and no signal here that would
    indicate one. README described the page as showing Charlie on the strength
    of this line. Adding the branch needs a way to know the profile is active;
    until then the graph is honestly static.
    """
    nodes = [
        {"id": "alice", "type": "node", "label": "Alice (WG + arnika + RP)"},
        {"id": "bob",   "type": "node", "label": "Bob (WG + arnika + RP)"},
        {"id": "kme-a", "type": "kme",  "label": "BB84 KME (Alice)"},
        {"id": "kme-b", "type": "kme",  "label": "BB84 KME (Bob)"},
    ]
    edges = [
        {"source": "alice", "target": "bob",   "label": "WireGuard tunnel (PSK=HKDF(QKD‖PQC))"},
        {"source": "alice", "target": "kme-a", "label": "ETSI 014"},
        {"source": "bob",   "target": "kme-b", "label": "ETSI 014"},
        {"source": "kme-a", "target": "kme-b", "label": "BB84 quantum + classical channel"},
    ]
    return {"nodes": nodes, "edges": edges}


